#!/usr/bin/env python3
"""Fetch only the eight audited CC-BY assets from the archived pinned manifest.

No remote scripts are executed. For example pass Unity's
ThirdParty/OpenObjects/manifest.json as --manifest. Per-model licences are
checked again before download; repository-wide licence assumptions are unsafe.
"""
import argparse
import hashlib
import json
import pathlib
import urllib.request


def get(url):
    request=urllib.request.Request(url,headers={'User-Agent':'LOTUSim-audited-assets/1.0'})
    with urllib.request.urlopen(request,timeout=90) as response:return response.read()


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',type=pathlib.Path,required=True)
    parser.add_argument('--output',type=pathlib.Path,required=True)
    args=parser.parse_args();records=json.loads(args.manifest.read_text())
    if len(records)!=8:raise ValueError('Expected the reviewed eight-asset lot')
    args.output.mkdir(parents=True,exist_ok=True)
    for info in records:
        key=info['key']
        if not key.replace('_','').isalnum() or info['license']!='CC-BY-4.0':raise ValueError('Unsafe or unaudited asset')
        folder=args.output/key;folder.mkdir(exist_ok=True)
        if 'sketchfab.com/3d-models/' in info['source']:
            uid=info['source'].rstrip('/').rsplit('-',1)[-1]
            raw=get('https://api.sketchfab.com/v3/models/'+uid);creator=json.loads(raw)
            if creator['license']['slug']!='by' or '/by/4.0' not in creator['license']['url']:raise ValueError('Licence changed; review '+key)
            (folder/'creator-license.json').write_bytes(raw)
        elif info['source']!='https://github.com/amvlab/aircraft-models':raise ValueError('Unknown original author repository')
        url=info['download'];revision=info['mirrorCommit']
        if len(revision)!=40 or '/'+revision+'/' not in url or not url.startswith('https://raw.githubusercontent.com/'):raise ValueError('Unpinned source')
        target=folder/('source.fbx' if info['format']=='fbx' else 'source.glb')
        data=target.read_bytes() if target.exists() else get(url)
        if hashlib.sha256(data).hexdigest()!=info['sha256']:raise ValueError('Source hash differs: '+key)
        target.write_bytes(data);(folder/'inspection.json').write_text(json.dumps(info,indent=2,ensure_ascii=False))
        print('Verified CC BY and SHA-256:',key,flush=True)
    notices={
        'srcejon/sdrangel-3d-models':('sdr',['LICENSE']),
        'amvlab/aircraft-models':('amv',['LICENSE','README.md']),
        'bilawalsidhu/gods-eye-view':('eye',['public/models/README.md']),
        'bob6664569/open-water':('water',['THIRD_PARTY_NOTICES.md']),
        'viniciusbarros/msc_game_obstacle_course':('bird',['README.md','ExternalMedia/Magpie/textures/Seagull-Base_Color.png'])}
    for repo,(prefix,paths) in notices.items():
        revision=next(i['mirrorCommit'] for i in records if i['mirrorRepository']==repo)
        for path in paths:(args.output/(prefix+'-'+path.replace('/','_'))).write_bytes(get(f'https://raw.githubusercontent.com/{repo}/{revision}/{path}'))
    (args.output/'manifest.json').write_text(json.dumps(records,indent=2,ensure_ascii=False))


if __name__=='__main__':main()
