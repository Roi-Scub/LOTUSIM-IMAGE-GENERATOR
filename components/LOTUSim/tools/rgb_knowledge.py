#!/usr/bin/env python3
"""Local visual references, not a probability model or a source of test labels.

Only ``public/`` is intended for the RGB worker. ``coordinator/`` preserves the
source paths, campaign/asset groups and normalized pixel hashes needed to audit
leakage. Unannotated RGB images are indexed there, never assigned a guessed class.
No network access or model loading is performed by this module.
"""

from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
from rgb_lineage import campaign_group


def _write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def pixel_sha256(image):
    """Hash decoded RGB pixels; PNG compression/EXIF do not affect identity."""
    return hashlib.sha256(image.convert("RGB").tobytes()).hexdigest()


def _unit(values):
    values = [float(value) for value in values]
    if not values or not all(math.isfinite(value) for value in values):
        raise ValueError("Visual features must be finite and non-empty")
    norm = math.sqrt(sum(value * value for value in values))
    if norm <= 1e-12:
        raise ValueError("Visual features have zero norm")
    return [value / norm for value in values]


def _weights_fingerprint(value):
    if value is not None and (
        not isinstance(value, str) or not re.fullmatch(r"[a-f0-9]{64}", value)
    ):
        raise ValueError("Encoder weights fingerprint must be a lowercase SHA-256 digest")
    return value


class VisualEncoder:
    """Reuse the already-loaded, local Grounding DINO Swin visual backbone.

    Features are pooled from its last feature map on a 224px RGB crop, using the
    model's image normalization. They are not trained for our class vocabulary.
    """

    description = "grounding_dino_local_swin_last_stage_rgb224_mean_pool_l2_v1"

    def __init__(self, model, processor, weights_sha256=None):
        self.model, self.processor = model, processor
        self.weights_sha256 = _weights_fingerprint(weights_sha256)

    def encode(self, image):
        import torch
        from PIL import Image

        resized = image.convert("RGB").resize((224, 224), Image.Resampling.BICUBIC)
        inputs = self.processor.image_processor(
            images=resized, do_resize=False, do_pad=False, return_tensors="pt"
        )
        values = inputs["pixel_values"]
        device = next(self.model.parameters()).device
        values = values.to(device)
        mask = inputs.get("pixel_mask")
        if mask is None:
            mask = torch.ones(
                values.shape[0], values.shape[-2], values.shape[-1], dtype=torch.long, device=device
            )
        else:
            mask = mask.to(device)
        with torch.inference_mode():
            maps = self.model.model.backbone.conv_encoder(values, mask)
            features, valid = maps[-1]
            valid = valid.to(features.dtype).unsqueeze(1)
            pooled = (features * valid).sum((-2, -1)) / valid.sum((-2, -1)).clamp(min=1)
        return _unit(pooled[0].detach().cpu().tolist())


def _safe_rgb(root):
    root = root.resolve(strict=True)
    rgb = root if root.name == "rgb" else root / "rgb"
    if rgb.is_symlink() or not rgb.is_dir():
        raise ValueError("Knowledge sources require a clean rgb/ folder, never overlays")
    if root.name in {"overlays", "masks", "amodal", "annotations"}:
        raise ValueError("Annotated overlays and masks are not RGB knowledge inputs")
    return rgb.parent, rgb.resolve()


def _bbox(bounds, width, height):
    if not isinstance(bounds, (list, tuple)) or len(bounds) != 4:
        raise ValueError("Reference bbox must contain x, y, width, height")
    x, y, w, h = map(float, bounds)
    if not all(math.isfinite(v) for v in (x, y, w, h)) or w <= 0 or h <= 0:
        raise ValueError("Reference bbox must have finite coordinates and positive size")
    left, top = max(0, math.floor(x)), max(0, math.floor(y))
    right, bottom = min(width, math.ceil(x + w)), min(height, math.ceil(y + h))
    if right <= left or bottom <= top:
        raise ValueError("Reference bbox is outside its RGB image")
    return left, top, right, bottom


def _coco_annotations(root):
    """Fallback for COCO-only campaigns; per-frame JSON takes precedence."""
    path = root / "annotations.coco.json"
    if not path.is_file():
        return {}
    coco = json.loads(path.read_text(encoding="utf-8"))
    images = {image["id"]: Path(image["file_name"]).name for image in coco.get("images", [])}
    categories = {category["id"]: category["name"] for category in coco.get("categories", [])}
    records = {}
    for annotation in coco.get("annotations", []):
        name = images.get(annotation.get("image_id"))
        if name is None:
            continue
        records.setdefault(name, []).append(
            dict(
                annotation,
                category=categories.get(annotation.get("category_id"), "unknown"),
                visiblePixels=annotation.get("area"),
            )
        )
    return records


def build_knowledge(sources, output, encoder, categories, min_area=256, max_per_class=8):
    """Build bounded references from clean RGB plus existing annotation boxes.

    A source is a campaign Path or ``{path, group?, kind?}``. The default campaign
    group is its resolved path; gallery asset identity is preserved separately.
    Class strings and the existing detector category dictionaries are accepted.
    Existing output directories are refused. No annotation is invented for raw RGB.
    """
    from PIL import Image

    if min_area < 1 or max_per_class < 1:
        raise ValueError("Knowledge bounds must be positive")
    weights_fingerprint = _weights_fingerprint(getattr(encoder, "weights_sha256", None))
    categories = {item["category"] if isinstance(item, dict) else str(item) for item in categories}
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    public, coordinator = output / "public", output / "coordinator"
    (public / "crops").mkdir(parents=True)
    coordinator.mkdir()
    frames, candidates, rejected, duplicates = [], [], [], []
    seen_frames = {}
    for source in sources:
        spec = source if isinstance(source, dict) else {"path": source}
        root, rgb = _safe_rgb(Path(spec["path"]))
        group = str(spec.get("group") or campaign_group(rgb))
        fallback = _coco_annotations(root)
        for path in sorted(rgb.glob("*.png")):
            if path.is_symlink() or path.resolve().parent != rgb:
                raise ValueError("Symlink knowledge images are refused")
            with Image.open(path) as source_image:
                image = source_image.convert("RGB")
            width, height = image.size
            digest = pixel_sha256(image)
            key = (width, height, digest)
            reference = root / "annotations" / (path.stem + ".json")
            payload = (
                json.loads(reference.read_text(encoding="utf-8")) if reference.is_file() else {}
            )
            if "width" in payload and (payload["width"], payload["height"]) != (width, height):
                raise ValueError("Annotation dimensions do not match RGB pixels")
            annotations = payload.get("annotations", fallback.get(path.name, []))
            active = {item.get("instance"): item for item in payload.get("activeObjects", [])}
            frame = {
                "path": str(path),
                "group": group,
                "width": width,
                "height": height,
                "rgbPixelSha256": digest,
                "labelStatus": "annotated" if annotations else "unlabeled",
                "annotationPath": str(reference) if reference.is_file() else None,
            }
            frames.append(frame)
            if key in seen_frames:
                duplicates.append(
                    {
                        "path": str(path),
                        "duplicateOf": seen_frames[key],
                        "group": group,
                        "rgbPixelSha256": digest,
                    }
                )
                continue
            seen_frames[key] = str(path)
            for annotation in annotations:
                category = annotation.get("category", "unknown")
                if category not in categories or category == "unknown":
                    rejected.append({"path": str(path), "reason": "unmapped_category"})
                    continue
                try:
                    box = _bbox(annotation.get("bbox"), width, height)
                    area = annotation.get("visiblePixels")
                    area = (
                        float(area)
                        if area is not None
                        else float((box[2] - box[0]) * (box[3] - box[1]))
                    )
                    if not math.isfinite(area) or area < min_area:
                        continue
                except (ValueError, TypeError) as error:
                    rejected.append({"path": str(path), "reason": str(error)})
                    continue
                instance = annotation.get("instance", "")
                asset = active.get(instance, {}).get("modelName") or instance
                candidates.append(
                    {
                        "path": path,
                        "category": category,
                        "box": box,
                        "visiblePixels": area,
                        "group": group,
                        "assetGroup": str(asset),
                        "rgbPixelSha256": digest,
                        "annotationPath": frame["annotationPath"],
                    }
                )
    # Clear references first. Selection is deterministic; all frames still remain
    # in provenance, including rejected/subpixel/unannotated and duplicate frames.
    candidates.sort(key=lambda item: (-item["visiblePixels"], str(item["path"]), item["box"]))
    counts, seen_crops, examples, provenance = Counter(), {}, [], []
    dimension = None
    for candidate in candidates:
        category = candidate["category"]
        if counts[category] >= max_per_class:
            continue
        with Image.open(candidate["path"]) as source_image:
            crop = source_image.convert("RGB").crop(candidate["box"])
        digest = pixel_sha256(crop)
        key = (crop.width, crop.height, digest)
        if key in seen_crops:
            duplicates.append(
                {
                    "path": str(candidate["path"]),
                    "cropDuplicateOf": seen_crops[key],
                    "category": category,
                    "cropPixelSha256": digest,
                }
            )
            continue
        feature = _unit(encoder.encode(crop))
        dimension = len(feature) if dimension is None else dimension
        if len(feature) != dimension:
            raise ValueError("Encoder feature dimensions changed during knowledge build")
        example_id = f"e{len(examples):06d}"
        filename = f"crops/{example_id}.png"
        crop.save(public / filename)
        examples.append(
            {
                "exampleId": example_id,
                "category": category,
                "crop": filename,
                "features": feature,
                "width": crop.width,
                "height": crop.height,
            }
        )
        provenance.append(
            {
                "exampleId": example_id,
                **{
                    key: str(value) if isinstance(value, Path) else value
                    for key, value in candidate.items()
                },
                "cropPixelSha256": digest,
            }
        )
        seen_crops[key] = example_id
        counts[category] += 1
    manifest = {
        "schema": "lotusim-visual-knowledge-1",
        "exampleCount": len(examples),
        "classCounts": dict(sorted(counts.items())),
        "featureDimension": dimension,
        "encoder": getattr(encoder, "description", type(encoder).__name__),
        "minVisiblePixels": min_area,
        "maxPerClass": max_per_class,
        "sourceFrameCount": len(frames),
        "unlabeledFrameCount": sum(f["labelStatus"] == "unlabeled" for f in frames),
        "duplicateCount": len(duplicates),
        "rejectedCount": len(rejected),
        "publicDirectory": "public",
        "probabilityCalibrated": False,
        "scoreMeaning": "cosine_similarity_not_probability",
    }
    public_index = {
        "schema": "lotusim-visual-knowledge-public-1",
        "encoder": manifest["encoder"],
        "featureDimension": dimension,
        "examples": examples,
        "scoreMeaning": "cosine_similarity_not_probability",
        "probabilityCalibrated": False,
    }
    if weights_fingerprint is not None:
        manifest["weightsSha256"] = weights_fingerprint
        public_index["weightsSha256"] = weights_fingerprint
    _write_json(public / "index.json", public_index)
    _write_json(
        coordinator / "provenance.json",
        {
            "schema": "lotusim-visual-knowledge-provenance-1",
            "frames": frames,
            "examples": provenance,
            "duplicates": duplicates,
            "rejected": rejected,
            "unlabeledPolicy": "Indexed for provenance only; never assigned an invented category",
        },
    )
    _write_json(output / "manifest.json", manifest)
    return manifest


class KnowledgeIndex:
    def __init__(self, directory, payload):
        self.directory = Path(directory)
        self.examples = payload["examples"]
        self.feature_dimension = payload.get("featureDimension")
        self.encoder_description = payload.get("encoder")
        self.weights_sha256 = _weights_fingerprint(payload.get("weightsSha256"))
        self.legacy_weights_unverified = self.weights_sha256 is None
        for example in self.examples:
            example["features"] = _unit(example["features"])
            if len(example["features"]) != self.feature_dimension:
                raise ValueError("Invalid knowledge feature dimensions")
            crop = Path(example["crop"])
            if crop.is_absolute() or ".." in crop.parts or crop.parts[:1] != ("crops",):
                raise ValueError("Unsafe public knowledge crop path")

    @classmethod
    def load(cls, directory):
        directory = Path(directory).resolve(strict=True)
        public = directory / "public" if (directory / "public").is_dir() else directory
        payload = json.loads((public / "index.json").read_text(encoding="utf-8"))
        if payload.get("schema") != "lotusim-visual-knowledge-public-1":
            raise ValueError("Unsupported visual knowledge schema")
        return cls(public, payload)

    def query(self, image, encoder, k=3):
        if not isinstance(k, int) or k < 1:
            raise ValueError("Nearest-neighbor count must be a positive integer")
        query_weights = _weights_fingerprint(getattr(encoder, "weights_sha256", None))
        if self.weights_sha256 is not None and query_weights != self.weights_sha256:
            raise ValueError("Knowledge/query encoder weights fingerprints differ or are missing")
        result = {
            "neighbors": [],
            "topCategory": "unknown",
            "similarity": None,
            "margin": None,
            "scoreMeaning": "cosine_similarity_not_probability",
            "confidenceCalibrated": False,
            "probabilityCalibrated": False,
            "classificationIsSuggestion": True,
            "knowledgeWeightsVerified": self.weights_sha256 is not None,
            "knowledgeWeightFingerprintStatus": (
                "verified" if self.weights_sha256 is not None else "legacy_unverified"
            ),
        }
        if not self.examples:
            return result
        feature = _unit(encoder.encode(image.convert("RGB")))
        if len(feature) != self.feature_dimension:
            raise ValueError("Query/knowledge feature dimensions differ")
        ranked = []
        for example in self.examples:
            similarity = max(
                -1.0, min(1.0, sum(a * b for a, b in zip(feature, example["features"])))
            )
            ranked.append(
                {
                    "exampleId": example["exampleId"],
                    "category": example["category"],
                    "similarity": similarity,
                    "crop": example["crop"],
                }
            )
        ranked.sort(key=lambda item: (-item["similarity"], item["exampleId"]))
        best = ranked[0]
        other = next((item for item in ranked if item["category"] != best["category"]), None)
        result.update(
            neighbors=ranked[:k],
            topCategory=best["category"],
            similarity=best["similarity"],
            margin=best["similarity"] - other["similarity"] if other else None,
            distinctCategoryCount=len({item["category"] for item in ranked}),
        )
        return result
