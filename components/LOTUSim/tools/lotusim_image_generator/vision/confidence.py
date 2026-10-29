"""Empirical precision estimates, not object-recognition probabilities.

Fit ONLY on independent detector predictions matched against held-out Unity
geometry. A record is one prediction, including false positives. Do not fit on
ground-truth crops, missing detections, human recognizability labels, or the
same images used to build the visual knowledge base. False negatives belong
in recall metrics; they are not samples of precision conditional on a score.

The interval is a descriptive Wilson interval for the prediction sample.
Correlated frames/objects violate the independent-Bernoulli assumption: for
scientific inference, also evaluate held-out scenes and use scene bootstrap.
This module intentionally refuses to turn an unsupported raw score into an
apparently calibrated certainty.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Iterable, Mapping
from itertools import combinations
from typing import Any

SCHEMA = "lotusim-rgb-empirical-confidence-1"
BIN_EDGES = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)
CALIBRATION_TARGET = "class-and-IoU>=0.5 against Unity geometry (not human recognition)"
REFERENCE = "held-out detector predictions; empirical precision, not exact probability"
Z_95 = 1.959963984540054


def _score(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("score must be a finite number in [0, 1]")
    value = float(value)
    if not math.isfinite(value) or value < 0.0 or value > 1.0:
        raise ValueError("score must be a finite number in [0, 1]")
    return value


def _text(value: Any, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a non-empty string")
    return value


def _fingerprint(signature: Any, *, optional: bool = False) -> str | None:
    if signature is None:
        if optional:
            return None
        raise ValueError("detector_signature must identify the detector and inference settings")
    if isinstance(signature, str):
        _text(signature, "signature")
    elif not isinstance(signature, Mapping) or not signature:
        raise ValueError("signature must be a non-empty string or JSON object")
    try:
        canonical = json.dumps(
            signature,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        )
    except (ValueError, TypeError) as error:
        raise ValueError("signature must contain finite JSON-serializable values") from error
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _bin_index(score: float) -> int:
    # Left-inclusive, right-exclusive, except the last interval contains 1.
    return next((i for i in range(4) if score < BIN_EDGES[i + 1]), 4)


def wilson_interval(correct: int, support: int) -> tuple[float, float] | None:
    """Return the two-sided 95% Wilson interval as proportions."""
    if (
        isinstance(correct, bool)
        or isinstance(support, bool)
        or not isinstance(correct, int)
        or not isinstance(support, int)
        or support < 0
        or correct < 0
        or correct > support
    ):
        raise ValueError("correct/support must be integer counts with 0 <= correct <= support")
    if support == 0:
        return None
    proportion = correct / support
    z2 = Z_95 * Z_95
    denominator = 1.0 + z2 / support
    center = (proportion + z2 / (2.0 * support)) / denominator
    half_width = (
        Z_95
        * math.sqrt(proportion * (1.0 - proportion) / support + z2 / (4.0 * support * support))
        / denominator
    )
    return max(0.0, center - half_width), min(1.0, center + half_width)


def _empty_bins() -> list[dict[str, Any]]:
    return [
        {
            "lower": BIN_EDGES[i],
            "upper": BIN_EDGES[i + 1],
            "upperInclusive": i == 4,
            "support": 0,
            "correct": 0,
        }
        for i in range(5)
    ]


def _finish_bins(bins: list[dict[str, Any]]) -> None:
    for bucket in bins:
        support, correct = bucket["support"], bucket["correct"]
        interval = wilson_interval(correct, support)
        bucket["empiricalPrecision"] = correct / support if support else None
        bucket["wilson95"] = list(interval) if interval else None


def fit_calibration(
    records: Iterable[Mapping[str, Any]],
    detector_signature: Any,
    knowledge_signature: Any = None,
    min_support: int = 20,
) -> dict[str, Any]:
    """Summarize held-out predictions in fixed score bins.

    Required record fields: score, correct (strict bool), category, sceneGroup,
    imageHash. The latter must hash normalized RGB pixels, not PNG container
    bytes. A source declaring GT/oracle cropping is explicitly rejected.
    min_support applies to the selected category/bin or pooled/bin, never to
    the whole dataset. There is no learned threshold or test-set fitting here.
    """
    if isinstance(min_support, bool) or not isinstance(min_support, int) or min_support < 1:
        raise ValueError("min_support must be a positive integer")
    detector_fingerprint = _fingerprint(detector_signature)
    knowledge_fingerprint = _fingerprint(knowledge_signature, optional=True)
    pooled = _empty_bins()
    categories: dict[str, list[dict[str, Any]]] = {}
    groups: set[str] = set()
    hashes: set[str] = set()
    count = 0
    for index, record in enumerate(records):
        if not isinstance(record, Mapping):
            raise ValueError(f"record {index} must be an object")
        try:
            score = _score(record["score"])
            category = _text(record["category"], "category")
            group = _text(record["sceneGroup"], "sceneGroup")
            image_hash = _text(record["imageHash"], "imageHash")
            correct = record["correct"]
        except KeyError as error:
            raise ValueError(f"record {index} missing required field: {error.args[0]}") from error
        if not isinstance(correct, bool):
            raise ValueError(f"record {index}: correct must be bool, not a score or label")
        declared_source = " ".join(
            str(record.get(k, "")) for k in ("source", "inferenceMode", "localizationSource")
        ).lower()
        if any(
            token in declared_source
            for token in ("ground_truth_crop", "ground-truth crop", "oracle", "gt_crop")
        ):
            raise ValueError("calibration must use independent predictions, not ground-truth crops")
        bucket_index = _bin_index(score)
        category_bins = categories.setdefault(category, _empty_bins())
        for bucket in (pooled[bucket_index], category_bins[bucket_index]):
            bucket["support"] += 1
            bucket["correct"] += int(correct)
        groups.add(group)
        hashes.add(image_hash)
        count += 1
    _finish_bins(pooled)
    for bins in categories.values():
        _finish_bins(bins)
    return {
        "schema": SCHEMA,
        "calibrationTarget": CALIBRATION_TARGET,
        "reference": REFERENCE,
        "detectorSignature": detector_signature,
        "knowledgeSignature": knowledge_signature,
        "detectorFingerprint": detector_fingerprint,
        "knowledgeFingerprint": knowledge_fingerprint,
        "binEdges": list(BIN_EDGES),
        "minSupport": min_support,
        "recordCount": count,
        "sceneGroups": sorted(groups),
        "imageHashes": sorted(hashes),
        "pooled": pooled,
        "categories": categories,
        "intervalMethod": "Wilson two-sided 95%, descriptive prediction-level interval",
        "limitations": [
            "Confidence concerns class plus IoU>=0.5 against geometry, not human recognition.",
            "Pooled fallback may mask class imbalance or class-specific performance.",
            "Nearby frames and multiple objects per scene are correlated; also test on held-out scenes.",
            "Knowledge/calibration/test isolation must be validated before fitting and evaluation.",
        ],
    }


def estimate_confidence(
    score: float,
    category: str,
    calibration: Mapping[str, Any] | None,
    detector_signature: Any = None,
    knowledge_signature: Any = None,
) -> dict[str, Any]:
    """Get observed held-out precision and its interval, or explicit unknown.

    Supplying the current detector and knowledge signatures is mandatory when
    calibration exists. A changed model, threshold, tiling or knowledge base
    invalidates the estimate; the caller must include those in its signatures.
    """
    score = _score(score)
    category = _text(category, "category")
    result = {
        "detectorScore": score,
        "category": category,
        "calibratedConfidencePercent": None,
        "confidenceIntervalPercent": None,
        "status": "uncalibrated",
        "reference": REFERENCE,
        "calibrationTarget": CALIBRATION_TARGET,
        "support": 0,
        "correctCount": 0,
        "calibrationScope": None,
        "scoreBin": [BIN_EDGES[_bin_index(score)], BIN_EDGES[_bin_index(score) + 1]],
    }
    if not calibration:
        result["status"] = "no_calibration"
        return result
    if calibration.get("schema") != SCHEMA or calibration.get("binEdges") != list(BIN_EDGES):
        result["status"] = "invalid_calibration"
        return result
    try:
        current_detector = _fingerprint(detector_signature)
        current_knowledge = _fingerprint(knowledge_signature, optional=True)
    except ValueError:
        result["status"] = "signature_mismatch"
        return result
    if current_detector != calibration.get(
        "detectorFingerprint"
    ) or current_knowledge != calibration.get("knowledgeFingerprint"):
        result["status"] = "signature_mismatch"
        return result
    try:
        index = _bin_index(score)
        minimum = calibration["minSupport"]
        if isinstance(minimum, bool) or not isinstance(minimum, int) or minimum < 1:
            raise ValueError("invalid support")
        category_bins = calibration.get("categories", {}).get(category)
        chosen = category_bins[index] if category_bins else None
        scope = "category"
        if not chosen or chosen["support"] < minimum:
            chosen = calibration["pooled"][index]
            scope = "pooled"
        support, correct = chosen["support"], chosen["correct"]
        interval = wilson_interval(correct, support)
        result.update(support=support, correctCount=correct, calibrationScope=scope)
        if support < minimum:
            result["status"] = "insufficient_support"
            return result
        # Recompute from counts rather than trusting serialized percentages.
        result["calibratedConfidencePercent"] = 100.0 * correct / support
        result["confidenceIntervalPercent"] = [100.0 * value for value in interval]
        result["status"] = (
            "empirical_precision" if scope == "category" else "pooled_empirical_precision"
        )
    except (KeyError, IndexError, TypeError, ValueError):
        result.update(
            calibratedConfidencePercent=None,
            confidenceIntervalPercent=None,
            status="invalid_calibration",
            support=0,
            correctCount=0,
            calibrationScope=None,
        )
    return result


def validate_split_isolation(
    splits: Mapping[str, Iterable[Mapping[str, Any]]],
) -> dict[str, Any]:
    """Reject shared scene groups or normalized pixel hashes across splits.

    Each record needs sceneGroup/imageHash. Multiple detections of one image
    within a split are allowed. Assign the SAME sceneGroup to crops, derived
    sensor modalities, seeds/trajectory replays and related capture sessions.
    Exact pixel hashing does not detect near-duplicate frames by itself.
    """
    if not isinstance(splits, Mapping) or not splits:
        raise ValueError("splits must be a non-empty mapping")
    summary: dict[str, dict[str, Any]] = {}
    for name, records in splits.items():
        _text(name, "split name")
        groups: set[str] = set()
        hashes: set[str] = set()
        count = 0
        for record in records:
            try:
                groups.add(_text(record["sceneGroup"], "sceneGroup"))
                hashes.add(_text(record["imageHash"], "imageHash"))
            except (KeyError, TypeError) as error:
                raise ValueError(
                    f"split {name}: records require sceneGroup and imageHash"
                ) from error
            count += 1
        summary[name] = {"records": count, "groups": groups, "hashes": hashes}
    for first, second in combinations(summary, 2):
        for field, label in (("groups", "sceneGroup"), ("hashes", "imageHash")):
            overlap = summary[first][field] & summary[second][field]
            if overlap:
                raise ValueError(
                    f"split leakage: {first}/{second} share {label}: "
                    + ", ".join(sorted(overlap)[:3])
                )
    return {
        "passed": True,
        "check": "disjoint declared scene groups and normalized pixel hashes",
        "splits": {
            name: {
                "records": data["records"],
                "sceneGroups": len(data["groups"]),
                "imageHashes": len(data["hashes"]),
            }
            for name, data in summary.items()
        },
        "limitation": "Requires correct lineage grouping; hashes alone do not detect near duplicates.",
    }


def validate_disjoint_splits(
    calibration_records: Iterable[Mapping[str, Any]],
    test_records: Iterable[Mapping[str, Any]],
    knowledge_records: Iterable[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    splits = {"calibration": calibration_records, "test": test_records}
    if knowledge_records is not None:
        splits["knowledge"] = knowledge_records
    return validate_split_isolation(splits)
