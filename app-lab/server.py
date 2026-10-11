"""Minimal public-cmdbox application bootstrap, strictly LOCAL MOCK only."""
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
import environment
import asyncio
from contextlib import asynccontextmanager
from dataclasses import asdict
from datetime import datetime, timezone
import json
import logging
import os
import threading
import traceback

# Import order matches cmdbox's normal application entry point.
from cmdbox.app import common, options
from cmdbox import version
from cmdbox.app.auth.signin import Signin
from cmdbox.app.commons.redis_client import RedisClient
from cmdbox.app.web import Web
from cmdbox.app.features.web.cmdbox_web_do_signin import DoSignin
from cmdbox.app.features.web.cmdbox_web_agent import Agent as WebAgent
from cmdbox.app.features.cli.cmdbox_agent_chat import AgentChat
from cmdbox_gateway import integration
from cmdbox_gateway.core import Binding, AuthorizedFlowBroker, WebJobIssuer, WorkerJobVerifier, RedisReplayGuard, GatewayError, canonical_uid
from cmdbox_gateway.fixtures import DUMMY_KEY, FLOW_A, FLOW_B, DummyCredentials, DummyMcpTransport
from storage import SyntheticSqliteBindings
from lifecycle import FakeLifecycle
from static_mock import StaticMockToolset
from cmdbox_gateway.config import validate_tool_config
from cmdbox.app.features.cli.cmdbox_agent_session_list import AgentSessionList
from cmdbox.app.features.cli.cmdbox_agent_session_del import AgentSessionDel
from cmdbox.app.features.web.cmdbox_web_users import Users
from cmdbox.app.commons import convert
from fastapi import FastAPI, Request, Response, HTTPException
from fastapi.responses import HTMLResponse
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types
import redis
from redis.asyncio import Redis
from starsessions import SessionMiddleware, SessionAutoloadMiddleware
from starsessions.stores.redis import RedisStore
import starsessions.session
import starsessions.middleware
import uvicorn

ROOT = environment.ROOT
DATA = environment.DATA
PORT = int(os.environ.get('CMDBOX_LAB_WEB_PORT','18090'))
if PORT not in (18090,18092): raise RuntimeError('Unconfigured lab listener')
FAKE_LIFECYCLE = os.environ.get('CMDBOX_LAB_FAKE_LIFECYCLE','0') == '1'
TRACE = ROOT / 'runtime-trace.jsonl'
RUNNER = 'adapter_lab'
REDIS_PORT = 18091
SVNAME = 'cmdboxlab'
logger = logging.getLogger('cmdbox.localmock')
logger.setLevel(logging.WARNING)
logger.addHandler(logging.StreamHandler())
trace_lock = threading.Lock()
def trace(stage, **metadata):
    with trace_lock:
        with TRACE.open('a', encoding='utf8') as file:
            file.write(json.dumps({'at': datetime.now(timezone.utc).isoformat(), 'stage': stage, 'instance':PORT, **metadata}) + '\n')

class LabApp:
    @classmethod
    def getInstance(cls, **kwargs): return cls()
    def main(self, **kwargs): raise RuntimeError('Unconfigured command is unavailable in LOCAL MOCK')

class FixedDummySessionHandler(starsessions.session.SessionHandler):
    async def save(self, remaining_time):
        if not self.session_id:
            uid = self.connection.session.get('signin', {}).get('uid')
            if uid not in (101,202,303,404):
                raise RuntimeError('Dummy session must originate from public password login')
            self.session_id = {101:'LITERAL_DUMMY_WEBSESSION_A',202:'LITERAL_DUMMY_WEBSESSION_B',303:'LITERAL_DUMMY_WEBSESSION_C',404:'LITERAL_DUMMY_WEBSESSION_D'}[uid]
        return await super().save(remaining_time)
# Test-only ID injection: native starsessions RedisStore/autoload/save remain in use.
# No cryptographic session token is generated. Never deploy this injection.
starsessions.middleware.SessionHandler = FixedDummySessionHandler

class TracedIssuer(WebJobIssuer):
    def attach(self, server_session, payload):
        result = super().attach(server_session, payload)
        trace('web_job_signed', uid=result['trusted_identity']['claims']['uid'], session_id=result['session_id'])
        return result
class TracedVerifier(WorkerJobVerifier):
    def verify(self, payload):
        actor = super().verify(payload)
        trace('redis_identity_verified', uid=actor.uid, adk_user_id=actor.adk_user_id, session_id=actor.requested_session_id)
        return actor
class TracedDummyTransport(DummyMcpTransport):
    async def call(self, **kwargs):
        result = await super().call(**kwargs)
        key = kwargs['cache_key']
        trace('approved_dummy_tool_called', uid=key[0], session_id=key[2], project=key[4], generation=key[6], marker=result['marker'])
        return result
class LocalScriptedLlm(BaseLlm):
    async def generate_content_async(self, llm_request, stream=False):
        responses = [p.function_response for p in llm_request.contents[-1].parts or [] if p.function_response]
        if responses:
            value = responses[-1].response
            content = types.Content(role='model', parts=[types.Part(text=json.dumps({'message': value.get('marker', value.get('error', 'unknown'))}))])
        else:
            names = list(llm_request.tools_dict)
            if names not in (['lab_identity'],['shared_marker']): raise RuntimeError('LOCAL MOCK model received an unapproved tool set')
            trace('adk_model_declared_tools', tools=names)
            content = types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(name=names[0], args={}))])
        yield LlmResponse(content=content, usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=0, candidates_token_count=0, total_token_count=0))

class LabAgentChat(AgentChat):
    mcp_toolset_factory = StaticMockToolset
    # Native apprun_generate/send_cmd_sse/svrun/session/run/serialization paths are inherited.
    def create_agent(self, *, logger, data_dir, disable_remote_agent, agent_conf, llm_conf, mcpsv_confs, payload):
        tools = self.create_tool_mcpsv(logger, mcpsv_confs, payload)
        return LlmAgent(name='lab_agent', model=LocalScriptedLlm(model='local-scripted-model'), tools=tools)
    def create_session_service(self, *, logger, data_dir, ds_conf):
        return super().create_session_service(logger=logger, data_dir=data_dir,
            ds_conf={'dbtype':'sqlite','db_fullpath':str(DATA / 'history.sqlite')})
    async def create_runner_plugin(self, **kwargs): return []
    def _setup_tts_engine(self, *args): return False, None
    async def error_chat_run(self, *, redis_cli, reskey, exc, **kwargs):
        code = exc.code if isinstance(exc, GatewayError) else 'local_mock_error'
        trace('worker_refused', error=code, errorType=type(exc).__name__,
              frames=[{'file':Path(f.filename).name,'line':f.lineno,'function':f.name}
                      for f in traceback.extract_tb(exc.__traceback__)])
        redis_cli.rpush(reskey, {'warn':{'error':code}, 'end':True})
        return self.RESP_WARN
class LabWebAgent(WebAgent):
    def get_startmsg(self, *args): return ''  # Avoid translation/TTS provider calls.
class TracedDoSignin(DoSignin):
    def set_session(self, req, user_session):
        trace('public_password_login_succeeded', uid=user_session['uid'])

def prepare_synthetic_data():
    DATA.mkdir(parents=True,exist_ok=True)
    (DATA / '.users').mkdir(exist_ok=True)
    (DATA / '.agent').mkdir(exist_ok=True)
    configs = {
        'runner-adapter_lab.json': {'runner_name':RUNNER,'agent':'lab_agent'},
        'agent-lab_agent.json': {'agent_name':'lab_agent','agent_type':'local','mcpservers':['synthetic_gateway']},
        'mcpsv-synthetic_gateway.json': {'mcpserver_auth_mode':'user_ap_binding','mcpserver_mcp_tools':['lab_identity']},
        'runner-adapter_static.json': {'runner_name':'adapter_static','agent':'static_agent'},
        'agent-static_agent.json': {'agent_name':'static_agent','agent_type':'local','mcpservers':['static_dummy']},
        'mcpsv-static_dummy.json': {'mcpserver_auth_mode':'static_api_key','mcpserver_mcp_tools':['shared_marker'],
                                  'mcpserver_url':'https://static-tool.invalid/mcp','mcpserver_apikey':'LITERAL-DUMMY-COMMON'},
    }
    for name, value in configs.items():
        (DATA / '.agent' / name).write_text(json.dumps(value, indent=2) + '\n', encoding='utf8')
    signin = {
        'users':[{'uid':uid,'name':name,'password':'LITERAL_DUMMY_PASSWORD','hash':'plain',
                  'groups':['lab-admin' if uid==404 else 'lab'],'home':'homes/' + name,'email':name+'@invalid','apikeys':{}}
                 for uid,name in ((101,'alice'),(202,'bob'),(303,'charlie'),(404,'dummy-admin'))],
        'groups':[{'gid':1,'name':'lab','parent':None,'home':'groups/lab','startpage':'lab'},
                  {'gid':2,'name':'lab-admin','parent':None,'home':'groups/admin','startpage':'lab'}],
        'pathrule':{'policy':'allow','rules':[]},
        'cmdrule':{'policy':'deny','rules':[]},
        'apikey':{'verify_jwt':{'enabled':False},'gen_cert':{'enabled':False},'gen_jwt':{'enabled':False}},
        'signin':{'signin_module':'cmdbox.app.auth.signin'},
        'oauth2':{'providers':{x:{'enabled':False,'client_id':'','client_secret':'','tenant_id':'',
                                 'redirect_uri':'','scope':[],'signin_module':None} for x in ('google','github','azure')}},
        'saml':{'providers':{'azure':{'enabled':False,'signin_module':None,'sp':{},'idp':{}}}},
    }
    return signin

raw_redis = redis.Redis(host='127.0.0.1',port=REDIS_PORT,db=0,protocol=2)
registry = SyntheticSqliteBindings(DATA / 'bindings.sqlite', [FLOW_A,FLOW_B])
for uid, label, flow in (('101','A',FLOW_A),('202','B',FLOW_B)):
    if not FAKE_LIFECYCLE and registry.get_record(uid) is None:
        registry.bind(Binding(uid,'DUMMY-AP-SUBJECT-'+label,'DUMMY-PROJECT-'+label,'DUMMY-GRANT-'+label,'dummy-ref-'+label.lower(),1,flow))
lifecycle = FakeLifecycle(registry)
broker = AuthorizedFlowBroker(registry, lifecycle if FAKE_LIFECYCLE else DummyCredentials(), TracedDummyTransport())
stop_worker = threading.Event(); worker_started = threading.Event()

def worker_thread():
    async def run():
        redis_client = RedisClient(logger,host='127.0.0.1',port=REDIS_PORT,password=None,svname=SVNAME)
        heartbeat = 'hb-cmdboxlab-worker-'+str(PORT)
        redis_client.redis_cli.hset(heartbeat, mapping={'status':'LOCAL_MOCK'})
        worker = LabAgentChat(LabApp,version,language='en_US')
        worker_started.set()
        trace('public_cmdbox_worker_started', queue='sv-cmdboxlab')
        try:
            while not stop_worker.is_set():
                result = redis_client.redis_cli.blpop('sv-cmdboxlab',timeout=1)
                if not result: continue
                msg = result[1].decode('utf8').split(' ',2)
                trace('native_redis_job_received', command=msg[0])
                if msg[0] == 'agent_chat':
                    await worker.svrun(DATA,logger,redis_client,msg,{})
                elif msg[0] in ('agent_session_list','agent_session_del'):
                    cls = AgentSessionList if msg[0]=='agent_session_list' else AgentSessionDel
                    class LocalResource(cls):
                        def create_session_service(self, **kwargs):
                            return worker.create_session_service(**kwargs)
                    await LocalResource(LabApp,version).svrun(DATA,logger,redis_client,msg,{})
                    trace('native_resource_worker_called',operation=msg[0])
                elif msg[0] == 'limiter_plan_list':
                    redis_client.rpush(msg[1],{'success':{'data':[]},'end':True})
                else:
                    redis_client.rpush(msg[1],{'warn':{'error':'unsupported_local_mock_command'},'end':True})
        finally:
            redis_client.redis_cli.delete(heartbeat)
            redis_client.close()
    asyncio.run(run())

@asynccontextmanager
async def lifespan(app):
    raw_redis.ping()
    # Separate nonce namespace and existing Redis connection; literal dummy signing key only.
    issuer = TracedIssuer(DUMMY_KEY, nonce_factory=lambda:'LITERAL_DUMMY_APP_NONCE_'+str(raw_redis.incr('lab:identity-nonce')))
    guard = RedisReplayGuard(raw_redis)
    verifier = TracedVerifier(DUMMY_KEY,guard)
    configs = [json.loads(p.read_text(encoding='utf8')) for p in (DATA/'.agent').glob('mcpsv-*.json')]
    integration.bootstrap(configs,issuer=issuer,verifier=verifier,broker=broker,shared_replay_guard=guard)
    thread = threading.Thread(target=worker_thread,daemon=True); thread.start()
    if not await asyncio.to_thread(worker_started.wait,10): raise RuntimeError('Mock worker failed to start')
    blocked = environment.install_socket_policy()
    trace('local_mock_bootstrap_ready', newSecretGenerated=False, actualApConnected=False)
    try:
        yield
    finally:
        stop_worker.set(); await asyncio.to_thread(thread.join,5)
        await async_redis.aclose(); raw_redis.close()
        trace('local_mock_shutdown', blockedSocketAttempts=len(blocked), workerStopped=not thread.is_alive())

app = FastAPI(title='Public cmdbox LOCAL MOCK', lifespan=lifespan)
signin_data = prepare_synthetic_data()
(DATA / 'dummy-signin.json').write_text(json.dumps(signin_data,indent=2) + '\n',encoding='utf8')
web = Web.getInstance(logger,DATA,appcls=LabApp,ver=version,language='en_US',redis_host='127.0.0.1',redis_port=REDIS_PORT,redis_password=None,svname=SVNAME,signin_file=DATA/'dummy-signin.json')
web.agent_chat_factory = LabAgentChat
web.options._options['cmd']['agent'] = {'chat': LabAgentChat(LabApp,version).get_option()}
TracedDoSignin(LabApp,version,language='en_US').route(web,app)
# Retain only the original password-login handlers; no OAuth/token/SAML routes.
app.router.routes[:] = [r for r in app.router.routes if getattr(r,'path','') in ('/dosignin/','/dosignin/{next:path}')]
LabWebAgent(LabApp,version,language='en_US').route(web,app)
before_users = len(app.router.routes)
Users(LabApp,version,language='en_US').route(web,app)
# Register only read-only native admin handlers. Key issuance/mutation routes are absent.
app.router.routes[before_users:] = [r for r in app.router.routes[before_users:] if r.path in ('/users/list','/groups/list')]
async_redis = Redis(host='127.0.0.1',port=REDIS_PORT,db=0,protocol=2)
app.add_middleware(SessionAutoloadMiddleware)
app.add_middleware(SessionMiddleware,store=RedisStore(connection=async_redis,prefix='cmdboxlab:session:'),
                   lifetime=1800,rolling=True,cookie_https_only=False,cookie_name='lab_session')

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi.responses import JSONResponse
class AdminReadGuard(BaseHTTPMiddleware):
    async def dispatch(self, req, call_next):
        if req.url.path in ('/users/list','/groups/list'):
            if 'signin' not in req.session: return JSONResponse({'error':'login_required'},status_code=401)
            if req.query_params: return JSONResponse({'error':'identity_selector_refused'},status_code=400)
            if 'lab-admin' not in req.session['signin'].get('groups',[]):
                return JSONResponse({'error':'admin_required'},status_code=403)
        return await call_next(req)
# Session middleware must execute before this guard.
app.user_middleware.insert(2, __import__('starlette.middleware',fromlist=['Middleware']).Middleware(AdminReadGuard))

@app.exception_handler(GatewayError)
async def gateway_error(req, error):
    return JSONResponse({'error':error.code},status_code=409)

def authenticated_uid(req,res):
    if req.query_params:
        raise HTTPException(400,'LOCAL MOCK API does not accept identity selectors')
    result = web.signin.check_signin(req,res)
    if result is not None: raise HTTPException(401,'Login required')
    return canonical_uid(req.session['signin']['uid'])
@app.get('/lab/status')
def status():
    return {'mode':'LOCAL-MOCK-ONLY','runner':RUNNER,'workerReady':worker_started.is_set()}
@app.get('/lab/api/me')
def me(req:Request,res:Response):
    uid = authenticated_uid(req,res)
    try: row = registry.resolve(uid); connection = row.status
    except GatewayError: connection = 'RECONNECT_REQUIRED'
    return {'uid':uid,'adk_user_id':'cmdbox_uid_'+uid,'connection':connection}

def mutation_uid(req,res):
    uid = authenticated_uid(req,res)
    if req.headers.get('X-Lab-Intent') != 'LITERAL-DUMMY-CONNECTION':
        raise HTTPException(403,'Explicit local dummy operation required')
    origin = req.headers.get('origin')
    if origin and origin != 'http://127.0.0.1:'+str(PORT): raise HTTPException(403,'Origin refused')
    return uid

@app.get('/lab/api/connection')
def connection_status(req:Request,res:Response):
    return lifecycle.status(authenticated_uid(req,res))
@app.post('/lab/api/connection/{operation}')
async def connection_operation(operation:str,req:Request,res:Response):
    if not FAKE_LIFECYCLE: raise HTTPException(404,'Fake lifecycle not enabled')
    uid = mutation_uid(req,res)
    body = await req.json()
    allowed = {'start':set(),'callback':{'state','code'},'refresh':{'generation'},'revoke':set()}
    if operation not in allowed or type(body) is not dict or set(body)!=allowed[operation]:
        raise HTTPException(400,'Unsupported fake operation fields')
    session = req.cookies.get('lab_session','')
    if operation=='start': result = await asyncio.to_thread(lifecycle.start,uid,session)
    elif operation=='callback':
        if not all(type(body[k]) is str for k in body): raise HTTPException(400,'String fields required')
        result = await asyncio.to_thread(lifecycle.complete,uid,session,body['state'],body['code'])
    elif operation=='refresh':
        if type(body['generation']) is not int or body['generation']<1: raise HTTPException(400,'Generation required')
        result = await asyncio.to_thread(lifecycle.renew,uid,body['generation'],force=True)
    else: result = await asyncio.to_thread(lifecycle.revoke,uid)
    trace('fake_connection_operation',uid=uid,operation=operation,generation=result.get('generation'))
    return result

async def native_resource(req,res,operation,session_id):
    authenticated_uid(req,res)
    payload = integration.attach_resource_job(req.session,operation,RUNNER,session_id)
    result_key = 'lab:resource-result:'+str(raw_redis.incr('lab:resource-result-id'))
    encoded = convert.str2b64str(common.to_str(payload))
    raw_redis.rpush('sv-cmdboxlab','agent_'+operation+' '+result_key+' '+encoded)
    reply = await asyncio.to_thread(raw_redis.blpop,result_key,30)
    if reply is None: raise HTTPException(503,'Local worker unavailable')
    return json.loads(reply[1])
@app.get('/lab/api/native/sessions')
async def native_sessions(req:Request,res:Response):
    return await native_resource(req,res,'session_list',None)
@app.get('/lab/api/native/history/{session_id}')
async def native_history(session_id:str,req:Request,res:Response):
    return await native_resource(req,res,'session_list',session_id)
@app.delete('/lab/api/native/sessions/{session_id}')
async def native_delete(session_id:str,req:Request,res:Response):
    mutation_uid(req,res)
    return await native_resource(req,res,'session_del',session_id)

def artifact_service(uid):
    return LabAgentChat(LabApp,version).create_artifact_service(logger=logger,
        artifact_root_dir=DATA/'.users'/('cmdbox_uid_'+uid)/'artifacts'/RUNNER)
@app.get('/lab/api/artifacts/{session_id}')
async def artifacts(session_id:str,req:Request,res:Response):
    uid = authenticated_uid(req,res)
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',session_id): raise HTTPException(400,'Invalid artifact identifier')
    return {'files':await artifact_service(uid).list_artifact_keys(app_name=RUNNER,user_id='cmdbox_uid_'+uid,session_id=session_id)}
@app.get('/lab/api/artifacts/{session_id}/{filename}')
async def artifact(session_id:str,filename:str,req:Request,res:Response):
    uid = authenticated_uid(req,res)
    import re
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',session_id) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}\.txt',filename):
        raise HTTPException(400,'Invalid artifact identifier')
    part = await artifact_service(uid).load_artifact(app_name=RUNNER,user_id='cmdbox_uid_'+uid,session_id=session_id,filename=filename)
    if part is None: raise HTTPException(404,'Artifact not found')
    return {'text':part.text}
@app.get('/lab/api/sessions')
async def list_sessions(req:Request,res:Response):
    uid = authenticated_uid(req,res); worker = LabAgentChat(LabApp,version)
    service = worker.create_session_service(logger=logger,data_dir=DATA,ds_conf={})
    try:
        listed = await service.list_sessions(app_name=RUNNER,user_id='cmdbox_uid_'+uid)
        return {'uid':uid,'sessions':[{'id':s.id,'user_id':s.user_id} for s in listed.sessions]}
    finally:
        await service.db_engine.dispose()
@app.get('/lab/api/history/{session_id}')
async def history(session_id:str,req:Request,res:Response):
    uid = authenticated_uid(req,res); worker = LabAgentChat(LabApp,version)
    service = worker.create_session_service(logger=logger,data_dir=DATA,ds_conf={})
    try:
        saved = await service.get_session(app_name=RUNNER,user_id='cmdbox_uid_'+uid,session_id=session_id)
        if saved is None: raise HTTPException(404,'Session not found')
        trace('uid_history_api_read',uid=uid,session_id=session_id)
        return {'uid':uid,'user_id':saved.user_id,'session_id':saved.id,
                'events':[e.model_dump(mode='json',exclude_none=True) for e in saved.events]}
    finally:
        await service.db_engine.dispose()
@app.get('/lab',response_class=HTMLResponse)
def landing():
    return '<h1>Public cmdbox LOCAL MOCK</h1><p>Literal dummy users only. Real OAuth and external services are disabled.</p>'

if __name__ == '__main__':
    config = uvicorn.Config(app,host='127.0.0.1',port=PORT,ws='wsproto',log_level='warning',access_log=False)
    server = uvicorn.Server(config)
    def stdin_control():
        for line in sys.stdin:
            if line.strip() == 'STOP':
                server.should_exit = True
                return
    threading.Thread(target=stdin_control,daemon=True).start()
    server.run()
