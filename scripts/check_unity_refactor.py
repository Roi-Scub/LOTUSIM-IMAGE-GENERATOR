#!/usr/bin/env python3
"""Compile portable C# against cached Unity references without launching Unity.

The cached response files remain read-only. Source overlays and all compiler
outputs are substituted into private copies; no scene, asset or runtime source
is edited. This is compilation evidence, not a GPU, Play or ROS validation.
"""

import argparse
import os
from pathlib import Path
import re
import subprocess
import tempfile

from check_unity_layout import source_aliases

ROOT = Path(__file__).resolve().parents[1]
SOURCE_ROOTS = (
    Path("components/LOTUSim-Unity-modules"),
    Path("references/modified-sources/LOTUSim-Unity-modules"),
)
OUTPUT_OPTIONS = {"out", "refout", "pdb", "doc", "errorlog", "generatedfilesout"}


def source_map(root):
    tracked = (
        subprocess.check_output(
            ["git", "ls-files", "-z", "--", "*.cs"],
            cwd=root,
            env={key: value for key, value in os.environ.items() if not key.startswith('GIT_')},
        )
        .decode("utf-8")
        .split("\0")
    )
    result = {}
    for name in tracked:
        if not name or "/Assets/RosMessages/" in name:
            continue
        path = Path(name)
        for source_root in SOURCE_ROOTS:
            try:
                relative = path.relative_to(source_root)
            except ValueError:
                continue
            source = root / path
            if source.is_symlink() or not source.is_file():
                raise ValueError("Expected a regular portable C# source: " + name)
            source.resolve(strict=True).relative_to(root)
            key = relative.as_posix()
            if key in result:
                raise ValueError("Ambiguous portable C# source: " + key)
            result[key] = source
    if not result:
        raise ValueError("No portable Unity C# source found")
    return result


def compile_response(original, target, unity, temporary, sources, seen, aliases=None):
    lines = []
    aliases = aliases or {}
    for line in original.read_text(encoding="utf-8").splitlines():
        option = re.match(r"^[-/]([a-z]+):(.*)$", line, flags=re.IGNORECASE)
        if option and option.group(1).lower() in OUTPUT_OPTIONS:
            key = option.group(1).lower()
            basename = Path(option.group(2).strip('"')).name
            destination = temporary / (basename or target)
            if key == "generatedfilesout":
                destination.mkdir(exist_ok=True)
            lines.append("-" + key + ':"' + str(destination) + '"')
            continue
        if target == "Assembly-CSharp-Editor" and line.startswith('-r:"'):
            reference = line[4:-1]
            if Path(reference).name in ("Assembly-CSharp.ref.dll", "Assembly-CSharp.dll"):
                lines.append('-r:"' + str(temporary / Path(reference).name) + '"')
                continue
        if line.startswith('"') and line.endswith('"') and line.lower().endswith('.cs"'):
            relative = Path(line[1:-1])
            if relative.is_absolute():
                try:
                    relative = relative.relative_to(unity)
                except ValueError:
                    pass
            canonical = aliases.get(relative.as_posix(), relative.as_posix())
            source = sources.get(canonical)
            if source is not None:
                lines.append('"' + str(source) + '"')
                seen.add(canonical)
                continue
        lines.append(line)
    response = temporary / (target + ".rsp")
    response.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return response


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--unity", type=Path, required=True, help="Existing complete Unity project")
    parser.add_argument("--editor", type=Path, required=True, help="Existing Unity.app/Contents")
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    unity = args.unity.resolve(strict=True)
    editor = args.editor.resolve(strict=True)
    compiler = editor / "DotNetSdkRoslyn/csc.dll"
    runtime = editor / "NetCoreRuntime/dotnet"
    if not compiler.is_file() or not runtime.is_file():
        raise ValueError(
            "The existing Unity compiler/runtime is unavailable; no native compile claimed"
        )
    sources = source_map(root)
    aliases = source_aliases(root)
    responses = {}
    for target in ("Assembly-CSharp", "Assembly-CSharp-Editor"):
        candidates = list((unity / "Library/Bee/artifacts").glob("*.dag/" + target + ".rsp"))
        if not candidates:
            raise ValueError(
                "No cached Unity response for " + target + "; no native compile claimed"
            )
        responses[target] = max(candidates, key=lambda path: path.stat().st_mtime_ns)

    with tempfile.TemporaryDirectory(prefix="lotusim-unity-csharp-check-") as directory:
        temporary = Path(directory).resolve()
        environment = dict(os.environ)
        environment.update(
            {
                "DOTNET_CLI_HOME": str(temporary / "dotnet-home"),
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
            }
        )
        seen = set()
        for target, original in responses.items():
            response = compile_response(original, target, unity, temporary, sources, seen, aliases)
            compiled = subprocess.run(
                [str(runtime), str(compiler), "@" + str(response)],
                cwd=unity,
                env=environment,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                timeout=120,
                check=False,
            )
            if compiled.stdout.strip():
                print(compiled.stdout.strip())
            if compiled.returncode:
                raise SystemExit(compiled.returncode)
            print(
                "PASS: " + target + " compiled with portable sources and cached native references"
            )
        missing = set(sources) - seen
        if missing:
            raise ValueError(
                "Cached responses omit portable sources: " + ", ".join(sorted(missing))
            )
        print(
            "PASS: all "
            + str(len(seen))
            + " portable Unity C# files covered. No Editor, Play, GPU or ROS execution."
        )


if __name__ == "__main__":
    main()
