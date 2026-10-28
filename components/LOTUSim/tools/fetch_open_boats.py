#!/usr/bin/env python3
"""Re-download the pinned CC-BY source files from the delivered manifest.

Uses only Python's standard library. Never executes remote files. The six
source GLBs are also delivered locally, so re-downloading is not required.
"""
import argparse
import hashlib
import json
import pathlib
import re
import urllib.request


def get(url):
    with urllib.request.urlopen(urllib.request.Request(url, headers={'User-Agent': 'LOTUSim-model-provenance/1.0'}), timeout=120) as response:
        return response.read()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=pathlib.Path, required=True)
    parser.add_argument('--dest', type=pathlib.Path, required=True)
    args = parser.parse_args()
    values = json.loads(args.manifest.read_text())
    for value in values:
        key = value['key']
        if not re.fullmatch('[a-z0-9_]+', key) or value['license'] != 'CC-BY-4.0':
            raise ValueError('Unsupported model/license')
        uid = value['source'].rsplit('-', 1)[-1]
        if not re.fullmatch('[a-f0-9]{32}', uid):
            raise ValueError('Invalid source model identifier')
        license_data = get('https://api.sketchfab.com/v3/models/'+uid)
        current = json.loads(license_data)
        if current['license']['slug'] != 'by' or '/by/4.0' not in current['license']['url']:
            raise ValueError('Creator license changed; manual review required')
        folder = args.dest/key
        folder.mkdir(parents=True, exist_ok=True)
        data = get(value['download'])
        if hashlib.sha256(data).hexdigest() != value['sha256']:
            raise ValueError('Source SHA-256 mismatch; nothing imported')
        target = folder/'source.glb'
        if target.exists() and target.read_bytes() != data:
            raise ValueError('Refusing to replace different local source')
        target.write_bytes(data)
        (folder/'sketchfab-license.json').write_bytes(license_data)
        (folder/'inspection.json').write_text(json.dumps(value, indent=2))
        print('PASS', key, value['sha256'], flush=True)
    commit = values[0]['mirrorCommit']
    if any(v['mirrorCommit'] != commit for v in values) or not re.fullmatch('[a-f0-9]{40}', commit):
        raise ValueError('Invalid/mixed mirror versions')
    (args.dest/'MIRROR_NOTICES.md').write_bytes(get(f'https://raw.githubusercontent.com/bob6664569/open-water/{commit}/THIRD_PARTY_NOTICES.md'))
    (args.dest/'LICENSE-CC-BY-4.0.txt').write_bytes(get('https://creativecommons.org/licenses/by/4.0/legalcode.txt'))


if __name__ == '__main__':
    main()
