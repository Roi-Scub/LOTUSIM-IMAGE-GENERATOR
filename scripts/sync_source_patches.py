#!/usr/bin/env python3
"""Rebuild source patches offline from pinned local Git objects and references.

Default --check never edits the export or supplied clones. --write publishes
validated patch candidates only; commits, working trees, engines, provenance and
serialized reference data remain untouched. No clone, fetch or restore is run.
"""

import argparse
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
REPOSITORIES = ("LOTUSim", "LOTUSim-Unity-modules")
DATASET_OVERLAPS = (
    "systems/lotusim_mas/include/lotusim_mas/dataset_motion.hpp",
    "systems/lotusim_mas/include/lotusim_mas/dataset_timeline.hpp",
    "systems/lotusim_mas/src/dataset_timeline.cpp",
)


@dataclass(frozen=True)
class FileState:
    data: bytes
    mode: int


def environment():
    # Inherited Git overrides must never redirect temporary index/worktree writes.
    result = {key: value for key, value in os.environ.items() if not key.startswith('GIT_')}
    result.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": os.devnull,
            "GIT_CONFIG_COUNT": "0",
            "GIT_ATTR_NOSYSTEM": "1",
            "GIT_NO_LAZY_FETCH": "1",
            "GIT_TERMINAL_PROMPT": "0",
        }
    )
    return result


def git(directory, *arguments, data=None, check=True):
    result = subprocess.run(
        [
            "git",
            "--no-pager",
            "--no-optional-locks",
            "--no-replace-objects",
            "-C",
            str(directory),
            *arguments,
        ],
        input=data,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        env=environment(),
        check=False,
        timeout=60,
    )
    if check and result.returncode:
        raise ValueError(
            "Git patch operation refused: " + result.stderr.decode("utf-8", "replace").strip()
        )
    return result


def relative_path(value):
    if (
        not isinstance(value, str)
        or not value
        or any(character in value for character in "\\\0\n\r\t")
    ):
        raise ValueError("Invalid portable source path")
    path = Path(value)
    if path.is_absolute() or ".git" in path.parts or ".." in path.parts or path.as_posix() != value:
        raise ValueError("Unsafe portable source path: " + value)
    return path


def read_reference(root, repository, name):
    reference_root = root / "references/modified-sources" / repository
    path = reference_root / relative_path(name)
    if not path.is_file() or path.is_symlink():
        raise ValueError("Missing regular modified source: " + name)
    path.resolve(strict=True).relative_to(reference_root.resolve(strict=True))
    mode = 0o100755 if path.stat().st_mode & 0o111 else 0o100644
    return FileState(path.read_bytes(), mode)


def read_baseline(clone, commit, name):
    listing = git(clone, "ls-tree", "-z", commit, "--", name).stdout
    if not listing:
        return None
    records = listing.rstrip(b"\0").split(b"\0")
    if len(records) != 1:
        raise ValueError("Ambiguous baseline path: " + name)
    metadata, recorded_name = records[0].split(b"\t", 1)
    mode, kind, _ = metadata.split(b" ")
    if (
        kind != b"blob"
        or int(mode, 8) not in (0o100644, 0o100755)
        or recorded_name.decode() != name
    ):
        raise ValueError("Unsupported baseline file mode: " + name)
    return FileState(git(clone, "cat-file", "blob", commit + ":" + name).stdout, int(mode, 8))


def write_state(directory, name, state):
    path = directory / relative_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(state.data)
    path.chmod(stat.S_IMODE(state.mode))


def temporary_repository(directory, baseline):
    directory.mkdir()
    git(directory, "-c", "init.templateDir=", "init", "--quiet")
    for key, value in (
        ("core.autocrlf", "false"),
        ("core.filemode", "true"),
        ("core.attributesFile", os.devnull),
        ("core.fsmonitor", "false"),
    ):
        git(directory, "config", "--local", key, value)
    existing = []
    for name, state in baseline.items():
        if state is not None:
            write_state(directory, name, state)
            existing.append(name)
    if existing:
        git(directory, "add", "-f", "--", *existing)
    return directory


def touched_paths(directory, payload):
    output = git(directory, "apply", "--numstat", "-z", "-", data=payload).stdout
    result = set()
    for record in output.split(b"\0"):
        if not record:
            continue
        fields = record.split(b"\t", 2)
        if len(fields) != 3:
            raise ValueError("Unsupported patch inventory record")
        name = fields[2].decode("utf-8")
        relative_path(name)
        result.add(name)
    return result


def matches_references(directory, expected):
    for name, target in expected.items():
        path = directory / name
        if not path.is_file() or path.is_symlink() or path.read_bytes() != target.data:
            return False
        mode = 0o100755 if path.stat().st_mode & 0o111 else 0o100644
        if mode != target.mode:
            return False
    return True


def apply_patch(directory, payload):
    git(directory, "apply", "--check", "--binary", "--whitespace=nowarn", "-", data=payload)
    git(directory, "apply", "--binary", "--whitespace=nowarn", "-", data=payload)


def build_patch(directory, baseline, expected):
    temporary_repository(directory, baseline)
    additions = []
    for name, target in expected.items():
        write_state(directory, name, target)
        if baseline[name] is None:
            additions.append(name)
    if additions:
        git(directory, "add", "-N", "-f", "--", *additions)
    payload = git(
        directory,
        "diff",
        "--binary",
        "--full-index",
        "--no-ext-diff",
        "--no-textconv",
        "--no-renames",
        "--no-color",
        "--src-prefix=a/",
        "--dst-prefix=b/",
        "--diff-algorithm=myers",
        "--unified=3",
        "--",
        *sorted(expected),
    ).stdout
    if not payload:
        raise ValueError("Declared patch group has no differences")
    if touched_paths(directory, payload) - set(expected):
        raise ValueError("Generated patch escaped its declared paths")
    return payload


def digest(data):
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Verify only (default)")
    mode.add_argument("--write", action="store_true", help="Write validated patch updates")
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument(
        "--core", type=Path, help="Local Git clone containing the pinned LOTUSim base"
    )
    parser.add_argument(
        "--unity", type=Path, help="Local Git clone containing the pinned Unity base"
    )
    args = parser.parse_args()
    root = args.root.resolve(strict=True)
    provenance_path = root / "provenance.json"
    provenance_bytes = provenance_path.read_bytes()
    provenance = json.loads(provenance_bytes)
    if provenance.get("schema") != "lotusim-export-provenance-1":
        raise ValueError("Unsupported provenance schema")
    clones = {
        "LOTUSim": (args.core or root / "runtime/LOTUSim").resolve(strict=True),
        "LOTUSim-Unity-modules": (args.unity or root / "runtime/LOTUSim-Unity-modules").resolve(
            strict=True
        ),
    }
    commits = {}
    for label in REPOSITORIES:
        commits[label] = provenance["repositories"][label]["baseCommit"]
        if not re.fullmatch(r"[0-9a-f]{40}", commits[label]):
            raise ValueError("Expected an immutable baseline commit for " + label)
        git(clones[label], "cat-file", "-e", commits[label] + "^{commit}")
    groups = provenance["patches"]
    if not isinstance(groups, list) or not groups:
        raise ValueError("Missing source patch groups")
    baselines = {label: {} for label in REPOSITORIES}
    targets = {label: {} for label in REPOSITORIES}
    originals = {}
    source_hashes = {}
    candidates = {}

    with tempfile.TemporaryDirectory(prefix="lotusim-source-patches-") as folder:
        temporary = Path(folder).resolve()
        for index, group in enumerate(groups):
            label = group["repository"]
            if label not in REPOSITORIES:
                raise ValueError("Unknown source repository")
            patch_name = relative_path(group["file"])
            if patch_name.parts[0] != "patches" or patch_name.suffix != ".patch":
                raise ValueError("Patch destination must stay inside patches/")
            path = root / patch_name
            if path.is_symlink() or not path.is_file():
                raise ValueError("Missing regular source patch: " + str(patch_name))
            path.resolve(strict=True).relative_to(root / "patches")
            originals[str(patch_name)] = path.read_bytes()
            baseline, expected = {}, {}
            for name in group["paths"]:
                relative_path(name)
                if name in targets[label]:
                    raise ValueError("Overlapping patch groups require explicit review: " + name)
                baseline[name] = read_baseline(clones[label], commits[label], name)
                expected[name] = read_reference(root, label, name)
                source_hashes[(label, name)] = digest(expected[name].data), expected[name].mode
            baselines[label].update(baseline)
            targets[label].update(expected)
            generated = build_patch(temporary / ("generate-" + str(index)), baseline, expected)
            current_repo = temporary_repository(temporary / ("current-" + str(index)), baseline)
            if touched_paths(current_repo, originals[str(patch_name)]) - set(expected):
                raise ValueError(
                    "Existing patch touches undeclared paths; preserved: " + str(patch_name)
                )
            # Keep already-correct historical patches byte-for-byte; full-index or
            # hunk-layout changes alone would add irrelevant review noise.
            current_applies = (
                git(
                    current_repo,
                    "apply",
                    "--check",
                    "--binary",
                    "--whitespace=nowarn",
                    "-",
                    data=originals[str(patch_name)],
                    check=False,
                ).returncode
                == 0
            )
            if current_applies:
                apply_patch(current_repo, originals[str(patch_name)])
            candidates[str(patch_name)] = (
                originals[str(patch_name)]
                if current_applies and matches_references(current_repo, expected)
                else generated
            )

        installed = {}
        for label in REPOSITORIES:
            installed[label] = temporary_repository(
                temporary / ("validate-" + label), baselines[label]
            )
        for group in groups:
            apply_patch(installed[group["repository"]], candidates[group["file"]])
        for label in REPOSITORIES:
            if not matches_references(installed[label], targets[label]):
                raise ValueError("Applied patches differ from the recorded references: " + label)
        for name in DATASET_OVERLAPS:
            portable = root / "components/LOTUSim" / name
            if (
                not portable.is_file()
                or portable.read_bytes() != (installed["LOTUSim"] / name).read_bytes()
            ):
                raise ValueError("Patch/overlay divergence would break installation: " + name)
        if provenance_path.read_bytes() != provenance_bytes:
            raise ValueError("Concurrent provenance edit; no patch was written")
        for (label, name), before in source_hashes.items():
            current = read_reference(root, label, name)
            if (digest(current.data), current.mode) != before:
                raise ValueError("Concurrent reference edit; no patch was written: " + name)
        for name, before in originals.items():
            if (root / name).read_bytes() != before:
                raise ValueError("Concurrent patch edit; no patch was written: " + name)
        changed = [name for name in candidates if candidates[name] != originals[name]]
        print(
            "PASS: all "
            + str(len(groups))
            + " groups apply to pinned bases and reproduce "
            + str(sum(len(items) for items in targets.values()))
            + " reference files and modes."
        )
        print("PASS: all three dataset source overlaps match the portable overlay byte-for-byte.")
        if args.write:
            for name in changed:
                destination = root / name
                descriptor, staging_name = tempfile.mkstemp(
                    prefix=".sync-patch-", dir=destination.parent
                )
                staging = Path(staging_name)
                try:
                    with os.fdopen(descriptor, "wb") as stream:
                        stream.write(candidates[name])
                        stream.flush()
                        os.fsync(stream.fileno())
                    staging.chmod(stat.S_IMODE(destination.stat().st_mode))
                    os.replace(staging, destination)
                finally:
                    if staging.exists():
                        staging.unlink()
            print(
                "Updated "
                + str(len(changed))
                + " source patches; supplied Git clones and provenance unchanged."
            )
            return 0
        if changed:
            print("Patch refresh required:")
            for name in changed:
                print("  " + name)
            return 1
        print("PASS: source patches are current; no export, clone or runtime file was changed.")
        return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError) as error:
        print("Patch synchronization refused: " + str(error), file=sys.stderr)
        raise SystemExit(2)
