#!/usr/bin/env python3
"""Format first-party C# offline without loading Unity, projects or packages.

The pinned SDK is used only for its bundled Roslyn compiler and whitespace
formatter. All compilation, CLI state and candidate sources stay in a private
temporary directory. --check is read-only; --write publishes verified candidates.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
PINNED_SDK = "10.0.102"
PINNED_RUNTIME = "10.0.2"
SOURCE_ROOTS = (
    "components/LOTUSim-Unity-modules/",
    "references/modified-sources/LOTUSim-Unity-modules/",
)
HOST_SOURCE = "scripts/formatting/FormatCSharpHost.cs"


def run(command, *, cwd, environment, timeout=120):
    result = subprocess.run(
        command,
        cwd=cwd,
        env=environment,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=timeout,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(result.stdout.strip() or "C# formatting command failed")
    return result.stdout


def tracked_sources(root):
    names = (
        subprocess.check_output(
            ['git', 'ls-files', '--cached', '--others', '--exclude-standard', '-z', '--', '*.cs'],
            cwd=root,
            env={key: value for key, value in os.environ.items() if not key.startswith('GIT_')},
        )
        .decode("utf-8")
        .split("\0")
    )
    if (root / HOST_SOURCE).is_file() and HOST_SOURCE not in names:
        names.append(HOST_SOURCE)
    selected = sorted(
        name
        for name in names
        if name
        and (name.startswith(SOURCE_ROOTS) or name == HOST_SOURCE)
        and "/Assets/RosMessages/" not in name
    )
    if not selected:
        raise ValueError("No first-party C# sources in the selected repository")
    for name in selected:
        path = root / name
        if path.is_symlink() or not path.is_file():
            raise ValueError("C# source must be a regular file: " + name)
        path.resolve(strict=True).relative_to(root)
    return selected


def sdk_paths(dotnet, root, environment):
    lines = run([dotnet, "--list-sdks"], cwd=root, environment=environment).splitlines()
    sdk = None
    for line in lines:
        match = re.fullmatch(re.escape(PINNED_SDK) + r"\s+\[(.+)\]", line.strip())
        if match:
            sdk = Path(match.group(1)) / PINNED_SDK
            break
    if sdk is None:
        raise ValueError("Install .NET SDK " + PINNED_SDK + " explicitly; no download is performed")
    packs = sdk.parents[1] / "packs/Microsoft.NETCore.App.Ref"
    pack = packs / PINNED_RUNTIME
    if not (pack / "ref/net10.0").is_dir():
        raise ValueError("The installed SDK has no local net10.0 reference pack " + PINNED_RUNTIME)
    return sdk, pack


def compile_host(root, temporary, dotnet, sdk, pack, environment):
    compiler = sdk / "Roslyn/bincore/csc.dll"
    roslyn = [
        sdk / ("Roslyn/bincore/" + name)
        for name in ("Microsoft.CodeAnalysis.dll", "Microsoft.CodeAnalysis.CSharp.dll")
    ]
    host = temporary / "FormatCSharpHost.dll"
    response = temporary / "host.rsp"
    references = sorted((pack / "ref/net10.0").glob("*.dll")) + roslyn
    arguments = [
        "-nostdlib+",
        "-target:exe",
        "-out:\"" + str(host) + "\"",
        *["-r:\"" + str(path) + "\"" for path in references],
        "\"" + str(root / HOST_SOURCE) + "\"",
    ]
    response.write_text("\n".join(arguments) + "\n", encoding="utf-8")
    run([dotnet, str(compiler), "@" + str(response)], cwd=root, environment=environment)
    for assembly in roslyn:
        shutil.copy2(assembly, temporary / assembly.name)
    (temporary / "FormatCSharpHost.runtimeconfig.json").write_text(
        json.dumps(
            {
                "runtimeOptions": {
                    "tfm": "net10.0",
                    "framework": {"name": "Microsoft.NETCore.App", "version": pack.name},
                    "rollForward": "LatestPatch",
                }
            }
        ),
        encoding="utf-8",
    )
    return host


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Check only (default)")
    mode.add_argument("--write", action="store_true", help="Write only verified formatting changes")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--dotnet", default=shutil.which("dotnet"))
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    if not args.dotnet:
        raise ValueError(".NET SDK " + PINNED_SDK + " is required; no package is installed")
    dotnet = str(Path(args.dotnet).resolve(strict=True))
    sources = tracked_sources(root)
    configuration = root / ".editorconfig"
    if not configuration.is_file():
        raise ValueError("The repository .editorconfig is required")

    with tempfile.TemporaryDirectory(prefix="lotusim-csharp-format-") as directory:
        temporary = Path(directory).resolve()
        environment = dict(os.environ)
        environment.update(
            {
                "DOTNET_CLI_HOME": str(temporary / "dotnet-home"),
                "DOTNET_SKIP_FIRST_TIME_EXPERIENCE": "1",
                "DOTNET_GENERATE_ASPNET_CERTIFICATE": "false",
                "DOTNET_CLI_TELEMETRY_OPTOUT": "1",
                "DOTNET_CLI_WORKLOAD_UPDATE_NOTIFY_DISABLE": "true",
                "DOTNET_NOLOGO": "1",
            }
        )
        sdk, pack = sdk_paths(dotnet, root, environment)
        host = compile_host(root, temporary, dotnet, sdk, pack, environment)
        candidate_root = temporary / "candidate"
        candidate_root.mkdir()
        shutil.copy2(configuration, candidate_root / ".editorconfig")
        (candidate_root / "global.json").write_text(
            json.dumps(
                {"sdk": {"version": PINNED_SDK, "rollForward": "disable", "allowPrerelease": False}}
            ),
            encoding="utf-8",
        )
        inventory = temporary / "inventory.json"
        pairs = [
            {
                "RelativePath": name,
                "OriginalPath": str(root / name),
                "CandidatePath": str(candidate_root / name),
            }
            for name in sources
        ]
        inventory.write_text(json.dumps(pairs), encoding="utf-8")
        before = {name: hashlib.sha256((root / name).read_bytes()).hexdigest() for name in sources}
        run([dotnet, str(host), "normalize", str(inventory)], cwd=root, environment=environment)
        # --folder is an ad-hoc workspace: no MSBuild, project load or restore.
        # The CLI rejects combining --folder with --no-restore.
        run(
            [
                dotnet,
                "format",
                "whitespace",
                "--folder",
                str(candidate_root),
                "--verbosity",
                "quiet",
            ],
            cwd=candidate_root,
            environment=environment,
        )
        proof = run(
            [dotnet, str(host), "verify", str(inventory)], cwd=root, environment=environment
        )
        changed = [
            name
            for name in sources
            if (root / name).read_bytes() != (candidate_root / name).read_bytes()
        ]
        for name in sources:
            if hashlib.sha256((root / name).read_bytes()).hexdigest() != before[name]:
                raise ValueError("Concurrent C# source edit detected; nothing published: " + name)
        print(proof.strip())
        if args.write:
            for name in changed:
                shutil.copy2(candidate_root / name, root / name)
            print(
                "Formatted "
                + str(len(changed))
                + " first-party C# files; Unity and runtime were not loaded."
            )
            return 0
        if changed:
            print("Formatting required for " + str(len(changed)) + " C# files:")
            for name in changed:
                print("  " + name)
            return 1
        print(
            "PASS: "
            + str(len(sources))
            + " first-party C# files already match the formatting policy."
        )
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as error:
        print("C# formatting refused: " + str(error), file=sys.stderr)
        raise SystemExit(2)
