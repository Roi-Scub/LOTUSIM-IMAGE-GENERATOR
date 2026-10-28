#!/usr/bin/env python3
"""Image-only visual agents: stage, infer, audit, compare and present.

Unity's existing CLI is preserved. Knowledge is learned from separate clean RGB
references. Test annotations are read ONLY after independent inference. A model
score or a visual similarity is never presented as a calibrated probability.
"""

import argparse
from collections import Counter
from datetime import datetime, timezone
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
import uuid

from rgb_observer_worker import atomic_json, iou, validate_config
from rgb_confidence import validate_split_isolation, validate_disjoint_splits
from rgb_lineage import campaign_group
from rgb_regions import prepare_search_inputs
from ops_runtime import OpsRuntime

ROOT = Path(os.environ.get('LOTUSIM_CORE_ROOT', Path(__file__).resolve().parents[1]))
DEFAULT_CONFIG = ROOT / 'assets/perception/rgb_observer.json'
DEFAULT_PLAN = ROOT / 'assets/perception/rgb_validation.json'
_OPS_RUNTIMES = {}


def pixel_hash(image):
    return hashlib.sha256(image.convert('RGB').tobytes()).hexdigest()


def stage(rgb, output, limit=0, sampling='first'):
    from PIL import Image

    rgb = Path(rgb).resolve(strict=True)
    if not rgb.is_dir() or rgb.name not in {'rgb', 'gazebo-rgb'}:
        raise ValueError('Select the CLEAN rgb/ folder, never overlays, masks or annotations')
    files = sorted(rgb.glob('*.png'))
    if not files:
        raise ValueError('No clean PNG images found')
    if limit and len(files) > limit:
        indices = (
            [round(i * (len(files) - 1) / (limit - 1)) for i in range(limit)]
            if sampling == 'uniform' and limit > 1
            else list(range(limit))
        )
        files = [files[i] for i in indices]
    destination = Path(output) / 'input/rgb'
    destination.mkdir(parents=True, exist_ok=False)
    mapping = []
    for index, path in enumerate(files):
        if path.is_symlink() or not re.fullmatch(r'[A-Za-z0-9_.-]+\.png', path.name):
            raise ValueError('Unsafe RGB filename refused')
        with Image.open(path) as source:
            image = source.convert('RGB')
        neutral = f'i{index:06d}.png'
        image.save(destination / neutral)
        mapping.append(
            {
                'workerImage': neutral,
                'sourceImage': path.name,
                'width': image.width,
                'height': image.height,
                'rgbPixelSha256': pixel_hash(image),
                'sceneGroup': campaign_group(rgb),
            }
        )
    atomic_json(Path(output) / 'input-map.json', mapping)
    return mapping


def references(truth_folder, mapping):
    """Read sidecars or COCO, after inference. Missing references remain missing."""
    truth_folder = Path(truth_folder)
    root = truth_folder.parent
    fallback = {}
    coco_file = root / 'annotations.coco.json'
    if coco_file.is_file():
        coco = json.loads(coco_file.read_text())
        cats = {c['id']: c['name'] for c in coco.get('categories', [])}
        image_map = {i['id']: i for i in coco.get('images', [])}
        for image in image_map.values():
            fallback[Path(image['file_name']).name] = {
                'width': image['width'],
                'height': image['height'],
                'annotations': [],
            }
        for a in coco.get('annotations', []):
            image = image_map.get(a.get('image_id'))
            if image:
                fallback[Path(image['file_name']).name]['annotations'].append(
                    {
                        **a,
                        'category': cats.get(a.get('category_id'), 'unknown'),
                        'visiblePixels': a.get('area'),
                    }
                )
    result = {}
    for item in mapping:
        path = truth_folder / (Path(item['sourceImage']).stem + '.json')
        payload = (
            json.loads(path.read_text()) if path.is_file() else fallback.get(item['sourceImage'])
        )
        if payload is not None and payload.get('schema') == 'lotusim-instance-geometry-1':
            # First buoy campaigns use a single-instance sidecar, without image
            # dimensions; the paired COCO image supplies those dimensions.
            base = fallback.get(item['sourceImage'], {})
            payload = {
                'width': base.get('width', item['width']),
                'height': base.get('height', item['height']),
                'annotations': (
                    [payload] if payload.get('annotationPresent') and payload.get('bbox') else []
                ),
            }
        result[item['sourceImage']] = payload
    return result


def compare(mapping, predictions, truth_folder, threshold=0.5):
    if (
        isinstance(threshold, bool)
        or not isinstance(threshold, (int, float))
        or not math.isfinite(threshold)
        or not 0 < threshold <= 1
    ):
        raise ValueError('IoU threshold must be in (0,1]')
    refs_by_image = references(truth_folder, mapping)
    results = []
    tp = fp = fn = 0
    by_status = {}
    by_class = {}
    by_size = {}
    calibration_records = []
    missing = []
    for item in mapping:
        prediction = json.loads(
            (Path(predictions) / (Path(item['workerImage']).stem + '.json')).read_text()
        )
        if prediction['rgbPixelSha256'] != item['rgbPixelSha256']:
            raise ValueError('Prediction/RGB pixel hash mismatch')
        truth = refs_by_image[item['sourceImage']]
        if truth is None:
            missing.append(item['sourceImage'])
            continue
        if truth['width'] != item['width'] or truth['height'] != item['height']:
            raise ValueError('Reference/native RGB dimensions differ')
        refs = truth.get('annotations', [])
        available = set(range(len(refs)))
        matches = []
        diagnostics = []
        for p in sorted(prediction['predictions'], key=lambda p: p['score'], reverse=True):
            candidates = [
                (iou(p['bbox'], refs[i]['bbox']), i)
                for i in available
                if refs[i]['category'] == p['category']
            ]
            best = max(candidates, default=(0, -1))
            correct = best[0] >= threshold
            stat = by_class.setdefault(p['category'], {'tp': 0, 'fp': 0, 'fn': 0})
            if correct:
                _, index = best
                available.remove(index)
                tp += 1
                stat['tp'] += 1
                matches.append({'prediction': p, 'referenceIndex': index, 'iou': best[0]})
                state = refs[index].get('recognitionStatus', 'unassessed')
                by_status.setdefault(state, {'matched': 0, 'missed': 0})['matched'] += 1
            else:
                fp += 1
                stat['fp'] += 1
                overlap = max(
                    [(iou(p['bbox'], r['bbox']), r['category']) for r in refs], default=(0, None)
                )
                diagnostics.append(
                    {
                        'prediction': p,
                        'bestAnyClassIou': overlap[0],
                        'nearestReferenceClass': overlap[1],
                        'reason': (
                            'class_or_localization_mismatch'
                            if overlap[0] > 0
                            else 'unmatched_detection_or_unannotated_foreground'
                        ),
                    }
                )
            calibration_records.append(
                {
                    'score': p['score'],
                    'correct': correct,
                    'category': p['category'],
                    'sceneGroup': item.get('sceneGroup', str(Path(truth_folder).parent)),
                    'imageHash': item['rgbPixelSha256'],
                    'localizationSource': 'independent_rgb_detector',
                }
            )
        matched_indices = {m['referenceIndex'] for m in matches}
        for index, r in enumerate(refs):
            state = r.get('recognitionStatus', 'unassessed')
            pixels = r.get('visiblePixels', r['bbox'][2] * r['bbox'][3])
            pixels = pixels if isinstance(pixels, (int, float)) else r['bbox'][2] * r['bbox'][3]
            bucket = (
                'under_32_pixels'
                if pixels < 32
                else '32_to_255_pixels' if pixels < 256 else '256_plus_pixels'
            )
            stat = by_size.setdefault(bucket, {'referenceObjects': 0, 'matched': 0})
            stat['referenceObjects'] += 1
            stat['matched'] += int(index in matched_indices)
            if index in available:
                by_status.setdefault(state, {'matched': 0, 'missed': 0})['missed'] += 1
                by_class.setdefault(r['category'], {'tp': 0, 'fp': 0, 'fn': 0})['fn'] += 1
        fn += len(available)
        results.append(
            {
                'image': item['sourceImage'],
                'predictions': len(prediction['predictions']),
                'referenceObjects': len(refs),
                'matched': len(matches),
                'missedReferenceIndices': sorted(available),
                'matches': matches,
                'falsePositiveDiagnostics': diagnostics,
            }
        )
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    return {
        'schema': 'lotusim-rgb-observer-comparison-2',
        'reference': 'Unity geometric ground truth, NOT manual human recognition',
        'matching': 'greedy descending confidence, class-aware IoU',
        'iouThreshold': threshold,
        'truePositives': tp,
        'falsePositives': fp,
        'falseNegatives': fn,
        'precision': precision,
        'recall': recall,
        'f1': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None,
        'byReferenceRecognitionStatus': by_status,
        'byCategory': by_class,
        'byVisiblePixelSize': by_size,
        'frames': results,
        'missingReferenceImages': missing,
        'calibrationRecords': calibration_records,
    }


def load_plan(path=None):
    file = Path(path) if path else DEFAULT_PLAN
    return json.loads(file.read_text()) if file.is_file() else {}


def knowledge_frames(directory):
    if not directory:
        return []
    directory = Path(directory)
    root = directory.parent if directory.name == 'public' else directory
    path = root / 'coordinator/provenance.json'
    if not path.is_file():
        raise ValueError('Knowledge provenance is missing; cannot verify test isolation')
    frames = json.loads(path.read_text())['frames']
    records = []
    for r in frames:
        for group in {campaign_group(Path(r['path']).parent), r['group']}:
            records.append({'sceneGroup': group, 'imageHash': r['rgbPixelSha256']})
    return records


def _safe_knowledge(directory, output):
    """Worker receives only the curated public examples, never provenance paths."""
    if not directory:
        return None
    directory = Path(directory)
    public = directory if directory.name == 'public' else directory / 'public'
    destination = Path(output) / 'knowledge'
    shutil.copytree(public, destination)
    return destination


def _event(output, events, agent, state, **details):
    events.append(
        {'agent': agent, 'state': state, 'at': datetime.now(timezone.utc).isoformat(), **details}
    )
    atomic_json(Path(output) / 'agent-events.json', events)
    atomic_json(Path(output) / 'status.json', {'status': state, 'agent': agent, **details})
    key = str(Path(output).resolve())
    if key not in _OPS_RUNTIMES:
        _OPS_RUNTIMES[key] = OpsRuntime(Path(output) / 'runtime.json', 'rgb_coordinator')
    runtime = _OPS_RUNTIMES[key]
    runtime.event({'agent': agent, 'state': state})
    runtime.update(
        state, currentAgent=agent, expected=details.get('expected', details.get('images'))
    )
    if state in ('complete', 'failed'):
        _OPS_RUNTIMES.pop(key, None)


def gallery(output, mapping, report=None, warnings=None):
    from rgb_visual_gallery import render_gallery

    render_gallery(Path(output), mapping, report, warnings or [])


def run(
    rgb,
    output,
    config_path=DEFAULT_CONFIG,
    limit=0,
    evaluate=False,
    via_gazebo=False,
    knowledge=None,
    calibration=None,
    role='test',
    sampling='first',
    strict_transport=False,
    plan_path=None,
    regions=None,
):
    rgb = Path(rgb)
    config = json.loads(Path(config_path).read_text())
    validate_config(config)
    plan = load_plan(plan_path)
    if output is None:
        stamp = datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S') + '_' + uuid.uuid4().hex[:8]
        output = rgb.resolve().parent / 'visual-observer' / stamp
    output = Path(output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    events = []
    warnings = []
    try:
        _event(output, events, 'orchestrator', 'staging', role=role)
        mapping = stage(rgb, output, limit, sampling)
        search = prepare_search_inputs(rgb.resolve().parent, output, mapping, ROOT, regions)
        config['searchRegionSignature'] = search['signature']
        warnings += search['provenance']['warnings']
        # Scene/pixel isolation is checked before reading any test annotation.
        kb = (
            Path(knowledge)
            if knowledge
            else ROOT / plan['knowledgeDirectory'] if plan.get('knowledgeDirectory') else None
        )
        if kb and not kb.exists():
            warnings.append(
                'Base visuelle absente : détection seule. Construire la base avant la prochaine analyse.'
            )
            kb = None
        known = knowledge_frames(kb)
        image_records = [
            {'sceneGroup': i['sceneGroup'], 'imageHash': i['rgbPixelSha256']} for i in mapping
        ]
        validate_split_isolation({'knowledge': known, role: image_records})
        cal_payload = json.loads(Path(calibration).read_text()) if calibration else None
        if cal_payload and role == 'calibration':
            raise ValueError(
                'Do not apply calibration while collecting its own reference predictions'
            )
        if cal_payload:
            if len(cal_payload.get('sceneGroups', [])) < 3:
                warnings.append(
                    'Calibration pilote sur moins de trois groupes de scènes : précision descriptive, pas probabilité de sûreté validée.'
                )
            calibrator_records = [
                {'sceneGroup': g, 'imageHash': 'calibration-group-' + g}
                for g in cal_payload.get('sceneGroups', [])
            ]
            calibrator_records += [
                {'sceneGroup': 'calibration-hash-only', 'imageHash': h}
                for h in cal_payload.get('imageHashes', [])
            ]
            validate_disjoint_splits(calibrator_records, image_records, known)
        transport = {'requested': via_gazebo, 'used': 'direct_rgb', 'fallback': False}
        if via_gazebo:
            _event(output, events, 'transport', 'transporting', images=len(mapping))
            try:
                from rgb_gazebo import roundtrip

                received = roundtrip(output / 'input/rgb', output / 'transport')
                proof = json.loads((output / 'transport/transport-proof.json').read_text())
                received_map = {r['source']: r['received'] for r in proof['records']}
                for item in mapping:
                    shutil.copyfile(
                        received / received_map[item['workerImage']],
                        output / 'input/rgb' / item['workerImage'],
                    )
                transport['used'] = 'gazebo_transport'
            except (OSError, ValueError, ImportError, subprocess.SubprocessError) as error:
                if strict_transport:
                    raise
                transport.update(fallback=True, error=str(error))
                warnings.append(
                    'Gazebo indisponible : repli explicite sur RGB direct, pixels inchangés.'
                )
        atomic_json(output / 'transport-status.json', transport)
        safe_kb = _safe_knowledge(kb, output)
        atomic_json(output / 'observer-config.json', config)
        model = Path(config['modelDirectory'])
        model = model if model.is_absolute() else ROOT / model
        environment = os.environ.copy()
        environment.update(
            HF_HUB_OFFLINE='1',
            TRANSFORMERS_OFFLINE='1',
            HF_HUB_DISABLE_TELEMETRY='1',
            TOKENIZERS_PARALLELISM='false',
            PYTHONDONTWRITEBYTECODE='1',
        )
        command = [
            sys.executable,
            str(Path(__file__).with_name('rgb_observer_worker.py')),
            '--rgb',
            str(output / 'input/rgb'),
            '--output',
            str(output / 'predictions'),
            '--config',
            str(output / 'observer-config.json'),
            '--model-directory',
            str(model),
        ]
        if safe_kb:
            command += ['--knowledge', str(safe_kb)]
        command += ['--regions', str(output / 'search-regions.json')]
        if search['masksDirectory']:
            command += ['--observer-masks', str(search['masksDirectory'])]
        if calibration:
            command += ['--calibration', str(Path(calibration).resolve())]
        _event(output, events, 'rgb_detector', 'inferencing', expected=len(mapping))
        subprocess.run(
            command, env=environment, check=True, cwd=output, timeout=max(900, 240 * len(mapping))
        )
        report = None
        if evaluate:
            _event(
                output,
                events,
                'independent_evaluator',
                'evaluating',
                reference='Unity geometry only, not human recognition',
            )
            report = compare(mapping, output / 'predictions', rgb.resolve().parent / 'annotations')
            if len(report['missingReferenceImages']) == len(mapping):
                warnings.append(
                    'Aucune annotation de référence : prédictions disponibles, évaluation omise.'
                )
                report = None
            elif report['missingReferenceImages']:
                warnings.append('Évaluation partielle : certaines images n’ont pas de référence.')
            if report is not None:
                atomic_json(output / 'comparison.json', report)
                atomic_json(
                    output / 'calibration-records.json',
                    {
                        'role': role,
                        'records': report['calibrationRecords'],
                        'reference': report['reference'],
                    },
                )
        atomic_json(
            output / 'run-manifest.json',
            {
                'schema': 'lotusim-visual-agent-pipeline-1',
                'role': role,
                'sourceFrameCount': len(list(rgb.glob('*.png'))),
                'analyzedImages': len(mapping),
                'preview': len(mapping) < len(list(rgb.glob('*.png'))),
                'sceneGroups': sorted({i['sceneGroup'] for i in mapping}),
                'knowledgeUsed': safe_kb is not None,
                'transport': transport,
                'warnings': warnings,
                'searchRegions': search['provenance'],
                'agentContract': 'clean RGB plus explicit observer-only scope exclusions and public references; target annotations accessed by evaluator only after inference',
                'confidenceMeaning': 'raw model score != similarity != estimated precision; no unsupported certainty',
            },
        )
        _event(output, events, 'reporter', 'reporting', images=len(mapping))
        gallery(output, mapping, report, warnings)
        _event(output, events, 'orchestrator', 'complete', images=len(mapping), warnings=warnings)
        print('[RGB Observer] COMPLETE: ' + str(output / 'index.html'), flush=True)
    except Exception as error:
        _event(output, events, 'orchestrator', 'failed', error=str(error))
        try:
            gallery(
                output,
                (
                    json.loads((output / 'input-map.json').read_text())
                    if (output / 'input-map.json').is_file()
                    else []
                ),
                None,
                [str(error)],
            )
        except Exception:
            pass
        raise
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--rgb', required=True, type=Path)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--config', type=Path)
    parser.add_argument('--plan', type=Path)
    parser.add_argument(
        '--limit', type=int, default=None, help='0=all images; otherwise bounded preview'
    )
    parser.add_argument('--sampling', choices=['first', 'uniform'], default='uniform')
    parser.add_argument('--all', action='store_true')
    parser.add_argument('--compare', action='store_true')
    parser.add_argument('--via-gazebo', action='store_true')
    parser.add_argument('--strict-transport', action='store_true')
    parser.add_argument('--knowledge', type=Path)
    parser.add_argument('--calibration', type=Path)
    parser.add_argument('--role', choices=['calibration', 'test'], default='test')
    parser.add_argument(
        '--regions',
        type=Path,
        help='Explicit normalized exclusion polygons; otherwise camera profile or exported observer masks',
    )
    args = parser.parse_args()
    plan = load_plan(args.plan)
    limit = (
        0 if args.all else args.limit if args.limit is not None else plan.get('previewLimit', 12)
    )
    if limit < 0:
        parser.error('limit must be non-negative')
    config = args.config or (
        ROOT / plan['detectorConfig'] if plan.get('detectorConfig') else DEFAULT_CONFIG
    )
    run(
        args.rgb,
        args.output,
        config,
        limit,
        args.compare,
        args.via_gazebo,
        args.knowledge,
        args.calibration,
        args.role,
        args.sampling,
        args.strict_transport,
        args.plan,
        args.regions,
    )


if __name__ == '__main__':
    main()
