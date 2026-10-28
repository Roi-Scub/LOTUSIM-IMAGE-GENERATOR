#!/usr/bin/env python3
"""Refresh the portable inventory only; runtime, private state and results stay excluded."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--write', action='store_true', help='Otherwise print summary without writing')
    args = parser.parse_args()
    manifest = json.loads((ROOT / 'manifest.json').read_text(encoding='utf-8'))
    paths = {record['path'] for record in manifest['files']}
    paths.update(('AGENTS.md', 'README.md', '.gitignore'))
    for filename in ('LICENSE', '.gitattributes', 'VERSION', 'CHANGELOG.md'):
        if (ROOT / filename).is_file():
            paths.add(filename)
    for folder in ('scripts', 'docs', 'components', 'examples', 'patches', 'references'):
        paths.update(str(path.relative_to(ROOT)) for path in (ROOT / folder).rglob('*')
                     if path.is_file() and not path.is_symlink() and
                     not any(part.startswith('.') or part == '__pycache__' for part in path.relative_to(ROOT).parts))
    records = []
    for name in sorted(paths):
        relative = Path(name)
        if relative.is_absolute() or '..' in relative.parts or relative.parts[0] in ('runtime', '.local'):
            raise ValueError('Unsafe portable path: ' + name)
        path = ROOT / relative
        path.resolve(strict=True).relative_to(ROOT)
        if not path.is_file() or path.is_symlink():
            raise ValueError('Not a regular portable file: ' + name)
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(chunk)
        records.append({'path': name, 'bytes': path.stat().st_size, 'sha256': digest.hexdigest()})
    manifest['files'] = records
    manifest['totalBytes'] = sum(record['bytes'] for record in records)
    manifest['updatedAt'] = datetime.now(timezone.utc).isoformat()
    manifest['scope'] = 'portable source snapshot; runtime and .local are not included'
    if args.write:
        (ROOT / 'manifest.json').write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(('Updated' if args.write else 'Preview') + ': ' + str(len(records)) + ' portable files, ' +
          str(manifest['totalBytes']) + ' bytes. Runtime is unchanged.')


if __name__ == '__main__':
    main()
