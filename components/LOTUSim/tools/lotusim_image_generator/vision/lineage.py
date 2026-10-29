"""Common campaign identity for knowledge, calibration and test isolation."""

import json
from pathlib import Path


def campaign_group(rgb):
    path = Path(rgb).resolve()
    root = path.parent if path.name in {'rgb', 'gazebo-rgb'} else path
    for name in ('requested-config.json', 'configuration.json', 'config.json'):
        file = root / name
        if file.is_file():
            data = json.loads(file.read_text())
            seed = data.get('seed', data.get('Seed'))
            if seed is not None:
                return 'lotusim-seed:' + str(seed)
    return str(root)
