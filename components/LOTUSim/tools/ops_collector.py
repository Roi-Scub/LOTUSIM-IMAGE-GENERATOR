"""Read-only, bounded local observations for the LOTUSim operations dashboard.

No ROS connection, service call, simulation control, process kill or network
probe is performed. Docker inspection reads only state, selected /proc facts
and listening sockets; process arguments and environments never enter the API.
"""
import datetime as dt
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import time
from urllib.parse import quote

from scene_preparation_status import observe_preparation
from renderer_telemetry import (RendererTelemetryAdapter, UnityTelemetryAdapter,
                                choose_renderer, safe_child)

SCHEMA = 'lotusim-ops-state-1'
TERMINAL = {'complete', 'completed', 'finished', 'success', 'done', 'complete_cleanup_unconfirmed'}
FAILED = {'failed', 'error', 'timeout', 'cancelled', 'aborted', 'interrupted'}
ACTIVE = {'starting', 'staging', 'transporting', 'inferencing', 'loading_model',
          'detecting', 'evaluating', 'reporting', 'warming_up', 'recording',
          'capturing', 'running', 'classifying', 'preparing'}
MAX_JSON = 2 * 1024 * 1024

# The shell reads only this one container's processes, and emits service labels
# and PIDs, never the argv used to recognize them. The probe excludes itself.
PROC_PROBE = r'''
for netfile in /proc/net/tcp /proc/net/tcp6; do
  [ -r "$netfile" ] || continue
  while read -r slot localaddr peer state rest; do
    [ "$state" = "0A" ] || continue
    case "${localaddr##*:}" in
      2710) printf 'L|ros|10000\n';;
      303A) printf 'L|xdyn|12346\n';;
      1F90) printf 'L|web|8080\n';;
      1388) printf 'L|api|5000\n';;
    esac
  done < "$netfile"
done
for entry in /proc/[0-9]*; do
  procid=${entry##*/}
  [ "$procid" = "$$" ] && continue
  [ -r "$entry/cmdline" ] || continue
  commandline=$(tr '\000' ' ' < "$entry/cmdline" 2>/dev/null)
  case "$commandline" in
    *default_server_endpoint*) printf 'P|ros|%s\n' "$procid";;
    *'.gz-wrapped sim '*|*gz-sim-server*) printf 'P|gazebo|%s\n' "$procid";;
    *xdyn-for-cs*) printf 'P|xdyn|%s\n' "$procid";;
    *lotusim_backend/dist/main.js*) printf 'P|api|%s\n' "$procid";;
    *static-web-server*'--port 8080'*) printf 'P|web|%s\n' "$procid";;
  esac
done
'''


def _iso(epoch):
    return dt.datetime.fromtimestamp(epoch, dt.timezone.utc).isoformat().replace('+00:00', 'Z')


def _epoch(value):
    if not isinstance(value, str):
        return None
    try:
        # Unity emits seven fractional digits. Python 3.9 accepts only three
        # or six; normalize to microseconds without changing the UTC offset.
        normalized=re.sub(r'([T ]\d{2}:\d{2}:\d{2})\.(\d+)',
                          lambda match:match.group(1)+'.'+match.group(2)[:6].ljust(6,'0'),value)
        parsed = dt.datetime.fromisoformat(normalized.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            return None
        return parsed.timestamp()
    except (ValueError, OverflowError):
        return None


def _num(value, default=None):
    try:
        return value if not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value) else default
    except OverflowError:
        return default


def _text(value, limit=180):
    return ' '.join(str(value or '').split())[:limit]


def _mtime(path):
    try:
        return path.stat().st_mtime
    except OSError:
        return 0.0


def _read(path):
    try:
        if path.is_symlink() or not path.is_file() or path.stat().st_size > MAX_JSON:
            return None
        def reject_constant(value):
            raise ValueError('Non-finite JSON constant')
        result = json.loads(path.read_text(encoding='utf-8'),parse_constant=reject_constant)
        return result if isinstance(result, (dict, list)) else None
    except (OSError, ValueError, UnicodeError):
        return None


def _dirs(path, limit=256):
    try:
        children = [Path(entry.path) for entry in os.scandir(path)
                    if entry.is_dir(follow_symlinks=False)]
        return sorted(children, key=_mtime, reverse=True)[:limit]
    except OSError:
        return []


class Collector:
    """Snapshots are read-only. The owning server serializes/caches calls.

    ``resolve_file(token)`` exposes a private registered Path to the server.
    Client JSON contains opaque URLs only. The server must validate descendants
    for HTML assets against the registered file's parent and reject symlinks.
    """
    def __init__(self, core_root, unity_root, *, clock=time.time, docker_enabled=True,
                 probe_runner=subprocess.run, asset_url=None, process_probe=None,
                 discovery_interval=5.0, docker_interval=10.0):
        self.core = Path(core_root).resolve()
        self.unity = Path(unity_root).resolve()
        self.clock = clock
        self.docker_enabled = docker_enabled
        self.runner = probe_runner
        self.asset_url = asset_url
        self.process_probe = process_probe or self._process_alive
        self.discovery_interval = discovery_interval
        self.docker_interval = max(10.0, docker_interval)
        self._discovered_at = -float('inf')
        self._docker_at = -float('inf')
        self._campaign_dirs = []
        self._job_dirs = []
        self._files = {}
        self._preview_cache = {}
        self._docker_cache = None
        self._files_roots = (self.core/'artifacts', self.unity/'artifacts')
        self._engine_profiles = []
        self._engine_profile = None
        self._renderer_roots = []

    def _engine_config(self):
        # Profile reads do not select/register/launch anything. The heartbeat's
        # source is validated independently against this registered id list.
        from engine_registry import EngineRegistry
        registry = EngineRegistry(self.core, self.unity)
        try:
            catalog = registry.catalog()
        except (OSError, ValueError):
            # An unreadable selection cannot suppress actual legacy evidence or
            # authorize an unregistered source. Expose failure, never select a
            # replacement profile or repair user files during a read.
            catalog = {'engines': [], 'selectedEngine': {'id': None, 'label': 'Profil indisponible',
                       'state': 'error', 'detail': 'Le profil configuré est illisible ou non sûr',
                       'nativeValidated': False}}
        self._engine_profiles = catalog['engines']
        self._engine_profile = catalog['selectedEngine']
        self._renderer_roots = [(self.core/'artifacts/renderers'/item['id'], item)
                                for item in self._engine_profiles]
        return self._engine_profile

    def _source(self, engine_id):
        descriptor = next((item for item in self._engine_profiles if item['id'] == engine_id), None)
        label = descriptor.get('label') if descriptor else 'Unity' if engine_id == 'unity' else None
        return {'engineId': engine_id, 'engineLabel': label,
                'sourceEngine': {'id': engine_id, 'label': label} if engine_id else None}

    def _directory_source(self, path):
        path = Path(path)
        for root, descriptor in self._renderer_roots:
            try:
                relative = path.relative_to(root)
                if safe_child(self.core, path, directory=True):
                    return self._source(descriptor['id']), str(relative).replace(os.sep, '/')
            except ValueError:
                pass
        try:
            relative = path.relative_to(self.unity/'artifacts')
            if safe_child(self.unity, path, directory=True):
                return self._source('unity'), str(relative).replace(os.sep, '/')
        except ValueError:
            pass
        return self._source(None), None

    def _renderer_path(self, renderer, value, *, directory=False):
        if renderer.get('type') == 'unity_legacy':
            root, authority = self.unity/'artifacts', self.unity
        elif renderer.get('engineId') in {item['id'] for item in self._engine_profiles}:
            root, authority = self.core/'artifacts/renderers'/renderer['engineId'], self.core
        else:
            return None
        if not isinstance(value, str) or not value or len(value)>4096:
            return None
        candidate = Path(value) if Path(value).is_absolute() else root/value
        candidate = safe_child(authority, candidate, directory=directory)
        if candidate is None:
            return None
        try:
            candidate.relative_to(root)
        except ValueError:
            return None
        return candidate

    def resolve_file(self, token):
        path = self._files.get(str(token))
        return path if path is not None and self._allowed(path) else None

    def file_url(self,path,kind='file'):
        """Register an existing allowlisted artifact for a local report link."""
        return self._asset(path,kind)

    def _allowed(self, path):
        path = Path(path)
        try:
            if path.is_symlink() or not path.is_file():
                return False
            real = path.resolve(strict=True)
            for root in self._files_roots:
                try:
                    if root.is_symlink():
                        continue
                    relative = real.relative_to(root.resolve())
                    # Reject symlinked directories as well as symlinked files.
                    current = root
                    for part in relative.parts:
                        current = current/part
                        if current.is_symlink():
                            return False
                    return True
                except ValueError:
                    pass
            return False
        except OSError:
            return False

    def _asset(self, path, kind='file'):
        path = Path(path)
        if not self._allowed(path):
            return None
        if self.asset_url is not None:
            return self.asset_url(path, kind)
        token = hashlib.sha256(str(path.resolve()).encode()).hexdigest()[:24]
        self._files[token] = path.resolve()
        return '/files/'+token+'/'+quote(path.name,safe='')

    def _relative(self, path):
        return self._directory_source(path)[1]

    def _discover(self, now):
        if now-self._discovered_at < self.discovery_interval:
            return
        campaigns = []
        roots = [(self.unity/'artifacts', False)] + [(root, True) for root, _ in self._renderer_roots]
        for artifacts, neutral in roots:
            authority = self.core if neutral else self.unity
            for group in _dirs(artifacts, 80):
                if not safe_child(authority, group, directory=True):
                    continue
                if neutral and (group/'status.json').is_file():
                    campaigns.append(group)
                    continue
                if not (group.name in ('datasets','manual-campaigns','captures','campaigns') or group.name.startswith('dataset-')):
                    continue
                for candidate in _dirs(group, 128):
                    if (candidate/'status.json').is_file():
                        campaigns.append(candidate)
                    else:
                        # Existing isolated diagnostics use one extra parent level.
                        campaigns.extend(p for p in _dirs(candidate, 24)
                                         if (p/'status.json').is_file())
        campaigns = sorted(set(campaigns), key=lambda p:_mtime(p/'status.json'), reverse=True)[:180]
        jobs = []
        for campaign in campaigns:
            for name in ('visual-observer', 'visual-verification'):
                jobs.extend(p for p in _dirs(campaign/name, 32) if (p/'status.json').is_file())
        # Diagnostic runs generated outside a Unity campaign are still useful
        # reports, but only this known directory depth is visited.
        base = self.core/'artifacts/rgb-validation/pilot-20261026'
        jobs.extend(p for p in _dirs(base, 32) if (p/'status.json').is_file())
        for root, _ in self._renderer_roots:
            jobs.extend(p for p in _dirs(root/'rgb-validation', 32)
                        if safe_child(self.core,p,directory=True) and (p/'status.json').is_file())
        self._campaign_dirs = campaigns
        self._job_dirs = sorted(set(jobs), key=lambda p:_mtime(p/'status.json'), reverse=True)[:120]
        self._discovered_at = now

    def _command(self, argv, timeout=2.0):
        try:
            result = self.runner(argv, capture_output=True, text=True, timeout=timeout, check=False,
                                 env={**os.environ,'LC_ALL':'C'})
            return result.stdout if result.returncode == 0 and len(result.stdout)<=4*1024*1024 else None
        except (OSError, subprocess.SubprocessError):
            return None

    def _docker(self, now):
        if now-self._docker_at < self.docker_interval and self._docker_cache is not None:
            return self._docker_cache
        self._docker_at = now
        result = {'state':'unknown', 'containerState':None, 'observedAt':_iso(now),
                  'detail':'Inspection Docker désactivée', 'processes':{}, 'listeners':{}, 'probeSucceeded':False}
        if not self.docker_enabled:
            self._docker_cache = result
            return result
        executable = shutil.which('docker')
        if not executable:
            executable = next((p for p in ('/usr/local/bin/docker', '/Applications/Docker.app/Contents/Resources/bin/docker') if Path(p).is_file()), None)
        if not executable:
            result['detail'] = 'Docker CLI introuvable ; état non mesuré'
            self._docker_cache = result
            return result
        text = self._command([executable, 'inspect', '--format', '{{json .State}}', 'lotusim-dev'])
        try:
            state = json.loads(text) if text else None
        except ValueError:
            state = None
        if not isinstance(state, dict):
            result['detail'] = 'Docker indisponible ou accès non autorisé'
        elif state.get('Running') is not True:
            result.update(state='stopped', containerState=_text(state.get('Status')), detail='Conteneur lotusim-dev arrêté')
        else:
            result.update(state='running', containerState='running', detail='Conteneur lotusim-dev actif')
            probe = self._command([executable, 'exec', 'lotusim-dev', 'sh', '-c', PROC_PROBE], timeout=3.0)
            if probe is not None:
                result['probeSucceeded'] = True
                for line in probe.splitlines()[:2000]:
                    parts = line.split('|')
                    if len(parts) != 3 or parts[1] not in {'ros','xdyn','web','api','gazebo'} or not parts[2].isdigit():
                        continue
                    if parts[0] == 'P':
                        result['processes'].setdefault(parts[1], []).append(int(parts[2]))
                    elif parts[0] == 'L':
                        result['listeners'][parts[1]] = result['listeners'].get(parts[1], 0)+1
            else:
                result['detail'] += ' ; détails des services non mesurés'
        self._docker_cache = result
        return result

    def _process_alive(self, runtime):
        pid = runtime.get('pid', runtime.get('workerPid', runtime.get('coordinatorPid')))
        birth = runtime.get('processBirth', runtime.get('processStart'))
        if isinstance(pid, bool) or not isinstance(pid, int) or pid <= 1 or not isinstance(birth, str) or not birth.strip():
            return None
        # PID plus process-birth fingerprint avoids treating a reused PID as the
        # old model process. Only the birth date is queried, never argv/env.
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False
        except (PermissionError, OSError):
            return None
        observed = self._command(['ps', '-p', str(pid), '-o', 'lstart='], timeout=.8)
        return observed.strip() == birth.strip() if observed else None

    def _job_state(self, status, path, now, runtime=None, corroborated=False):
        phase = _text(status.get('status','unknown'), 80)
        age = max(0.0, now-_mtime(path))
        active = phase in ACTIVE or phase.startswith('lotusim_')
        if phase in TERMINAL:
            return 'ready', age, False
        if phase in FAILED:
            return 'error', age, False
        if phase == 'idle':
            return 'idle', age, False
        if active:
            alive = self.process_probe(runtime or {}) if runtime else None
            if corroborated or alive is True:
                return 'running', age, True
            if alive is False or age > 30:
                return 'stale', age, False
            return 'unknown', age, False
        return 'unknown', age, False

    def _unity(self, now):
        return UnityTelemetryAdapter(self.unity).observe(now)

    def _renderer(self, now, unity):
        neutral = RendererTelemetryAdapter(self.core, self._engine_profiles).observe(now)
        return choose_renderer(neutral, unity)

    def _campaign(self, directory, now):
        path = directory/'status.json'; status = _read(path)
        if not isinstance(status, dict):
            return None
        state, age, live = self._job_state(status,path,now)
        return {'id':hashlib.sha256(str(directory).encode()).hexdigest()[:16],
                'name':directory.name, 'outputName':self._relative(directory),
                'status':_text(status.get('status','unknown'),80), 'state':state,
                'captured':_num(status.get('captured'),_num(status.get('completed'),0)), 'expected':_num(status.get('expected')),
                'boxes':_num(status.get('boxes')), 'updatedAt':_iso(_mtime(path)),
                'ageSeconds':round(age,2), 'live':live, 'historical':True,
                'reportUrl':self._asset(directory/'index.html','capture'),
                'previewUrl':None, 'error':self._safe_error(status.get('error')),
                **self._directory_source(directory)[0]}

    def _safe_error(self, value):
        # Error summaries only, not stack traces containing local paths/tokens.
        lines = str(value or '').splitlines()
        text = lines[0] if lines else ''
        return _text(text.replace(str(self.core),'[LOTUSim]').replace(str(self.unity),'[Unity]'),220)

    def _vision(self, now, renderer_raw, renderer):
        if not self._job_dirs:
            return {'status':'idle','state':'idle','live':False,'completed':0,'expected':None,
                    'progress':None,'ageSeconds':None,'detail':'Aucune analyse RGB enregistrée'}, None
        candidates = []
        for directory in self._job_dirs[:80]:
            status = _read(directory/'status.json')
            if not isinstance(status,dict):
                continue
            phase = _text(status.get('status','unknown'),80)
            worker = _read(directory/'predictions/status.json')
            if isinstance(worker,dict) and phase not in TERMINAL|FAILED:
                detail = worker
                state_path = directory/'predictions/status.json'
            else:
                detail, state_path = status, directory/'status.json'
            runtime = _read(directory/'predictions/runtime.json') or _read(directory/'runtime.json')
            observer = renderer_raw.get('rgbObserver') if isinstance(renderer_raw.get('rgbObserver'),dict) else {}
            source, _ = self._directory_source(directory)
            same_output = False
            try:
                observed_directory = self._renderer_path(renderer,observer.get('outputDirectory',''),directory=True)
                same_output = observed_directory is not None and observed_directory.resolve() == directory.resolve()
            except (OSError,ValueError,TypeError):
                pass
            corroborated = (renderer.get('fresh') and observer.get('running') is True and same_output
                            and source['engineId'] == renderer.get('engineId'))
            state, age, live = self._job_state(detail,state_path,now,runtime if isinstance(runtime,dict) else None,corroborated)
            completed = _num(detail.get('completed',status.get('images')),0)
            expected = _num(detail.get('expected',status.get('expected',status.get('images'))))
            region, regions = _num(detail.get('region')), _num(detail.get('regions'))
            fractional = (region/regions) if region is not None and regions and live else 0
            progress = min(1,max(0,(completed+fractional)/expected)) if expected else None
            if phase in TERMINAL and expected:
                completed, progress = expected, 1.0
            value = {'id':hashlib.sha256(str(directory).encode()).hexdigest()[:16],
                     'status':_text(detail.get('status','unknown'),80), 'state':state,
                     'live':live,'historical':not live,'completed':completed,'expected':expected,
                     'currentImage':_text(detail.get('currentImage'),80), 'region':region,
                     'regions':regions, 'progress':progress,'ageSeconds':round(age,2),
                     'updatedAt':_iso(_mtime(state_path)), 'name':directory.name,
                     'reportUrl':self._asset(directory/'index.html','visual_review'),
                     'detail':'Analyse active confirmée' if live else 'État ancien : exécution non confirmée' if state=='stale' else 'Dernière analyse enregistrée',
                     **source}
            candidates.append((live,_mtime(directory/'status.json'),value,directory))
        if not candidates:
            return {'status':'idle','state':'idle','live':False,'completed':0,'expected':None,'progress':None,'ageSeconds':None},None
        chosen = max(candidates,key=lambda item:(item[0],item[1]))
        return chosen[2], chosen[3]

    def _last_rgb(self, directory):
        rgb = directory/'rgb'
        mtime = _mtime(rgb)
        cached = self._preview_cache.get(str(rgb))
        if cached and cached[0] == mtime:
            return cached[1]
        try:
            # Read just this selected RGB directory, never masks or all frames.
            files = (Path(entry.path) for entry in os.scandir(rgb)
                     if entry.is_file(follow_symlinks=False) and entry.name.lower().endswith(('.png','.jpg','.jpeg')))
            latest = max(files,key=lambda p:p.name,default=None)
        except OSError:
            latest = None
        self._preview_cache[str(rgb)] = (mtime,latest)
        return latest

    def _preview(self, now, renderer_raw, renderer, capture_directory):
        info = renderer_raw.get('preview')
        source = self._source(renderer.get('engineId'))
        if (isinstance(info,dict) and isinstance(info.get('file'), str)
                and _epoch(info.get('updatedAt')) is not None
                and (_num(info.get('width'),0)>0) and (_num(info.get('height'),0)>0)):
            filename = info['file']
            if filename == 'preview.jpg':
                filename = 'operations/preview.jpg'
            path = self._renderer_path(renderer, filename)
            url = self._asset(path,'preview') if path and path.suffix.lower() in ('.jpg','.jpeg','.png','.webp') else None
            if url:
                observed = _epoch(info.get('updatedAt')) or _mtime(path)
                age = max(0,now-observed)
                live = renderer['fresh'] and info.get('live') is True and age<=8 and observed<=now+5
                label = renderer.get('label') or 'moteur graphique'
                return {'url':url,'kind':'live' if live else 'historical',
                        'label':'Aperçu '+label+' récent' if live else 'Dernier aperçu '+label+' — pas un direct',
                        'live':live,'updatedAt':_iso(observed),'ageSeconds':round(age,2),
                        'width':_num(info.get('width')),'height':_num(info.get('height')),
                        'source':_text(info.get('source')), **source}
        candidates=([capture_directory] if capture_directory is not None else [])
        candidates += [path for path in self._campaign_dirs[:5] if path not in candidates]
        for directory in candidates[:6]:
            image = self._last_rgb(directory)
            if image:
                url = self._asset(image,'preview')
                if not url:
                    continue
                return {'url':url,'kind':'historical',
                        'label':'Dernière capture — pas une vidéo directe','live':False,
                        'updatedAt':_iso(_mtime(image)),'ageSeconds':round(max(0,now-_mtime(image)),2),
                        'width':None,'height':None,'source':'completed_rgb_file',
                        'campaignName':directory.name, **self._directory_source(directory)[0]}
        return {'url':None,'kind':'unavailable','label':'Aucun aperçu disponible','live':False,
                'updatedAt':None,'ageSeconds':None,'width':None,'height':None, **self._source(None)}

    def _scene(self, raw, renderer, capture):
        source = raw.get('lotusim')
        engine_source = self._source(renderer.get('engineId'))
        label = renderer.get('label') or 'moteur non observé'
        if not isinstance(source,dict) or source.get('hasFrame') is not True:
            return {'source':label+' / dernier instantané LOTUSim reçu','available':False,
                    'live':False,'objects':[],'frame':None,'timeSeconds':None,'observerId':None,
                    **engine_source}
        objects=[]
        values=source.get('objects') if isinstance(source.get('objects'),list) else []
        for item in values[:256]:
            if not isinstance(item,dict) or any(_num(item.get(key)) is None for key in ('eastM','northM','altitudeM')):
                continue
            objects.append({key:_text(item.get(key),100) if key in ('id','model') else item[key]
                            for key in ('id','model','eastM','northM','altitudeM')})
        observed=_epoch(source.get('snapshotUpdatedAt'))
        age=max(0,self.clock()-observed) if observed else None
        return {'source':'Dernier instantané LOTUSim reçu par '+label, 'available':True,
                'live':bool(renderer['fresh'] and renderer['isPlaying'] and not renderer['isPaused']
                            and capture.get('live') and observed is not None and 0<=self.clock()-observed<=8),
                'frame':_num(source.get('frame')),'timeSeconds':_num(source.get('timeSeconds')),
                'worldTimeSeconds':_num(source.get('worldTimeSeconds')),
                'observerId':_text(source.get('observerId'),100),'objects':objects,
                'objectCount':len(objects),'updatedAt':_iso(observed) if observed else None,
                'paused':bool(renderer['isPaused']),
                'ageSeconds':round(age,2) if age is not None else None, **engine_source}

    def _planner(self,now):
        candidates=[]
        paths = [self.unity/'artifacts/traffic-agents/ops-status.json',
                 self.core/'artifacts/traffic-agents/ops-status.json']
        paths.extend(root/'traffic-agents/ops-status.json' for root, _ in self._renderer_roots)
        for path in paths:
            if not self._allowed(path):
                continue
            runtime=_read(path)
            if not isinstance(runtime,dict) or runtime.get('schema')!='lotusim-ops-job-1':continue
            status={'status':runtime.get('state','unknown')}
            state,age,live=self._job_state(status,path,now,runtime)
            candidates.append((_mtime(path),{'status':status['status'],'state':state,'ageSeconds':round(age,2),
                               'live':live,'updatedAt':_iso(_mtime(path)),
                               'currentAgent':_text(runtime.get('currentAgent'),80)},runtime))
        if not candidates:return {'status':'idle','state':'idle','live':False,'updatedAt':None},None
        chosen=max(candidates,key=lambda item:item[0]);return chosen[1],chosen[2]

    def _events(self, campaign_directory, job_directory, now,planner_runtime=None, preparation_events=()):
        events=[]
        if job_directory:
            source = _read(job_directory/'agent-events.json')
            if isinstance(source,list):
                for index,item in enumerate(source[-60:]):
                    if not isinstance(item,dict):continue
                    at=_epoch(item.get('at')) or _mtime(job_directory/'agent-events.json')
                    phase=_text(item.get('state'),80);agent=_text(item.get('agent'),80)
                    message=agent+' · '+phase
                    if item.get('error'):message+=' : '+self._safe_error(item['error'])
                    events.append({'id':hashlib.sha256((str(job_directory)+str(index)+message).encode()).hexdigest()[:20],
                                   'at':_iso(at),'source':agent or 'vision','level':'error' if phase=='failed' else 'info',
                                   'message':message,'historical':now-at>15})
        if campaign_directory:
            path=campaign_directory/'traffic-agent-messages.json';source=_read(path)
            messages=source.get('messages',[]) if isinstance(source,dict) and isinstance(source.get('messages'),list) else []
            for item in messages[-30:]:
                if not isinstance(item,dict):continue
                sender=_text(item.get('sender'),80);recipient=_text(item.get('recipient'),80)
                message=sender+' → '+recipient+' · '+_text(item.get('kind'),80)
                events.append({'id':'plan-'+str(item.get('index',len(events))), 'at':_iso(_mtime(path)),
                               'source':'planification','level':'info','message':message,'historical':True})
        if isinstance(planner_runtime,dict):
            values=planner_runtime.get('events') if isinstance(planner_runtime.get('events'),list) else []
            for index,item in enumerate(values[-60:]):
                if not isinstance(item,dict):continue
                at=_epoch(item.get('at')) or _epoch(planner_runtime.get('updatedAt')) or now
                source=_text(item.get('source'),80)
                message=_text(item.get('message'),200) or source+' · '+_text(item.get('kind'),80)
                events.append({'id':'planner-'+str(item.get('id',index)), 'at':_iso(at),
                               'source':source or 'planification','level':'error' if item.get('kind')=='failed' else 'info',
                               'message':message,'historical':now-at>15})
        events.extend(preparation_events)
        return sorted(events,key=lambda e:e['at'],reverse=True)[:80]

    def snapshot(self):
        now=self.clock();profile=self._engine_config();self._discover(now)
        unity,unity_raw=self._unity(now)
        renderer,raw=self._renderer(now,(unity,unity_raw));docker=self._docker(now)
        renderer['profileMismatch'] = bool(profile.get('id') and renderer.get('engineId') and renderer['engineId'] != profile['id'])
        campaigns=[c for directory in self._campaign_dirs for c in [self._campaign(directory,now)] if c]
        by_id={hashlib.sha256(str(p).encode()).hexdigest()[:16]:p for p in self._campaign_dirs}
        capture=campaigns[0].copy() if campaigns else {'status':'idle','state':'idle','live':False,
                    'captured':0,'expected':None,'boxes':None,'outputName':None,'updatedAt':None,'ageSeconds':None,
                    **self._source(None)}
        capture_directory=by_id.get(capture.get('id'))
        current=raw.get('capture')
        if renderer['fresh'] and isinstance(current,dict) and current.get('outputDirectory'):
            try:
                directory=self._renderer_path(renderer,current['outputDirectory'],directory=True)
                if directory is not None:
                    source, relative=self._directory_source(directory)
                    capture_directory=directory
                    phase=_text(current.get('status','idle'),80)
                    active=phase in ACTIVE or phase.startswith('lotusim_')
                    state='error' if phase in FAILED else 'ready' if phase in TERMINAL else 'paused' if renderer['isPaused'] else 'running' if renderer['isPlaying'] and active else 'idle'
                    capture={'status':phase,'state':state,'captured':_num(current.get('captured'),0),
                             'expected':_num(current.get('expected')),'boxes':_num(current.get('boxes')),
                             'outputName':relative,'updatedAt':renderer['updatedAt'],
                             'ageSeconds':renderer['ageSeconds'],'live':state=='running',
                             'historical':False,'reportUrl':self._asset(directory/'index.html','capture'),
                             **source}
            except (OSError,ValueError,TypeError):
                pass
        vision,job=self._vision(now,raw,renderer)
        for key,value in self._source(vision.get('engineId')).items():
            vision.setdefault(key,value)
        planner,planner_runtime=self._planner(now)
        # Preparation runs in this dashboard interpreter. Its non-persisted
        # owner token confirms process incarnation without a ps/argv probe.
        preparation,preparation_events=observe_preparation(self.core,now=now,
                                                         process_alive=lambda pid:pid==os.getpid())
        preparation['engineLabel']=self._source(preparation.get('engine'))['engineLabel']
        services=[{'id':'docker','label':'Docker','state':docker['state'],'detail':docker['detail'],
                   'evidence':'docker_state','updatedAt':docker['observedAt']}]
        for identifier,label,port in [('gazebo','LOTUSim / Gazebo',None),('ros','ROS TCP',10000),
                                      ('xdyn','xDyn',12346),('web','Interface Web',8080),('api','API LOTUSim',5000)]:
            processes=docker['processes'].get(identifier,[]);listeners=docker['listeners'].get(identifier,0)
            if docker['state']=='stopped':state='stopped';detail='Conteneur arrêté'
            elif docker['state']!='running' or not docker['probeSucceeded']:state='unknown';detail='État non mesuré'
            elif processes and (port is None or listeners):state='running';detail='Processus observé'+(' ; écoute sur '+str(port) if port else '')
            elif listeners:state='unknown';detail='Port en écoute ; processus non identifié'
            else:state='stopped';detail='Service non détecté dans le conteneur'
            services.append({'id':identifier,'label':label,'state':state,'detail':detail,
                             'evidence':'container_proc_and_listeners','updatedAt':docker['observedAt'],
                             'listenerCount':listeners,'optional':identifier=='xdyn'})
        services.append({'id':'renderer','label':'Moteur graphique','state':renderer['state'],
                         'detail':(renderer.get('label')+' · ' if renderer.get('label') else '')+renderer['detail'],
                         'evidence':renderer['source'],'updatedAt':renderer['updatedAt'],
                         **self._source(renderer.get('engineId'))})
        warnings=[]
        if profile.get('id') is None:warnings.append('Profil du moteur illisible : aucun remplacement ou enregistrement automatique effectué.')
        if docker['state']=='unknown':warnings.append('Docker non observé : aucune hypothèse d’exécution des services.')
        if not renderer['fresh']:warnings.append('Aucune télémétrie récente du moteur graphique : aperçu et instantanés peuvent être historiques.')
        if renderer['profileMismatch']:
            warnings.append('Profil configuré '+profile['label']+' ; source observée '+renderer['label']+' : les images conservent leur provenance réelle.')
        if docker['state']=='running' and any(s['id'] in ('gazebo','ros') and s['state']!='running' for s in services):
            warnings.append('Chaîne incomplète : Gazebo ou ROS TCP ne sont pas observés comme actifs.')
        if _num((renderer.get('ros') or {}).get('activeInstanceCount'),0)>1:
            warnings.append('Plusieurs instances ROS actives signalées par '+renderer['label']+' ; aucun arrêt automatique effectué.')
        agents=[preparation]
        stage_labels=[('orchestrator','Orchestrateur','planification'),('planner','Agents de trajectoire','planification'),
                      ('lotusim','Synchronisation LOTUSim','simulation'),('renderer','Rendu graphique','capture'),
                      ('rgb_detector','Détecteur RGB','vision'),('proposal_reviewer','Revue des propositions','vision'),
                      ('reporter','Galerie et exports','sortie')]
        phase=vision.get('status','idle')
        for identifier,label,group in stage_labels:
            state='idle';detail='En veille'
            if identifier=='orchestrator' and vision.get('live') and phase in ('staging','transporting','preparing'):
                state='running';detail='Préparation de l’analyse RGB'
            elif identifier in ('orchestrator','planner') and planner.get('live'):
                state='running';detail=planner.get('currentAgent') or 'Planification déterministe en cours'
            elif identifier in ('orchestrator','planner') and planner.get('state')=='stale':
                state='stale';detail='Ancienne planification en cours, processus non confirmé'
            elif identifier in ('orchestrator','planner') and planner.get('state')=='error':
                state='error';detail='Dernière planification en erreur'
            elif identifier in ('orchestrator','planner') and capture_directory and (capture_directory/'traffic-agent-messages.json').is_file():
                state='ready';detail='Plan déterministe archivé — pas un agent actif'
            elif identifier=='renderer' and capture.get('live'):
                state='running';detail='Capture en cours'
            elif identifier=='lotusim' and capture.get('live') and isinstance(raw.get('lotusim'),dict) and raw['lotusim'].get('hasFrame') is True:
                state='running';detail='Instantanés synchronisés' if identifier=='lotusim' else 'Capture en cours'
            elif identifier in ('lotusim','renderer') and capture.get('state')=='paused':
                state='paused';detail='Play en pause'
            elif identifier=='rgb_detector' and vision.get('live') and phase in ('loading_model','detecting','running','inferencing','classifying'):
                state='running';detail='Calcul local sur les RGB'
            elif identifier=='proposal_reviewer' and vision.get('live') and phase in ('evaluating','reviewing'):
                state='running';detail='Contrôle des propositions'
            elif identifier=='reporter' and vision.get('live') and phase=='reporting':
                state='running';detail='Écriture du rapport'
            if identifier=='rgb_detector' and vision.get('state')=='stale':
                state='stale';detail='Ancien état en cours, processus non confirmé'
            agents.append({'id':identifier,'label':label,'group':group,'state':state,'detail':detail,
                           'historical':detail=='Plan déterministe archivé — pas un agent actif',
                           'updatedAt':vision.get('updatedAt') if group in ('vision','sortie') else capture.get('updatedAt')})
            if identifier == 'renderer':
                agents[-1].update(self._source(renderer.get('engineId')))
        reports=[]
        for path,label,kind in [(self.core/'artifacts/rgb-validation/index.html','Validation visuelle — synthèse','overview'),
                                (self.core/'artifacts/traffic-agents/index.html','Plan du trafic coopératif','traffic_plan')]:
            url=self._asset(path,kind)
            if url:reports.append({'id':hashlib.sha256(str(path).encode()).hexdigest()[:16],'label':label,'url':url,'kind':kind,'updatedAt':_iso(_mtime(path))})
        for root,descriptor in self._renderer_roots:
            for path,label in ((root/'index.html','Rapports · '+descriptor['label']),
                               (root/'rgb-validation/index.html','Validation RGB · '+descriptor['label'])):
                url=self._asset(path,'renderer_report')
                if url:reports.append({'id':hashlib.sha256(str(path).encode()).hexdigest()[:16],
                                       'label':label,'url':url,'kind':'renderer_report','updatedAt':_iso(_mtime(path)),
                                       **self._source(descriptor['id'])})
        for directory in self._job_dirs[:12]:
            url=self._asset(directory/'index.html','visual_review')
            if url:reports.append({'id':hashlib.sha256(str(directory).encode()).hexdigest()[:16],
                                   'label':'Revue RGB · '+directory.name,'url':url,'kind':'visual_review','updatedAt':_iso(_mtime(directory/'index.html')),
                                   **self._directory_source(directory)[0]})
        for item in campaigns[:6]:
            if item.get('reportUrl'):reports.append({'id':item['id'],'label':'Capture · '+item['name'],'url':item['reportUrl'],'kind':'capture','updatedAt':item['updatedAt'],
                                                    **self._source(item.get('engineId'))})
        events=self._events(capture_directory,job,now,planner_runtime,preparation_events)
        preview=self._preview(now,raw,renderer,capture_directory)
        if campaigns and capture_directory is not None:
            for item in campaigns:
                if by_id.get(item['id'])==capture_directory:item['previewUrl']=preview.get('url')
        return {'schema':SCHEMA,'generatedAt':_iso(now),
                'health':{'state':'ready' if renderer['fresh'] and renderer['state'] in ('running','idle','ready','paused') and all(next(s for s in services if s['id']==identifier)['state']=='running' for identifier in ('docker','gazebo','ros')) else 'degraded',
                          'readOnly':True,'noRosClientCreated':True,'pollIntervalSeconds':2,
                          'servicesRunning':sum(s['state'] in ('running','ready','idle','paused') for s in services),
                          'servicesObserved':len(services),'dockerProbeAgeSeconds':round(max(0,now-self._docker_at),2),
                          'unityTelemetryAgeSeconds':unity['ageSeconds'],
                          'rendererTelemetryAgeSeconds':renderer['ageSeconds'],'warnings':warnings},
                'services':services,'renderer':renderer,'engineProfile':profile,'unity':unity,
                'preview':preview,'capture':capture,'vision':vision,'planner':planner,
                'preparation':preparation,
                'agents':agents,'events':events,'campaigns':campaigns[:16],
                'reports':reports[:24],'scene':self._scene(raw,renderer,capture)}
