#!/usr/bin/env python3
"""Safely apply this export to fresh, pinned LOTUSim and Unity checkouts.

Default is a dry run. No clone, download, compilation, git commit, reset,
container control or Unity launch is performed by this installer.
"""
import argparse
import json
from pathlib import Path
import shutil
import subprocess
import sys
from verify_export import ROOT,digest,verify

def git(root,*arguments):
    result=subprocess.run(['git','-C',str(root),*arguments],text=True,capture_output=True)
    if result.returncode:raise ValueError('Git check failed in '+root.name+': '+result.stderr.strip())
    return result.stdout.strip()

def target_path(root,relative):
    relative=Path(relative)
    if relative.is_absolute() or '..' in relative.parts:raise ValueError('Unsafe overlay path')
    current=root
    for part in relative.parts:
        current=current/part
        if current.is_symlink():raise ValueError('Target symlink refused: '+str(relative))
    current.resolve().relative_to(root)
    return current

def prepare(root,args,provenance):
    targets={'LOTUSim':args.core.resolve(strict=True),'LOTUSim-Unity-modules':args.unity.resolve(strict=True)}
    for label,target in targets.items():
        if Path(git(target,'rev-parse','--show-toplevel')).resolve()!=target:raise ValueError('Use the repository root for '+label)
        if git(target,'rev-parse','HEAD')!=provenance['repositories'][label]['baseCommit']:
            raise ValueError(label+' is not at the recorded base commit; use a fresh compatible clone.')
        if git(target,'diff','--name-only') or git(target,'diff','--cached','--name-only'):
            raise ValueError(label+' has tracked local edits. They were preserved. Use fresh checkouts, not your working project.')
    if targets['LOTUSim'].parent!=targets['LOTUSim-Unity-modules'].parent or targets['LOTUSim'].name!='LOTUSim' or targets['LOTUSim-Unity-modules'].name!='LOTUSim-Unity-modules':
        raise ValueError('Unity builders expect sibling repositories named LOTUSim and LOTUSim-Unity-modules.')
    selected=[item for item in provenance['patches'] if item['default'] or
              item['option']=='environment' and args.with_environment or
              item['option']=='interactive' and args.with_interactive]
    for item in selected:
        patch=root/item['file'];target=targets[item['repository']]
        git(target,'apply','--check',str(patch))
    copies=[]
    for label,target in targets.items():
        overlay=root/'components'/label
        for source in sorted(overlay.rglob('*')):
            if not source.is_file():continue
            if source.is_symlink():raise ValueError('Unexpected overlay symlink')
            relative=source.relative_to(overlay)
            # Runtime datasets created by using the stand-alone dashboard are
            # deliberately not installed into another project.
            if 'artifacts' in relative.parts or '__pycache__' in relative.parts or source.suffix=='.pyc':continue
            destination=target_path(target,relative)
            if destination.exists() and (not destination.is_file() or digest(source)!=digest(destination)):
                raise ValueError('Existing differing file preserved: '+label+'/'+relative.as_posix())
            copies.append((source,destination))
    return targets,selected,copies

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core',type=Path,required=True)
    parser.add_argument('--unity',type=Path,required=True)
    parser.add_argument('--apply',action='store_true',help='Write only after every preflight passes; default is dry-run')
    parser.add_argument('--with-environment',action='store_true',help='Include Nix/Mise CPU-rendering and local ignore patches')
    parser.add_argument('--with-interactive',action='store_true',help='Include legacy Launcher/camera and local XR settings patches')
    args=parser.parse_args()
    try:
        verify(ROOT)
        provenance=json.loads((ROOT/'provenance.json').read_text(encoding='utf-8'))
        targets,selected,copies=prepare(ROOT,args,provenance)
        print('Preflight PASS: '+str(len(selected))+' patch groups, '+str(len(copies))+' source/asset files.')
        for item in selected:print('  '+item['id'])
        if not args.apply:
            print('DRY RUN: no files changed. Add --apply after closing Unity and using fresh checkouts.')
            return
        for item in selected:git(targets[item['repository']],'apply',str(ROOT/item['file']))
        for source,destination in copies:
            if destination.exists():
                if digest(source)!=digest(destination):raise ValueError('Concurrent target edit detected; file preserved: '+str(destination))
                continue
            destination.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,destination)
        print('Installed. No compilation, service start or Play was performed. Continue with docs/INSTALLATION_COMPLETE.md.')
    except (ValueError,OSError) as error:
        print('Installation refused: '+str(error),file=sys.stderr)
        raise SystemExit(2)

if __name__=='__main__':main()
