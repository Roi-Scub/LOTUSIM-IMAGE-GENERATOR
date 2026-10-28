#!/usr/bin/env python3
"""Build image references and estimate precision on isolated calibration runs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
from rgb_confidence import fit_calibration, validate_split_isolation
from rgb_observer import ROOT, DEFAULT_CONFIG, knowledge_frames
from rgb_observer_worker import atomic_json, validate_config


def review_existing(args):
    """Review cached RGB hypotheses without claiming a new masked inference."""
    import copy
    import shutil
    from collections import Counter
    from PIL import Image
    from rgb_observer import compare, gallery, pixel_hash
    from rgb_regions import prepare_search_inputs, exclusion_mask
    from rgb_postprocess import postprocess_predictions
    from rgb_observer_worker import render_overlay, effective_review_settings

    source = args.run_folder.resolve(strict=True)
    campaign = args.source.resolve(strict=True)
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    mapping = json.loads((source / 'input-map.json').read_text())
    for item in mapping:
        with Image.open(source / 'input/rgb' / item['workerImage']) as image:
            if (
                image.size != (item['width'], item['height'])
                or pixel_hash(image) != item['rgbPixelSha256']
            ):
                raise ValueError('Cached RGB and input provenance differ')
    shutil.copytree(source / 'input/rgb', output / 'input/rgb')
    if (source / 'knowledge').is_dir():
        shutil.copytree(source / 'knowledge', output / 'knowledge')
    atomic_json(output / 'input-map.json', mapping)
    search = prepare_search_inputs(campaign, output, mapping, ROOT, getattr(args, 'regions', None))
    config_file = getattr(args, 'config', None) or source / 'observer-config.json'
    config = json.loads(Path(config_file).read_text()) if Path(config_file).is_file() else None
    settings = effective_review_settings(config) if config else None
    if search['masksDirectory'] and not search['policy']['excludeRegions']:
        settings = {**(settings or {}), 'rejectExcludedCenter': False, 'maskOverlapThreshold': 1.0}
    predictions = output / 'predictions'
    predictions.mkdir()
    (predictions / 'overlays').mkdir()
    totals = Counter()
    for item in mapping:
        name = item['workerImage']
        stem = Path(name).stem
        prior = json.loads((source / 'predictions' / (stem + '.json')).read_text())
        if prior['rgbPixelSha256'] != item['rgbPixelSha256']:
            raise ValueError('Cached prediction/RGB hash mismatch')
        raw = copy.deepcopy(prior.get('rawPredictions', prior['predictions']))
        dynamic = search['masksDirectory'] / name if search['masksDirectory'] else None
        mask = exclusion_mask((item['width'], item['height']), search['policy'], dynamic)
        result = postprocess_predictions(raw, item['width'], item['height'], mask, settings)
        # Reuse only visual evidence attached to the exact same source box,
        # class and score. No target annotation is used to enrich a proposal.
        key = lambda p: (p['category'], p['score'], tuple(p['bbox']))
        prior_evidence = {key(p): p for p in prior['predictions']}
        for p in result['predictions']:
            previous = prior_evidence.get(key(p), {})
            for field in (
                'semanticEvidence',
                'semanticConflict',
                'recognitionDecision',
                'decisionReason',
            ):
                if field in previous:
                    p[field] = copy.deepcopy(previous[field])
            if previous.get('semanticEvidence'):
                p['semanticEvidenceSource'] = 'cached_matching_rgb_box'
            p['confidenceCalibrated'] = False
            p['calibratedConfidencePercent'] = None
            p['confidenceEvidence'] = {
                'status': 'postprocessing_changed',
                'calibratedConfidencePercent': None,
                'confidenceIntervalPercent': None,
            }
        review = result['review']
        review['excludeRegions'] = search['policy']['excludeRegions']
        matched_scope = prior.get('review', {}).get('searchRegionSignature') == search['signature']
        review['searchExclusionAppliedBeforeInference'] = bool(
            prior.get('searchExclusionAppliedBeforeInference') and matched_scope
        )
        review['searchRegionSignature'] = search['signature']
        if dynamic:
            review['exclusionMask'] = 'input/observer-exclusion/' + name
        totals.update(review['counts'])
        updated = {
            **prior,
            'predictions': result['predictions'],
            'rawPredictions': raw,
            'review': review,
            'postprocessedWithoutInference': True,
            'confidenceCalibrated': False,
            'calibrationApplicable': False,
            'sourceDetectorSignature': prior.get('detectorSignature'),
        }
        updated.pop('detectorSignature', None)
        atomic_json(predictions / (stem + '.json'), updated)
        with Image.open(output / 'input/rgb' / name) as image:
            render_overlay(
                image, [p for p in result['predictions'] if p['reviewStatus'] == 'retained']
            ).save(predictions / 'overlays' / name)
    report = compare(mapping, predictions, campaign / 'annotations')
    atomic_json(output / 'comparison.json', report)
    warnings = [
        'Révision des propositions existantes sans nouvelle inférence. Le JSON indique si cette même exclusion était déjà appliquée à l’entrée du modèle source.',
        'Les cadres ambigus sont masqués par défaut, mais restent dans les métriques et les JSON. Retenue ne signifie pas identification validée.',
    ] + search['provenance']['warnings']
    atomic_json(
        output / 'run-manifest.json',
        {
            'schema': 'lotusim-rgb-cached-review-1',
            'role': 'postprocessed_review',
            'sourceRun': str(source),
            'analyzedImages': len(mapping),
            'postprocessedWithoutInference': True,
            'counts': dict(totals),
            'searchRegions': search['provenance'],
            'warnings': warnings,
        },
    )
    atomic_json(
        predictions / 'manifest.json',
        {
            'schema': 'lotusim-rgb-cached-review-1',
            'status': 'complete',
            'calibrationApplicable': False,
        },
    )
    atomic_json(
        output / 'agent-events.json',
        [{'agent': 'proposal_reviewer', 'state': 'complete', 'cachedImages': len(mapping)}],
    )
    atomic_json(
        output / 'status.json',
        {'status': 'complete', 'images': len(mapping), 'postprocessedWithoutInference': True},
    )
    gallery(output, mapping, report, warnings)
    print(
        json.dumps(
            {'output': str(output), 'counts': dict(totals), 'newInference': False},
            ensure_ascii=False,
            indent=2,
        )
    )


def report_existing(args):
    from rgb_observer import compare, gallery

    output = args.run_folder.resolve()
    mapping = json.loads((output / 'input-map.json').read_text())
    report = compare(mapping, output / 'predictions', args.source.resolve() / 'annotations')
    atomic_json(output / 'comparison.json', report)
    manifest = (
        json.loads((output / 'run-manifest.json').read_text())
        if (output / 'run-manifest.json').is_file()
        else {
            'role': 'test',
            'warnings': [
                'Rapport repris après correction de l’adaptateur de références. Prédictions conservées sans nouvelle inférence.'
            ],
        }
    )
    manifest.setdefault('schema', 'lotusim-visual-agent-pipeline-1')
    manifest.setdefault(
        'sourceFrameCount', len(list((args.source.resolve() / 'rgb').glob('*.png')))
    )
    manifest.setdefault('analyzedImages', len(mapping))
    manifest.setdefault('preview', len(mapping) < manifest['sourceFrameCount'])
    manifest.setdefault('sceneGroups', sorted({i['sceneGroup'] for i in mapping}))
    manifest.setdefault('reportResumedWithoutInference', True)
    atomic_json(
        output / 'calibration-records.json',
        {
            'role': manifest.get('role', 'test'),
            'records': report['calibrationRecords'],
            'reference': report['reference'],
        },
    )
    atomic_json(output / 'run-manifest.json', manifest)
    gallery(output, mapping, report, manifest.get('warnings', []))
    atomic_json(
        output / 'status.json',
        {'status': 'complete', 'images': len(mapping), 'reportResumedWithoutInference': True},
    )
    from datetime import datetime, timezone

    events_file = output / 'agent-events.json'
    events = json.loads(events_file.read_text()) if events_file.is_file() else []
    events.append(
        {
            'agent': 'reporter',
            'state': 'complete',
            'at': datetime.now(timezone.utc).isoformat(),
            'reportResumedWithoutInference': True,
            'images': len(mapping),
        }
    )
    atomic_json(events_file, events)
    print(
        json.dumps(
            {
                key: report[key]
                for key in (
                    'truePositives',
                    'falsePositives',
                    'falseNegatives',
                    'precision',
                    'recall',
                )
            },
            indent=2,
        )
    )


def build(args):
    os.environ.update(
        HF_HUB_OFFLINE='1',
        TRANSFORMERS_OFFLINE='1',
        HF_HUB_DISABLE_TELEMETRY='1',
        TOKENIZERS_PARALLELISM='false',
    )
    import torch
    from transformers import AutoProcessor, AutoModelForZeroShotObjectDetection
    from rgb_knowledge import VisualEncoder, build_knowledge

    config = json.loads(args.config.read_text())
    validate_config(config)
    model_dir = Path(config['modelDirectory'])
    model_dir = model_dir if model_dir.is_absolute() else ROOT / model_dir
    with (model_dir / 'model.safetensors').open('rb') as stream:
        digest = hashlib.file_digest(stream, 'sha256').hexdigest()
    if config.get('weightsSha256') and digest != config['weightsSha256']:
        raise ValueError('Model checksum mismatch')
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
    manifest = build_knowledge(
        args.source,
        args.output,
        VisualEncoder(model, processor, weights_sha256=digest),
        config['categories'],
        min_area=args.min_area,
        max_per_class=args.max_per_class,
    )
    manifest['weightsSha256'] = digest
    atomic_json(args.output / 'manifest.json', manifest)
    index = json.loads((args.output / 'public/index.json').read_text())
    import html

    cards = ''.join(
        '<figure><img width="200" height="160" style="object-fit:contain" src="public/'
        + html.escape(e['crop'])
        + '"><figcaption>'
        + html.escape(e['category'])
        + '</figcaption></figure>'
        for e in index['examples']
    )
    (args.output / 'index.html').write_text(
        '<!doctype html><meta charset="utf-8"><title>Base de références visuelles</title><body style="font:16px system-ui"><h1>Base de connaissances visuelle</h1><p>Images propres + classes géométriques Unity. Références distinctes des images de test. Les images non annotées ne reçoivent aucune classe inventée.</p><pre>'
        + html.escape(json.dumps(manifest, ensure_ascii=False, indent=2))
        + '</pre><main style="display:flex;flex-wrap:wrap">'
        + cards
        + '</main></body>'
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    print(args.output / 'index.html')


def calibrate(args):
    records = []
    all_frames = []
    detector = None
    knowledge = None
    for folder in args.run:
        run = json.loads((folder / 'run-manifest.json').read_text())
        if run.get('role') != 'calibration':
            raise ValueError('Only explicitly designated calibration runs may fit calibration')
        manifest = json.loads((folder / 'predictions/manifest.json').read_text())
        if manifest.get('coverageLimited'):
            raise ValueError('Incomplete region coverage cannot fit calibration')
        current = (manifest['detectorSignature'], manifest.get('knowledgeSignature'))
        if detector is None:
            detector, knowledge = current
        elif current != (detector, knowledge):
            raise ValueError('Calibration runs must use identical model/tiling/knowledge')
        records += json.loads((folder / 'calibration-records.json').read_text())['records']
        all_frames += [
            {'sceneGroup': i['sceneGroup'], 'imageHash': i['rgbPixelSha256']}
            for i in json.loads((folder / 'input-map.json').read_text())
        ]
    known = knowledge_frames(args.knowledge) if args.knowledge else []
    validate_split_isolation({'knowledge': known, 'calibration': all_frames})
    result = fit_calibration(records, detector, knowledge, min_support=args.min_support)
    result['sceneGroups'] = sorted({i['sceneGroup'] for i in all_frames})
    result['imageHashes'] = sorted({i['imageHash'] for i in all_frames})
    result['calibrationImages'] = len(all_frames)
    result['lineageIncludesZeroDetectionFrames'] = True
    result['independentSceneGroups'] = len(result['sceneGroups'])
    result['experimentalStatus'] = 'pilot_descriptive_only'
    result['humanRecognitionValidated'] = False
    if args.output.exists():
        raise FileExistsError('Choose a new calibration filename')
    atomic_json(args.output, result)
    print(
        json.dumps(
            {
                'predictions': result['recordCount'],
                'groups': result['sceneGroups'],
                'minSupportPerBin': result['minSupport'],
                'file': str(args.output),
                'warning': 'Descriptive empirical precision against Unity geometry, not individual/human recognition certainty',
            },
            indent=2,
        )
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    p = sub.add_parser('knowledge')
    p.add_argument('--source', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--config', type=Path, default=DEFAULT_CONFIG)
    p.add_argument('--min-area', type=int, default=256)
    p.add_argument('--max-per-class', type=int, default=8)
    p.set_defaults(func=build)
    p = sub.add_parser('calibrate')
    p.add_argument('--run', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--knowledge', type=Path)
    p.add_argument('--min-support', type=int, default=20)
    p.set_defaults(func=calibrate)
    p = sub.add_parser('report')
    p.add_argument('--run-folder', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True, help='Original campaign folder')
    p.set_defaults(func=report_existing)
    p = sub.add_parser('review')
    p.add_argument('--run-folder', type=Path, required=True)
    p.add_argument('--source', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--regions', type=Path)
    p.add_argument('--config', type=Path)
    p.set_defaults(func=review_existing)
    args = parser.parse_args()
    args.func(args)


if __name__ == '__main__':
    main()
