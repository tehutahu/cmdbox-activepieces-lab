"""Literal-only lifecycle + two real Web/worker processes + pinned native APIs."""
from pathlib import Path
import os
import sys
ROOT = Path(__file__).resolve().parent
from datetime import datetime,timezone
RUN = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
os.environ['CMDBOX_LAB_DATA_ROOT'] = str(ROOT/'data'/('continuation-'+RUN))
os.environ['CMDBOX_LAB_FAKE_LIFECYCLE'] = '1'
sys.path.insert(0,str(ROOT))
import environment
import asyncio
from contextlib import closing
from dataclasses import replace
import hashlib
import hmac
import json
import socket
import sqlite3
import subprocess
import time
import traceback
import httpx
import redis
from websockets.asyncio.client import connect
from cmdbox_gateway.core import GatewayError, WebJobIssuer, WorkerJobVerifier, RedisReplayGuard, canonical, invocation_scope, AuthorizedFlowBroker
from cmdbox_gateway.fixtures import DUMMY_KEY,FLOW_A,FLOW_B,payload,login,context,DummyMcpTransport
from cmdbox_gateway.adk_adapter import ScopedSyntheticToolset
from cmdbox.app.commons import convert
from google.adk.sessions import DatabaseSessionService
from google.adk.events import Event
from google.adk.artifacts.file_artifact_service import FileArtifactService
from google.genai import types
from storage import SyntheticSqliteBindings
from lifecycle import FakeLifecycle,FakeProvider
from migrate_synthetic_history import migrate,rollback,fingerprint

DATA = environment.DATA
DATA.mkdir(parents=True,exist_ok=False)
TRACE = ROOT/'runtime-trace.jsonl'
trace_start = len(TRACE.read_text(encoding='utf8').splitlines()) if TRACE.exists() else 0
outcomes = []; owned = []; clients = []
r = redis.Redis(host='127.0.0.1',port=18091,protocol=2)
registry = SyntheticSqliteBindings(DATA/'bindings.sqlite',[FLOW_A,FLOW_B])
life = FakeLifecycle(registry)
HEADERS = {'X-Lab-Intent':'LITERAL-DUMMY-CONNECTION'}

def expect(code, function):
    try: function()
    except GatewayError as error: assert error.code == code, error.code
    else: raise AssertionError('Expected sanitized refusal: '+code)

async def check(name,function):
    try:
        await function()
        outcomes.append({'name':name,'status':'pass'})
        print('PASS '+name,flush=True)
    except Exception:
        outcomes.append({'name':name,'status':'fail'})
        raise

def start(port):
    with socket.socket() as probe:
        assert probe.connect_ex(('127.0.0.1',port)) != 0, 'Preserve an existing listener'
    env = dict(os.environ,CMDBOX_LAB_WEB_PORT=str(port))
    log = (DATA/('server-'+str(port)+'.log')).open('w',encoding='utf8')
    process = subprocess.Popen([sys.executable,'-X','utf8',str(ROOT/'server.py')],cwd=ROOT,env=env,
        stdin=subprocess.PIPE,stdout=log,stderr=log,text=True,encoding='utf8',
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    owned.append((process,log))
    end = time.monotonic()+40
    with httpx.Client(base_url='http://127.0.0.1:'+str(port),trust_env=False,timeout=1) as http:
        while time.monotonic()<end:
            assert process.poll() is None, 'Inspect the owned synthetic server log'
            try:
                if http.get('/lab/status').json().get('workerReady'): return process
            except (httpx.HTTPError,ValueError): pass
            time.sleep(.25)
    raise AssertionError('Owned server startup timeout')

def stop(process):
    if process.poll() is None:
        process.stdin.write('STOP\n');process.stdin.flush()
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate();process.wait(timeout=5)
            raise AssertionError('Owned process graceful shutdown failed')
    assert process.returncode == 0

def http_client(port,user=None):
    http = httpx.Client(base_url='http://127.0.0.1:'+str(port),trust_env=False,timeout=35)
    clients.append(http)
    if user:
        assert http.post('/dosignin/lab',data={'name':user,'password':'LITERAL_DUMMY_PASSWORD'}).headers.get('signin')=='success'
    return http

def post(http,operation,body=None):
    return http.post('/lab/api/connection/'+operation,json=body or {},headers=HEADERS)

def connected(http):
    pending = post(http,'start').json()
    assert pending['method']=='S256' and 'verifier' not in pending
    result = post(http,'callback',{'state':pending['state'],'code':pending['fakeCode']})
    assert result.status_code==200 and result.json()['status']=='ACTIVE'
    return result.json()

async def turn(http,port,session='same-chat',runner='adapter_lab'):
    cookie = '; '.join(k+'='+v for k,v in http.cookies.items())
    messages=[]
    async with connect('ws://127.0.0.1:'+str(port)+'/lab/chat/ws/'+runner+'/'+session,
                       additional_headers={'Cookie':cookie},open_timeout=20) as ws:
        assert 'success' in json.loads(await ws.recv())
        await ws.send('call_tts_off');await ws.send('IDENTITY')
        for _ in range(20):
            message=json.loads(await asyncio.wait_for(ws.recv(),35));messages.append(message)
            if message.get('end'): break
        else: raise AssertionError('Unfinished native stream')
    return json.dumps(messages)

async def queued(job, result_id, command='agent_chat'):
    key='lab:continuation-result:'+RUN+':'+result_id
    r.rpush('sv-cmdboxlab',command+' '+key+' '+convert.str2b64str(json.dumps(job)))
    messages=[]
    for _ in range(20):
        reply=await asyncio.to_thread(r.blpop,key,35)
        assert reply is not None
        value=json.loads(reply[1]);messages.append(value)
        if value.get('end'): break
    return json.dumps(messages)

async def migration_tests():
    service=DatabaseSessionService(db_url='sqlite+aiosqlite:///'+str(DATA/'history.sqlite'))
    for name,marker in (('legacy-alice','LEGACY_A_ONLY'),('legacy-bob','LEGACY_B_ONLY')):
        session=await service.create_session(app_name='adapter_lab',user_id=name,session_id='legacy-chat',state={'user:theme':marker})
        await service.append_event(session=session,event=Event(author='user',invocation_id='LITERAL-DUMMY-MIGRATION',
            content=types.Content(role='user',parts=[types.Part(text=marker)])))
    await service.db_engine.dispose()
    with closing(sqlite3.connect(DATA/'history.sqlite')) as db: before=fingerprint(db)
    expect('ambiguous_uid_mapping',lambda:migrate(DATA/'history.sqlite',[('legacy-alice',101),('legacy-bob',101)],DATA/'ambiguous.sqlite'))
    report=migrate(DATA/'history.sqlite',[('legacy-alice',101),('legacy-bob',202)],DATA/'rollback.sqlite')
    service=DatabaseSessionService(db_url='sqlite+aiosqlite:///'+str(DATA/'history.sqlite'))
    assert await service.get_session(app_name='adapter_lab',user_id='legacy-alice',session_id='legacy-chat') is None
    for uid,marker,other in (('101','LEGACY_A_ONLY','LEGACY_B_ONLY'),('202','LEGACY_B_ONLY','LEGACY_A_ONLY')):
        saved=await service.get_session(app_name='adapter_lab',user_id='cmdbox_uid_'+uid,session_id='legacy-chat')
        text=saved.model_dump_json();assert marker in text and other not in text
    await service.db_engine.dispose()
    # Collision must preserve all existing rows and create no rollback file.
    expect('migration_collision',lambda:migrate(DATA/'history.sqlite',[('legacy-alice',101)],DATA/'collision.sqlite'))
    assert not (DATA/'collision.sqlite').exists()
    rollback(DATA/'history.sqlite',DATA/'rollback.sqlite',report['after'])
    with closing(sqlite3.connect(DATA/'history.sqlite')) as db: assert fingerprint(db)==before
    report=migrate(DATA/'history.sqlite',[('legacy-alice',101),('legacy-bob',202)],DATA/'rollback-second.sqlite')
    # Additional actual ADK writes must block stale rollback, preserving new work.
    service=DatabaseSessionService(db_url='sqlite+aiosqlite:///'+str(DATA/'history.sqlite'))
    await service.create_session(app_name='adapter_lab',user_id='cmdbox_uid_101',session_id='new-work')
    await service.db_engine.dispose()
    expect('rollback_new_work_detected',lambda:rollback(DATA/'history.sqlite',DATA/'rollback-second.sqlite',report['after']))
    for uid,marker in (('101','ARTIFACT_A_ONLY'),('202','ARTIFACT_B_ONLY')):
        artifact=FileArtifactService(DATA/'.users'/('cmdbox_uid_'+uid)/'artifacts'/'adapter_lab')
        await artifact.save_artifact(app_name='adapter_lab',user_id='cmdbox_uid_'+uid,session_id='same-chat',filename='marker.txt',artifact=types.Part(text=marker))

async def lifecycle_faults():
    isolated=SyntheticSqliteBindings(DATA/'faults.sqlite',[FLOW_A,FLOW_B])
    now=[1000]; f=FakeLifecycle(isolated,clock=lambda:now[0])
    pending=f.start('101','LITERAL_DUMMY_WEBSESSION_A')
    expect('state_session_mismatch',lambda:f.complete('202','LITERAL_DUMMY_WEBSESSION_B',pending['state'],pending['fakeCode']))
    expect('state_session_mismatch',lambda:f.complete('101','LITERAL_DUMMY_WEBSESSION_OTHER',pending['state'],pending['fakeCode']))
    now[0]=1120
    expect('state_expired',lambda:f.complete('101','LITERAL_DUMMY_WEBSESSION_A',pending['state'],pending['fakeCode']))
    expect('state_missing_or_consumed',lambda:f.complete('101','LITERAL_DUMMY_WEBSESSION_A',pending['state'],pending['fakeCode']))
    class WrongSubject(FakeProvider):
        def exchange(self,*args): return {**super().exchange(*args),'subject':'DUMMY-AP-SUBJECT-B'}
    class WrongProject(FakeProvider):
        def exchange(self,*args): return {**super().exchange(*args),'project':'DUMMY-PROJECT-B'}
    class BadPkce(FakeProvider):
        def exchange(self,code,verifier,proof,identity): return super().exchange(code,verifier,proof+'wrong',identity)
    for provider,code in ((WrongSubject(),'subject_project_grant_mismatch'),(WrongProject(),'subject_project_grant_mismatch'),(BadPkce(),'fake_pkce_or_code_invalid')):
        f.provider=provider;p=f.start('101','LITERAL_DUMMY_WEBSESSION_A')
        expect(code,lambda:f.complete('101','LITERAL_DUMMY_WEBSESSION_A',p['state'],p['fakeCode']))
        assert isolated.get_record('101') is None
    f.provider=FakeProvider();p=f.start('101','LITERAL_DUMMY_WEBSESSION_A')
    # One successful callback invalidates all parallel older-generation callbacks.
    q=f.start('101','LITERAL_DUMMY_WEBSESSION_A')
    f.complete('101','LITERAL_DUMMY_WEBSESSION_A',p['state'],p['fakeCode'])
    expect('stale_connect_state',lambda:f.complete('101','LITERAL_DUMMY_WEBSESSION_A',q['state'],q['fakeCode']))
    old=isolated.resolve('101');now[0]+=61
    f.ensure_active(old)
    assert isolated.resolve('101').generation==old.generation+1
    assert f.status('101')['refreshCount']==1
    f.revoke('101');expect('reconnect_required',lambda:isolated.resolve('101'))
    p=f.start('101','LITERAL_DUMMY_WEBSESSION_A');f.complete('101','LITERAL_DUMMY_WEBSESSION_A',p['state'],p['fakeCode'])
    class BadRefresh(FakeProvider):
        def refresh(self,*args): raise GatewayError('fake_invalid_grant')
    f.provider=BadRefresh()
    gen=isolated.resolve('101').generation
    expect('reconnect_required',lambda:f.renew('101',gen,force=True))
    assert isolated.get_record('101').generation==gen+1
    expect('reconnect_required',lambda:isolated.resolve('101'))

async def exercise():
    await check('Actual ADK legacy migration: UID partition, ambiguous mapping/collision, exact rollback and new-work refusal',migration_tests)
    await check('Fake provider faults: state TTL/consume, S256, subject/project mismatch and stale callbacks fail closed',lifecycle_faults)
    p=start(18090);q=start(18092)
    a=http_client(18090,'alice');a2=http_client(18092,'alice');b=http_client(18092,'bob');c=http_client(18090,'charlie')
    anon=http_client(18090);admin=http_client(18090,'dummy-admin')
    async def config_and_static():
        assert 'reconnect_required' in await turn(a,18090)
        ra,rb=await asyncio.gather(turn(a,18090,runner='adapter_static'),turn(c,18090,runner='adapter_static'))
        assert 'COMMON_ONLY' in ra and 'COMMON_ONLY' in rb and 'A_ONLY' not in ra
        assert anon.get('/lab/api/connection').status_code==401
        assert a.post('/lab/api/connection/start',json={}).status_code==403
        assert post(a,'start',{'uid':202}).status_code==400
        assert a.post('/lab/api/connection/start',json={},headers={**HEADERS,'Origin':'https://wrong.invalid'}).status_code==403
        for filename,change,code in (
            ('mcpsv-synthetic_gateway.json',{'mcpserver_apikey':'LITERAL-DUMMY-WRONG'},'mixed_or_unknown_tool_config'),
            ('mcpsv-static_dummy.json',{'mcpserver_apikey':''},'static_tool_key_required')):
            file=DATA/'.agent'/filename;saved=file.read_text(encoding='utf8')
            try:
                file.write_text(json.dumps({**json.loads(saved),**change}),encoding='utf8')
                assert code in await turn(a,18090,runner='adapter_static' if 'static' in filename else 'adapter_lab')
            finally: file.write_text(saved,encoding='utf8')
        forced=WebJobIssuer(DUMMY_KEY,nonce_factory=lambda:'LITERAL_DUMMY_STATIC_PAYLOAD_'+RUN).attach(login(303,'charlie'),
            {**payload(runner='adapter_static'),'mcpserver_apikey':'LITERAL-DUMMY-WRONG'})
        assert 'COMMON_ONLY' in await queued(forced,'static-payload-key-ignored')
    await check('Native worker explicit UID fail-closed and shared static API-key tools through actual ADK',config_and_static)
    async def connect_ui():
        pending=post(a,'start').json()
        assert post(b,'callback',{'state':pending['state'],'code':pending['fakeCode']}).json()['error']=='state_session_mismatch'
        result=post(a2,'callback',{'state':pending['state'],'code':pending['fakeCode']})
        assert result.status_code==200
        assert post(a,'callback',{'state':pending['state'],'code':pending['fakeCode']}).json()['error']=='state_missing_or_consumed'
        connected(b)
        for http in (a,b):
            text=http.get('/lab/api/connection').text
            assert 'LITERAL-DUMMY-AP-' not in text and 'refresh' not in text.replace('refreshCount','')
    await check('Native password sessions drive fake connect/callback across two Web processes without token disclosure',connect_ui)
    async def uid_partition():
        for _ in range(2):
            ra,rb=await asyncio.gather(turn(a,18090),turn(b,18092))
            assert 'A_ONLY' in ra and 'B_ONLY' not in ra
            assert 'B_ONLY' in rb and 'A_ONLY' not in rb
        for http,own,other in ((a,'A_ONLY','B_ONLY'),(b,'B_ONLY','A_ONLY')):
            text=http.get('/lab/api/native/history/same-chat').text
            assert own in text and other not in text
            legacy=http.get('/lab/api/native/history/legacy-chat').text
            assert 'LEGACY_'+own in legacy and 'LEGACY_'+other not in legacy
        assert a.get('/lab/api/native/sessions?uid=202').status_code==400
    await check('Two native Web/worker processes and standard session/history workers preserve same-chat UID separation',uid_partition)
    async def replay_ttl():
        issuer=WebJobIssuer(DUMMY_KEY,nonce_factory=lambda:'LITERAL_DUMMY_MULTI_REPLAY_'+RUN)
        job=issuer.attach(login(),payload(session='replay-chat'))
        first,second=await asyncio.gather(queued(job,'replay-1'),queued(job,'replay-2'))
        assert sum('A_ONLY' in x for x in (first,second))==1
        assert sum('identity_replay' in x for x in (first,second))==1
        key='cmdbox:ap-job:nonce:v1:'+hashlib.sha256(job['trusted_identity']['claims']['nonce'].encode()).hexdigest()
        ttl_ms=r.pttl(key)
        assert 0<ttl_ms<=125000, 'Nonce PTTL outside signed lifespan plus verifier clock allowance: '+str(ttl_ms)
        expire=WebJobIssuer(DUMMY_KEY,clock=lambda:time.time()-121,nonce_factory=lambda:'LITERAL_DUMMY_EXPIRED_'+RUN).attach(login(),payload())
        assert 'identity_expired_or_future' in await queued(expire,'expired')
        # Real TTL storage expires independently; an expired signed job still cannot be revived.
        guard=RedisReplayGuard(r);nonce='LITERAL_DUMMY_TTL_'+RUN;now=int(time.time())
        assert guard.claim(nonce,now+2,now) and not guard.claim(nonce,now+2,now)
        await asyncio.sleep(2.2)
        ttlkey='cmdbox:ap-job:nonce:v1:'+hashlib.sha256(nonce.encode()).hexdigest()
        assert r.get(ttlkey) is None
        assert 'identity_expired_or_future' in await queued(expire,'expired-again')
    await check('Two workers share atomic Redis replay guard, real TTL expiry, and reject expired queued native jobs',replay_ttl)
    async def refresh_cache():
        gen=life.status('101')['generation'];count=life.status('101')['refreshCount']
        results=await asyncio.gather(asyncio.to_thread(post,a,'refresh',{'generation':gen}),asyncio.to_thread(post,a2,'refresh',{'generation':gen}))
        assert all(x.status_code==200 for x in results)
        assert life.status('101')['generation']==gen+1 and life.status('101')['refreshCount']==count+1
        # Cache a real ADK tool at a generation, then rotate durable binding in another Web.
        actor=WorkerJobVerifier(DUMMY_KEY,RedisReplayGuard(r)).verify(WebJobIssuer(DUMMY_KEY,nonce_factory=lambda:'LITERAL_DUMMY_CACHE_'+RUN).attach(login(),payload()))
        broker=AuthorizedFlowBroker(registry,life,DummyMcpTransport());tools=ScopedSyntheticToolset(broker)
        with invocation_scope(actor,'same-chat'):
            saved=(await tools.get_tools(context(actor)))[0]
            newer=post(a2,'refresh',{'generation':gen+1});assert newer.status_code==200
            assert (await saved.run_async(args={},tool_context=context(actor)))['error']=='stale_or_wrong_identity_tool'
            renewed=(await tools.get_tools(context(actor)))[0]
            assert (await renewed.run_async(args={},tool_context=context(actor)))['marker']=='A_ONLY'
        other=WorkerJobVerifier(DUMMY_KEY,RedisReplayGuard(r)).verify(WebJobIssuer(DUMMY_KEY,nonce_factory=lambda:'LITERAL_DUMMY_CACHE_B_'+RUN).attach(login(202,'bob'),payload()))
        with invocation_scope(other,'same-chat'):
            assert (await renewed.run_async(args={},tool_context=context(other)))['error']=='stale_or_wrong_identity_tool'
        assert 'A_ONLY' in await turn(a,18090)
        # Expire literal vault in the ignored test DB; native preflight must rotate before ADK discovery.
        before=life.status('101')['generation']
        with closing(sqlite3.connect(DATA/'bindings.sqlite')) as db, db: db.execute('UPDATE fake_vault SET expires=0 WHERE uid=?',('101',))
        assert 'A_ONLY' in await turn(a2,18092)
        assert life.status('101')['generation']==before+1
    await check('Concurrent Web refresh single-winner, actual ADK cached-tool invalidation and worker automatic refresh',refresh_cache)
    async def revoke_cache():
        before=life.status('101')['generation']
        assert post(a,'revoke').status_code==200
        assert 'reconnect_required' in await turn(a2,18092)
        assert 'B_ONLY' in await turn(b,18092)
        assert post(a2,'refresh',{'generation':before}).json()['error']=='reconnect_required'
        assert life.status('101')['generation']==before+1
        state=connected(a2);assert state['generation']>before+1
        assert 'A_ONLY' in await turn(a,18090)
        # Serialize refresh and revoke across separate processes; final state must be disabled.
        gen=life.status('101')['generation']
        await asyncio.gather(asyncio.to_thread(post,a,'refresh',{'generation':gen}),asyncio.to_thread(post,a2,'revoke'))
        assert life.status('101')['status']=='RECONNECT_REQUIRED'
        assert 'reconnect_required' in await turn(a,18090)
        connected(a)
        # In-flight actual ADK tool must discard a result revoked by the other Web process.
        entered=asyncio.Event();release=asyncio.Event()
        class PausedTransport(DummyMcpTransport):
            async def call(self,**kwargs):
                entered.set();await release.wait()
                return await super().call(**kwargs)
        actor=WorkerJobVerifier(DUMMY_KEY,RedisReplayGuard(r)).verify(WebJobIssuer(DUMMY_KEY,nonce_factory=lambda:'LITERAL_DUMMY_REVOKE_AWAIT_'+RUN).attach(login(),payload()))
        broker=AuthorizedFlowBroker(registry,life,PausedTransport())
        with invocation_scope(actor,'same-chat'):
            tool=(await ScopedSyntheticToolset(broker).get_tools(context(actor)))[0]
            task=asyncio.create_task(tool.run_async(args={},tool_context=context(actor)))
            await asyncio.wait_for(entered.wait(),5)
            assert post(a2,'revoke').status_code==200
            release.set()
            assert (await task)['error']=='reconnect_required'
        connected(a)
    await check('Cross-process revoke blocks stale refresh and worker tools, reconnect increases generation, refresh/revoke race cannot resurrect',revoke_cache)
    async def standard_apis():
        assert anon.get('/users/list').status_code==401
        assert a.get('/users/list').status_code==403
        assert admin.get('/users/list').status_code==200
        assert a.get('/groups/list').status_code==403
        assert admin.get('/groups/list?uid=101').status_code==400
        for path in ('/users/add','/users/edit','/users/del','/users/apikey/add','/gui/apikey/add','/exec_cmd','/exec_sse_cmd','/filer','/filer_download','/filer_upload','/raw_cmd'):
            assert a.post(path,json={}).status_code in (404,405)
        assert a.get('/lab/api/artifacts/same-chat').json()['files']==['marker.txt']
        assert a.get('/lab/api/artifacts/same-chat/marker.txt').json()['text']=='ARTIFACT_A_ONLY'
        assert b.get('/lab/api/artifacts/same-chat/marker.txt').json()['text']=='ARTIFACT_B_ONLY'
        assert a.get('/lab/api/artifacts/same-chat/marker.txt?uid=202').status_code==400
        assert anon.get('/lab/api/native/sessions').status_code==401
        for command in ('agent_session_list','agent_session_del'):
            unsigned={'runner_name':'adapter_lab','user_name':'cmdbox_uid_101','session_id':'same-chat'}
            text=await queued(unsigned,'unsigned-'+command,command)
            assert 'signed_resource_job_required' in text and 'A_ONLY' not in text
        await turn(a,18090,session='private-delete')
        assert 'A_ONLY' not in b.get('/lab/api/native/history/private-delete').text
        assert b.delete('/lab/api/native/sessions/private-delete',headers=HEADERS).status_code==200
        assert 'A_ONLY' in a.get('/lab/api/native/history/private-delete').text
        assert a.delete('/lab/api/native/sessions/private-delete',headers=HEADERS).status_code==200
        assert 'A_ONLY' not in a.get('/lab/api/native/history/private-delete').text
    await check('Native admin read role guard, unmounted mutation/key/generic APIs, UID artifact read and native delete isolation',standard_apis)
    async def rename():
        issuer=WebJobIssuer(DUMMY_KEY,nonce_factory=lambda:'LITERAL_DUMMY_RENAME_'+RUN)
        job=issuer.attach(login(101,'alice-renamed'),payload(session='same-chat'))
        assert 'A_ONLY' in await queued(job,'renamed-display')
        assert 'A_ONLY' in a2.get('/lab/api/native/history/same-chat').text
    await check('Migrated legacy history and a renamed trusted display still use the stable native UID owner',rename)
    stop(p);stop(q)
    p=start(18090)
    async def restart():
        assert a.get('/lab/api/connection').json()['status']=='ACTIVE'
        assert 'A_ONLY' in await turn(a,18090)
        assert 'LEGACY_A_ONLY' in a.get('/lab/api/native/history/legacy-chat').text
    await check('Fresh application bootstrap restores fake lifecycle generations and migrated native history',restart)
    stop(p)

def main():
    status='fail'
    try:
        asyncio.run(exercise());status='pass'
    except Exception:
        traceback.print_exc()
    finally:
        for process,log in owned:
            try: stop(process)
            finally: log.close()
        for http in clients: http.close()
        r.close()
    trace=[json.loads(line) for line in TRACE.read_text(encoding='utf8').splitlines()[trace_start:]]
    if status=='pass':
        try:
            assert {x['instance'] for x in trace if x['stage']=='redis_identity_verified'}=={18090,18092}
            assert {x['instance'] for x in trace if x['stage']=='web_job_signed'}=={18090,18092}
            assert all(x['blockedSocketAttempts']==0 and x['workerStopped'] for x in trace if x['stage']=='local_mock_shutdown')
            assert any(x['stage']=='native_resource_worker_called' for x in trace)
            assert all(x['tools'] in (['lab_identity'],['shared_marker']) for x in trace if x['stage']=='adk_model_declared_tools')
            outcomes.append({'name':'Trace verifies both Web/worker processes, native resources, exact tool allowlists and zero forbidden socket attempts','status':'pass'})
        except AssertionError:
            outcomes.append({'name':'Trace verification','status':'fail'});status='fail'
    evidence={'status':status,'mode':'CONTINUATION-LOCAL-MOCK','outcomes':outcomes,
        'webProcesses':2,'workerProcesses':2,'actualRedis':True,'actualAdk':True,
        'actualApContacted':False,'actualProviderCredential':False,'newSecretOrGrant':False,
        'boundaryProbesResumed':False,'allOwnedProcessesStopped':all(p.poll() is not None for p,l in owned),
        'limits':['Fake lifecycle is not actual AP OAuth or a production vault','Selected native API workers and read admin routes; full standard UI not mounted',
                  'Offline synthetic ADK2.8 SQLite history migration only; filesystem legacy artifacts and actual user histories not migrated',
                  'Static native MCPToolset factory is substituted in-process after native config/header construction; no actual static MCP socket'],
        'trace':trace}
    (ROOT.parent/'evidence').mkdir(exist_ok=True)
    (ROOT.parent/'evidence'/('continuation-'+RUN+'.json')).write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf8')
    print('CONTINUATION '+status.upper()+' '+str(len(outcomes))+' scenarios',flush=True)
    return 0 if status=='pass' else 1
if __name__=='__main__': sys.exit(main())
