"""Engine-independent scene requests in SI/ENU; no native engine code or I/O."""
import copy
import json
import math

CLASS_IDS = {'buoy': 1, 'drone': 2, 'helicopter': 3, 'airplane': 4, 'bird': 5,
             'fishing_trawler': 6, 'container_ship': 7, 'motor_yacht': 8, 'speedboat': 9,
             'jetski': 10, 'ferry': 11, 'sailboat': 12, 'other': 13}


def _json(value):
    return (json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n').encode('utf-8')


def scene_contract(campaign, identifier, campaign_sha, descriptor, catalogue):
    """Factorized requests stay bounded even for 2,000 images × 40 actors.

    This is not a claim that different engines produce identical random draws,
    radiometry, sea physics or pixels. Existing native recipes are unchanged.
    """
    assets = {item['model']: item for item in catalogue['assets']}
    used = sorted({row['model'] for block in campaign['blocks'] for row in block['objects']})
    models, classes = [], {}
    for key in used:
        record = assets[key]
        category = record['category']
        class_id = record.get('classId', CLASS_IDS.get(category))
        if type(class_id) is not int or not 1 <= class_id <= 255:
            raise ValueError('A stable class identifier is required for ' + key)
        if category in CLASS_IDS and class_id != CLASS_IDS[category]:
            raise ValueError('Class identifier conflicts with the stable category mapping for ' + key)
        if category in classes and classes[category] != class_id:
            raise ValueError('Inconsistent class mapping for ' + category)
        classes[category] = class_id
        binding = {'kind': 'lotusim_model_reference', 'uri': 'model://' + key,
                   'nativeMeshResolved': False, 'license': record.get('license', ''),
                   'sourceUrl': record.get('sourceUrl', '')}
        for field in ('importId', 'revisionSha256', 'requestSha256', 'geometrySha256'):
            if record.get(field):
                binding[field] = record[field]
        if isinstance(record.get('neutralSource'), dict):
            binding['preparedSource'] = copy.deepcopy(record['neutralSource'])
        models.append({'id': key, 'classId': class_id, 'category': category,
                       'domain': record['domain'],
                       'dimensionsM': {name: record.get(name) for name in ('lengthM', 'beamM', 'heightM', 'draftM')},
                       'capabilitiesRequested': {'maxSpeedMps': record.get('maxSpeedMps', 0),
                                                 'maxAltitudeM': record.get('maxAltitudeM', 0)},
                       'sourceBinding': binding,
                       'evidence': record.get('evidence', 'catalogue_assumption')})
    blocks, frame_start = [], 0
    for block in campaign['blocks']:
        placements = []
        for row in block['objects']:
            placements.append({'requestId': row['id'], 'modelId': row['model'],
                               'classId': classes[assets[row['model']]['category']],
                               'instanceIds': ['%s:%s:%02d' % (block['id'], row['id'], index)
                                               for index in range(row['count'])],
                               'horizontalRangeM': row['distanceM'], 'relativeBearingDeg': row['bearingDeg'],
                               'angularSpreadDeg': row['spreadDeg'], 'altitudeM': row['altitudeM'],
                               'speedMps': row['speedMps'], 'headingDeg': row['headingDeg'],
                               'distanceModeRequested': row['distanceMode'],
                               'pixelHeightRequested': row.get('targetHeightPx'),
                               'positionRule': 'cameraHorizontalOriginENU + [range*sin(bearing), range*cos(bearing), absoluteAltitudeM]',
                               'bearingRule': 'observerHeadingDeg + cameraRelativeHeadingDeg + relativeBearingDeg + seededAngularOffset'})
        blocks.append({'id': block['id'], 'name': block['name'], 'firstFrameIndex': frame_start,
                       'frameCount': block['images'], 'environmentRequested': copy.deepcopy(block['environment']),
                       'objects': placements})
        frame_start += block['images']
    camera = campaign['camera']
    fy = camera['height'] / (2 * math.tan(math.radians(camera['verticalFovDeg']) / 2))
    return {'schema': 'lotusim-neutral-scene-contract-1', 'id': identifier,
            'engineProfile': {'id': descriptor['id'], 'label': descriptor['label'], 'mode': descriptor['mode']},
            'campaignSha256': campaign_sha, 'campaignFile': 'campaign.json',
            'coordinates': {'world': 'ENU', 'units': 'SI', 'length': 'metre', 'speed': 'metre_per_second',
                            'eastAxis': '+X', 'northAxis': '+Y', 'upAxis': '+Z',
                            'heading': 'degrees_clockwise_from_north', 'imageOrigin': 'top_left'},
            'sampling': {'seed': campaign['seed'], 'sampleCount': campaign['totalImages'],
                         'imageSemantics': 'independent_seeded_samples', 'factorizedBlocks': True,
                         'frameSeedRule': 'signed32((seed * 397) XOR (frameIndex * 7919))',
                         'angularSampling': 'adapter_owned_seeded_uniform_within_requested_spread',
                         'crossEnginePixelOrRandomDrawParityGuaranteed': False},
            'camera': {'model': 'pinhole', 'widthPx': camera['width'], 'heightPx': camera['height'],
                       'verticalFovDeg': camera['verticalFovDeg'], 'farClipM': camera['farClipM'],
                       'intrinsicsPx': {'fx': fy, 'fy': fy, 'cx': camera['width'] / 2,
                                        'cy': camera['height'] / 2},
                       'relativeHeadingDeg': camera['viewHeadingDeg'],
                       'downPitchDeg': camera['viewDownPitchDeg'],
                       'stationRequested': camera['station'], 'distortion': 'none_requested'},
            'observerRequested': dict(campaign['observer'], model='fremm_observer',
                                      excludeFromAnnotations=True, originENUmetres=[0, 0, 0],
                                      mountResolution='native_adapter_or_explicit_external_binding'),
            'classes': [{'id': value, 'name': key} for key, value in sorted(classes.items(), key=lambda pair: pair[1])],
            'models': models, 'blocks': blocks, 'sensorsRequested': copy.deepcopy(campaign['sensors']),
            'annotationContract': {'automaticAnnotationsProduced': False,
                                   'requiredOutputs': ['rgb_image', 'class_and_instance_id', 'visible_bbox_or_mask',
                                                       'occlusion_fraction', 'recognizability_status'],
                                   'observerExcluded': True,
                                   'recognizabilityThresholds': 'must_be_validated_not_inferred_from_model_identity'},
            'limitations': ['Environment values are requests, not applied native effects or calibrated physics.',
                            'Source references and dimensions do not imply a native mesh binding is installed.',
                            'Frame ranges describe independent images, not continuous engine time or live poses.',
                            'Native adapters retain their existing scene recipes; cross-engine equivalence needs validation.']}


def prepare_neutral(campaign, identifier, campaign_sha, core_root, unity_root, catalogue, descriptor):
    instructions = [
        'This package is a neutral scene contract for ' + descriptor['label'] + ', not a native project or executable scene.',
        'Implement or install a separately trusted adapter for the selected engine. No adapter, plugin, command or user code is loaded from this profile.',
        'Read scene-contract.json and adapter-requirements.json; resolve the declared mesh references, licences, coordinate conversion and camera mount explicitly.',
        'Implement independent samples, requested environments and RGB captures, then verify source hashes and annotation visibility rules.',
        'No engine was started, no image or annotation was generated, and no live LOTUSim/ROS connection was opened.']
    requirements = {'schema': 'lotusim-neutral-adapter-requirements-1', 'engineId': descriptor['id'],
                    'engineLabel': descriptor['label'], 'nativeAdapterImplemented': False,
                    'nativeValidated': False, 'sceneContractFile': 'scene-contract.json',
                    'requiredCapabilities': ['SI_ENU_conversion', 'pinhole_camera', 'mesh_source_resolution',
                                             'independent_seeded_samples', 'environment_mapping', 'rgb_capture',
                                             'visibility_aware_annotations', 'observer_exclusion'],
                    'requestedCapabilities': descriptor['capabilities'],
                    'mustNotInfer': ['native_adapter_from_profile_name', 'recognizability_from_ground_truth_identity',
                                     'calibrated_waves_or_weather', 'cross_engine_pixel_parity'],
                    'automaticExecution': False}
    return {'files': {'adapter-requirements.json': _json(requirements),
                      'engine-instructions.txt': ('\n\n'.join(instructions) + '\n').encode('utf-8')},
            'manifest': {'scenePath': 'scene-contract.json', 'adapterPath': 'tools/neutral_scene_adapter.py',
                         'instructions': instructions, 'runtimeRequirements': ['A separately implemented and trusted native engine adapter'],
                         'nativeValidated': False, 'mode': 'neutral_contract_only',
                         'limitations': ['No native scene, rendering, waves, live poses or annotations are implemented for this engine profile.']}}
