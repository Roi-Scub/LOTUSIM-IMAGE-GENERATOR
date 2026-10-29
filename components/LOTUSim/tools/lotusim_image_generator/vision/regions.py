"""Explicit image-space exclusions of the observer, never target annotations.

Normalized polygons are a scoped camera prior, not semantic recognition. A
same-render visible ownship mask is preferred when Unity exports a verified
RGB/mask pair. The RGB used as reference remains untouched.
"""

import copy
import hashlib
from io import BytesIO
import json
import math
from pathlib import Path
import re

SCHEMA = 'lotusim-rgb-search-regions-1'


def _number(value):
    return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def validate_regions(value):
    if not isinstance(value, dict) or set(value) - {
        'schema',
        'coordinateSystem',
        'excludeRegions',
        'profileId',
        'notes',
        'observerMaskSource',
    }:
        raise ValueError('Invalid search-region configuration')
    if value.get('schema') != SCHEMA or value.get('coordinateSystem') != 'normalized_image':
        raise ValueError('Search regions require normalized_image coordinates')
    regions = value.get('excludeRegions', [])
    if not isinstance(regions, list) or len(regions) > 16:
        raise ValueError('At most 16 exclusion polygons are supported')
    for region in regions:
        if not isinstance(region, dict) or set(region) - {'id', 'polygon', 'label'}:
            raise ValueError('Invalid exclusion region')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_-]{0,63}', str(region.get('id', ''))):
            raise ValueError('Invalid exclusion identifier')
        points = region.get('polygon')
        if not isinstance(points, list) or not 3 <= len(points) <= 128:
            raise ValueError('An exclusion polygon requires 3 to 128 points')
        if any(
            not isinstance(p, list)
            or len(p) != 2
            or any(not _number(v) or not 0 <= v <= 1 for v in p)
            for p in points
        ):
            raise ValueError('Exclusion points must be finite normalized coordinates')
        if len({tuple(p) for p in points}) != len(points):
            raise ValueError('Polygon vertices must be unique; do not repeat its first point')
        area = (
            abs(
                sum(
                    points[i][0] * points[(i + 1) % len(points)][1]
                    - points[(i + 1) % len(points)][0] * points[i][1]
                    for i in range(len(points))
                )
            )
            / 2
        )
        if area < 1e-8:
            raise ValueError('Exclusion polygon has no area')
        for i in range(len(points)):
            a, b = points[i], points[(i + 1) % len(points)]
            for j in range(i + 1, len(points)):
                if j in (i, (i + 1) % len(points)) or (j + 1) % len(points) == i:
                    continue
                c, d = points[j], points[(j + 1) % len(points)]
                if (
                    _cross(a, b, c) * _cross(a, b, d) <= 0
                    and _cross(c, d, a) * _cross(c, d, b) <= 0
                ):
                    # Collinear disjoint edges are harmless; crossing/touching
                    # non-adjacent edges are rejected, never silently rasterized.
                    overlap = max(min(a[0], b[0]), min(c[0], d[0])) <= min(
                        max(a[0], b[0]), max(c[0], d[0])
                    ) and max(min(a[1], b[1]), min(c[1], d[1])) <= min(
                        max(a[1], b[1]), max(c[1], d[1])
                    )
                    if overlap:
                        raise ValueError('Self-intersecting exclusion polygon')
    if len({r['id'] for r in regions}) != len(regions):
        raise ValueError('Duplicate exclusion identifiers')
    if value.get('observerMaskSource', 'none') not in ('none', 'unity_observer_visible_depth'):
        raise ValueError('Unsupported observer mask source')
    for key in ('profileId', 'notes'):
        if key in value and (not isinstance(value[key], str) or len(value[key]) > 2048):
            raise ValueError('Invalid region metadata')
    return copy.deepcopy(value)


def empty_policy():
    return {'schema': SCHEMA, 'coordinateSystem': 'normalized_image', 'excludeRegions': []}


def region_signature(policy):
    policy = validate_regions(policy)
    effective = {
        key: policy[key]
        for key in (
            'schema',
            'coordinateSystem',
            'excludeRegions',
            'profileId',
            'observerMaskSource',
        )
        if key in policy
    }
    return hashlib.sha256(
        json.dumps(effective, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
    ).hexdigest()


def exclusion_mask(size, policy, mask_path=None):
    from PIL import Image, ImageChops, ImageDraw

    policy = validate_regions(policy)
    mask = Image.new('L', size, 0)
    draw = ImageDraw.Draw(mask)
    for region in policy['excludeRegions']:
        draw.polygon(
            [(round(u * (size[0] - 1)), round(v * (size[1] - 1))) for u, v in region['polygon']],
            fill=255,
        )
    if mask_path is not None:
        path = Path(mask_path)
        if path.is_symlink():
            raise ValueError('Symlinked observer mask refused')
        with Image.open(path) as source:
            if source.size != size:
                raise ValueError('Observer mask and RGB dimensions differ')
            extra = source.convert('L')
            histogram = extra.histogram()
            if sum(histogram[1:255]):
                raise ValueError('Observer exclusion must be a binary monochrome mask')
        mask = ImageChops.lighter(mask, extra)
    return mask


def masked_rgb(image, mask):
    if mask.size != image.size:
        raise ValueError('Search mask and RGB dimensions differ')
    result = image.convert('RGB').copy()
    result.paste((127, 127, 127), (0, 0), mask)
    return result


def _get(source, path):
    result = source
    for component in path.split('.'):
        if not isinstance(result, dict) or component not in result:
            return None
        result = result[component]
    return result


def profile_matches(config, match):
    if not isinstance(config, dict) or not isinstance(match, dict) or not match:
        return False
    for field, wanted in match.items():
        if field == 'aspectRatio':
            width, height = config.get('width'), config.get('height')
            if not _number(width) or not _number(height) or height <= 0:
                return False
            actual = width / height
        elif field == 'relativeViewHeadingDeg':
            view, route = config.get('viewHeadingDeg'), config.get('routeHeadingDeg')
            if not _number(view) or not _number(route):
                return False
            actual = view - route
        else:
            actual = _get(config, field)
        if _number(wanted):
            if not _number(actual) or abs(wanted - actual) > 1e-4:
                return False
        elif isinstance(wanted, bool):
            if not isinstance(actual, bool) or wanted != actual:
                return False
        elif wanted != actual:
            return False
    return True


def _hash_file(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare_search_inputs(campaign, output, mapping, core, regions_path=None):
    """Stage only explicit regions/ownship masks, never any target annotation."""
    from PIL import Image

    campaign = Path(campaign).resolve()
    output = Path(output)
    core = Path(core)
    explicit = (
        Path(regions_path).resolve(strict=True)
        if regions_path
        else campaign / 'rgb-observer-regions.json'
    )
    if regions_path and not explicit.is_file():
        raise ValueError('Explicit search regions must be a JSON file')
    policy = empty_policy()
    provenance = {'method': 'none', 'legacyApproximation': False, 'warnings': []}
    masks_dir = None
    mask_records = {}
    manifest_file = campaign / 'observer-exclusion.json'
    manifest = None
    if manifest_file.is_file():
        if manifest_file.is_symlink():
            raise ValueError('Symlinked observer manifest refused')
        manifest = json.loads(manifest_file.read_text())
        expected = {
            'schema': 'lotusim-observer-exclusion-1',
            'coordinateSystem': 'image_pixels_top_left',
            'maskDirectory': 'observer-exclusion',
            'foregroundValue': 255,
            'source': 'unity_observer_visible_depth',
            'observerOnly': True,
        }
        if (
            any(manifest.get(k) != v for k, v in expected.items())
            or manifest.get('observerOnly') is not True
        ):
            raise ValueError('Invalid ownship-only mask provenance')
        for record in manifest.get('frames', []):
            if not isinstance(record, dict) or not re.fullmatch(
                r'rgb/[A-Za-z0-9_.-]+\.png', str(record.get('imageFile', ''))
            ):
                raise ValueError('Invalid observer RGB pair')
            if record['imageFile'] in mask_records:
                raise ValueError('Duplicate observer RGB pair')
            mask_records[record['imageFile']] = record
        if not mask_records:
            raise ValueError('Ownship manifest contains no verified frame pairs')
        policy['observerMaskSource'] = 'unity_observer_visible_depth'
        provenance['method'] = 'unity_observer_visible_depth'
    if explicit.is_file():
        policy = validate_regions(json.loads(explicit.read_text()))
        if manifest is not None:
            policy['observerMaskSource'] = 'unity_observer_visible_depth'
        provenance.update(
            method='explicit_polygon' + ('_and_visible_mask' if manifest else ''),
            source=str(explicit),
        )
    elif manifest is None:
        config_file = campaign / 'requested-config.json'
        profiles_file = core / 'assets/perception/rgb_region_profiles.json'
        if config_file.is_file() and profiles_file.is_file():
            config = json.loads(config_file.read_text())
            registry = json.loads(profiles_file.read_text())
            if registry.get('schema') != 'lotusim-rgb-region-profiles-1':
                raise ValueError('Invalid camera region registry')
            candidates = [
                p
                for p in registry.get('profiles', [])
                if profile_matches(config, p.get('match', {}))
            ]
            if len(candidates) > 1:
                raise ValueError('Ambiguous observer camera profiles')
            if candidates:
                policy = validate_regions(candidates[0]['regions'])
                provenance.update(
                    method='matched_camera_polygon',
                    profileId=candidates[0]['id'],
                    legacyApproximation=True,
                )
                provenance['warnings'].append(
                    'Exclusion polygonale approximative liée au profil de caméra ; elle ne remplace pas un masque visible par frame.'
                )
    validate_regions(policy)
    if (
        policy.get('observerMaskSource', 'none') == 'unity_observer_visible_depth'
        and manifest is None
    ):
        raise ValueError('Declared observer masks require their verified frame-pair manifest')
    if manifest is not None:
        masks_dir = output / 'input/observer-exclusion'
        masks_dir.mkdir(parents=True, exist_ok=False)
        provenance['frames'] = []
        for item in mapping:
            name = item['sourceImage']
            record = mask_records.get('rgb/' + name)
            if record is None:
                raise ValueError('Missing verified ownship pair for ' + name)
            if record.get('maskFile') != 'observer-exclusion/' + name:
                raise ValueError('Observer mask must match the source RGB stem')
            source_rgb = campaign / 'rgb' / name
            source_mask = campaign / record['maskFile']
            if (
                source_rgb.is_symlink()
                or source_mask.is_symlink()
                or source_mask.parent.is_symlink()
            ):
                raise ValueError('Symlinked observer pair refused')
            # Read each pair once. Reopening either file after hash validation
            # could silently pair a changed RGB or mask with the staged input.
            rgb_bytes = source_rgb.read_bytes()
            mask_bytes = source_mask.read_bytes()
            if hashlib.sha256(rgb_bytes).hexdigest() != record.get('rgbSha256') or hashlib.sha256(
                mask_bytes
            ).hexdigest() != record.get('maskSha256'):
                raise ValueError('Ownship pair file hash mismatch')
            expected_pixels = item.get('rgbPixelSha256')
            if not isinstance(expected_pixels, str) or not re.fullmatch(
                r'[a-f0-9]{64}', expected_pixels
            ):
                raise ValueError('Staged RGB pixel hash is required for ownship pairing')
            with Image.open(BytesIO(rgb_bytes)) as image:
                if image.size != (item['width'], item['height']):
                    raise ValueError('Ownship source RGB/native dimensions differ')
                if hashlib.sha256(image.convert('RGB').tobytes()).hexdigest() != expected_pixels:
                    raise ValueError('Ownship source RGB differs from staged RGB pixel hash')
            staged_rgb = output / 'input/rgb' / item['workerImage']
            if staged_rgb.is_file():
                if staged_rgb.is_symlink():
                    raise ValueError('Symlinked staged RGB refused')
                with Image.open(BytesIO(staged_rgb.read_bytes())) as image:
                    if image.size != (item['width'], item['height']):
                        raise ValueError('Ownship staged RGB/native dimensions differ')
                    if (
                        hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()
                        != expected_pixels
                    ):
                        raise ValueError('Ownship staged RGB pixel hash mismatch')
            with Image.open(BytesIO(mask_bytes)) as image:
                if image.size != (item['width'], item['height']) or image.size != (
                    manifest.get('width'),
                    manifest.get('height'),
                ):
                    raise ValueError('Ownship manifest/native dimensions differ')
                if sum(image.convert('L').histogram()[1:255]):
                    raise ValueError('Observer exclusion must be a binary monochrome mask')
            neutral = masks_dir / item['workerImage']
            neutral.write_bytes(mask_bytes)
            provenance['frames'].append(
                {
                    'workerImage': item['workerImage'],
                    'maskSha256': record['maskSha256'],
                    'rgbSha256': record['rgbSha256'],
                    'rgbPixelSha256': expected_pixels,
                    'unityFrame': record.get('unityFrame'),
                }
            )
    (output / 'search-regions.json').write_text(json.dumps(policy, ensure_ascii=False, indent=2))
    (output / 'search-region-provenance.json').write_text(
        json.dumps(provenance, ensure_ascii=False, indent=2)
    )
    return {
        'policy': policy,
        'signature': region_signature(policy),
        'masksDirectory': masks_dir,
        'provenance': provenance,
    }
