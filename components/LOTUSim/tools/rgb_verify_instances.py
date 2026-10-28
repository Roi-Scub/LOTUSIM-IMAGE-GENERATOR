#!/usr/bin/env python3
"""Visual classification with Unity-provided localization, NOT detection.

The coordinator uses Unity boxes to export neutrally named RGB crops. A separate
worker reads only those crops, fixed settings and public visual references. Test
classes remain in the coordinator and are compared AFTER classification. This
is an input contract, not an operating-system security sandbox. No similarity
is converted into a correctness probability or detector calibration sample.
"""

import argparse
import hashlib
import html
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time

from rgb_confidence import validate_split_isolation
from rgb_lineage import campaign_group
from rgb_observer import DEFAULT_CONFIG, ROOT, knowledge_frames, references
from rgb_observer_worker import atomic_json, validate_config

MODE = "classification_with_unity_provided_localization"
MODE_FR = "Classification avec localisation fournie par Unity"
MIN_VISIBLE_PIXELS = 32
MIN_SIDE = 4
MIN_MARGIN = 0.03


def _finite(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def crop_box(bbox, width, height):
    if not isinstance(bbox, (list, tuple)) or len(bbox) != 4:
        raise ValueError("A crop requires x, y, width, height")
    if not all(_finite(value) for value in bbox) or bbox[2] <= 0 or bbox[3] <= 0:
        raise ValueError("Invalid finite positive crop geometry")
    x, y, w, h = bbox
    box = (
        max(0, math.floor(x)),
        max(0, math.floor(y)),
        min(width, math.ceil(x + w)),
        min(height, math.ceil(y + h)),
    )
    if box[2] <= box[0] or box[3] <= box[1]:
        raise ValueError("Crop outside the RGB image")
    return box


def _unknown(reason, **extra):
    return {
        "mode": MODE,
        "category": "unknown",
        "decision": "indeterminate",
        "decisionReason": reason,
        "probabilityCalibrated": False,
        "calibratedConfidencePercent": None,
        "scoreMeaning": "cosine_similarity_not_probability",
        **extra,
    }


def classify_crop(image, knowledge, encoder, min_margin=MIN_MARGIN):
    """Pure RGB + public examples; no expected class or Unity instance input."""
    if not _finite(min_margin) or not 0 <= min_margin <= 2:
        raise ValueError("Invalid cosine margin")
    if image.width * image.height < MIN_VISIBLE_PIXELS or min(image.width, image.height) < MIN_SIDE:
        return _unknown("insufficient_native_crop_pixels", neighbors=[])
    evidence = knowledge.query(image, encoder, k=3)
    margin = evidence.get("margin")
    similarity = evidence.get("similarity")
    category = evidence.get("topCategory", "unknown")
    details = {
        "neighbors": evidence.get("neighbors", []),
        "margin": margin,
        "similarity": similarity,
        "hypothesisCategory": category,
        "nativeCropPixels": image.width * image.height,
    }
    if not _finite(similarity) or not _finite(margin) or category == "unknown":
        return _unknown("insufficient_reference_diversity", **details)
    if margin < min_margin:
        return _unknown("ambiguous_visual_neighbors", **details)
    return {
        "mode": MODE,
        "category": category,
        "decision": "visual_suggestion",
        "decisionReason": "nearest_visual_class_with_margin",
        "probabilityCalibrated": False,
        "calibratedConfidencePercent": None,
        "scoreMeaning": "cosine_similarity_not_probability",
        **details,
    }


def evaluate_instances(private_records, predictions, knowledge_categories=None):
    """Compare classification AFTER inference; no detection/IoU metrics."""
    rows = []
    correct = decided = rejected = geometry_rejected = visual_abstentions = 0
    covered = set(knowledge_categories) if knowledge_categories is not None else None
    expected_categories = set()
    for record in private_records:
        neutral = record["workerCrop"]
        if neutral not in predictions:
            raise ValueError("A worker crop has no classification: " + neutral)
        # Keep the RGB-only result intact: the optional geometry quality gate
        # is an evaluator decision, not evidence available to the classifier.
        raw_prediction = dict(predictions[neutral])
        prediction = dict(raw_prediction)
        if prediction.get("mode") != MODE:
            raise ValueError("Unexpected classifier mode")
        visible = record.get("visiblePixels")
        if visible is not None and (not _finite(visible) or visible < 0):
            raise ValueError("Invalid visible-pixel reference")
        gate_applied = visible is not None and visible < MIN_VISIBLE_PIXELS
        geometry_gate = {
            "status": (
                "rejected" if gate_applied else "passed" if visible is not None else "unavailable"
            ),
            "applied": gate_applied,
            "visiblePixels": visible,
            "minimumVisiblePixels": MIN_VISIBLE_PIXELS,
            "reason": (
                "too_few_unity_visible_pixels"
                if gate_applied
                else (
                    "unity_visible_pixel_threshold_met"
                    if visible is not None
                    else "unity_visible_pixel_count_unavailable"
                )
            ),
            "source": "Unity geometry, coordinator only AFTER RGB classification",
            "isVisualInference": False,
        }
        geometry_rejected += int(gate_applied)
        visual_abstentions += int(
            raw_prediction.get("decision") != "visual_suggestion"
            or raw_prediction.get("category") == "unknown"
        )
        if gate_applied:
            prediction.update(
                category="unknown",
                decision="indeterminate",
                decisionReason="insufficient_visible_pixels_unity_geometry",
            )
        expected_categories.add(record["expectedCategory"])
        unsupported = record["expectedCategory"] not in covered if covered is not None else None
        is_decided = (
            prediction.get("decision") == "visual_suggestion"
            and prediction.get("category") != "unknown"
        )
        matched = prediction.get("category") == record["expectedCategory"] if is_decided else None
        decided += int(is_decided)
        correct += int(matched is True)
        rejected += int(not is_decided)
        rows.append(
            {
                "crop": neutral,
                "rawClassification": raw_prediction,
                "geometryQualityGate": geometry_gate,
                "classification": prediction,
                "evaluator": {
                    "referenceCategory": record["expectedCategory"],
                    "proposedCategory": prediction.get("category"),
                    "correct": matched,
                    "visiblePixels": visible,
                    "unsupportedCategoryRisk": unsupported,
                    "reference": "Unity geometric category; not human recognizability",
                },
            }
        )
    return {
        "schema": "lotusim-localized-visual-verification-1",
        "mode": MODE,
        "modeLabel": MODE_FR,
        "instances": len(rows),
        "decidedInstances": decided,
        "indeterminateInstances": rejected,
        "correctDecidedInstances": correct,
        "visualAbstentionInstances": visual_abstentions,
        "geometryRejectedInstances": geometry_rejected,
        "accuracyOnDecidedInstances": correct / decided if decided else None,
        "abstentionRate": rejected / len(rows) if rows else None,
        "detectorMetricsApplicable": False,
        "calibrationApplicable": False,
        "reference": "Unity classes, evaluated only after RGB classification",
        "knowledgeCoverageAssessed": covered is not None,
        "coveredKnowledgeClasses": sorted(covered) if covered is not None else None,
        "expectedClassesMissingFromKnowledge": (
            sorted(expected_categories - covered) if covered is not None else None
        ),
        "limitations": [
            "Localization is supplied by Unity: this is NOT independent detection.",
            "Cosine similarity and class margin are NOT correctness probabilities.",
            "rawClassification is RGB-only; geometryQualityGate is a separate evaluator check.",
            "A class absent from the knowledge base cannot be proposed by this closed reference lookup.",
            "Accuracy is conditional on selected, localized and non-abstained instances.",
            "No manual recognizability reference is available.",
        ],
        "rows": rows,
    }


def prepare_instances(campaign, output, knowledge, limit=4, max_objects=12):
    from PIL import Image
    from rgb_knowledge import pixel_sha256

    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 4:
        raise ValueError("This bounded pilot permits 1 to 4 RGB frames")
    if (
        isinstance(max_objects, bool)
        or not isinstance(max_objects, int)
        or not 1 <= max_objects <= 12
    ):
        raise ValueError("This bounded pilot permits 1 to 12 object crops")
    root = Path(campaign).resolve(strict=True)
    rgb = root if root.name == "rgb" else root / "rgb"
    root = rgb.parent
    if not rgb.is_dir() or rgb.is_symlink():
        raise ValueError("Select a clean campaign rgb folder")
    files = sorted(rgb.glob("*.png"))
    if not files:
        raise ValueError("No RGB PNG images found")
    if len(files) > limit:
        indices = (
            [round(i * (len(files) - 1) / (limit - 1)) for i in range(limit)] if limit > 1 else [0]
        )
        files = [files[i] for i in indices]
    mapping = []
    for index, path in enumerate(files):
        if path.is_symlink() or not re.fullmatch(r"[A-Za-z0-9_.-]+\.png", path.name):
            raise ValueError("Unsafe RGB filename")
        with Image.open(path) as image:
            width, height = image.size
            digest = pixel_sha256(image)
        mapping.append(
            {
                "workerImage": f"i{index:06d}.png",
                "sourceImage": path.name,
                "width": width,
                "height": height,
                "rgbPixelSha256": digest,
                "sceneGroup": campaign_group(rgb),
            }
        )
    isolation = validate_split_isolation(
        {
            "knowledge": knowledge_frames(knowledge),
            "localized_test": [
                {"sceneGroup": item["sceneGroup"], "imageHash": item["rgbPixelSha256"]}
                for item in mapping
            ],
        }
    )
    # This is explicitly an oracle-localization coordinator, not the detector.
    truth = references(root / "annotations", mapping)
    private = []
    candidates = []
    for item in mapping:
        payload = truth.get(item["sourceImage"])
        if payload is None:
            raise ValueError("Missing reference annotations for " + item["sourceImage"])
        if (payload.get("width", item["width"]), payload.get("height", item["height"])) != (
            item["width"],
            item["height"],
        ):
            raise ValueError("Reference and RGB dimensions differ")
        for annotation in payload.get("annotations", []):
            if annotation.get("annotationPresent") is False:
                continue
            category = annotation.get("category")
            if not isinstance(category, str) or not category:
                raise ValueError("An annotated instance has no category")
            bbox = crop_box(annotation.get("bbox"), item["width"], item["height"])
            visible = annotation.get("visiblePixels", annotation.get("area"))
            if visible is not None and (not _finite(visible) or visible < 0):
                raise ValueError("Invalid annotated visible-pixel count")
            candidates.append(
                {
                    "frame": item,
                    "bbox": bbox,
                    "expectedCategory": category,
                    "visiblePixels": visible,
                    "instance": annotation.get("instance"),
                }
            )
    # Largest instances first is an explicit diagnostic selection, not a random
    # scientific sample. It does not change the worker's class suggestion.
    candidates.sort(
        key=lambda item: (
            -(
                item["visiblePixels"]
                if item["visiblePixels"] is not None
                else (item["bbox"][2] - item["bbox"][0]) * (item["bbox"][3] - item["bbox"][1])
            ),
            item["frame"]["sourceImage"],
            item["bbox"],
        )
    )
    destination = Path(output) / "input" / "crops"
    destination.mkdir(parents=True, exist_ok=False)
    for index, item in enumerate(candidates[:max_objects]):
        neutral = f"c{index:06d}.png"
        with Image.open(rgb / item["frame"]["sourceImage"]) as image:
            crop = image.convert("RGB").crop(item["bbox"])
        crop.save(destination / neutral)
        private.append(
            {
                "workerCrop": neutral,
                "cropPixelSha256": pixel_sha256(crop),
                "width": crop.width,
                "height": crop.height,
                "sourceFrame": item["frame"],
                "sourceBBoxXYXY": list(item["bbox"]),
                "expectedCategory": item["expectedCategory"],
                "visiblePixels": item["visiblePixels"],
                "instance": item["instance"],
            }
        )
    if not private:
        raise ValueError("No annotated visible instances available")
    coordinator = Path(output) / "coordinator"
    coordinator.mkdir()
    atomic_json(
        coordinator / "private-reference.json",
        {
            "mode": MODE,
            "records": private,
            "selection": "largest visible instances among uniformly spaced selected frames",
            "sourceFrames": mapping,
            "isolation": isolation,
        },
    )
    return private, isolation


def worker(crops, public_knowledge, config_path, output):
    """Read neutral RGB crops and PUBLIC KB only; never references/truth."""
    os.environ.update(
        HF_HUB_OFFLINE="1",
        TRANSFORMERS_OFFLINE="1",
        HF_HUB_DISABLE_TELEMETRY="1",
        TOKENIZERS_PARALLELISM="false",
    )
    import torch
    from PIL import Image
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    from rgb_knowledge import KnowledgeIndex, VisualEncoder, pixel_sha256

    config = json.loads(Path(config_path).read_text())
    validate_config(config)
    model_dir = Path(config["modelDirectory"])
    model_dir = model_dir if model_dir.is_absolute() else ROOT / model_dir
    with (model_dir / "model.safetensors").open("rb") as stream:
        checksum = hashlib.file_digest(stream, "sha256").hexdigest()
    if not config.get("weightsSha256") or checksum != config["weightsSha256"]:
        raise ValueError("The visual encoder requires the pinned local weights checksum")
    torch.set_num_threads(4)
    processor = AutoProcessor.from_pretrained(
        model_dir, local_files_only=True, trust_remote_code=False
    )
    model = AutoModelForZeroShotObjectDetection.from_pretrained(
        model_dir,
        local_files_only=True,
        trust_remote_code=False,
        use_safetensors=True,
        disable_custom_kernels=True,
    ).eval()
    index = KnowledgeIndex.load(public_knowledge)
    encoder = VisualEncoder(model, processor, weights_sha256=checksum)
    if index.encoder_description != encoder.description:
        raise ValueError("Knowledge and worker visual encoders differ")
    if index.weights_sha256 is not None and index.weights_sha256 != checksum:
        raise ValueError("Knowledge and classifier weights differ")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = {}
    start = time.monotonic()
    for path in sorted(Path(crops).glob("*.png")):
        if path.is_symlink() or not re.fullmatch(r"c\d{6}\.png", path.name):
            raise ValueError("Classifier receives neutral crop filenames only")
        with Image.open(path) as image:
            image = image.convert("RGB")
            prediction = classify_crop(image, index, encoder)
            prediction["cropPixelSha256"] = pixel_sha256(image)
        results[path.name] = prediction
        atomic_json(output / (path.stem + ".json"), prediction)
    atomic_json(
        output / "manifest.json",
        {
            "mode": MODE,
            "encoder": encoder.description,
            "weightsSha256": checksum,
            "elapsedSeconds": time.monotonic() - start,
            "knowledgeWeightsVerified": not index.legacy_weights_unverified,
            "cropCount": len(results),
            "inputContract": "neutral RGB crops + PUBLIC visual KB only",
            "osSandbox": False,
            "probabilityCalibrated": False,
            "calibrationApplicable": False,
        },
    )
    return results


def render_gallery(output, report):
    output = Path(output)
    escape = lambda text: html.escape(str(text), quote=True)
    cards = []
    for row in report["rows"]:
        prediction = row["classification"]
        raw = row.get("rawClassification", prediction)
        gate = row.get("geometryQualityGate", {})
        neighbors = []
        for neighbor in prediction.get("neighbors", [])[:3]:
            path = Path(neighbor["crop"])
            if path.is_absolute() or ".." in path.parts or path.parts[:1] != ("crops",):
                raise ValueError("Unsafe knowledge gallery crop path")
            neighbors.append(
                '<figure><img src="knowledge/'
                + escape(path.as_posix())
                + '"><figcaption>'
                + escape(neighbor["category"])
                + " · cosine "
                + escape(f'{neighbor["similarity"]:.3f}')
                + "</figcaption></figure>"
            )
        evaluator = row["evaluator"]
        outcome = (
            "abstention"
            if evaluator["correct"] is None
            else "correct" if evaluator["correct"] else "désaccord"
        )
        cards.append(
            '<article><div class="crop"><img src="input/crops/'
            + escape(row["crop"])
            + '"><p>'
            + escape(row["crop"])
            + "</p></div><div><h2>"
            + escape(prediction["category"])
            + " · "
            + escape(prediction["decision"])
            + "</h2><p>Résultat visuel brut : "
            + escape(raw.get("category"))
            + " · "
            + escape(raw.get("decision"))
            + " · "
            + escape(raw.get("decisionReason"))
            + "</p><p>Contrôle géométrique séparé (après inférence) : "
            + escape(gate.get("status", "non documenté"))
            + " · "
            + escape(gate.get("reason", ""))
            + "</p><p>Décision finale : "
            + escape(prediction["decisionReason"])
            + "</p><p>Cosine : "
            + escape(prediction.get("similarity"))
            + " ; marge : "
            + escape(prediction.get("margin"))
            + '</p><div class="neighbors">'
            + "".join(neighbors)
            + '</div><section class="evaluator"><strong>Évaluateur après classification</strong><p>Référence Unity : '
            + escape(evaluator["referenceCategory"])
            + " · "
            + escape(outcome)
            + " · pixels visibles : "
            + escape(evaluator["visiblePixels"])
            + (
                " · ATTENTION : classe de référence absente de la base de connaissances"
                if evaluator.get("unsupportedCategoryRisk")
                else ""
            )
            + "</p></section></div></article>"
        )
    accuracy = report["accuracyOnDecidedInstances"]
    summary = (
        "Non estimable : aucune décision."
        if accuracy is None
        else f'{report["correctDecidedInstances"]}/{report["decidedInstances"]} classes concordantes parmi les décisions ({100*accuracy:.1f} %).'
    )
    coverage = (
        "Couverture des classes non vérifiée."
        if not report.get("knowledgeCoverageAssessed")
        else (
            "Classes couvertes par les références : "
            + ", ".join(report["coveredKnowledgeClasses"])
            + ". Classes attendues absentes de cette base : "
            + (", ".join(report["expectedClassesMissingFromKnowledge"]) or "aucune")
            + ". Une classe absente ne peut pas être proposée par cette recherche de voisins."
        )
    )
    page = (
        '<!doctype html><html lang="fr"><meta charset="utf-8"><title>Vérification visuelle d’instances</title><style>body{font:16px system-ui;background:#edf3f5;color:#173042;margin:32px}main{max-width:1600px;margin:auto}article{display:grid;grid-template-columns:300px 1fr;gap:24px;background:white;border-radius:12px;padding:22px;margin:20px 0}.crop img{width:280px;height:240px;object-fit:contain;background:#e6edf0}.neighbors{display:flex;gap:16px;flex-wrap:wrap}figure{margin:0}figure img{width:200px;height:160px;object-fit:contain;background:#e6edf0}figcaption{max-width:210px}.warning,.evaluator{padding:14px;background:#fff2cc;border-radius:6px}.evaluator{background:#e7eef7;margin-top:16px}p{line-height:1.5}</style><main><h1>'
        + MODE_FR
        + '</h1><div class="warning">Ce mode vérifie visuellement une classe dans une boîte fournie par Unity. Ce n’est ni une détection indépendante, ni une probabilité de reconnaissance, ni une calibration du détecteur. Les catégories de test ne sont communiquées à l’évaluateur qu’après l’inférence RGB. Le contrôle du nombre de pixels visibles est géométrique et reste distinct de la décision visuelle brute.</div><p>'
        + escape(summary)
        + ' '
        + escape(report["indeterminateInstances"])
        + " abstentions sur "
        + escape(report["instances"])
        + " instances. Sélection diagnostique des plus grandes cibles, pas échantillon statistique.</p><p>"
        + escape(coverage)
        + "</p>"
        + "".join(cards)
        + "</main></html>"
    )
    (output / "index.html").write_text(page, encoding="utf-8")


def run(campaign, knowledge, config_path, output, limit=4, max_objects=12):
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    atomic_json(output / "status.json", {"status": "preparing", "mode": MODE})
    try:
        private, isolation = prepare_instances(campaign, output, knowledge, limit, max_objects)
        knowledge = Path(knowledge).resolve(strict=True)
        public = knowledge if knowledge.name == "public" else knowledge / "public"
        shutil.copytree(public, output / "knowledge")
        config = json.loads(Path(config_path).read_text())
        validate_config(config)
        atomic_json(output / "worker-config.json", config)
        environment = os.environ.copy()
        environment.update(
            HF_HUB_OFFLINE="1",
            TRANSFORMERS_OFFLINE="1",
            HF_HUB_DISABLE_TELEMETRY="1",
            TOKENIZERS_PARALLELISM="false",
            PYTHONDONTWRITEBYTECODE="1",
        )
        command = [
            sys.executable,
            str(Path(__file__).resolve()),
            "--worker",
            "--crops",
            str(output / "input/crops"),
            "--knowledge",
            str(output / "knowledge"),
            "--config",
            str(output / "worker-config.json"),
            "--output",
            str(output / "classifications"),
        ]
        atomic_json(
            output / "status.json",
            {"status": "classifying", "mode": MODE, "instances": len(private)},
        )
        # Deliberately no timeout: the explicitly bounded CPU pilot completes or
        # reports its real error; no model download, remote API or GPU is used.
        subprocess.run(command, check=True, env=environment, cwd=output)
        predictions = {}
        for record in private:
            path = output / "classifications" / (Path(record["workerCrop"]).stem + ".json")
            prediction = json.loads(path.read_text())
            if prediction.get("cropPixelSha256") != record["cropPixelSha256"]:
                raise ValueError("Classified crop and private reference pixel hashes differ")
            predictions[record["workerCrop"]] = prediction
        public_index = json.loads((output / "knowledge/index.json").read_text())
        covered = {example["category"] for example in public_index["examples"]}
        report = evaluate_instances(private, predictions, knowledge_categories=covered)
        report["isolation"] = isolation
        atomic_json(output / "comparison.json", report)
        render_gallery(output, report)
        atomic_json(
            output / "status.json",
            {
                "status": "complete",
                "mode": MODE,
                "instances": len(private),
                "calibrationApplicable": False,
            },
        )
        print("[Localized RGB Verification] COMPLETE: " + str(output / "index.html"), flush=True)
        return output
    except Exception as error:
        atomic_json(output / "status.json", {"status": "failed", "mode": MODE, "error": str(error)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--campaign", type=Path)
    parser.add_argument("--knowledge", required=True, type=Path)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=4)
    parser.add_argument("--max-objects", type=int, default=12)
    parser.add_argument("--worker", action="store_true", help=argparse.SUPPRESS)
    parser.add_argument("--crops", type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        if args.campaign or not args.crops:
            parser.error("Classifier worker only receives neutral crops, no campaign")
        worker(args.crops, args.knowledge, args.config, args.output)
    else:
        if not args.campaign or args.crops:
            parser.error("Choose --campaign for coordinator mode")
        run(args.campaign, args.knowledge, args.config, args.output, args.limit, args.max_objects)


if __name__ == "__main__":
    main()
