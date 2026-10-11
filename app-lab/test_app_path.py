"""Actual HTTP/password login/WebSocket/Redis/native worker/ADK path; dummy-only."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
import environment
import asyncio
from dataclasses import replace
from datetime import datetime,timezone
import hashlib
import importlib.metadata
import json
import subprocess
import time
import httpx
from websockets.asyncio.client import connect
from cmdbox_gateway.fixtures import FLOW_A,FLOW_B
from storage import SyntheticSqliteBindings

ROOT=environment.ROOT
BASE='http://127.0.0.1:18090'
outcomes=[]; observations={}; processes=[]
registry=SyntheticSqliteBindings(ROOT/'data'/'bindings.sqlite',[FLOW_A,FLOW_B])
trace_file=ROOT/'runtime-trace.jsonl'
trace_start=len(trace_file.read_text(encoding='utf8').splitlines()) if trace_file.exists() else 0

def start_server(label):
    # Never replace or kill an unknown existing listener.
    import socket
    with socket.socket() as check:
        assert check.connect_ex(('127.0.0.1',18090)) != 0, 'Lab Web port already occupied; stop only its known owner first'
    log=(ROOT/('server-'+label+'.log')).open('w',encoding='utf8')
    process=subprocess.Popen([sys.executable,str(ROOT/'server.py')],cwd=ROOT,stdin=subprocess.PIPE,
                            stdout=log,stderr=log,text=True,encoding='utf8',
                            creationflags=subprocess.CREATE_NO_WINDOW if sys.platform=='win32' else 0)
    processes.append((process,log))
    deadline=time.monotonic()+40
    with httpx.Client(base_url=BASE,trust_env=False,timeout=1) as client:
        while time.monotonic()<deadline:
            if process.poll() is not None: raise RuntimeError('Local mock bootstrap failed; inspect its lab-only log')
            try:
                if client.get('/lab/status').json()['workerReady']: return process
            except (httpx.HTTPError,ValueError,KeyError): pass
            time.sleep(0.25)
    raise RuntimeError('Local mock boot timeout')

def stop_server(process):
    if process.poll() is None:
        process.stdin.write('STOP\n');process.stdin.flush()
        try: process.wait(timeout=15)
        except subprocess.TimeoutExpired:
            process.terminate();process.wait(timeout=5)
            raise RuntimeError('Graceful local mock shutdown timed out')
    assert process.returncode==0, 'Local mock exited with error'

def client(): return httpx.Client(base_url=BASE,trust_env=False,timeout=20)
def login(user):
    result=client()
    response=result.post('/dosignin/lab',data={'name':user,'password':'LITERAL_DUMMY_PASSWORD'})
    assert response.status_code in (302,303,307) and response.headers.get('signin')=='success'
    assert result.cookies.get('lab_session','').startswith('LITERAL_DUMMY_WEBSESSION_')
    return result

async def turn(http,session='same-chat',query=''):
    cookie='; '.join(k+'='+v for k,v in http.cookies.items())
    messages=[]
    async with connect('ws://127.0.0.1:18090/lab/chat/ws/adapter_lab/'+session+query,
                       additional_headers={'Cookie':cookie},open_timeout=20) as ws:
        greeting=json.loads(await asyncio.wait_for(ws.recv(),20))
        assert 'success' in greeting
        await ws.send('call_tts_off');await ws.send('IDENTITY')
        for _ in range(20):
            value=json.loads(await asyncio.wait_for(ws.recv(),30));messages.append(value)
            if value.get('end'):break
        else:raise AssertionError('Native cmdbox stream did not finish')
    return json.dumps(messages),messages

async def check(name,operation):
    try:
        await operation()
        outcomes.append({'name':name,'status':'pass'});print('PASS '+name,flush=True)
    except Exception as error:
        outcomes.append({'name':name,'status':'fail','errorType':type(error).__name__})
        raise

async def exercise():
    a=b=c=None
    try:
        # Previous interrupted tests can leave this intentionally synthetic row disabled.
        old=registry.get_record('101')
        if old and old.status!='ACTIVE':
            registry.bind(replace(old,status='ACTIVE',generation=old.generation+1))
        process=start_server('initial')
        async def bootstrap():
            with client() as public:
                assert public.get('/lab/status').json()['mode']=='LOCAL-MOCK-ONLY'
                assert public.get('/lab/api/me').status_code==401
                bad=public.post('/dosignin/lab',data={'name':'alice','password':'LITERAL_DUMMY_WRONG'})
                assert bad.headers.get('signin')!='success' and not public.cookies.get('lab_session')
                # OAuth/token/SAML routes were not mounted at all.
                assert public.get('/oauth2/google/callback').status_code==404
        await check('Public cmdbox bootstrap; unauthenticated and wrong-password requests refused',bootstrap)
        a,b,c=login('alice'),login('bob'),login('charlie')
        async def principals():
            for http,uid in ((a,'101'),(b,'202'),(c,'303')):
                identity=http.get('/lab/api/me').json()
                assert identity['uid']==uid and identity['adk_user_id']=='cmdbox_uid_'+uid
            assert c.get('/lab/api/me').json()['connection']=='RECONNECT_REQUIRED'
        await check('Native password login creates separate server-side UID sessions',principals)
        async def parallel():
            ra,rb=await asyncio.gather(turn(a),turn(b))
            assert 'A_ONLY' in ra[0] and 'B_ONLY' not in ra[0]
            assert 'B_ONLY' in rb[0] and 'A_ONLY' not in rb[0]
            observations['firstMarkers']={'101':'A_ONLY','202':'B_ONLY'}
        await check('Real WebSocket -> native Redis queue -> native worker -> actual ADK -> approved dummy tool',parallel)
        async def histories():
            await parallel()
            for http,uid,own,other in ((a,'101','A_ONLY','B_ONLY'),(b,'202','B_ONLY','A_ONLY')):
                response=http.get('/lab/api/history/same-chat');assert response.status_code==200
                history=response.json();text=json.dumps(history)
                assert history['user_id']=='cmdbox_uid_'+uid and own in text and other not in text
                listed=http.get('/lab/api/sessions').json()
                assert all(s['user_id']=='cmdbox_uid_'+uid for s in listed['sessions'])
                observations['history-'+uid]={'eventCount':len(history['events']),'otherMarkerAbsent':True}
        await check('UID history APIs and persistent ADK SQLite separate same session ID across repeated turns',histories)
        async def selectors():
            assert a.get('/lab/api/history/same-chat?uid=202').status_code==400
            assert a.get('/lab/api/me?project_id=DUMMY-PROJECT-B').status_code==400
            ra,_=await turn(a,query='?uid=202&project_id=DUMMY-PROJECT-B')
            assert 'A_ONLY' in ra and 'B_ONLY' not in ra
            await turn(a,session='a-private-chat')
            assert b.get('/lab/api/history/a-private-chat').status_code==404
        await check('Client UID/project selectors cannot change principal; B cannot read A-only history',selectors)
        async def unbound():
            ra,messages=await turn(c)
            assert 'reconnect_required' in ra and 'A_ONLY' not in ra and 'B_ONLY' not in ra
        await check('Unbound authenticated UID fails before ADK model/tool execution',unbound)
        async def durable_binding():
            rows=[registry.resolve(uid) for uid in ('101','202')]
            other=SyntheticSqliteBindings(ROOT/'data'/'bindings.sqlite',[FLOW_A,FLOW_B])
            assert [other.resolve(x.uid) for x in rows]==rows
            assert all(x.subject.startswith('DUMMY-') for x in rows)
        await check('Synthetic-only binding persists in SQLite and reloads in another registry instance',durable_binding)
        async def disconnect():
            registry.disable('101')
            ra,_=await turn(a)
            assert 'reconnect_required' in ra and 'A_ONLY' not in ra and 'B_ONLY' not in ra
            rb,_=await turn(b);assert 'B_ONLY' in rb and 'A_ONLY' not in rb
            assert a.get('/lab/api/me').json()['connection']=='RECONNECT_REQUIRED'
        await check('Durable dummy disconnect stops A through actual Web path; B continues',disconnect)
        stop_server(process);process=start_server('restart')
        async def restart():
            assert a.get('/lab/api/me').json()['connection']=='RECONNECT_REQUIRED'
            assert 'A_ONLY' in a.get('/lab/api/history/same-chat').text
            rb,_=await turn(b);assert 'B_ONLY' in rb and 'A_ONLY' not in rb
            assert 'A_ONLY' not in b.get('/lab/api/history/same-chat').text
        await check('Application restart retains UID history and disabled binding without reactivation',restart)
        async def reconnect_fixture():
            old=registry.get_record('101')
            registry.bind(replace(old,status='ACTIVE',generation=old.generation+1))
            ra,_=await turn(a);assert 'A_ONLY' in ra and 'B_ONLY' not in ra
        await check('Explicit local dummy binding update uses a newer generation; no OAuth/grant creation',reconnect_fixture)
    finally:
        for http in (a,b,c):
            if http:http.close()
        for owned,log in processes:
            if owned.poll() is None:stop_server(owned)
            log.close()

def main():
    status='fail'
    try:
        asyncio.run(exercise())
        status='pass'
    except Exception as error:
        print('APP PATH FAIL '+type(error).__name__,flush=True)
    trace=[json.loads(line) for line in trace_file.read_text(encoding='utf8').splitlines()[trace_start:]] if trace_file.exists() else []
    if status=='pass':
        try:
            stages={row['stage'] for row in trace}
            required={'public_password_login_succeeded','web_job_signed','native_redis_job_received','redis_identity_verified',
                      'adk_model_declared_tools','approved_dummy_tool_called','uid_history_api_read','local_mock_shutdown'}
            assert required<=stages
            assert all(x['tools']==['lab_identity'] for x in trace if x['stage']=='adk_model_declared_tools')
            assert all(x['blockedSocketAttempts']==0 and x['workerStopped'] for x in trace if x['stage']=='local_mock_shutdown')
            assert {x['uid'] for x in trace if x['stage']=='approved_dummy_tool_called'}=={'101','202'}
            outcomes.append({'name':'Runtime trace proves native handoffs, exact allowlist, no AP/external socket attempts and clean shutdown','status':'pass'})
        except AssertionError:
            status='fail';outcomes.append({'name':'Runtime trace validation','status':'fail'})
    stages={row['stage'] for row in trace}
    evidence=dict(at=datetime.now(timezone.utc).isoformat(),status=status,mode='PUBLIC-CMDBOX-APPLICATION-LOCAL-MOCK',
        publicCmdboxCopyUsed=True,originalSourceUnmodified=True,
        realHttpLogin='public_password_login_succeeded' in stages,realWebSocket='web_job_signed' in stages,
        realRedis='native_redis_job_received' in stages,actualGoogleAdk='adk_model_declared_tools' in stages,
        actualApContacted=False,newSecretKeyOrActualTokenCreated=False,sessionIdMode='Literal dummy IDs in native starsessions RedisStore',
        providerInference=False,externalCredentials=False,networkBoundaryTestsResumed=False,
        python=sys.version.split()[0],googleAdk=importlib.metadata.version('google-adk'),
        redisServer='7.4.8',redisPython=importlib.metadata.version('redis'),starsessions=importlib.metadata.version('starsessions'),
        outcomes=outcomes,observations=observations,trace=trace,serverProcessesStopped=all(p.poll() is not None for p,_ in processes),
        limitations=['LOCAL MOCK password/keys/cookies are public literals and unsuitable for deployment',
                     'Minimal selected native cmdbox routes; full administration UI not exercised',
                     'No AP OAuth/transport/vault, real provider data or production identity verification'])
    (ROOT.parent/'evidence').mkdir(exist_ok=True)
    dest=ROOT.parent/'evidence'/'cmdbox-app-path-results.json'
    if dest.exists():
        archived=dest.parent/'history'/('cmdbox-app-path-results-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.json')
        archived.parent.mkdir(exist_ok=True);archived.write_bytes(dest.read_bytes())
    dest.write_text(json.dumps(evidence,indent=2)+'\n',encoding='utf8')
    print('APP PATH '+status.upper()+' '+str(len(outcomes))+' scenarios',flush=True)
    return 0 if status=='pass' else 1
if __name__=='__main__':sys.exit(main())
