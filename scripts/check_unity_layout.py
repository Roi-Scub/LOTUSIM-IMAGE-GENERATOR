#!/usr/bin/env python3
"""Validate Unity source layout, GUID identity and Editor/runtime boundaries offline."""

import json
from pathlib import Path, PurePosixPath
import re

ROOT = Path(__file__).resolve().parents[1]
LAYOUT_FILE = 'references/unity-code-layout.json'
PROJECT_PATH = 'components/LOTUSim-Unity-modules'
SCHEMA = 'lotusim-unity-code-layout-1'
SOURCE_ROOTS = {
    'runtime': 'Assets/Scripts/Dataset',
    'editor': 'Assets/Editor/Dataset',
    'test': 'Assets/Tests/Editor/Dataset',
}


def asset_path(value):
    """Accept a canonical Unity asset path, never a host or traversal path."""
    if not isinstance(value, str) or not value or len(value) > 512:
        raise ValueError('Expected a Unity asset path')
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or not value.startswith('Assets/')
        or value != path.as_posix()
        or any(part.startswith('.') for part in path.parts)
        or '\\' in value
        or any(ord(character) < 32 for character in value)
    ):
        raise ValueError('Unsafe Unity asset path: ' + value)
    return path


def assembly_for(value):
    parts = asset_path(value).parts
    if any(part in {'Plugins', 'Standard Assets', 'Pro Standard Assets'} for part in parts):
        raise ValueError('First-pass assembly relocation is not supported')
    return 'Assembly-CSharp-Editor' if 'Editor' in parts else 'Assembly-CSharp'


def load_layout(root=ROOT):
    root = Path(root)
    layout = json.loads((root / LAYOUT_FILE).read_text(encoding='utf-8'))
    if layout.get('schema') != SCHEMA or not layout.get('moves') or not layout.get('groups'):
        raise ValueError('Unsupported or empty Unity code layout')
    if not set(layout['groups']) <= set(SOURCE_ROOTS.values()):
        raise ValueError('Undeclared Unity source root')
    previous, current, identifiers = set(), set(), set()
    for move in layout['moves']:
        before, after = asset_path(move['from']), asset_path(move['to'])
        if (
            before.suffix != '.cs'
            or before.name != after.name
            or before.as_posix() in previous
            or after.as_posix() in current
            or move['guid'] in identifiers
            or not re.fullmatch(r'[0-9a-f]{32}', move['guid'])
            or assembly_for(before.as_posix()) != move['assembly']
            or assembly_for(after.as_posix()) != move['assembly']
            or move.get('role') not in {'runtime', 'editor', 'test'}
            or (move['role'] == 'runtime') != (move['assembly'] == 'Assembly-CSharp')
            or not after.as_posix().startswith(SOURCE_ROOTS[move['role']] + '/')
        ):
            raise ValueError('Ambiguous Unity move, name, GUID or assembly: ' + move['to'])
        previous.add(before.as_posix())
        current.add(after.as_posix())
        identifiers.add(move['guid'])
    return layout


def regular_asset(project, relative):
    path = project.joinpath(*asset_path(relative).parts)
    current = project
    for part in path.relative_to(project).parts:
        current = current / part
        if current.is_symlink():
            raise ValueError('Unity source symlink refused: ' + relative)
    path.resolve(strict=True).relative_to(project.resolve(strict=True))
    if not path.is_file():
        raise ValueError('Expected a regular Unity source: ' + relative)
    return path


def file_guid(metadata):
    matches = re.findall(r'^guid: ([0-9a-f]{32})$', metadata.read_text(encoding='utf-8'), re.M)
    if len(matches) != 1:
        raise ValueError('Expected one valid Unity GUID: ' + str(metadata))
    return matches[0]


def source_aliases(root=ROOT):
    """Map old cached compiler paths only after verifying the moved script GUID."""
    root = Path(root)
    project = root / PROJECT_PATH
    layout = load_layout(root)
    aliases = {}
    for move in layout['moves']:
        regular_asset(project, move['to'])
        metadata = regular_asset(project, move['to'] + '.meta')
        if file_guid(metadata) != move['guid']:
            raise ValueError('Moved Unity script identity changed: ' + move['to'])
        obsolete = project / move['from']
        if move['from'] != move['to'] and (obsolete.exists() or obsolete.is_symlink()):
            raise ValueError('Obsolete duplicate Unity source remains: ' + move['from'])
        obsolete_metadata = project / (move['from'] + '.meta')
        if move['from'] != move['to'] and (
            obsolete_metadata.exists() or obsolete_metadata.is_symlink()
        ):
            raise ValueError('Obsolete Unity metadata remains: ' + move['from'])
        aliases[move['from']] = move['to']
    return aliases


def check(root=ROOT):
    root = Path(root)
    project = root / PROJECT_PATH
    layout = load_layout(root)
    source_aliases(root)
    sources, folders = [], set()
    for relative, groups in layout['groups'].items():
        directory = project / asset_path(relative)
        if not directory.is_dir() or directory.is_symlink():
            raise ValueError('Unity code directory missing: ' + relative)
        for path in directory.rglob('*.cs'):
            relative_path = path.relative_to(project).as_posix()
            regular_asset(project, relative_path)
            regular_asset(project, relative_path + '.meta')
            within = path.relative_to(directory)
            if len(within.parts) < 2 or within.parts[0] not in groups:
                raise ValueError(
                    'Unity source has no declared responsibility group: ' + relative_path
                )
            if not re.fullmatch(r'[A-Z][A-Za-z0-9]*', path.stem):
                raise ValueError('Unity C# filenames must use PascalCase: ' + relative_path)
            if path.stem.endswith('Tests') and not relative_path.startswith(
                SOURCE_ROOTS['test'] + '/'
            ):
                raise ValueError('Unity test sources belong under Tests/Editor: ' + relative_path)
            if (
                relative.startswith('Assets/Scripts')
                and assembly_for(relative_path) != 'Assembly-CSharp'
            ):
                raise ValueError('Runtime source entered an Editor assembly: ' + relative_path)
            for parent in path.parents:
                if parent == project / 'Assets':
                    break
                metadata = parent.with_name(parent.name + '.meta')
                # The overlay inherits the existing Scripts parent from upstream.
                if parent == project / 'Assets/Scripts' and not metadata.exists():
                    continue
                regular_asset(project, metadata.relative_to(project).as_posix())
                if not re.search(r'^folderAsset: yes$', metadata.read_text(encoding='utf-8'), re.M):
                    raise ValueError('Unity folder metadata missing: ' + str(parent))
                folders.add(parent)
            sources.append(relative_path)
        if list(directory.rglob('*.asmdef')) or list(directory.rglob('*.asmref')):
            raise ValueError('Assembly boundaries changed; explicit assembly migration is required')
    if len(set(sources)) != len(sources):
        raise ValueError('Overlapping Unity source roots')
    if not {move['to'] for move in layout['moves']} <= set(sources):
        raise ValueError('A moved source is outside the declared Unity modules')
    for resource in layout['resources']:
        regular_asset(project, resource['path'])
        if (
            not resource['path'].startswith('Assets/Resources/Dataset/')
            or file_guid(regular_asset(project, resource['path'] + '.meta')) != resource['guid']
        ):
            raise ValueError('Resources.Load shader identity or path changed')
    identifiers = {}
    for path in (project / 'Assets').rglob('*.meta'):
        regular_asset(project, path.relative_to(project).as_posix())
        identifier = file_guid(path)
        if identifier in identifiers:
            raise ValueError(
                'Duplicate Unity GUID: ' + str(path) + ' / ' + str(identifiers[identifier])
            )
        identifiers[identifier] = path
    return {
        'scripts': len(sources),
        'moves': len(layout['moves']),
        'guids': len(identifiers),
        'folders': len(folders),
        'resources': len(layout['resources']),
    }


def main():
    result = check()
    print(
        'Unity layout PASS: {scripts} scripts, {guids} unique GUIDs, {resources} stable Resources shaders.'.format(
            **result
        )
    )
    print(
        'Original type names and assembly ownership retained; no Unity, Play, GPU or ROS execution.'
    )


if __name__ == '__main__':
    main()
