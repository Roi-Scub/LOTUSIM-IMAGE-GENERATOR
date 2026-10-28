#!/usr/bin/env python3
"""Send CLEAN RGB through Gazebo Transport, verifying every received pixel.

Gazebo is the message transport here, NOT a semantic recognition engine.
No world is launched, no annotation sensor receives the scene, no ROS TCP
connection is opened. The resulting gazebo-rgb/ can be analyzed independently.
"""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import uuid


def roundtrip(rgb, output, container="lotusim-dev", limit=0):
    from PIL import Image

    if rgb.name != "rgb" or not rgb.is_dir():
        raise ValueError("Select the raw rgb/ folder")
    output.mkdir(parents=True, exist_ok=False)
    received = output / "gazebo-rgb"
    received.mkdir()
    files = sorted(rgb.glob("*.png"))
    files = files[:limit] if limit else files
    if not files:
        raise ValueError("No PNG images")
    partition = "lotusim-rgb-observer-" + uuid.uuid4().hex
    records = []
    for index, path in enumerate(files):
        if path.is_symlink():
            raise ValueError("Symlink refused")
        with Image.open(path) as source:
            image = source.convert("RGB")
        pixels = image.tobytes()
        command = [
            "docker",
            "exec",
            "-i",
            "-e",
            "GZ_PARTITION=" + partition,
            container,
            "/workspace/artifacts/rgb-observer-gazebo/relay",
            "roundtrip",
            "/dataset/rgb_observer/image_raw",
            str(image.width),
            str(image.height),
        ]
        result = subprocess.run(
            command,
            input=pixels,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=40,
            check=True,
        )
        if result.stdout != pixels:
            raise ValueError("Gazebo RGB roundtrip changed pixels")
        name = f"f{index:06d}.png"
        Image.frombytes("RGB", image.size, result.stdout).save(received / name)
        records.append(
            {
                "source": path.name,
                "received": name,
                "width": image.width,
                "height": image.height,
                "pixelSha256": hashlib.sha256(pixels).hexdigest(),
                "verifiedEqual": True,
            }
        )
        print(f"[Gazebo RGB] {index+1}/{len(files)} pixels verified", flush=True)
    (output / "transport-proof.json").write_text(
        json.dumps(
            {
                "schema": "lotusim-rgb-gazebo-transport-1",
                "semanticInferenceInGazebo": False,
                "gazeboTransport": "gz-transport13 / gz.msgs.Image RGB_INT8",
                "partition": partition,
                "topic": "/dataset/rgb_observer/image_raw",
                "records": records,
            },
            indent=2,
        )
    )
    return received


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--rgb", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--limit", type=int, default=0)
    p.add_argument("--container", default="lotusim-dev")
    a = p.parse_args()
    roundtrip(a.rgb, a.output, a.container, a.limit)
