"""Deterministic offline roles dispatched only to repository-owned adapters."""

import json
from pathlib import Path
import re

from engine_registry import (
    EngineRegistry,
    PREPARED_FILES,
    UNITY_ADAPTER,
    UNITY_SCENE,
    UNREAL_SCENE,
    expected_artifacts,
    _runtime_candidates,
)
from neutral_scene_adapter import prepare_neutral, scene_contract
from unity_scene_adapter import prepare_unity

SCHEMA = 'lotusim-render-engine-agent-1'
_UUID = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$')


def _json(value):
    return (
        json.dumps(value, ensure_ascii=False, allow_nan=False, sort_keys=True, indent=2) + '\n'
    ).encode('utf-8')


def engine_catalog(core_root, unity_root=None):
    """Compatibility entry point; profiles are centralized in EngineRegistry."""
    entries = EngineRegistry(core_root, unity_root).catalog()['engines']
    for item in entries:
        item['runtimeDetected'] = any(
            path.is_file()
            for path in _runtime_candidates(
                item['id'], Path(unity_root) if unity_root is not None else None
            )
        )
    return entries


def _unity(campaign, identifier, campaign_sha, core_root):
    """Compatibility alias; Unity-specific code lives in its trusted adapter."""
    return prepare_unity(campaign, identifier, campaign_sha, core_root)


def _prepare_unreal(*args, **kwargs):
    from unreal_scene_adapter import prepare_unreal

    return prepare_unreal(*args, **kwargs)


_ADAPTERS = {'unity': prepare_unity, 'unreal': _prepare_unreal, 'neutral': prepare_neutral}


def prepare_engine(campaign, identifier, campaign_sha, core_root, unity_root, catalogue):
    """Planner -> trusted adapter/neutral contract builder -> static validator."""
    if not isinstance(identifier, str) or not _UUID.fullmatch(identifier):
        raise ValueError('Expected an opaque campaign UUID')
    if not isinstance(campaign_sha, str) or not re.fullmatch(r'[0-9a-f]{64}', campaign_sha):
        raise ValueError('Expected a campaign SHA-256')
    descriptor = EngineRegistry(core_root, unity_root).get(campaign['engine'])
    engine, adapter_id = descriptor['id'], descriptor['adapterId']
    models = sorted({row['model'] for block in campaign['blocks'] for row in block['objects']})
    traces = [
        {
            'role': 'planner',
            'engine': engine,
            'state': 'completed',
            'decisions': [
                'Use the registered engine profile: ' + engine + ' (' + descriptor['mode'] + ').',
                'Prepare %d independent seeded RGB requests across %d environment blocks.'
                % (campaign['totalImages'], len(campaign['blocks'])),
                'Resolve %d catalogue models without changing their native scale.' % len(models),
                'Do not launch an engine, connect ROS, enter Play, or execute generated code.',
            ],
        }
    ]
    arguments = (
        campaign,
        identifier,
        campaign_sha,
        Path(core_root),
        Path(unity_root) if unity_root is not None else None,
        catalogue,
    )
    result = (
        _ADAPTERS[adapter_id](*arguments, descriptor=descriptor)
        if adapter_id == 'neutral'
        else _ADAPTERS[adapter_id](*arguments)
    )
    files, metadata = result.get('files'), result.get('manifest')
    if not isinstance(files, dict) or not isinstance(metadata, dict):
        raise ValueError('Engine adapter returned an invalid package')
    files = dict(
        files,
        **{
            'scene-contract.json': _json(
                scene_contract(campaign, identifier, campaign_sha, descriptor, catalogue)
            )
        },
    )
    expected = expected_artifacts(descriptor) - {'campaign.json', 'engine-agent.json'}
    if set(files) != expected:
        raise ValueError('Engine adapter returned an unexpected file set')
    if any(
        name not in PREPARED_FILES or not isinstance(data, bytes) or len(data) > 1_048_576
        for name, data in files.items()
    ):
        raise ValueError('Engine adapter returned an unsafe artifact')
    if not isinstance(metadata.get('scenePath'), str) or not isinstance(
        metadata.get('instructions'), list
    ):
        raise ValueError('Engine adapter returned incomplete instructions')
    if any(not isinstance(line, str) or len(line) > 4000 for line in metadata['instructions']):
        raise ValueError('Engine instructions must be bounded strings')
    if not isinstance(metadata.get('limitations', []), list) or any(
        not isinstance(line, str) or len(line) > 4000 for line in metadata.get('limitations', [])
    ):
        raise ValueError('Engine limitations must be bounded strings')
    metadata = dict(
        metadata,
        nativeValidated=False,
        mode=descriptor['mode'],
        neutralSceneContractFile='scene-contract.json',
        capabilities=descriptor['capabilities'],
    )
    script_detail = (
        'Generated a neutral contract only; no native engine script or adapter exists for this profile.'
        if adapter_id == 'neutral'
        else 'Generated repository-owned scene templates for ' + engine + '.'
    )
    traces.append(
        {
            'role': 'scene_script_builder',
            'engine': engine,
            'state': 'completed',
            'decisions': [
                script_detail,
                'Outputs remain inert until explicitly consumed by a trusted native adapter.',
            ],
            'artifacts': sorted(files),
        }
    )
    traces.append(
        {
            'role': 'validator',
            'engine': engine,
            'state': 'completed',
            'decisions': [
                'Checked the registered adapter file inventory, byte budgets and required metadata.',
                'Campaign schema/count/capability validation was performed before scene preparation.',
                'Artifact hashes bind this package; native compilation, rendering, licences and sensor accuracy were not validated.',
            ],
        }
    )
    report = {
        'schema': SCHEMA,
        'kind': 'deterministic_role_pipeline',
        'engine': engine,
        'engineLabel': descriptor['label'],
        'mode': descriptor['mode'],
        'id': identifier,
        'campaignSha256': campaign_sha,
        'nativeValidated': False,
        'nativeScriptGenerated': adapter_id != 'neutral',
        'models': models,
        'traces': traces,
        'capabilities': [
            'offline_campaign_planning',
            'neutral_scene_contract_generation',
            'static_package_validation',
        ],
        'limitations': [
            'These roles are deterministic software, not autonomous LLM agents.',
            'No editor, simulation, image generation or annotation validation ran during preparation.',
        ]
        + metadata.get('limitations', []),
    }
    files['engine-agent.json'] = _json(report)
    return {'files': files, 'manifest': metadata, 'report': report}
