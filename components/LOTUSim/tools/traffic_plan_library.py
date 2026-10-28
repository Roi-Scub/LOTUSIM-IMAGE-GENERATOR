"""Immutable local SQLite library of cooperative plans, never active scenarios.

SQLite works on a private temporary copy under an advisory library lock; a
committed database is published atomically through a no-follow directory fd.
This is compatible with Python 3.9 and avoids SQLite reopening user-controlled
symlinks or placing journal files outside the fixed storage directory.
"""
from contextlib import contextmanager
import copy
import datetime as dt
import fcntl
import hashlib
import io
import json
import os
from pathlib import Path
import sqlite3
import stat
import tempfile
import threading
import time
import uuid
import zipfile

from traffic_plan_editor import (TrafficPlanStore, TrafficValidationError,
                                 TrafficConflictError, TrafficPlanSecurityError,
                                 _UUID, _decode, _encode)
from capture_schedule import summary as capture_summary

SCHEMA = 'lotusim-traffic-library-1'
CONTEXT_VERSION = 'lotusim-cooperative-context-1'
MAX_DATABASE = 64 * 1024 * 1024
MAX_RECORD = 4 * 1024 * 1024
MAX_REQUEST = 1024 * 1024
MAX_RECORDS = 200
FILES = frozenset(('plan.json','scope.snapshot.json','catalogue.snapshot.json',
                   'unity-template.json','safety-report.json','agent-messages.json',
                   'scenario.yaml','manifest.json','instructions.txt'))
_CREATE = '''CREATE TABLE plans (
 id TEXT PRIMARY KEY, parent_id TEXT REFERENCES plans(id), created_at TEXT NOT NULL,
 name TEXT NOT NULL, kind TEXT NOT NULL, audit_status TEXT NOT NULL,
 plan_sha TEXT NOT NULL, source_sha TEXT NOT NULL, context_sha TEXT NOT NULL,
 actor_count INTEGER NOT NULL, duration_seconds REAL NOT NULL, metadata TEXT NOT NULL,
 payload BLOB NOT NULL, payload_sha TEXT NOT NULL)'''
_THREAD_LOCKS = {}
_THREAD_LOCKS_GUARD = threading.Lock()


def _sha(raw):
    return hashlib.sha256(raw).hexdigest()


def _identifier(value):
    if not isinstance(value,str) or not _UUID.fullmatch(value):
        raise TrafficPlanSecurityError('Expected an opaque library plan UUID')
    return value


def _bounded(value, maximum=MAX_RECORD):
    try:
        data = _encode(value)
        if len(data) > maximum:
            raise ValueError('JSON byte limit exceeded')
        return data
    except (TypeError,ValueError,OverflowError,RecursionError) as error:
        raise TrafficValidationError([{'path':'$','message':'Expected bounded finite JSON'}]) from error


def _stamp(clock):
    return dt.datetime.fromtimestamp(clock(),dt.timezone.utc).isoformat().replace('+00:00','Z')


class TrafficPlanLibrary:
    def __init__(self,core_root,unity_root,*,clock=time.time,generator=None,auditor=None,scenario_writer=None):
        self.core,self.unity = Path(core_root).resolve(),Path(unity_root).resolve()
        self.clock=clock;self.editor=TrafficPlanStore(self.core,self.unity,clock=clock)
        self.generator=generator;self.auditor=auditor;self.scenario_writer=scenario_writer
        with _THREAD_LOCKS_GUARD:
            self._thread_lock=_THREAD_LOCKS.setdefault(str(self.core),threading.RLock())

    @contextmanager
    def _directory(self,create=False):
        descriptor=os.open(str(self.core),os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW)
        try:
            for component in ('artifacts','traffic-library'):
                if create:
                    try:os.mkdir(component,0o700,dir_fd=descriptor)
                    except FileExistsError:pass
                child=os.open(component,os.O_RDONLY|os.O_DIRECTORY|os.O_NOFOLLOW,dir_fd=descriptor)
                os.close(descriptor);descriptor=child
            yield descriptor
        except OSError as error:
            if error.errno in (20,40,62):
                raise TrafficPlanSecurityError('Library storage must not contain symlinks') from error
            raise
        finally:os.close(descriptor)

    @staticmethod
    def _read_at(descriptor,filename,maximum):
        fd=os.open(filename,os.O_RDONLY|os.O_NOFOLLOW|os.O_NONBLOCK,dir_fd=descriptor)
        with os.fdopen(fd,'rb') as stream:
            info=os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or info.st_size>maximum:
                raise TrafficPlanSecurityError('Expected a bounded regular library file')
            data=stream.read(maximum+1)
            if len(data)>maximum:raise TrafficPlanSecurityError('Library byte limit exceeded')
            return data

    @staticmethod
    def _publish(descriptor,data):
        if len(data)>MAX_DATABASE:raise ValueError('Traffic library reached its 64 MiB limit')
        try:
            current=os.stat('library.sqlite3',dir_fd=descriptor,follow_symlinks=False)
            if not stat.S_ISREG(current.st_mode):raise TrafficPlanSecurityError('Unsafe library database file')
        except FileNotFoundError:pass
        name='.library-'+uuid.uuid4().hex+'.tmp'
        fd=os.open(name,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600,dir_fd=descriptor)
        try:
            with os.fdopen(fd,'wb') as stream:
                stream.write(data);stream.flush();os.fsync(stream.fileno())
            os.replace(name,'library.sqlite3',src_dir_fd=descriptor,dst_dir_fd=descriptor)
            os.fsync(descriptor)
        finally:
            try:os.unlink(name,dir_fd=descriptor)
            except FileNotFoundError:pass

    @contextmanager
    def _database(self,write=False):
        try:
            with self._thread_lock:
                with self._database_transaction(write=write) as connection:
                    yield connection
        except sqlite3.Error as error:
            raise TrafficPlanSecurityError('Traffic library database is unavailable, invalid or at capacity') from error

    @contextmanager
    def _database_transaction(self,write=False):
        with self._directory(create=write) as descriptor:
            lock_flags=os.O_RDWR|os.O_NOFOLLOW
            if write:
                try:lock=os.open('library.lock',lock_flags|os.O_CREAT|os.O_EXCL,0o600,dir_fd=descriptor)
                except FileExistsError:lock=os.open('library.lock',lock_flags,dir_fd=descriptor)
            else:lock=os.open('library.lock',lock_flags,dir_fd=descriptor)
            try:
                if not stat.S_ISREG(os.fstat(lock).st_mode):raise TrafficPlanSecurityError('Unsafe library lock')
                fcntl.flock(lock,fcntl.LOCK_EX if write else fcntl.LOCK_SH)
                try:data=self._read_at(descriptor,'library.sqlite3',MAX_DATABASE)
                except FileNotFoundError:
                    if not write:raise
                    data=None
                with tempfile.TemporaryDirectory(prefix='lotusim-sqlite-') as folder:
                    path=Path(folder)/'library.sqlite3'
                    if data is not None:
                        with path.open('xb') as stream:stream.write(data)
                    connection=sqlite3.connect(str(path),timeout=5,isolation_level=None)
                    try:
                        connection.row_factory=sqlite3.Row
                        connection.execute('PRAGMA trusted_schema=OFF')
                        connection.execute('PRAGMA foreign_keys=ON')
                        connection.execute('PRAGMA max_page_count=16384')
                        connection.execute('PRAGMA journal_mode=DELETE')
                        budget=[0]
                        def progress():
                            budget[0]+=1
                            return 1 if budget[0]>100000 else 0
                        connection.set_progress_handler(progress,100)
                        if data is None:
                            connection.execute(_CREATE)
                            connection.execute('PRAGMA user_version=1')
                        else:
                            row=connection.execute("SELECT type,sql FROM sqlite_master WHERE name='plans'").fetchone()
                            if row is None or row['type']!='table' or row['sql']!=_CREATE or connection.execute('PRAGMA user_version').fetchone()[0]!=1:
                                raise TrafficPlanSecurityError('Unsupported traffic library schema')
                        if write:connection.execute('BEGIN IMMEDIATE')
                        else:connection.execute('PRAGMA query_only=ON')
                        yield connection
                        if write:
                            connection.execute('COMMIT')
                            connection.close();connection=None
                            with path.open('rb') as stream:updated=stream.read(MAX_DATABASE+1)
                            self._publish(descriptor,updated)
                    except BaseException:
                        if connection is not None and connection.in_transaction:connection.execute('ROLLBACK')
                        raise
                    finally:
                        if connection is not None:connection.close()
            finally:os.close(lock)

    @staticmethod
    def _summary(row):
        metadata=row['metadata']
        if not isinstance(metadata,str) or len(metadata.encode('utf-8'))>8192:
            raise TrafficPlanSecurityError('Invalid library metadata')
        metadata=_decode(metadata.encode('utf-8'))
        if not isinstance(metadata,dict):raise TrafficPlanSecurityError('Invalid library metadata')
        return {'id':row['id'],'parentId':row['parent_id'],'name':row['name'],'kind':row['kind'],
                'createdAt':row['created_at'],'auditStatus':row['audit_status'],
                'ready':row['audit_status']=='approved','planSha256':row['plan_sha'],
                'sourceSha256':row['source_sha'],'contextSha256':row['context_sha'],
                'sourceContextVersion':CONTEXT_VERSION,'actorCount':row['actor_count'],
                'durationSeconds':row['duration_seconds'],'applied':False,
                'requiresRevalidation':row['audit_status']!='approved','metadata':metadata,
                'status':'ready' if row['audit_status']=='approved' else 'needs_revalidation' if row['audit_status']=='requires_revalidation' else 'refused',
                'readyScope':'bounded_kinematic_audit_only','isSafetyCertified':False,
                **{key:metadata[key] for key in ('plannedCaptureImages','captureMode','captureIntervalSeconds',
                    'captureDurationSeconds','captureLastSeconds','captureClock','captureScheduleSha256') if key in metadata}}

    def list(self):
        try:
            with self._database() as connection:
                rows=connection.execute('SELECT id FROM plans ORDER BY created_at DESC,rowid DESC LIMIT ?', (MAX_RECORDS,)).fetchall()
                return {'schema':SCHEMA,'plans':[self._fetch(connection,row['id'])[0] for row in rows],'applied':False}
        except FileNotFoundError:return {'schema':SCHEMA,'plans':[],'applied':False}

    @staticmethod
    def _fetch(connection,identifier):
        row=connection.execute('SELECT * FROM plans WHERE id=? LIMIT 1',(_identifier(identifier),)).fetchone()
        if row is None:raise FileNotFoundError('Unknown library plan')
        if not isinstance(row['payload'],(bytes,bytearray,memoryview)):
            raise TrafficPlanSecurityError('Invalid library record storage type')
        raw=bytes(row['payload'])
        if len(raw)>MAX_RECORD or _sha(raw)!=row['payload_sha']:
            raise TrafficPlanSecurityError('Library record integrity check failed')
        payload=_decode(raw)
        if (not isinstance(payload,dict) or _sha(_encode(payload.get('plan')))!=row['plan_sha']
                or _sha(_encode(payload.get('context')))!=row['context_sha']):
            raise TrafficPlanSecurityError('Library plan/context integrity check failed')
        record=TrafficPlanLibrary._summary(row)
        bound_keys=('id','parentId','name','kind','createdAt','auditStatus','planSha256','sourceSha256',
                    'contextSha256','actorCount','durationSeconds','metadata')
        if payload.get('recordMetadata')!={key:record[key] for key in bound_keys}:
            raise TrafficPlanSecurityError('Library metadata integrity check failed')
        if (record['ready']!=(payload.get('audit',{}).get('approved') is True)
                or payload['context'].get('version')!=CONTEXT_VERSION):
            raise TrafficPlanSecurityError('Library audit/version integrity check failed')
        TrafficPlanStore._check_plan(payload['plan'])
        return record,payload

    def _load(self,identifier):
        with self._database() as connection:return self._fetch(connection,identifier)

    @staticmethod
    def _source(record):
        return {'id':record['id'],'kind':'library_record','engineId':None,
                'label':record['name']+' · bibliothèque locale','relativePath':None,
                'sha256':record['planSha256'],'updatedAt':record['createdAt'],
                'runtimeExecutionConfirmed':False,'contextSha256':record['contextSha256']}

    def _preview(self,record,payload):
        context=payload['context'];changes={item['actorId']:item for item in payload.get('changes',[])}
        result=self.editor._normalize((self._source(record),payload['plan'],context['scope'],context['catalogue'],context['template']),changes=changes)
        result.update(planId=record['id'],record=record,audit=payload['audit'],
                      requiresRevalidation=not record['ready'],collisionChecked=record['ready'],
                      exportFiles=sorted(self._files(record,payload)))
        if isinstance(payload['plan'].get('captureSchedule'),dict):
            result['captureSchedule']=copy.deepcopy(payload['plan']['captureSchedule'])
        limitations=payload['audit'].get('limitations',[])
        if isinstance(limitations,list):
            result['warnings']=list(dict.fromkeys(result['warnings']+[item[:1000] for item in limitations[:16] if isinstance(item,str)]))
        return result

    def get(self,identifier):
        record,payload=self._load(identifier)
        return self._preview(record,payload)

    def _prepare_record(self,name,kind,plan,scope,catalogue,template,audit,*,parent=None,source_sha=None,
                        messages=None,scenario=None,changes=None,request=None,status=None,metadata=None):
        TrafficPlanStore._check_plan(plan)
        if not isinstance(name,str) or not 1<=len(name.strip())<=120 or any(ord(c)<32 for c in name):
            raise TrafficValidationError([{'path':'$.name','message':'Use 1–120 printable characters'}])
        for value in (scope,catalogue,template,audit):
            if not isinstance(value,dict):raise ValueError('Incomplete cooperative plan context')
        plan=copy.deepcopy(plan)
        context={'version':CONTEXT_VERSION,'scope':scope,'catalogue':catalogue,'template':template}
        plan_sha,context_sha=_sha(_bounded(plan)),_sha(_bounded(context))
        approved=(audit.get('approved') is True and status not in ('failed','unsupported','requires_revalidation')
                  and audit.get('status') not in ('failed','unsupported','requires_revalidation'))
        audit_status='approved' if approved else status or ('unsupported' if audit.get('status')=='unsupported' else 'failed')
        bound_audit=dict(audit,approved=approved,continuousSafetyApproved=approved,
                         planSha256=plan_sha,contextSha256=context_sha,notCertified=True,fullColregCompliance=False)
        if scenario is not None and (not isinstance(scenario,str) or len(scenario.encode('utf-8'))>MAX_REQUEST):
            raise ValueError('Scenario YAML exceeds the export byte limit')
        payload={'schema':SCHEMA,'plan':plan,'context':context,'audit':bound_audit,
                 'messages':messages if isinstance(messages,dict) else {},'scenarioYaml':scenario if approved else None,
                 'changes':changes or [],'request':request or {},'applied':False}
        events=plan['events'];duration=max(e['endSeconds'] for e in events)-min(e['startSeconds'] for e in events)
        metadata=copy.deepcopy(metadata) if isinstance(metadata,dict) else {}
        metadata.update(capture_summary(plan.get('captureSchedule')))
        if request:
            campaign=request.get('campaign') if isinstance(request.get('campaign'),dict) else {}
            block=next((item for item in campaign.get('blocks',[]) if isinstance(item,dict) and item.get('id')==request.get('blockId')),None)
            if block is None and isinstance(campaign.get('blocks'),list) and len(campaign['blocks'])==1:block=campaign['blocks'][0]
            metadata.update({key:value for key,value in {
                'blockId':block.get('id') if isinstance(block,dict) else request.get('blockId'),
                'campaignName':campaign.get('name'),'engineId':campaign.get('engine'),
                'requestedImages':block.get('images') if isinstance(block,dict) else campaign.get('totalImages'),
                'actionProfile':request.get('actionProfile'),'seed':request.get('seed')}.items() if value is not None})
        _bounded(metadata,8192)
        record={'id':str(uuid.uuid4()),'parentId':parent,'createdAt':_stamp(self.clock),'name':name.strip(),
                'kind':kind,'auditStatus':audit_status,'planSha256':plan_sha,'sourceSha256':source_sha or plan_sha,
                'contextSha256':context_sha,'actorCount':len(events),'durationSeconds':duration,'metadata':metadata}
        payload['recordMetadata']=copy.deepcopy(record)
        raw=_bounded(payload);record['payloadSha256']=_sha(raw)
        return record,payload,raw

    @staticmethod
    def _insert(connection,prepared):
        record,payload,raw=prepared
        if connection.execute('SELECT COUNT(*) FROM plans').fetchone()[0]>=MAX_RECORDS:
            raise ValueError('Traffic library reached its 200 record limit')
        connection.execute('INSERT INTO plans VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                           (record['id'],record['parentId'],record['createdAt'],record['name'],record['kind'],
                            record['auditStatus'],record['planSha256'],record['sourceSha256'],record['contextSha256'],
                            record['actorCount'],record['durationSeconds'],_encode(record['metadata']).decode('utf-8'),sqlite3.Binary(raw),record['payloadSha256']))
        return TrafficPlanLibrary._fetch(connection,record['id'])

    def _response(self,record,payload):
        return {'id':record['id'],'planId':record['id'],'record':record,'preview':self._preview(record,payload),
                'files':sorted(self._files(record,payload)),'applied':False}

    def generate(self,payload):
        _bounded(payload,MAX_REQUEST)
        if not isinstance(payload,dict):raise TrafficValidationError([{'path':'$','message':'Une demande de scénario structurée est requise'}])
        if self.generator is None:
            from cooperative_scenario import generate
            generator=generate
        else:generator=self.generator
        try:generated=generator(self.core,self.unity,payload)
        except TrafficValidationError:raise
        except (ValueError,RuntimeError,ArithmeticError,TypeError) as error:
            # Planner errors are scenario constraints, not filesystem paths or
            # stack traces. Keep a bounded useful reason for the local editor.
            reason=' '.join(str(error).split())[:220]
            for root in (self.core,self.unity):reason=reason.replace(str(root),'[projet]')
            raise TrafficValidationError([{'path':'$.scenario','message':'Scénario refusé : '+reason}]) from error
        if not isinstance(generated,dict):raise ValueError('Invalid cooperative generator result')
        prepared=self._prepare_record(payload.get('name'),'generated',generated['plan'],generated['scope'],
                                      generated['catalogue'],generated['template'],generated['audit'],
                                      messages=generated.get('messages'),scenario=generated.get('scenarioYaml'),request=payload,
                                      metadata={key:value for key,value in {'effectiveSeed':generated['plan'].get('seed'),
                                                'generationAttempts':generated.get('generationAttempts')}.items() if value is not None})
        with self._database(write=True) as connection:record,stored=self._insert(connection,prepared)
        return self._response(record,stored)

    def save_draft(self,payload):
        _bounded(payload,MAX_REQUEST)
        if not isinstance(payload,dict) or set(payload)!={'planId','baseSha256','name','changes'}:
            raise TrafficValidationError([{'path':'$','message':'Expected planId, baseSha256, name, changes'}])
        identifier=payload['planId'];legacy=identifier=='source'
        snapshot=None
        if legacy:
            loaded=self.editor._load()
            if loaded is None:raise TrafficConflictError('The legacy source plan is unavailable')
            source,plan,scope,catalogue,template=loaded
            parent_record=None;parent_payload={'changes':[]}
            snapshot=self._prepare_record(scope.get('name','MaritimeTrafficAgents source'),'legacy_snapshot',plan,scope,catalogue,template,
                                          {'approved':False,'status':'requires_revalidation','reason':'Legacy source has not been independently revalidated'},
                                          source_sha=source['sha256'],status='requires_revalidation')
        else:
            parent_record,parent_payload=self._load(_identifier(identifier))
            context=parent_payload['context'];source=self._source(parent_record);plan=parent_payload['plan']
            scope,catalogue,template=context['scope'],context['catalogue'],context['template']
            loaded=(source,plan,scope,catalogue,template)
        edit_payload={key:payload[key] for key in ('baseSha256','name','changes')}
        built=self.editor.build_draft(edit_payload,loaded)
        draft=built['draft'];effective={item['actorId']:item for item in parent_payload.get('changes',[])}
        effective.update({item['actorId']:item for item in draft['changes']})
        revised=draft['kinematicPlan'];revised['containsUncompiledControlPoints']=any('controlPoints' in item for item in effective.values())
        prepared=self._prepare_record(payload['name'],'manual_revision',revised,scope,catalogue,template,
                                      {'approved':False,'status':'requires_revalidation','reason':'Manual changes need an independent cooperative audit',
                                       'limitations':draft['warnings']},parent=parent_record['id'] if parent_record else None,
                                      source_sha=source['sha256'],changes=list(effective.values()),status='requires_revalidation',
                                      metadata=parent_record.get('metadata',{}) if parent_record else {'sourceEngineId':'unity'})
        with self._database(write=True) as connection:
            if legacy:
                refreshed=self.editor._load()
                if refreshed is None or refreshed[0]['sha256']!=payload['baseSha256']:
                    raise TrafficConflictError('The legacy source plan changed')
                existing=connection.execute("SELECT id FROM plans WHERE kind='legacy_snapshot' AND source_sha=? AND context_sha=? LIMIT 1",
                                             (snapshot[0]['sourceSha256'],snapshot[0]['contextSha256'])).fetchone()
                parent_id=existing['id'] if existing else self._insert(connection,snapshot)[0]['id']
                prepared[0]['parentId']=parent_id
                prepared[1]['recordMetadata']['parentId']=parent_id
                raw=_bounded(prepared[1]);prepared[0]['payloadSha256']=_sha(raw)
                prepared=(prepared[0],prepared[1],raw)
            else:
                current,_=self._fetch(connection,identifier)
                if current['planSha256']!=payload['baseSha256']:raise TrafficConflictError('The selected revision changed')
            record,stored=self._insert(connection,prepared)
        return self._response(record,stored)

    def revalidate(self,identifier):
        parent,payload=self._load(_identifier(identifier));context=payload['context'];plan=payload['plan']
        if plan.get('containsUncompiledControlPoints') or any('controlPoints' in item for item in payload.get('changes',[])):
            audit={'approved':False,'status':'unsupported','reason':'Waypoint revisions need a compatible native trajectory audit; not treated as straight original events'}
        else:
            if self.auditor is None:
                from cooperative_scenario import revalidate_plan
                auditor=revalidate_plan
            else:auditor=self.auditor
            try:audit=auditor(copy.deepcopy(plan),copy.deepcopy(context['scope']),copy.deepcopy(context['catalogue']),copy.deepcopy(context['template']))
            except (ValueError,RuntimeError) as error:
                audit={'approved':False,'status':'failed','reason':'Independent cooperative audit rejected this revision','errorType':type(error).__name__}
        scenario=None
        if isinstance(audit,dict) and audit.get('approved') is True:
            if self.scenario_writer is None:
                from cooperative_scenario import render_scenario_yaml
                writer=render_scenario_yaml
            else:writer=self.scenario_writer
            try:scenario=writer(copy.deepcopy(plan),copy.deepcopy(context['scope']),copy.deepcopy(context['template']))
            except (ValueError,RuntimeError) as error:
                audit=dict(audit,approved=False,status='failed',reason='Scenario export failed independent safety validation',errorType=type(error).__name__)
        prepared=self._prepare_record(parent['name'],'revalidation',plan,context['scope'],context['catalogue'],context['template'],audit,
                                      parent=parent['id'],source_sha=parent['planSha256'],messages=payload.get('messages'),
                                      scenario=scenario,changes=payload.get('changes'),metadata=parent.get('metadata',{}))
        with self._database(write=True) as connection:record,stored=self._insert(connection,prepared)
        return self._response(record,stored)

    @staticmethod
    def _files(record,payload):
        context=payload['context']
        result={'plan.json':_encode(payload['plan']),'scope.snapshot.json':_encode(context['scope']),
                'catalogue.snapshot.json':_encode(context['catalogue']),'unity-template.json':_encode(context['template']),
                'safety-report.json':_encode(payload['audit']),'agent-messages.json':_encode(payload.get('messages',{}))}
        if record['ready'] and payload.get('scenarioYaml'):
            result['scenario.yaml']=payload['scenarioYaml'].encode('utf-8')
        result['instructions.txt']=('Plan local immuable, jamais appliqué automatiquement.\n'
                                    'Audit : '+record['auditStatus']+'.\n'
                                    'La validation porte sur un modèle cinématique borné, sans certification COLREG complète.\n'
                                    'Sans scénario YAML approuvé, conserver cet export comme données de travail uniquement.\n').encode('utf-8')
        manifest={'schema':'lotusim-traffic-library-bundle-1','record':record,'applied':False,
                  'requiresRevalidation':not record['ready'],'sourceContextVersion':CONTEXT_VERSION,
                  'changes':payload.get('changes',[]),
                  'files':{name:{'sha256':_sha(data),'bytes':len(data)} for name,data in sorted(result.items())}}
        manifest['artifacts']=[dict(name=name,**item) for name,item in manifest['files'].items()]
        result['manifest.json']=_encode(manifest)
        return result

    def read_file(self,identifier,filename):
        _identifier(identifier)
        if filename not in FILES:raise TrafficPlanSecurityError('Unknown library export filename')
        record,payload=self._load(identifier);files=self._files(record,payload)
        if filename not in files:raise TrafficPlanSecurityError('Executable scenario export requires an approved independent audit')
        return files[filename]

    def read_bundle(self,identifier):
        record,payload=self._load(_identifier(identifier));files=self._files(record,payload)
        if sum(len(data) for data in files.values())>8*1024*1024:raise ValueError('Export bundle exceeds 8 MiB')
        output=io.BytesIO()
        with zipfile.ZipFile(output,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            for name,data in sorted(files.items()):
                info=zipfile.ZipInfo(name,date_time=(1980,1,1,0,0,0));info.compress_type=zipfile.ZIP_DEFLATED
                info.external_attr=0o600<<16;archive.writestr(info,data)
        return output.getvalue()
