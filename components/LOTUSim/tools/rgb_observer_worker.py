#!/usr/bin/env python3
"""Offline RGB detector, optional public visual references and empirical confidence.

Inference receives only neutrally named PNGs, a fixed vocabulary and, optionally,
the PUBLIC reference index. It never reads test annotations, masks or scene poses.
This input contract is not an OS sandbox. Similarity is never a probability.
"""

import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import re
import time

from rgb_postprocess import postprocess_predictions, validate_settings
from rgb_regions import empty_policy, validate_regions, region_signature, exclusion_mask, masked_rgb
from ops_runtime import OpsRuntime

DEFAULTS = {"tileOverlap": 0.2, "minCropPixels": 32, "minCropSide": 4}


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".partial")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding="utf-8"
    )
    temporary.replace(path)


def iou(a, b):
    x = max(0, min(a[0] + a[2], b[0] + b[2]) - max(a[0], b[0]))
    y = max(0, min(a[1] + a[3], b[1] + b[3]) - max(a[1], b[1]))
    intersection = x * y
    union = a[2] * a[3] + b[2] * b[3] - intersection
    return intersection / union if union > 0 else 0


def suppress(predictions, threshold):
    """Class-aware NMS; legacy category-free callers keep their old semantics."""
    selected = []
    for prediction in sorted(predictions, key=lambda p: p["score"], reverse=True):
        if not any(
            (
                "category" not in prediction
                or "category" not in other
                or prediction["category"] == other["category"]
            )
            and iou(prediction["bbox"], other["bbox"]) > threshold
            for other in selected
        ):
            selected.append(prediction)
    return selected


def category_for(label, categories):
    text = re.sub(r"[^a-z0-9 ]", " ", label.lower())
    matches = []
    for category in categories:
        query = re.sub(r"^(a|an) ", "", category["query"].lower())
        if re.search(r"\b" + re.escape(query) + r"\b", text):
            matches.append(category)
    return (
        matches[0] if len(matches) == 1 else {"category": "unknown", "displayName": "indéterminé"}
    )


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_config(config):
    allowed = {
        "schema",
        "model",
        "revision",
        "weightsSha256",
        "modelDirectory",
        "license",
        "device",
        "boxThreshold",
        "textThreshold",
        "nmsIou",
        "tileSize",
        "categories",
        "reviewSettings",
        "searchRegionSignature",
        *DEFAULTS,
    }
    if (
        not isinstance(config, dict)
        or set(config) - allowed
        or config.get("schema") != "lotusim-rgb-observer-config-1"
    ):
        raise ValueError(
            "Invalid image-only observer configuration; scene-specific keys are forbidden"
        )
    if not re.fullmatch(r"[a-f0-9]{40}", str(config.get("revision", ""))):
        raise ValueError("Pin a model revision, not a mutable branch")
    if not isinstance(config.get("model"), str) or not config["model"].strip():
        raise ValueError("A fixed detector model is required")
    if config.get("device") != "cpu":
        raise ValueError("This validated observer supports CPU only")
    for field in ("boxThreshold", "textThreshold", "nmsIou"):
        value = config.get(field)
        if not _number(value) or not 0 < value <= 1:
            raise ValueError("Invalid detector threshold: " + field)
    tile = config.get("tileSize")
    if isinstance(tile, bool) or not isinstance(tile, int) or not 0 <= tile <= 2048:
        raise ValueError("Invalid tile size")
    overlap = config.get("tileOverlap", DEFAULTS["tileOverlap"])
    if not _number(overlap) or not 0 <= overlap < 1:
        raise ValueError("tileOverlap must be finite and in [0, 1)")
    for field in ("minCropPixels", "minCropSide"):
        value = config.get(field, DEFAULTS[field])
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError(field + " must be a positive integer")
    categories = config.get("categories")
    if not isinstance(categories, list) or not 1 <= len(categories) <= 30:
        raise ValueError("Invalid fixed vocabulary")
    seen = set()
    for category in categories:
        if (
            not isinstance(category, dict)
            or set(category) != {"category", "displayName", "query"}
            or not re.fullmatch(r"[a-z][a-z0-9_]{0,39}", str(category.get("category", "")))
            or not all(
                isinstance(category.get(k), str) and category[k].strip()
                for k in ("displayName", "query")
            )
            or category["category"] in seen
        ):
            raise ValueError("Vocabulary contains invalid, duplicate or scene-specific categories")
        seen.add(category["category"])
    if config.get("weightsSha256") and not re.fullmatch(r"[a-f0-9]{64}", config["weightsSha256"]):
        raise ValueError("Invalid pinned weights checksum")
    validate_settings(config.get('reviewSettings'))
    if config.get('searchRegionSignature') is not None and not re.fullmatch(
        r'[a-f0-9]{64}', str(config['searchRegionSignature'])
    ):
        raise ValueError('Invalid search-region signature')


def detector_signature(config):
    """Portable hash of effective detection/decision settings, excluding paths."""
    validate_config(config)
    fields = (
        "model",
        "revision",
        "weightsSha256",
        "boxThreshold",
        "textThreshold",
        "nmsIou",
        "tileSize",
    )
    effective = {key: config.get(key) for key in fields}
    effective.update({key: config.get(key, value) for key, value in DEFAULTS.items()})
    effective["categories"] = [
        {"category": c["category"], "query": c["query"]} for c in config["categories"]
    ]
    effective['reviewSettings'] = effective_review_settings(config)
    effective['searchRegionSignature'] = config.get('searchRegionSignature') or region_signature(
        empty_policy()
    )
    effective["implementation"] = "cross_class_audited_review_observer_exclusion_4"
    effective["preprocessing"] = "pinned_local_processor_fullframe_plus_overlapping_tiles"
    payload = json.dumps(
        effective, sort_keys=True, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def effective_review_settings(config):
    return validate_settings(
        {'sameClassIou': config['nmsIou'], **(config.get('reviewSettings') or {})}
    )


def tile_regions(width, height, size, overlap=0.2):
    """Return full frame then unique tiles, including exact right/bottom edges."""
    if (
        any(isinstance(v, bool) or not isinstance(v, int) or v < 1 for v in (width, height))
        or isinstance(size, bool)
        or not isinstance(size, int)
        or size < 0
        or not _number(overlap)
        or not 0 <= overlap < 1
    ):
        raise ValueError("Invalid tile geometry")
    regions = [(0, 0, width, height)]
    if not size or (width <= size and height <= size):
        return regions
    step = max(1, int(size * (1 - overlap)))
    xs = sorted(set([*range(0, max(1, width - size), step), max(0, width - size)]))
    ys = sorted(set([*range(0, max(1, height - size), step), max(0, height - size)]))
    for y in ys:
        for x in xs:
            box = (x, y, min(width, x + size), min(height, y + size))
            if box not in regions:
                regions.append(box)
    return regions


def prepare_prediction(prediction, config):
    """Keep detector hypotheses but abstain from naming native subpixel targets."""
    result = dict(prediction)
    category = prediction.get("category", "unknown")
    score = prediction["score"]
    if not _number(score) or not 0 <= score <= 1:
        raise ValueError("Invalid prediction score")
    box = prediction["bbox"]
    if len(box) != 4 or not all(_number(v) for v in box) or box[2] <= 0 or box[3] <= 0:
        raise ValueError("Invalid prediction box")
    result.update(
        hypothesisCategory=category,
        hypothesisDisplayName=prediction.get("displayName", "indéterminé"),
        detectorScorePercent=100.0 * score,
        confidenceCalibrated=False,
        calibratedConfidencePercent=None,
        recognitionDecision="hypothesis",
        decisionReason="rgb_detector_hypothesis_not_verified",
        semanticConflict=False,
    )
    too_small = box[2] * box[3] < config.get("minCropPixels", DEFAULTS["minCropPixels"]) or min(
        box[2:]
    ) < config.get("minCropSide", DEFAULTS["minCropSide"])
    if too_small or category == "unknown":
        result.update(
            category="unknown",
            displayName="indéterminé",
            recognitionDecision="indeterminate",
            decisionReason=(
                "insufficient_native_pixels" if too_small else "ambiguous_detector_label"
            ),
        )
    return result


def clip_region_box(raw_box, region):
    """A detector cannot provide visible evidence outside its actual input tile."""
    if len(raw_box) != 4 or not all(_number(value) for value in raw_box):
        return None
    left, top, right, bottom = region
    x0, y0, x1, y1 = raw_box
    x0, x1 = max(left, min(right, x0 + left)), max(left, min(right, x1 + left))
    y0, y1 = max(top, min(bottom, y0 + top)), max(top, min(bottom, y1 + top))
    return [x0, y0, x1 - x0, y1 - y0] if x1 > x0 and y1 > y0 else None


def attach_evidence(prediction, image, knowledge, encoder):
    """Only detector boxes may form query crops; never consult test labels."""
    if knowledge is None or prediction["decisionReason"] == "insufficient_native_pixels":
        return prediction
    x, y, width, height = prediction["bbox"]
    box = (
        max(0, math.floor(x)),
        max(0, math.floor(y)),
        min(image.width, math.ceil(x + width)),
        min(image.height, math.ceil(y + height)),
    )
    evidence = knowledge.query(image.crop(box), encoder, k=3)
    prediction["semanticEvidence"] = evidence
    top = evidence.get("topCategory", "unknown")
    if top not in ("unknown", prediction["hypothesisCategory"]):
        prediction.update(semanticConflict=True, decisionReason="detector_reference_disagreement")
    # Neither agreement nor high cosine similarity promotes a class/probability.
    return prediction


def _overlay_font(size):
    """Prefer real Unicode fonts; the last-resort bitmap font gets ASCII."""
    from PIL import ImageFont

    for candidate in (
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/Library/Fonts/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
        "/usr/share/fonts/truetype/liberation2/LiberationSans-Regular.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Regular.ttf",
        "Arial.ttf",
        "DejaVuSans.ttf",
        "LiberationSans-Regular.ttf",
    ):
        try:
            return ImageFont.truetype(candidate, size=size), True
        except (OSError, ValueError):
            pass
    try:
        return ImageFont.load_default(size=size), False
    except TypeError:
        return ImageFont.load_default(), False


def _overlay_text(prediction, unicode_supported=True):
    """Short raw-score label; probabilities/details stay in the HTML report."""
    name = str(prediction.get("displayName") or prediction.get("category", "objet"))
    name = " ".join(name.split())
    if len(name) > 28:
        name = name[:27] + "…"
    score = prediction.get("score")
    percent = 100.0 * score if _number(score) else prediction.get("detectorScorePercent", 0)
    text = f"{name} · score brut {percent:.0f}%"
    if prediction.get("semanticConflict"):
        text += " · ! réf."
    if not unicode_supported:
        import unicodedata

        text = text.replace("·", "|").replace("…", "...")
        text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode("ascii")
    return text


def _rect_overlap(first, second):
    return max(0, min(first[2], second[2]) - max(first[0], second[0])) * max(
        0, min(first[3], second[3]) - max(first[1], second[1])
    )


def overlay_label_layout(image_size, predictions):
    """Bounded labels, greedily separated where there is enough image space.

    Every prediction retains its box and a label record. In an overcrowded or
    tiny image, overlap/truncation is unavoidable; do not discard hypotheses.
    Coordinates are half-open and always within the native RGB dimensions.
    """
    from PIL import Image, ImageDraw

    width, height = image_size
    if width < 1 or height < 1:
        raise ValueError("Overlay image dimensions must be positive")
    size = max(1, min(max(11, min(34, width // 110)), max(1, height - 4)))
    font, unicode_supported = _overlay_font(size)
    draw = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    padding = min(4, max(0, (min(width, height) - 1) // 3))
    occupied, records = [], []
    for prediction in predictions:
        x, y, w, h = prediction["bbox"]
        box = (
            max(0, min(width - 1, x)),
            max(0, min(height - 1, y)),
            max(1, min(width, x + w)),
            max(1, min(height, y + h)),
        )
        text = _overlay_text(prediction, unicode_supported)
        available = max(1, width - 2 * padding)
        suffix = "…" if unicode_supported else "..."
        # A long category cannot push the label off the image's right edge.
        if draw.textbbox((0, 0), text, font=font)[2] > available:
            while text and draw.textbbox((0, 0), text + suffix, font=font)[2] > available:
                text = text[:-1]
            text = text + suffix if text else ""
        bounds = draw.textbbox((0, 0), text, font=font)
        label_width = min(width, max(1, bounds[2] - bounds[0] + 2 * padding))
        label_height = min(height, max(1, bounds[3] - bounds[1] + 2 * padding))
        xs = [box[0], box[2] - label_width, (box[0] + box[2] - label_width) / 2]
        ys = [box[1] - label_height - 2, box[3] + 2, box[1] + 2]
        ys += list(range(0, max(1, height - label_height + 1), label_height + 2))
        candidates = []
        for cy in ys:
            for cx in xs:
                left = int(max(0, min(width - label_width, cx)))
                top = int(max(0, min(height - label_height, cy)))
                rect = (left, top, left + label_width, top + label_height)
                overlap = sum(_rect_overlap(rect, other) for other in occupied)
                distance = abs(left - box[0]) + abs(top - box[1])
                candidates.append((overlap, distance, rect))
        _, _, rect = min(candidates)
        occupied.append(rect)
        records.append(
            {
                "prediction": prediction,
                "box": box,
                "text": text,
                "labelRect": rect,
                "font": font,
                "unicodeSupported": unicode_supported,
                "textOrigin": (rect[0] + padding - bounds[0], rect[1] + padding - bounds[1]),
            }
        )
    return records


def render_overlay(image, predictions):
    """Render legible diagnostic boxes without changing RGB input or predictions."""
    from PIL import ImageDraw

    overlay = image.convert("RGB").copy()
    draw = ImageDraw.Draw(overlay)
    layout = overlay_label_layout(overlay.size, predictions)
    for item in layout:
        prediction = item["prediction"]
        color = (
            "#ffbd59"
            if prediction.get("semanticConflict")
            else ("#40d9ff" if prediction.get("category") != "unknown" else "#aeb7c1")
        )
        left, top, right, bottom = item["box"]
        draw.rectangle(
            (left, top, max(left, right - 1), max(top, bottom - 1)),
            outline=color,
            width=max(1, overlay.width // 1000),
        )
    for item in layout:
        left, top, right, bottom = item["labelRect"]
        draw.rectangle((left, top, right - 1, bottom - 1), fill="#08212f")
        draw.text(item["textOrigin"], item["text"], fill="white", font=item["font"])
    return overlay


def run(
    rgb_folder,
    output,
    config,
    model_directory,
    knowledge=None,
    calibration=None,
    max_regions=0,
    regions=None,
    observer_masks=None,
):
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false",
    )
    validate_config(config)
    policy = validate_regions(json.loads(Path(regions).read_text())) if regions else empty_policy()
    if (observer_masks is not None) != (
        policy.get('observerMaskSource', 'none') == 'unity_observer_visible_depth'
    ):
        raise ValueError('Observer mask inputs and declared scope source must agree')
    if observer_masks is not None and (
        Path(observer_masks).is_symlink() or not Path(observer_masks).is_dir()
    ):
        raise ValueError('Expected a neutral observer-mask directory')
    config = dict(config)
    supplied = config.get('searchRegionSignature')
    if supplied is not None and supplied != region_signature(policy):
        raise ValueError('Prepared search-region policy and detector signature differ')
    config['searchRegionSignature'] = region_signature(policy)
    if observer_masks is not None and not policy['excludeRegions']:
        # Visible ownship pixels are a precise mask, not an ignored rectangular
        # region. Preserve sparse foreground targets in front of the hull.
        config['reviewSettings'] = {
            **effective_review_settings(config),
            'rejectExcludedCenter': False,
            'maskOverlapThreshold': 1.0,
        }
    if isinstance(max_regions, bool) or not isinstance(max_regions, int) or max_regions < 0:
        raise ValueError("max_regions must be zero (all) or a positive integer")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "overlays").mkdir()
    runtime = OpsRuntime(output / 'runtime.json', 'rgb_detector')
    runtime.update('loading_model', currentAgent='rgb_detector')
    started = time.monotonic()
    frames, files, total_regions, evaluated_regions = [], [], 0, 0
    signature = detector_signature(config)
    knowledge_signature = None
    manifest = {
        "schema": "lotusim-rgb-observer-run-1",
        "model": config["model"],
        "revision": config["revision"],
        "modelLicense": config.get("license"),
        "inputContract": "clean RGB + declared observer-only exclusions + public references; no target ground truth",
        "osSandbox": False,
        "config": config,
        "detectorSignature": signature,
        "knowledgeSignature": None,
        "frames": frames,
        "maxRegions": max_regions,
        "status": "loading_model",
        "coverageLimited": False,
        "scoreMeaning": "raw_detector_score_not_probability",
    }
    atomic_json(output / "manifest.json", manifest)
    atomic_json(output / "status.json", {"status": "loading_model", "completed": 0})
    try:
        from PIL import Image, ImageDraw, ImageFont
        import torch
        from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection

        torch.set_num_threads(min(4, torch.get_num_threads()))
        model_directory = Path(model_directory).resolve(strict=True)
        weights_file = model_directory / "model.safetensors"
        if not weights_file.is_file():
            raise ValueError("Download the pinned safetensors model before inference")
        with weights_file.open("rb") as weights:
            model_hash = hashlib.file_digest(weights, "sha256").hexdigest()
        if config.get("weightsSha256") and model_hash != config["weightsSha256"]:
            raise ValueError("Local model weights do not match the pinned checksum")
        manifest["weightsSha256"] = model_hash
        processor = AutoProcessor.from_pretrained(
            str(model_directory), local_files_only=True, trust_remote_code=False
        )
        model = AutoModelForZeroShotObjectDetection.from_pretrained(
            str(model_directory),
            local_files_only=True,
            trust_remote_code=False,
            use_safetensors=True,
            disable_custom_kernels=True,
        ).eval()
        index, encoder = None, None
        if knowledge is not None:
            from rgb_knowledge import VisualEncoder, KnowledgeIndex

            index = KnowledgeIndex.load(Path(knowledge))
            encoder = VisualEncoder(model, processor, weights_sha256=model_hash)
            if index.encoder_description != encoder.description:
                raise ValueError("Knowledge and detector visual encoders differ")
            if index.weights_sha256 is not None and index.weights_sha256 != model_hash:
                raise ValueError("Knowledge and detector weights differ")
            knowledge_signature = hashlib.sha256(
                (index.directory / "index.json").read_bytes()
            ).hexdigest()
            manifest["knowledgeSignature"] = knowledge_signature
            manifest["referenceExamples"] = len(index.examples)
            manifest["knowledgeWeightsVerified"] = not index.legacy_weights_unverified
        calibration_data = None
        if calibration is not None:
            calibration_data = json.loads(Path(calibration).read_text(encoding="utf-8"))
        from rgb_confidence import estimate_confidence

        prompt = ". ".join(c["query"].lower() for c in config["categories"]) + "."
        files = sorted(Path(rgb_folder).glob("*.png"))
        if not files:
            raise ValueError("No staged RGB PNG images")
        runtime.update('running', currentAgent='rgb_detector', expected=len(files))
        for frame_number, path in enumerate(files):
            if path.is_symlink() or not re.fullmatch(r"i[0-9]{6}\.png", path.name):
                raise ValueError("Worker accepts only neutrally named, staged PNG files")
            with Image.open(path) as source:
                image = source.convert("RGB")
            width, height = image.size
            ownship_path = Path(observer_masks) / path.name if observer_masks else None
            mask = exclusion_mask(image.size, policy, ownship_path)
            search_image = masked_rgb(image, mask)
            regions = tile_regions(
                width,
                height,
                config["tileSize"],
                config.get("tileOverlap", DEFAULTS["tileOverlap"]),
            )
            planned_count = len(regions)
            if max_regions:
                regions = regions[:max_regions]
            manifest["coverageLimited"] |= len(regions) < planned_count
            manifest["status"] = "running"
            total_regions += planned_count
            predictions = []
            for region_number, (left, top, right, bottom) in enumerate(regions):
                atomic_json(
                    output / "status.json",
                    {
                        "status": "detecting",
                        "completed": len(frames),
                        "expected": len(files),
                        "currentImage": path.name,
                        "region": region_number + 1,
                        "regions": len(regions),
                        "plannedRegions": planned_count,
                        "regionsEvaluated": evaluated_regions,
                    },
                )
                crop = search_image.crop((left, top, right, bottom))
                inputs = processor(images=crop, text=prompt, return_tensors="pt")
                with torch.inference_mode():
                    outputs = model(**inputs)
                result = processor.post_process_grounded_object_detection(
                    outputs,
                    inputs.input_ids,
                    threshold=config["boxThreshold"],
                    text_threshold=config["textThreshold"],
                    target_sizes=[(crop.height, crop.width)],
                )[0]
                for raw_box, raw_score, label in zip(
                    result["boxes"], result["scores"], result["text_labels"]
                ):
                    box = clip_region_box(
                        [float(value) for value in raw_box], (left, top, right, bottom)
                    )
                    score = float(raw_score)
                    if box is None or not math.isfinite(score) or not 0 <= score <= 1:
                        continue
                    category = category_for(str(label), config["categories"])
                    predictions.append(
                        {
                            "category": category["category"],
                            "displayName": category["displayName"],
                            "textLabel": str(label),
                            "score": score,
                            "bbox": box,
                            'regionIndex': region_number,
                            'sourceRegion': [left, top, right, bottom],
                            'fullFrame': region_number == 0,
                            'touchesSourceBoundary': (
                                box[0] <= left + 2
                                or box[1] <= top + 2
                                or box[0] + box[2] >= right - 2
                                or box[1] + box[3] >= bottom - 2
                            ),
                        }
                    )
                evaluated_regions += 1
                # Recovery if interrupted: regional predictions are not a completed frame.
                atomic_json(
                    output / (path.stem + ".partial.json"),
                    {
                        "image": path.name,
                        "complete": False,
                        "evaluatedRegions": region_number + 1,
                        "plannedRegions": planned_count,
                        "predictions": suppress(predictions, config["nmsIou"]),
                    },
                )
            raw_predictions = [prepare_prediction(p, config) for p in predictions]
            reviewed = postprocess_predictions(
                raw_predictions, width, height, mask, effective_review_settings(config)
            )
            predictions = reviewed['predictions']
            review = reviewed['review']
            review['excludeRegions'] = policy['excludeRegions']
            review['searchRegionSignature'] = region_signature(policy)
            review['maskedPixelCount'] = mask.histogram()[255]
            if ownship_path is not None:
                review['exclusionMask'] = 'input/observer-exclusion/' + path.name
            for prediction in predictions:
                attach_evidence(prediction, search_image, index, encoder)
                confidence = estimate_confidence(
                    prediction["score"],
                    prediction["category"],
                    calibration_data,
                    detector_signature=signature,
                    knowledge_signature=knowledge_signature,
                )
                if (
                    prediction["recognitionDecision"] == "indeterminate"
                    or prediction.get('reviewStatus') == 'uncertain'
                ):
                    confidence["calibratedConfidencePercent"] = None
                    confidence["confidenceIntervalPercent"] = None
                    confidence["status"] = "indeterminate"
                prediction["confidenceEvidence"] = confidence
                prediction["calibratedConfidencePercent"] = confidence[
                    "calibratedConfidencePercent"
                ]
                prediction["confidenceCalibrated"] = (
                    confidence["calibratedConfidencePercent"] is not None
                )
            record = {
                "schema": "lotusim-rgb-observer-frame-1",
                "image": path.name,
                "width": width,
                "height": height,
                "rgbPixelSha256": hashlib.sha256(image.tobytes()).hexdigest(),
                'inferenceRgbPixelSha256': hashlib.sha256(search_image.tobytes()).hexdigest(),
                'searchExclusionAppliedBeforeInference': bool(mask.getbbox()),
                "predictions": predictions,
                'rawPredictions': raw_predictions,
                'review': review,
                "input": manifest["inputContract"],
                "confidenceCalibrated": any(p["confidenceCalibrated"] for p in predictions),
                "visibilityPercentAvailable": False,
                "plannedRegions": planned_count,
                "evaluatedRegions": len(regions),
                "coverageLimited": len(regions) < planned_count,
                "detectorSignature": signature,
                "knowledgeSignature": knowledge_signature,
            }
            atomic_json(output / (path.stem + ".json"), record)
            overlay = render_overlay(
                image, [p for p in predictions if p.get('reviewStatus') == 'retained']
            )
            overlay.save(output / "overlays" / path.name)
            frames.append(
                {
                    "image": path.name,
                    "predictionCount": len(predictions),
                    "plannedRegions": planned_count,
                    "evaluatedRegions": len(regions),
                }
            )
            manifest.update(
                elapsedSeconds=time.monotonic() - started,
                plannedRegions=total_regions,
                evaluatedRegions=evaluated_regions,
            )
            atomic_json(output / "manifest.json", manifest)
            atomic_json(
                output / "status.json",
                {
                    "status": "running",
                    "completed": len(frames),
                    "expected": len(files),
                    "regionsEvaluated": evaluated_regions,
                },
            )
            print(
                f'[RGB Observer] {frame_number+1}/{len(files)}: {len(predictions)} predictions; {len(regions)}/{planned_count} regions',
                flush=True,
            )
        manifest.update(status="complete", elapsedSeconds=time.monotonic() - started)
        atomic_json(output / "manifest.json", manifest)
        atomic_json(
            output / "status.json",
            {
                "status": "complete",
                "completed": len(frames),
                "expected": len(files),
                "regionsEvaluated": evaluated_regions,
                "coverageLimited": bool(max_regions and evaluated_regions < total_regions),
            },
        )
        runtime.complete()
    except Exception as error:
        runtime.fail(error)
        manifest.update(
            status="failed",
            elapsedSeconds=time.monotonic() - started,
            plannedRegions=total_regions,
            evaluatedRegions=evaluated_regions,
            error={"type": type(error).__name__, "message": str(error)},
        )
        atomic_json(output / "manifest.json", manifest)
        atomic_json(
            output / "status.json",
            {
                "status": "failed",
                "completed": len(frames),
                "expected": len(files),
                "error": str(error),
                "errorType": type(error).__name__,
                "regionsEvaluated": evaluated_regions,
                "completedPredictionsPreserved": True,
            },
        )
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rgb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("--model-directory", type=Path, required=True)
    parser.add_argument("--knowledge", type=Path)
    parser.add_argument("--calibration", type=Path)
    parser.add_argument('--regions', type=Path)
    parser.add_argument('--observer-masks', type=Path)
    parser.add_argument(
        "--max-regions",
        type=int,
        default=0,
        help="Limit regions per image for a smoke test; 0 evaluates every region",
    )
    args = parser.parse_args()
    run(
        args.rgb.resolve(strict=True),
        args.output,
        json.loads(args.config.read_text(encoding="utf-8")),
        args.model_directory,
        knowledge=args.knowledge,
        calibration=args.calibration,
        max_regions=args.max_regions,
        regions=args.regions,
        observer_masks=args.observer_masks,
    )


if __name__ == "__main__":
    main()
