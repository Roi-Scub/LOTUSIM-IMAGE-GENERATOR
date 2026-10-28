#!/usr/bin/env python3
"""Local LOTUSim dashboard and inert scenario preparation. No simulation controls."""
import argparse
import copy
from datetime import datetime, timezone
import http.server
import html
import io
from html.parser import HTMLParser
import json
import mimetypes
import os
from pathlib import Path
import re
import socket
import threading
import time
import zipfile
from urllib.parse import unquote, urlsplit, parse_qs

from ops_collector import Collector
from campaign_settings import CampaignStore,CampaignValidationError,CampaignSecurityError,MAX_JSON_BYTES,load_json_bytes
from mesh_library import MeshLibrary,MeshError,MAX_UPLOAD
from mesh_integration import MeshIntegrationService
from engine_registry import EngineRegistry
from traffic_plan_editor import (TrafficPlanStore, TrafficValidationError,
                                 TrafficConflictError, TrafficPlanSecurityError)
from traffic_plan_library import TrafficPlanLibrary

ROOT=Path(__file__).resolve().parents[1]
UI_ROOT=Path(__file__).with_name('ops_dashboard_ui')
EXTENSIONS={'.html','.htm','.png','.jpg','.jpeg','.webp','.json','.txt','.css','.js','.svg'}

_HTML_ATTRIBUTES=re.compile(r'''(?P<prefix>\s+)(?P<name>[^\s=/>]+)(?P<assign>\s*=\s*)(?:(?P<double>"[^"]*")|(?P<single>'[^']*')|(?P<bare>[^\s>]+))''',re.S)

def rewrite_report_html(data,path,server):
    """Retokenize existing artifact links, not request traversal permissions.

    Only href/src attributes in actual HTML start tags are inspected. Text,
    scripts, CSS and all unrelated markup are byte-for-byte preserved. A link
    may refer to another allowed artifacts root, but never arbitrary host files.
    Existing request paths still pass safe_child and cannot contain '..'.
    """
    register=getattr(server.hub.collector,'file_url',None)
    if register is None:return data
    try:text=data.decode('utf-8')
    except UnicodeDecodeError:return data
    source=Path(path).resolve();offsets=[0]
    for index,character in enumerate(text):
        if character=='\n':offsets.append(index+1)
    replacements=[]
    def link_url(value):
        value=html.unescape(value)
        if '\\' in value or '\0' in value:return None
        try:parts=urlsplit(value)
        except ValueError:return None
        if parts.scheme or parts.netloc or not parts.path or parts.path.startswith('/'):
            return None
        decoded=unquote(parts.path)
        if '\\' in decoded or '\0' in decoded:return None
        pieces=decoded.split('/')
        if any(p.startswith('.') and p not in ('.','..') for p in pieces):return None
        candidate=source.parent.joinpath(decoded)
        if candidate.suffix.lower() not in EXTENSIONS or not candidate.is_file():return None
        if not server.allowed_file(candidate):return None
        target=register(candidate,'report_asset')
        return parts._replace(path=target).geturl() if target else None
    class Links(HTMLParser):
        def __init__(self):super().__init__(convert_charrefs=False)
        def handle_starttag(self,tag,attrs):
            raw=self.get_starttag_text();line,column=self.getpos();base=offsets[line-1]+column
            for found in _HTML_ATTRIBUTES.finditer(raw):
                if found.group('name').lower() not in ('href','src'):continue
                group=next(name for name in ('double','single','bare') if found.group(name) is not None)
                token=found.group(group);value=token[1:-1] if group!='bare' else token
                replacement=link_url(value)
                if replacement is not None:
                    replacements.append((base+found.start(group),base+found.end(group),
                                         '"'+html.escape(replacement,quote=True)+'"'))
        def handle_startendtag(self,tag,attrs):self.handle_starttag(tag,attrs)
    parser=Links()
    try:parser.feed(text);parser.close()
    except (ValueError,OSError):return data
    if not replacements:return data
    rebuilt=[];cursor=0
    for start,end,replacement in sorted(replacements):
        if start<cursor:continue
        rebuilt.extend((text[cursor:start],replacement));cursor=end
    rebuilt.append(text[cursor:])
    return ''.join(rebuilt).encode('utf-8')

def iso_now():
    return datetime.now(timezone.utc).isoformat()

def safe_child(root,relative):
    """Resolve only non-hidden relative assets inside an allowed directory."""
    root=Path(root).resolve()
    if not isinstance(relative,str) or not relative or '\\' in relative or '\0' in relative:
        return None
    parts=relative.split('/')
    if any(not p or p in {'.','..'} or p.startswith('.') for p in parts):return None
    path=root.joinpath(*parts).resolve()
    try:path.relative_to(root)
    except ValueError:return None
    if path.suffix.lower() not in EXTENSIONS or not path.is_file():return None
    return path

class StateHub:
    def __init__(self,collector,interval=2.0):
        self.collector=collector;self.interval=interval
        self.condition=threading.Condition();self.stopped=threading.Event()
        self.version=0;self.error=None;self.thread=None
        self.state={'schema':'lotusim-ops-state-1','generatedAt':iso_now(),
            'health':{'state':'unknown','detail':'Démarrage du collecteur local'},
            'services':[],'agents':[],'events':[],'campaigns':[],'reports':[],
            'unity':None,'preview':None,'capture':None,'vision':None,'scene':None}
    def refresh(self):
        try:
            state=self.collector.snapshot()
            json.dumps(state,allow_nan=False)
            self.error=None
        except Exception as error:
            state=copy.deepcopy(self.state)
            self.error=type(error).__name__
            state['health']={'state':'error','detail':'Collecte indisponible ; dernier état conservé',
                             'errorType':self.error}
            for service in state.get('services',[]):service['state']='unknown'
            for agent in state.get('agents',[]):agent['state']='unknown'
            if isinstance(state.get('preview'),dict):state['preview']['live']=False
        state['monitor']={'updatedAt':iso_now(),'intervalSeconds':self.interval,
                          'readOnly':True,'collectorError':self.error}
        with self.condition:
            self.state=state;self.version+=1;self.condition.notify_all()
        return state
    def start(self):
        def loop():
            while not self.stopped.is_set():
                started=time.monotonic();self.refresh()
                self.stopped.wait(max(.05,self.interval-(time.monotonic()-started)))
        self.thread=threading.Thread(target=loop,name='lotusim-ops-collector',daemon=True)
        self.thread.start()
    def current(self):
        with self.condition:return self.version,copy.deepcopy(self.state)
    def close(self):
        self.stopped.set()
        with self.condition:self.condition.notify_all()
        if self.thread:self.thread.join(timeout=2)

class DashboardServer(http.server.ThreadingHTTPServer):
    daemon_threads=True
    allow_reuse_address=True
    def __init__(self,address,hub,ui_root=UI_ROOT,allowed_roots=(),settings=None,assets=None,integration=None,engines=None,traffic=None,traffic_library=None):
        self.hub=hub;self.ui_root=Path(ui_root).resolve()
        self.settings=settings
        self.assets=assets
        self.integration=integration
        self.engines=engines
        self.traffic=traffic
        self.traffic_library=traffic_library
        self.traffic_generation_slot=threading.BoundedSemaphore(1)
        self.import_slot=threading.BoundedSemaphore(1)
        self.allowed_roots=tuple(Path(p).resolve() for p in allowed_roots)
        self.stream_slots=threading.BoundedSemaphore(8)
        super().__init__(address,DashboardHandler)
    def allowed_file(self,path):
        path=Path(path).resolve()
        return any(path==root or root in path.parents for root in self.allowed_roots)

class DashboardHandler(http.server.BaseHTTPRequestHandler):
    protocol_version='HTTP/1.1'
    server_version='LOTUSimOps/1'
    def log_message(self,*args):pass
    def _authorized(self):
        port=self.server.server_address[1]
        hosts={'127.0.0.1:'+str(port),'localhost:'+str(port)}
        host=self.headers.get('Host','').lower()
        if host not in hosts:return False
        origin=self.headers.get('Origin')
        if origin is not None and origin not in {'http://'+h for h in hosts}:return False
        if self.headers.get('Sec-Fetch-Site')=='cross-site':return False
        return True
    def _headers(self,status,content_type,length=None,report=False,cache='no-store',attachment=None):
        if attachment is not None and (len(attachment)>100 or not re.fullmatch(r'[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+',attachment)):
            raise ValueError('Unsafe attachment name')
        self.send_response(status)
        self.send_header('Content-Type',content_type)
        if length is not None:self.send_header('Content-Length',str(length))
        self.send_header('Cache-Control',cache)
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        if attachment is not None:
            # Callers supply fixed generated artifact names, never a user title.
            self.send_header('Content-Disposition','attachment; filename="'+attachment+'"')
        scripts="'self' 'unsafe-inline'" if report else "'self'"
        styles="'self' 'unsafe-inline'" if report else "'self'"
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src "+scripts+
            "; style-src "+styles+"; img-src 'self' data: blob:; connect-src 'self' blob:; frame-ancestors 'none'; base-uri 'none'; object-src 'none'")
        self.send_header('Connection','close' if length is not None else 'keep-alive')
        self.end_headers()
        if length is not None:self.close_connection=True
    def _json(self,status,payload,head=False):
        data=json.dumps(payload,ensure_ascii=False,allow_nan=False,separators=(',',':')).encode('utf-8')
        self._headers(status,'application/json; charset=utf-8',len(data))
        if not head:self.wfile.write(data)
    def _file(self,path,head=False,report=False):
        try:
            with Path(path).open('rb') as stream:
                length=os.fstat(stream.fileno()).st_size
                if length>96*1024*1024:
                    return self._json(413,{'error':'Fichier trop volumineux pour cet aperçu'},head)
                kind=mimetypes.guess_type(str(path))[0] or 'application/octet-stream'
                if kind.startswith('text/') or kind in {'application/json','application/javascript'}:kind+='; charset=utf-8'
                if report and Path(path).suffix.lower() in {'.html','.htm'}:
                    data=rewrite_report_html(stream.read(),path,self.server)
                    self._headers(200,kind,len(data),report=True,cache='no-cache')
                    if not head:self.wfile.write(data)
                    return
                self._headers(200,kind,length,report=report,cache='no-cache')
                if not head:
                    while True:
                        data=stream.read(256*1024)
                        if not data:break
                        self.wfile.write(data)
        except (FileNotFoundError,PermissionError,IsADirectoryError):
            self._json(404,{'error':'Fichier indisponible'},head)
    def _events(self):
        if not self.server.stream_slots.acquire(blocking=False):
            return self._json(503,{'error':'Trop de flux ouverts'})
        try:
            self._headers(200,'text/event-stream; charset=utf-8')
            self.connection.settimeout(15)
            seen=-1
            while not self.server.hub.stopped.is_set():
                version,state=self.server.hub.current()
                if version!=seen:
                    payload=json.dumps(state,ensure_ascii=False,allow_nan=False,separators=(',',':'))
                    self.wfile.write(('id: '+str(version)+'\nevent: state\ndata: '+payload+'\n\n').encode('utf-8'))
                    self.wfile.flush();seen=version
                with self.server.hub.condition:self.server.hub.condition.wait(timeout=5)
                self.wfile.write(b': local-heartbeat\n\n');self.wfile.flush()
        except (BrokenPipeError,ConnectionResetError,ConnectionAbortedError,socket.timeout,OSError):pass
        finally:
            self.close_connection=True;self.server.stream_slots.release()
    def _handle(self,head=False):
        if not self._authorized():return self._json(403,{'error':'Accès local de même origine uniquement'},head)
        path=unquote(urlsplit(self.path).path)
        if path=='/api/health':
            return self._json(200,{'schema':'lotusim-ops-api-1','service':'lotusim-ops-dashboard','readOnly':True,
                                  'simulationReadOnly':True,'configurationEditing':self.server.settings is not None,
                                  'assetLibraryEditing':self.server.assets is not None,
                                  'trafficLibraryEditing':self.server.traffic_library is not None},head)
        if path=='/api/state':return self._json(200,self.server.hub.current()[1],head)
        if path=='/api/engines':
            if self.server.engines is None:return self._json(404,{'error':'Registre des moteurs indisponible'},head)
            try:return self._json(200,self.server.engines.catalog(),head)
            except (OSError,ValueError):return self._json(503,{'error':'Lecture du profil moteur impossible'},head)
        if path=='/api/traffic/plans':
            if self.server.traffic_library is None:return self._json(404,{'error':'Bibliothèque de plans indisponible'},head)
            try:return self._json(200,self.server.traffic_library.list(),head)
            except (OSError,ValueError):return self._json(503,{'error':'Lecture de la bibliothèque locale impossible'},head)
        if path=='/api/traffic/plan':
            if self.server.traffic is None:return self._json(404,{'error':'Lecture du plan de trafic indisponible'},head)
            try:
                query=parse_qs(urlsplit(self.path).query,keep_blank_values=True,max_num_fields=4)
                if set(query)-{'planId'} or any(len(values)!=1 for values in query.values()):
                    return self._json(400,{'error':'Un seul identifiant de plan est accepté'},head)
                identifier=query.get('planId',['source'])[0]
                if identifier=='source':result=self.server.traffic.get()
                elif re.fullmatch(r'[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}',identifier) and self.server.traffic_library is not None:
                    result=self.server.traffic_library.get(identifier)
                else:return self._json(404,{'error':'Plan local introuvable'},head)
                return self._json(200,result,head)
            except FileNotFoundError:return self._json(404,{'error':'Plan local introuvable'},head)
            except (OSError,ValueError):return self._json(503,{'error':'Plan local indisponible ; aucune simulation modifiée'},head)
        traffic_file=re.fullmatch(r'/api/traffic/plans/([a-f0-9-]{36})/(bundle\.zip|plan\.json|scope\.snapshot\.json|catalogue\.snapshot\.json|unity-template\.json|safety-report\.json|agent-messages\.json|scenario\.yaml|manifest\.json|instructions\.txt)',path)
        if traffic_file:
            if self.server.traffic_library is None:return self._json(404,{'error':'Bibliothèque de plans indisponible'},head)
            identifier,filename=traffic_file.groups()
            try:
                data=self.server.traffic_library.read_bundle(identifier) if filename=='bundle.zip' else self.server.traffic_library.read_file(identifier,filename)
                kind='application/zip' if filename=='bundle.zip' else 'application/json; charset=utf-8' if filename.endswith('.json') else 'application/octet-stream'
                self._headers(200,kind,len(data),attachment='traffic-'+identifier+'.zip' if filename=='bundle.zip' else filename)
                if not head:self.wfile.write(data)
                return
            except TrafficValidationError as error:return self._json(409,error.validation,head)
            except (OSError,ValueError):return self._json(404,{'error':'Export de plan introuvable ou non disponible'},head)
        traffic_draft=re.fullmatch(r'/api/traffic/drafts/([a-f0-9-]{36})/draft\.json',path)
        if traffic_draft:
            if self.server.traffic is None:return self._json(404,{'error':'Brouillon indisponible'},head)
            try:
                data=self.server.traffic.read_draft(traffic_draft.group(1))
                self._headers(200,'application/json; charset=utf-8',len(data),attachment='traffic-draft.json')
                if not head:self.wfile.write(data)
                return
            except (OSError,ValueError):return self._json(404,{'error':'Brouillon de trafic introuvable'},head)
        if path=='/api/assets/catalog':
            if self.server.assets is None:return self._json(404,{'error':'Bibliothèque indisponible'},head)
            try:return self._json(200,self.server.assets.catalog(),head)
            except (OSError,ValueError):return self._json(503,{'error':'Lecture du catalogue impossible'},head)
        model=re.fullmatch(r'/api/assets/files/([A-Za-z0-9_-]{1,101})/(.+)',path)
        if model:
            asset=self.server.assets.resolve(model.group(1),model.group(2)) if self.server.assets else None
            return self._file(asset,head) if asset else self._json(404,{'error':'Ressource 3D introuvable'},head)
        if path.startswith('/api/settings/'):
            return self._settings_get(path,head)
        if path=='/api/events':
            return self._json(405,{'error':'GET requis'},True) if head else self._events()
        static={'/':'index.html','/index.html':'index.html','/styles.css':'styles.css','/app.js':'app.js',
                '/settings.js':'settings.js','/settings.css':'settings.css',
                '/assets.js':'assets.js','/assets.css':'assets.css','/mesh-viewer.js':'mesh-viewer.js',
                '/traffic.js':'traffic.js','/traffic.css':'traffic.css'}
        if path in static:
            asset=safe_child(self.server.ui_root,static[path])
            return self._file(asset,head) if asset else self._json(404,{'error':'Interface absente'},head)
        if path.startswith('/vendor/three/'):
            asset=safe_child(self.server.ui_root/'vendor/three',path[len('/vendor/three/'):])
            return self._file(asset,head) if asset else self._json(404,{'error':'Dépendance locale absente'},head)
        match=re.fullmatch(r'/files/([A-Za-z0-9_-]{8,80})/(.+)',path)
        if match:
            base=self.server.hub.collector.resolve_file(match.group(1))
            if base is not None and self.server.allowed_file(base):
                base=Path(base).resolve()
                if base.suffix.lower() in {'.html','.htm'}:
                    file=safe_child(base.parent,match.group(2))
                elif match.group(2)==base.name and base.suffix.lower() in EXTENSIONS and base.is_file():file=base
                else:file=None
                if file is not None and self.server.allowed_file(file):
                    return self._file(file,head,report=file.suffix.lower() in {'.html','.htm','.js','.css'})
        self._json(404,{'error':'Ressource non autorisée ou indisponible'},head)
    def do_GET(self):
        try:self._handle()
        except (BrokenPipeError,ConnectionResetError):pass
    def do_HEAD(self):
        try:self._handle(True)
        except (BrokenPipeError,ConnectionResetError):pass
    def _settings_get(self,path,head=False):
        store=self.server.settings
        if store is None:return self._json(404,{'error':'Paramétrage indisponible'},head)
        try:
            if path=='/api/settings/catalog':return self._json(200,store.catalog(),head)
            if path=='/api/settings/campaigns':return self._json(200,{'campaigns':store.list()},head)
            match=re.fullmatch(r'/api/settings/campaigns/([a-f0-9-]{32,36})',path)
            if match:return self._json(200,store.get(match.group(1)),head)
            match=re.fullmatch(r'/api/settings/prepared/([a-f0-9-]{32,36})/(campaign\.json|manifest\.json|engine-agent\.json|scene-plan\.json|scene-contract\.json|adapter-requirements\.json|engine-instructions\.txt|scene_unity\.cs|scene_unreal\.py|LOTUSimPrepared\.uproject|unity-instructions\.txt|unreal-instructions\.txt|bundle\.zip)',path)
            if match:
                identifier,filename=match.groups()
                if filename=='bundle.zip':
                    files=store.read_bundle(identifier)
                    # Each entry is revalidated against the immutable manifest;
                    # this endpoint only packages bytes, never executes scripts.
                    if len(files)>16 or sum(map(len,files.values()))>16*1024*1024:
                        raise ValueError('Prepared bundle exceeds the download budget')
                    archive=io.BytesIO()
                    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_DEFLATED) as bundle:
                        for name,data in sorted(files.items()):
                            if not re.fullmatch(r'[A-Za-z0-9_-]+\.[A-Za-z0-9]+',name):
                                raise ValueError('Unsafe prepared bundle entry')
                            bundle.writestr(name,data)
                    data=archive.getvalue();kind='application/zip';attachment='lotusim_'+identifier+'.zip'
                else:
                    data=store.read_prepared(identifier,filename)
                    kind='application/json; charset=utf-8' if filename.endswith('.json') else 'application/octet-stream'
                    attachment=None if filename in ('campaign.json','manifest.json') else filename
                self._headers(200,kind,len(data),attachment=attachment)
                if not head:self.wfile.write(data)
                return
        except (FileNotFoundError,CampaignSecurityError,ValueError):
            return self._json(404,{'error':'Campagne locale introuvable'},head)
        except OSError:
            return self._json(503,{'error':'Stockage local momentanément indisponible'},head)
        return self._json(404,{'error':'Route de configuration introuvable'},head)
    def do_POST(self):
        path=unquote(urlsplit(self.path).path)
        if path=='/api/engines/select':return self._engine_select()
        if path=='/api/traffic/drafts':return self._traffic_draft()
        if path=='/api/traffic/generate':return self._traffic_mutation('generate')
        revalidate=re.fullmatch(r'/api/traffic/plans/([a-f0-9-]{36})/revalidate',path)
        if revalidate:return self._traffic_mutation('revalidate',revalidate.group(1))
        if path=='/api/assets/import':return self._asset_import()
        integration=re.fullmatch(r'/api/assets/(import-[a-f0-9-]{36})/integrate',path)
        if integration:return self._asset_integrate(integration.group(1))
        if path not in {'/api/settings/validate','/api/settings/save','/api/settings/prepare'} or self.server.settings is None:
            return self._json(405,{'error':'Aucune commande de simulation ; édition des configurations uniquement'})
        if not self._authorized() or self.headers.get('X-LOTUSim-Settings')!='1':
            return self._json(403,{'error':'Édition locale de même origine requise'})
        if self.headers.get('Transfer-Encoding'):
            return self._json(400,{'error':'Corps JSON de taille explicite requis'})
        if self.headers.get_content_type()!='application/json':
            return self._json(415,{'error':'Content-Type application/json requis'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self._json(400,{'error':'Taille du corps JSON invalide'})
        if length<=0:return self._json(400,{'error':'Une configuration JSON est requise'})
        if length>MAX_JSON_BYTES:return self._json(413,{'error':'Configuration supérieure à 1 Mio'})
        try:
            self.connection.settimeout(5)
            payload=load_json_bytes(self.rfile.read(length))
            method={'/api/settings/validate':'validate','/api/settings/save':'save','/api/settings/prepare':'prepare'}[path]
            result=getattr(self.server.settings,method)(payload)
            if method=='prepare':
                result['downloadUrl']='/api/settings/prepared/'+result['id']+'/campaign.json'
                result['manifestUrl']='/api/settings/prepared/'+result['id']+'/manifest.json'
                result['bundleUrl']='/api/settings/prepared/'+result['id']+'/bundle.zip'
                result['campaignFile']='artifacts/campaign-settings/prepared/'+result['id']+'/campaign.json'
                result['manifestFile']='artifacts/campaign-settings/prepared/'+result['id']+'/manifest.json'
                result['importFile']=result['manifestFile']
                if result.get('engineActions',{}).get('engine',result.get('campaign',{}).get('engine'))=='unity':
                    result['unityMenu']='LOTUSim > Dataset > Manual campaigns > Import prepared campaign'
            return self._json(200,result)
        except CampaignValidationError as error:
            return self._json(400,error.validation)
        except (CampaignSecurityError,ValueError,UnicodeError,TypeError):
            return self._json(400,{'valid':False,'errors':[{'path':'$','message':'JSON ou configuration invalide.'}],'warnings':[]})
        except (OSError,socket.timeout):
            return self._json(503,{'error':'Écriture locale impossible ou requête interrompue ; aucune simulation lancée.'})
    def _engine_select(self):
        if self.server.engines is None:return self._json(404,{'error':'Registre des moteurs indisponible'})
        if not self._authorized() or self.headers.get('X-LOTUSim-Engines')!='1':
            return self._json(403,{'error':'Modification locale de même origine requise'})
        if self.headers.get('Transfer-Encoding'):
            return self._json(400,{'error':'Taille JSON explicite requise'})
        if self.headers.get_content_type()!='application/json':
            return self._json(415,{'error':'Content-Type application/json requis'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self._json(400,{'error':'Taille JSON invalide'})
        if not 0<length<=4096:return self._json(413,{'error':'Profil moteur vide ou trop volumineux'})
        try:
            self.connection.settimeout(5)
            raw=self.rfile.read(length)
            if len(raw)!=length:return self._json(400,{'error':'Corps JSON incomplet ; profil inchangé'})
            payload=load_json_bytes(raw)
            return self._json(200,self.server.engines.select(payload))
        except (ValueError,TypeError,UnicodeError):
            return self._json(400,{'error':'Moteur ou nom invalide ; aucun code ni chemin exécutable accepté'})
        except (OSError,socket.timeout):
            return self._json(503,{'error':'Enregistrement local du profil impossible ; aucun moteur lancé'})
    def _traffic_draft(self):
        return self._traffic_mutation('draft')
    def _traffic_mutation(self,operation,identifier=None):
        if self.server.traffic is None:return self._json(404,{'error':'Éditeur de trafic indisponible'})
        if operation!='draft' and self.server.traffic_library is None:return self._json(404,{'error':'Bibliothèque de plans indisponible'})
        if not self._authorized() or self.headers.get('X-LOTUSim-Traffic')!='1':
            return self._json(403,{'error':'Édition locale de même origine requise'})
        if self.headers.get('Transfer-Encoding'):return self._json(400,{'error':'Taille JSON explicite requise'})
        if self.headers.get_content_type()!='application/json':return self._json(415,{'error':'Content-Type application/json requis'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self._json(400,{'error':'Taille JSON invalide'})
        if not 0<length<=MAX_JSON_BYTES:return self._json(413,{'error':'Brouillon vide ou supérieur à 1 Mio'})
        try:
            self.connection.settimeout(5)
            raw=self.rfile.read(length)
            if len(raw)!=length:return self._json(400,{'error':'Brouillon JSON incomplet'})
            payload=load_json_bytes(raw)
            if not isinstance(payload,dict):return self._json(400,{'error':'Un objet JSON est requis'})
            uses_library=operation!='draft' or 'planId' in payload
            if uses_library and self.server.traffic_library is None:return self._json(404,{'error':'Bibliothèque de plans indisponible'})
            slot=operation in ('generate','revalidate')
            if slot and not self.server.traffic_generation_slot.acquire(blocking=False):
                return self._json(409,{'error':'Une planification est déjà en cours ; aucun second calcul lancé'})
            try:
                if operation=='generate':
                    self.connection.settimeout(60)
                    result=self.server.traffic_library.generate(payload)
                elif operation=='revalidate':
                    if payload:return self._json(400,{'error':'La revalidation ne reçoit aucun paramètre ni nouvelle trajectoire'})
                    self.connection.settimeout(60)
                    result=self.server.traffic_library.revalidate(identifier)
                elif uses_library:result=self.server.traffic_library.save_draft(payload)
                else:result=self.server.traffic.save_draft(payload)
            finally:
                if slot:self.server.traffic_generation_slot.release()
            if uses_library:
                result['downloadUrl']='/api/traffic/plans/'+result['id']+'/plan.json'
                result['bundleUrl']='/api/traffic/plans/'+result['id']+'/bundle.zip'
            else:result['downloadUrl']='/api/traffic/drafts/'+result['id']+'/draft.json'
            return self._json(200,result)
        except FileNotFoundError:return self._json(404,{'error':'Plan local introuvable'})
        except TrafficConflictError:return self._json(409,{'error':'Le plan source a changé ; recharger avant de modifier'})
        except TrafficValidationError as error:return self._json(400,{'valid':False,**error.validation})
        except CampaignValidationError as error:return self._json(400,error.validation)
        except (ValueError,TypeError,UnicodeError):return self._json(400,{'error':'Brouillon de trafic invalide'})
        except (OSError,socket.timeout):return self._json(503,{'error':'Écriture du brouillon impossible ; aucune trajectoire appliquée'})
    def _asset_import(self):
        if self.server.assets is None:return self._json(404,{'error':'Bibliothèque indisponible'})
        if not self._authorized() or self.headers.get('X-LOTUSim-Asset-Import')!='1':
            return self._json(403,{'error':'Import local de même origine requis'})
        if self.headers.get('Transfer-Encoding'):
            return self._json(400,{'error':'Taille explicite requise'})
        if self.headers.get_content_type()!='multipart/form-data':
            return self._json(415,{'error':'Content-Type multipart/form-data requis'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self._json(400,{'error':'Taille invalide'})
        if not 0<length<=MAX_UPLOAD:return self._json(413,{'error':'Import vide ou supérieur à 64 Mio'})
        if not self.server.import_slot.acquire(blocking=False):
            return self._json(409,{'error':'Un import est déjà en cours ; réessayer ensuite'})
        try:
            self.connection.settimeout(30)
            body=self.rfile.read(length)
            if len(body)!=length:raise MeshError('Transfert incomplet ; aucun modèle ajouté.')
            asset=self.server.assets.import_multipart(self.headers.get('Content-Type',''),body)
            return self._json(201,{'asset':asset})
        except (MeshError,ValueError,UnicodeError,TypeError,KeyError,AttributeError) as error:
            # User-facing parser errors are bounded and do not reveal host paths.
            message=str(error)[:500] if isinstance(error,MeshError) else 'Fichier ou métadonnées invalides.'
            return self._json(400,{'error':message})
        except (OSError,socket.timeout):
            return self._json(503,{'error':'Import local interrompu ou impossible. Aucun scénario modifié.'})
        finally:self.server.import_slot.release()
    def _asset_integrate(self, identifier):
        if self.server.integration is None:return self._json(503,{'error':'Intégration automatique indisponible'})
        if not self._authorized() or self.headers.get('X-LOTUSim-Asset-Import')!='1':
            return self._json(403,{'error':'Intégration locale de même origine requise'})
        if self.headers.get('Transfer-Encoding') or self.headers.get_content_type()!='application/json':
            return self._json(415,{'error':'JSON de taille explicite requis'})
        try:length=int(self.headers.get('Content-Length','0'))
        except ValueError:return self._json(400,{'error':'Taille JSON invalide'})
        if not 0<length<=8192:return self._json(413,{'error':'Options vides ou supérieures à 8 Kio'})
        try:
            self.connection.settimeout(5)
            body=self.rfile.read(length)
            if len(body)!=length:raise MeshError('Requête incomplète')
            payload=load_json_bytes(body)
            if not isinstance(payload,dict) or set(payload)!={'options'}:raise MeshError('Champ options requis')
            result=self.server.integration.request(identifier,payload['options'])
            if self.server.assets:self.server.assets._updated=0
            return self._json(202,{'integration':result})
        except (ValueError,MeshError,TypeError,KeyError):
            return self._json(400,{'error':'Options ou identifiant d’import invalides.'})
        except (OSError,socket.timeout):
            return self._json(503,{'error':'Écriture des options impossible ; aucune simulation modifiée.'})
    def _no_mutation(self):self._json(405,{'error':'Méthode non autorisée'})
    do_PUT=do_DELETE=do_PATCH=_no_mutation

def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--core',type=Path,default=ROOT)
    parser.add_argument('--unity',type=Path)
    parser.add_argument('--port',type=int,default=8766)
    parser.add_argument('--interval',type=float,default=2.0)
    parser.add_argument('--no-docker',action='store_true',help='Ne pas lire l’état Docker')
    args=parser.parse_args()
    if not 1024<=args.port<=65535:parser.error('Choisir un port utilisateur entre 1024 et 65535')
    if not .5<=args.interval<=30:parser.error('La cadence doit être comprise entre 0,5 et 30 secondes')
    core=args.core.resolve(strict=True);unity=(args.unity or core.parent/'LOTUSim-Unity-modules').resolve()
    collector=Collector(core,unity,docker_enabled=not args.no_docker)
    hub=StateHub(collector,args.interval)
    settings=CampaignStore(core,unity)
    assets=MeshLibrary(core,unity)
    integration=MeshIntegrationService(core,unity)
    engines=EngineRegistry(core,unity)
    traffic=TrafficPlanStore(core,unity)
    traffic_library=TrafficPlanLibrary(core,unity)
    try:server=DashboardServer(('127.0.0.1',args.port),hub,allowed_roots=(core/'artifacts',unity/'artifacts'),settings=settings,assets=assets,integration=integration,engines=engines,traffic=traffic,traffic_library=traffic_library)
    except OSError as error:
        raise SystemExit('Port local '+str(args.port)+' indisponible ; aucun processus existant arrêté. '+str(error))
    hub.start();integration.start()
    print('[LOTUSim Ops] http://127.0.0.1:'+str(server.server_address[1])+' — supervision locale et paramétrage des campagnes ; aucune commande de simulation ni connexion ROS additionnelle.',flush=True)
    try:server.serve_forever(poll_interval=.25)
    except KeyboardInterrupt:pass
    finally:integration.close();hub.close();server.server_close()

if __name__=='__main__':main()
