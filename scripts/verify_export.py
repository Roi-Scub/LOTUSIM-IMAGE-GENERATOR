#!/usr/bin/env python3
"""Verify the immutable source/asset snapshot hashes; does not modify files."""

import argparse
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    value = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def verify(root=ROOT):
    root = Path(root).resolve(strict=True)
    manifest = json.loads((root / 'manifest.json').read_text(encoding='utf-8'))
    errors = []
    for record in manifest['files']:
        relative = Path(record['path'])
        if relative.is_absolute() or '..' in relative.parts:
            raise ValueError('Unsafe manifest path')
        path = root / relative
        try:
            path.resolve(strict=True).relative_to(root)
            if path.is_symlink() or not path.is_file():
                raise ValueError('Not a regular snapshot file')
            if path.stat().st_size != record['bytes'] or digest(path) != record['sha256']:
                errors.append(str(relative))
        except (OSError, ValueError):
            errors.append(str(relative))
    if errors:
        raise ValueError('Snapshot differs: ' + ', '.join(errors[:20]))
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, default=ROOT)
    args = parser.parse_args()
    manifest = verify(args.root)
    print(
        'PASS: '
        + str(len(manifest['files']))
        + ' files; '
        + str(manifest['totalBytes'])
        + ' bytes; all SHA-256 checks match.'
    )


if __name__ == '__main__':
    main()
