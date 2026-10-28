"""Audited RGB proposal review: camera exclusions and conservative deduplication.

This module never reads an annotation, pose, asset class or target mask. An
optional exclusion mask is a declared camera prior (for example the observer's
deck). White pixels are ignored. A retained proposal is NOT a verified object;
uncertain proposals remain available, and every rejected original is logged.
Coordinates are native top-left XYWH pixels and are never adjusted here.
"""

from copy import deepcopy
import math


DEFAULT_SETTINGS = {
    "sameClassIou": .55,
    "crossClassIou": .85,
    "fragmentMinContainment": .96,
    "fragmentMinAreaRatio": .5,
    "fragmentMaxCenterDistance": .12,
    "largeAreaFraction": .04,
    "largeMaxScore": .65,
    "rejectExcludedCenter": True,
    "maskOverlapThreshold": .5,
    "minNativePixels": 32,
    "minNativeSide": 4,
}

_NAVAL = {"fishing_trawler", "container_ship", "motor_yacht", "speedboat",
          "jetski", "ferry", "sailboat", "boat", "ship"}
_FAMILIES = {**{category: "naval" for category in _NAVAL},
             "buoy": "buoy", "drone": "drone", "helicopter": "helicopter",
             "airplane": "airplane", "bird": "bird"}


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def validate_settings(settings=None):
    """Return effective settings, refusing unknown keys and non-finite units."""
    if settings is not None and (not isinstance(settings, dict) or set(settings)-set(DEFAULT_SETTINGS)):
        raise ValueError("Invalid or unknown RGB review settings")
    effective = {**DEFAULT_SETTINGS, **(settings or {})}
    for key, value in effective.items():
        if key == "rejectExcludedCenter":
            if not isinstance(value, bool):
                raise ValueError(key+" must be a boolean")
        elif key in {"minNativePixels", "minNativeSide"}:
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise ValueError(key+" must be a positive integer")
        elif not _number(value) or not 0 <= value <= 1:
            raise ValueError(key+" must be finite and in [0, 1]")
        elif key not in {"largeMaxScore", "fragmentMaxCenterDistance"} and value == 0:
            raise ValueError(key+" must be greater than zero")
    return effective


def _area(box):
    return box[2]*box[3]


def _geometry(first, second):
    a, b = first["bbox"], second["bbox"]
    intersection = max(0, min(a[0]+a[2], b[0]+b[2])-max(a[0], b[0])) * max(
        0, min(a[1]+a[3], b[1]+b[3])-max(a[1], b[1]))
    area_a, area_b = _area(a), _area(b)
    union = area_a+area_b-intersection
    center_distance = math.hypot(a[0]+a[2]/2-b[0]-b[2]/2,
                                 a[1]+a[3]/2-b[1]-b[3]/2)
    diagonal = min(math.hypot(a[2], a[3]), math.hypot(b[2], b[3]))
    return {"iou": intersection/union if union else 0,
            "intersectionOverSmaller": intersection/min(area_a, area_b),
            "areaRatio": min(area_a, area_b)/max(area_a, area_b),
            "normalizedCenterDistance": center_distance/diagonal if diagonal else 0}


def _family(prediction):
    # An ambiguous textual label is not silently promoted to a known family.
    return _FAMILIES.get(prediction.get("category"))


def _has_tile_provenance(prediction):
    region = prediction.get("sourceRegion")
    index = prediction.get("regionIndex")
    return (isinstance(region, (list, tuple)) and len(region) == 4
            and all(_number(value) for value in region)
            and region[2] > region[0] and region[3] > region[1]
            and not isinstance(index, bool) and isinstance(index, int) and index >= 0)


def _duplicate(first, second, settings):
    geometry = _geometry(first, second)
    same_class = first["category"] == second["category"]
    if same_class and geometry["iou"] >= settings["sameClassIou"]:
        return "duplicate_same_class", geometry
    if not same_class and geometry["iou"] >= settings["crossClassIou"]:
        return "duplicate_cross_class", geometry
    # A small real target can lie inside a large box. Containment alone must
    # never suppress it. Fragment dedup requires distinct actual input regions,
    # a clipped/touching source edge, comparable sizes and very close centers.
    family = _family(first)
    if (family is not None and family == _family(second)
            and _has_tile_provenance(first) and _has_tile_provenance(second)
            and tuple(first["sourceRegion"]) != tuple(second["sourceRegion"])
            and (first.get("touchesSourceBoundary") is True
                 or second.get("touchesSourceBoundary") is True)
            and geometry["intersectionOverSmaller"] >= settings["fragmentMinContainment"]
            and geometry["areaRatio"] >= settings["fragmentMinAreaRatio"]
            and geometry["normalizedCenterDistance"] <= settings["fragmentMaxCenterDistance"]):
        return "duplicate_tile_fragment", geometry
    return None, geometry


def _mask_evidence(mask, box, width, height):
    center_x, center_y = math.floor(box[0]+box[2]/2), math.floor(box[1]+box[3]/2)
    center_inside = (0 <= center_x < width and 0 <= center_y < height
                     and mask.getpixel((center_x, center_y)) == 255)
    rectangle = (max(0, min(width, math.floor(box[0]))),
                 max(0, min(height, math.floor(box[1]))),
                 max(0, min(width, math.ceil(box[0]+box[2]))),
                 max(0, min(height, math.ceil(box[1]+box[3]))))
    pixels = max(0, rectangle[2]-rectangle[0])*max(0, rectangle[3]-rectangle[1])
    fraction = mask.crop(rectangle).histogram()[255]/pixels if pixels else 0
    return center_inside, fraction


def _validate_prediction(prediction):
    if not isinstance(prediction, dict):
        raise ValueError("A prediction must be a JSON object")
    box = prediction.get("bbox")
    if (not isinstance(box, (list, tuple)) or len(box) != 4
            or not all(_number(value) for value in box) or box[2] <= 0 or box[3] <= 0):
        raise ValueError("A prediction requires a finite positive XYWH bbox")
    if not _number(prediction.get("score")) or not 0 <= prediction["score"] <= 1:
        raise ValueError("A prediction requires a finite score in [0, 1]")
    if not isinstance(prediction.get("category"), str) or not prediction["category"]:
        raise ValueError("A prediction requires a category")


def _alternative(index, prediction):
    return {"originalIndex": index, "category": prediction["category"],
            "score": prediction["score"], "bbox": deepcopy(prediction["bbox"]),
            "textLabel": prediction.get("textLabel")}


def postprocess_predictions(predictions, width, height, exclusion_mask=None, settings=None):
    """Review native RGB proposals, retaining geometry and auditable originals.

    Counts are mutually exclusive: input = retained + uncertain + rejected.
    ``predictions`` contains both retained and uncertain proposals, in descending
    raw-score order. Cross-class near-duplicates keep the strongest original
    box/class and expose alternatives; they are explicitly class-ambiguous.
    """
    settings = validate_settings(settings)
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1
           for value in (width, height)):
        raise ValueError("Native image dimensions must be positive integers")
    if not isinstance(predictions, (list, tuple)):
        raise ValueError("Predictions must be a list or tuple")
    originals = deepcopy(list(predictions))
    for prediction in originals:
        _validate_prediction(prediction)
    mask = None
    if exclusion_mask is not None:
        from PIL import Image
        if not isinstance(exclusion_mask, Image.Image) or exclusion_mask.size != (width, height):
            raise ValueError("Exclusion mask dimensions must match the native RGB")
        # Do not mutate the caller's mask, and define white consistently for
        # binary or anti-aliased user-drawn polygons.
        mask = exclusion_mask.convert("L").point(lambda value: 255 if value >= 128 else 0)
    rejected, retained, groups = [], [], {}
    for original_index in sorted(range(len(originals)), key=lambda index: (-originals[index]["score"], index)):
        original = originals[original_index]
        prediction = deepcopy(original)
        prediction["reviewOriginalIndex"] = original_index
        center_inside, fraction = _mask_evidence(mask, original["bbox"], width, height) if mask else (False, 0)
        prediction["exclusionFraction"] = fraction
        prediction["exclusionCenterInside"] = center_inside
        reject_center = center_inside and settings["rejectExcludedCenter"]
        if reject_center or fraction >= settings["maskOverlapThreshold"]:
            rejected.append({"prediction": deepcopy(original), "originalIndex": original_index,
                "reason": "excluded_center" if reject_center else "excluded_overlap",
                "exclusionFraction": fraction, "exclusionCenterInside": center_inside})
            continue
        duplicate = None
        for representative in retained:
            reason, geometry = _duplicate(original, representative, settings)
            if reason:
                duplicate = representative, reason, geometry
                break
        if duplicate:
            representative, reason, geometry = duplicate
            representative_index = representative["reviewOriginalIndex"]
            rejected.append({"prediction": deepcopy(original), "originalIndex": original_index,
                             "reason": reason, "representativeOriginalIndex": representative_index,
                             **geometry})
            group = groups.setdefault(representative_index, {
                "representativeOriginalIndex": representative_index,
                "memberOriginalIndices": [representative_index], "categories": [representative["category"]],
                "reasons": [],
            })
            group["memberOriginalIndices"].append(original_index)
            if original["category"] not in group["categories"]:
                group["categories"].append(original["category"])
            if reason not in group["reasons"]:
                group["reasons"].append(reason)
            alternatives = representative.setdefault("classAlternatives", [_alternative(representative_index, originals[representative_index])])
            alternatives.append(_alternative(original_index, original))
            if original["category"] != representative["category"]:
                representative["classAmbiguity"] = True
            continue
        retained.append(prediction)
    certain_count = uncertain_count = 0
    for prediction in retained:
        box = prediction["bbox"]
        reasons = []
        if _area(box)/(width*height) > settings["largeAreaFraction"] and prediction["score"] < settings["largeMaxScore"]:
            reasons.append("large_weak_proposal")
        if (prediction["category"] == "unknown" or prediction.get("recognitionDecision") == "indeterminate"):
            reasons.append("ambiguous_or_unrecognizable")
        if _area(box) < settings["minNativePixels"] or min(box[2:]) < settings["minNativeSide"]:
            reasons.append("insufficient_native_pixels")
        if prediction.get("classAmbiguity"):
            reasons.append("ambiguous_class_duplicates")
        if box[0] < 0 or box[1] < 0 or box[0]+box[2] > width or box[1]+box[3] > height:
            reasons.append("box_outside_image")
        prediction["reviewReasons"] = reasons
        prediction["reviewStatus"] = "uncertain" if reasons else "retained"
        certain_count += not bool(reasons)
        uncertain_count += bool(reasons)
    return {"predictions": retained, "review": {
        "schema": "lotusim-rgb-review-1", "settings": settings,
        "coordinateConvention": "native_xywh_pixels_top_left",
        "exclusionApplied": mask is not None,
        "exclusionMeaning": "declared camera exclusion; no target annotations consulted",
        "rejected": rejected, "duplicateGroups": list(groups.values()),
        "counts": {"input": len(originals), "retained": certain_count,
                   "uncertain": uncertain_count, "rejected": len(rejected)},
        "limitations": [
            "Retained does not mean correct, calibrated or human-recognizable.",
            "Near-identical boxes may concern overlapping objects; original proposals remain auditable.",
            "Large weak boxes are uncertain, not silently removed.",
            "Legacy predictions without source-region provenance do not use containment-only deduplication.",
        ],
    }}
