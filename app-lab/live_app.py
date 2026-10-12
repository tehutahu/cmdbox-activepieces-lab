"""Small native cmdbox/ADK app for the explicitly approved local synthetic AP test.

Configuration/keys/passwords are injected from a protected encrypted settings file.
No provider LLM, static API key, registration, account creation or default AP target.
The browser alone presses AP Authorize. GET /status never starts an OAuth transaction.
"""
import asyncio
import base64
from contextlib import asynccontextmanager
from contextvars import ContextVar
import hashlib
import hmac
import html
import json
import logging
from pathlib import Path
import threading
import time
import httpx
import redis
from fastapi import FastAPI, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from starsessions import SessionMiddleware, SessionAutoloadMiddleware
from starsessions.stores.memory import InMemoryStore
from starsessions.session import get_session_handler, regenerate_session_id
from cmdbox.app import common
from cmdbox import version
from cmdbox.app.web import Web
from cmdbox.app.auth.signin import Signin
from cmdbox.app.features.web.cmdbox_web_do_signin import DoSignin
from cmdbox.app.features.web.cmdbox_web_agent import Agent as NativeWebAgent
from cmdbox.app.features.cli.cmdbox_agent_chat import AgentChat
from cmdbox.app.commons.redis_client import RedisClient
from cmdbox_gateway import integration
from cmdbox_gateway.core import AuthorizedFlowBroker, WebJobIssuer, WorkerJobVerifier, RedisReplayGuard, GatewayError, require
from cmdbox_gateway.lifecycle_live import LiveLifecycle
from cmdbox_gateway.cleanup_live import CleanupOperator
from google.adk.agents import LlmAgent
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

_operation_uid = ContextVar('approved_ap_operation_uid', default=None)


class Window:
    def __init__(self, store, *, clock=time.time, flow_budget_store=None):
        self.store, self.clock = store, clock
        self.flow_budget_store = flow_budget_store or store
        with store.db() as db:
            db.execute('CREATE TABLE IF NOT EXISTS app_window (id INTEGER PRIMARY KEY CHECK(id=1), started INTEGER)')
            db.execute('CREATE TABLE IF NOT EXISTS app_control (id INTEGER PRIMARY KEY CHECK(id=1), reason TEXT)')
            db.execute('CREATE TABLE IF NOT EXISTS app_budget (uid TEXT, operation TEXT, n INTEGER, PRIMARY KEY(uid,operation))')

    def started(self):
        with self.store.db() as db:
            row = db.execute('SELECT started FROM app_window WHERE id=1').fetchone()
        return row[0] if row else None

    def begin(self):
        with self.store.db() as db:
            db.execute('INSERT OR IGNORE INTO app_window VALUES (1,?)', (int(self.clock()),))

    def close(self, reason):
        with self.store.db() as db:
            db.execute('INSERT OR IGNORE INTO app_control VALUES (1,?)', (reason,))

    def valid(self):
        start = self.started()
        with self.store.db() as db:
            closed = db.execute('SELECT reason FROM app_control WHERE id=1').fetchone()
            blocked = db.execute('SELECT reason FROM operator_control WHERE id=1').fetchone()
        return not closed and not blocked and start is not None and int(self.clock()) < start + 7200

    def spend(self, uid, operation, maximum):
        require(self.valid(), 'authorization_window_closed')
        budget_store = self.flow_budget_store if operation == 'flow' else self.store
        with budget_store.db() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT n FROM app_budget WHERE uid=? AND operation=?', (uid, operation)).fetchone()
            number = row[0] if row else 0
            require(number < maximum, 'approved_operation_budget_exhausted')
            db.execute('INSERT INTO app_budget VALUES (?,?,?) ON CONFLICT(uid,operation) DO UPDATE SET n=excluded.n', (uid, operation, number + 1))


class BudgetedProvider:
    def __init__(self, provider, window):
        self.provider, self.window, self.config = provider, window, provider.config

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def exchange(self, code, verifier):
        uid = _operation_uid.get()
        require(uid is not None, 'verified_operation_uid_required')
        self.window.spend(uid, 'exchange', 1)
        return self.provider.exchange(code, verifier)

    def refresh(self, refresh):
        uid = _operation_uid.get()
        require(uid is not None, 'verified_operation_uid_required')
        self.window.spend(uid, 'refresh', 1)
        return self.provider.refresh(refresh)


class BudgetedLifecycle(LiveLifecycle):
    def complete(self, uid, *args):
        token = _operation_uid.set(uid)
        try:
            return super().complete(uid, *args)
        finally:
            _operation_uid.reset(token)

    def renew(self, uid, *args, **kwargs):
        token = _operation_uid.set(uid)
        try:
            return super().renew(uid, *args, **kwargs)
        finally:
            _operation_uid.reset(token)


class BudgetedBroker(AuthorizedFlowBroker):
    def __init__(self, *args, window, **kwargs):
        super().__init__(*args, **kwargs)
        self.window = window

    async def call(self, context, **kwargs):
        invocation, binding = self.binding_for(context)
        require(kwargs.get('expected_uid') == invocation.actor.uid and kwargs.get('expected_generation') == binding.generation,
                'stale_or_wrong_identity_tool')
        require(kwargs.get('alias') == 'lab_identity' and kwargs.get('arguments') == {}, 'tool_not_allowed')
        self.window.spend(invocation.actor.uid, 'flow', 2)
        try:
            result = await super().call(context, **kwargs)
            require(self.window.valid(), 'authorization_window_closed')
        except GatewayError:
            # A missing/changed synthetic target or upstream identity failure stops
            # this approved connection. Never recreate a flow or try another tool.
            await asyncio.to_thread(self._credentials.revoke, invocation.actor.uid)
            raise
        return result


def create_apps(settings, registry, provider, transport, entropy, data, *, on_expired=lambda: None, clock=time.time):
    data = Path(data)
    labels = settings.get('login_labels', {'A': '101', 'B': '202'})
    require(data.is_dir() and type(labels) is dict and set(labels) <= {'A', 'B'} and labels
            and set(settings['passwords']) == set(labels) and set(labels.values()) == set(registry.targets),
            'preprovisioned_native_fixture_required')
    stock = 'stock_drive' in settings
    policies = None
    if stock:
        from cmdbox_gateway.stock_drive import verified_settings
        policies = verified_settings(settings, registry.targets, actual=settings['mode'] == 'APPROVED-LOCAL-AP')
    logger = logging.getLogger('cmdbox.ap.approved')
    logger.setLevel(logging.WARNING)
    window = Window(registry.store, clock=clock, flow_budget_store=getattr(registry, 'flow_budget_store', None))
    life = BudgetedLifecycle(registry, BudgetedProvider(provider, window), entropy, clock=clock)
    cleanup = CleanupOperator(registry, provider.config, clock=clock)
    key = base64.b64decode(settings['job_key'])
    session_key = base64.b64decode(settings['session_secret'])
    require(len(key) == 32 and len(session_key) == 32, 'approved_application_keys_required')
    if stock:
        from cmdbox_gateway.stock_drive import StockDriveBroker
        broker = StockDriveBroker(registry, life, transport, policies, resource=provider.config.resource, window=window)
    else:
        broker = BudgetedBroker(registry, life, transport, resource=provider.config.resource, window=window)
    alias = broker.tool_alias
    raw_redis = redis.Redis(host='127.0.0.1', port=18091, db=0, protocol=2)
    stop = threading.Event()
    worker_ready = threading.Event()
    svname = 'cmdboxlive'
    runner = 'adapter_lab'
    store = InMemoryStore()
    handoffs = {}

    class App:
        @classmethod
        def getInstance(cls, **kwargs):
            return cls()
        def main(self, **kwargs):
            raise GatewayError('unconfigured_command')

    class ScriptedModel(BaseLlm):
        async def generate_content_async(self, llm_request, stream=False):
            responses = [p.function_response for p in llm_request.contents[-1].parts or [] if p.function_response]
            if responses:
                value = responses[-1].response
                content = types.Content(role='model', parts=[types.Part(text=json.dumps({'message': value if stock else value.get('marker', value.get('error', 'unknown'))}))])
            else:
                require(list(llm_request.tools_dict) == [alias], 'synthetic_model_toolset_required')
                content = types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(name=alias, args={}))])
            yield LlmResponse(content=content, usage_metadata=types.GenerateContentResponseUsageMetadata(
                prompt_token_count=0, candidates_token_count=0, total_token_count=0))

    class Worker(AgentChat):
        def create_agent(self, *, logger, mcpsv_confs, payload, **kwargs):
            tools = self.create_tool_mcpsv(logger, mcpsv_confs, payload)
            return LlmAgent(name='lab_agent', model=ScriptedModel(model='local-scripted-model'), tools=tools)
        def create_session_service(self, *, logger, data_dir, ds_conf):
            return super().create_session_service(logger=logger, data_dir=data_dir, ds_conf={'dbtype': 'sqlite', 'db_fullpath': str(data / 'history.sqlite')})
        async def create_runner_plugin(self, **kwargs):
            return []
        def _setup_tts_engine(self, *args):
            return False, None
        async def error_chat_run(self, *, redis_cli, reskey, exc, **kwargs):
            code = exc.code if isinstance(exc, GatewayError) else 'approved_app_error'
            redis_cli.rpush(reskey, {'warn': {'error': code}, 'end': True})
            return self.RESP_WARN

    def run_worker():
        async def run():
            client = RedisClient(logger, host='127.0.0.1', port=18091, password=None, svname=svname)
            heartbeat = 'hb-cmdboxlive-approved-worker'
            client.redis_cli.hset(heartbeat, mapping={'status': 'APPROVED_LOCAL_AP'})
            worker = Worker(App, version, language='en_US')
            worker_ready.set()
            try:
                while not stop.is_set():
                    result = client.redis_cli.blpop('sv-' + svname, timeout=1)
                    if not result:
                        continue
                    msg = result[1].decode('utf-8').split(' ', 2)
                    if msg[0] == 'agent_chat':
                        await worker.svrun(data, logger, client, msg, {})
                    elif msg[0] == 'limiter_plan_list':
                        client.rpush(msg[1], {'success': {'data': []}, 'end': True})
                    else:
                        client.rpush(msg[1], {'warn': {'error': 'unconfigured_command'}, 'end': True})
            finally:
                client.redis_cli.delete(heartbeat)
                client.close()
        asyncio.run(run())

    shutdown_lock = asyncio.Lock()
    async def shutdown(reason):
        async with shutdown_lock:
            if stop.is_set():
                return
            window.close(reason)
            integration.install_web_runtime(None)
            try:
                # Disable every local UID atomically before any upstream cleanup.
                with registry.store.db() as db:
                    db.execute('BEGIN IMMEDIATE')
                    for uid in labels.values():
                        life._disable(db, uid)
                for uid in labels.values():
                    try:
                        await asyncio.to_thread(life.attempt_cleanup, uid)
                    except Exception:
                        logger.error('Grant cleanup needs operator review')
            finally:
                try:
                    if stock:
                        from cmdbox_gateway.stock_retention import purge_local_tokens
                        app.state.retention_tokens = purge_local_tokens(registry)
                finally:
                    try:
                        on_expired()
                    finally:
                        stop.set()

    @asynccontextmanager
    async def lifespan(app):
        raw_redis.ping()
        guard = RedisReplayGuard(raw_redis)
        issuer = WebJobIssuer(key, nonce_factory=lambda: base64.urlsafe_b64encode(entropy(24)).decode().rstrip('='))
        verifier = WorkerJobVerifier(key, guard)
        integration.bootstrap([{'mcpserver_auth_mode': 'user_ap_binding', 'mcpserver_mcp_tools': [alias]}],
                              issuer=issuer, verifier=verifier, broker=broker, shared_replay_guard=guard)
        thread = threading.Thread(target=run_worker, daemon=True)
        thread.start()
        require(await asyncio.to_thread(worker_ready.wait, 10), 'native_worker_start_failed')
        async def watch():
            while not stop.is_set():
                await asyncio.sleep(2)
                for digest, item in list(handoffs.items()):
                    if item['expires'] <= int(time.time()):
                        del handoffs[digest]
                        await store.remove(item['session'])
                try:
                    await asyncio.to_thread(cleanup.apply)
                except GatewayError:
                    logger.error('Formal review proof quarantined')
                if cleanup.blocked() or window.started() is not None and not window.valid():
                    await shutdown('operator_quarantine' if cleanup.blocked() else 'authorization_expired')
        watcher = asyncio.create_task(watch())
        try:
            yield
        finally:
            if stock:
                await shutdown('server_exit')
            stop.set()
            watcher.cancel()
            await asyncio.to_thread(thread.join, 10)
            app.state.worker_stopped = not thread.is_alive()
            # Only this dedicated native app's cache field, never a Redis flush.
            web.redis_cli.redis_cli.hdel(web.redis_cli.memname, 'signin_file_data')
            raw_redis.close()

    app, callback = FastAPI(lifespan=lifespan), FastAPI()
    app.state.shutdown_approved = shutdown
    app.state.worker_stopped = False
    app.state.retention_tokens = {'localTokenMaterialRemoved': False}
    (data / '.agent').mkdir(exist_ok=True)
    for filename, record in {
        'runner-adapter_lab.json': {'runner_name': runner, 'agent': 'lab_agent'},
        'agent-lab_agent.json': {'agent_name': 'lab_agent', 'agent_type': 'local', 'mcpservers': ['approved_gateway']},
        'mcpsv-approved_gateway.json': {'mcpserver_auth_mode': 'user_ap_binding', 'mcpserver_mcp_tools': [alias]},
    }.items():
        path = data / '.agent' / filename
        if path.exists():
            require(json.loads(path.read_text()) == record, 'native_config_changed')
        else:
            path.write_text(json.dumps(record), encoding='utf-8')
    # Explicit control-plane loader injection for this one fixture file. The
    # marker file contains no password/hash; actual passwords remain DPAPI settings.
    # Native password comparison/session creation still execute unchanged.
    signin_data = {
        'users': [{'uid': int(uid), 'name': 'alice' if label == 'A' else 'bob', 'hash': 'sha256',
                   'password': hashlib.sha256(settings['passwords'][label].encode()).hexdigest(),
                   'groups': ['lab'], 'home': 'homes/' + label, 'email': label.lower() + '@example.invalid', 'apikeys': {}}
                  for label, uid in labels.items()],
        'groups': [{'gid': 1, 'name': 'lab', 'parent': None, 'home': 'groups/lab', 'startpage': 'connect'}],
        'pathrule': {'policy': 'allow', 'rules': []}, 'cmdrule': {'policy': 'deny', 'rules': []},
        'oauth2': {'providers': {x: {'enabled': False, 'client_id': '', 'client_secret': '', 'tenant_id': '',
                                    'redirect_uri': '', 'scope': [], 'signin_module': None} for x in ('google', 'github', 'azure')}},
        'saml': {'providers': {'azure': {'enabled': False, 'signin_module': None, 'sp': {}, 'idp': {}}}}}
    signin_data['signin'] = {'signin_module': 'cmdbox.app.auth.signin'}
    signin_data['apikey'] = {'verify_jwt': {'enabled': False}, 'gen_cert': {'enabled': False}, 'gen_jwt': {'enabled': False}}
    marker = data / 'signin-control.json'
    if not marker.exists():
        marker.write_text('{"mode":"SERVER-OWNED-ENCRYPTED-SETTINGS"}', encoding='utf-8')
    original_loader = Signin.load_signin_file
    def load_fixture(cls, path, cached=None, **kwargs):
        if path is not None and Path(path).resolve() == marker.resolve():
            return signin_data
        return original_loader(path, cached, **kwargs)
    Signin.load_signin_file = classmethod(load_fixture)
    web = Web.getInstance(logger, data, appcls=App, ver=version, language='en_US',
                          redis_host='127.0.0.1', redis_port=18091, redis_password=None, svname=svname, signin_file=marker)
    class PasswordLogin(DoSignin):
        def set_session(self, req, user_session):
            req.session['signin'].pop('password', None)
    PasswordLogin(App, version, language='en_US').route(web, app)
    app.router.routes[:] = [r for r in app.router.routes if getattr(r, 'path', '') in ('/dosignin/', '/dosignin/{next:path}')]
    class WebAgent(NativeWebAgent):
        def get_startmsg(self, *args):
            return ''
    web.agent_chat_factory = Worker
    web.options._options['cmd']['agent'] = {'chat': Worker(App, version).get_option()}
    WebAgent(App, version, language='en_US').route(web, app)
    for surface in (app, callback):
        surface.add_middleware(SessionAutoloadMiddleware)
        surface.add_middleware(SessionMiddleware, store=store, lifetime=7200, rolling=False,
                               cookie_https_only=False, cookie_name='cmdbox_ap_live', cookie_same_site='lax')
        @surface.exception_handler(GatewayError)
        async def refusal(req, error):
            return JSONResponse({'error': error.code}, status_code=409)

    def actor(req):
        value = req.session.get('signin', {})
        uid = str(value.get('uid', ''))
        require(uid in labels.values(), 'native_password_login_required')
        return uid

    def csrf(req, value):
        require(req.headers.get('origin') == 'http://localhost:18090' and type(value) is str
                and hmac.compare_digest(value, req.session.get('csrf', '')), 'same_origin_csrf_required')

    def status():
        return {'ready': worker_ready.is_set(), 'mode': 'APPROVED-LOCAL-AP', 'client': provider.config.client_name,
                'clientRecognizedAtAuthorize': 'VERIFIED_TOKEN_CLIENT' if any(registry.get_record(uid) for uid in labels.values()) else 'PENDING',
                'authorizationStartedAt': window.started(),
                'deadline': window.started() + 7200 if window.started() else None,
                'connections': {label: life.status(uid) for label, uid in labels.items()},
                'pendingStateCount': registry.store.path.exists() and pending_count(),
                'cleanup': cleanup.summary()}
    def pending_count():
        with registry.store.db() as db:
            return db.execute('SELECT count(*) FROM pending').fetchone()[0]
    app.get('/status')(status)
    callback.get('/status')(status)

    async def promote(req, inner_session, uid):
        handler = get_session_handler(req)
        trusted = handler.serializer.deserialize(await store.read(inner_session, 7200))
        trusted.pop('__metadata__', None)
        require(str(trusted.get('signin', {}).get('uid')) == uid, 'native_fixture_uid_mismatch')
        req.session.clear()
        req.session.update(trusted)
        regenerate_session_id(req)
        await store.remove(inner_session)

    @app.post('/handoff/{label}')
    async def handoff(label: str, req: Request):
        require(label in labels and actor(req) == labels[label], 'native_password_login_required')
        body = await req.json()
        require(type(body) is dict and set(body) == {'csrf'}, 'unsupported_handoff_fields')
        csrf(req, body['csrf'])
        now = int(time.time())
        ticket = base64.urlsafe_b64encode(entropy(32)).decode().rstrip('=')
        digest = hashlib.sha256(ticket.encode()).hexdigest()
        require(digest not in handoffs, 'handoff_entropy_collision')
        handoffs[digest] = {'session': req.cookies['cmdbox_ap_live'], 'uid': labels[label], 'expires': now + 30, 'label': label}
        return {'url': 'http://localhost:18090/handoff/' + label + '?ticket=' + ticket}

    @app.get('/handoff/{label}')
    async def take_handoff(label: str, req: Request):
        require(label in labels and set(req.query_params) == {'ticket'}, 'unsupported_handoff_fields')
        digest = hashlib.sha256(req.query_params['ticket'].encode()).hexdigest()
        item = handoffs.get(digest)
        require(item is not None and item['label'] == label, 'handoff_missing_or_wrong_label')
        del handoffs[digest]
        require(item['expires'] > int(time.time()), 'handoff_expired')
        await promote(req, item['session'], item['uid'])
        response = RedirectResponse('/connect/' + label, status_code=303)
        response.headers['Referrer-Policy'] = 'no-referrer'
        return response

    @app.get('/connection')
    def connection(req: Request):
        uid = actor(req)
        value = hmac.new(session_key, entropy(32), hashlib.sha256).hexdigest()
        req.session['csrf'] = value
        return {**life.status(uid), 'csrf': value}

    @app.post('/connection/{operation}')
    async def operation(operation: str, req: Request):
        uid = actor(req)
        body = await req.json()
        required = {'csrf', 'generation'} if operation == 'refresh' else {'csrf'}
        require(operation in ('refresh', 'revoke') and type(body) is dict and set(body) == required, 'unsupported_connection_fields')
        csrf(req, body['csrf'])
        require(window.valid(), 'authorization_window_closed')
        if operation == 'refresh':
            return await asyncio.to_thread(life.renew, uid, body['generation'], force=True)
        return await asyncio.to_thread(life.revoke, uid)

    @app.get('/connect/{label}', response_class=HTMLResponse)
    async def entry(label: str, req: Request):
        require(label in labels and actor(req) == labels[label], 'native_password_login_required')
        nonce = base64.urlsafe_b64encode(entropy(32)).decode().rstrip('=')
        proof = hmac.new(session_key, nonce.encode(), hashlib.sha256).hexdigest()
        req.session['csrf'] = proof
        return '<h1>合成AP接続 ' + label + '</h1><p>' + html.escape(provider.config.client_name) + \
            ' / mcp（管理操作を含む広いscope）。既存account/projectを確認し、APのAuthorizeは本人が操作してください。</p>' + \
            '<p>開始ボタンから最大2時間。state/PKCEは開始時に生成します。</p><form method="post"><input type="hidden" name="csrf" value="' + proof + \
            '"><button>接続を開始</button></form>'

    @app.post('/connect/{label}')
    async def begin(label: str, req: Request):
        require(label in labels, 'approved_target_required')
        require(actor(req) == labels[label], 'native_password_login_required')
        form = await req.form()
        require(set(form) == {'csrf'}, 'unsupported_connection_fields')
        csrf(req, form['csrf'])
        require(not life.status(labels[label])['cleanupPending'], 'formal_cleanup_required')
        with registry.store.db() as db:
            attempts = db.execute('SELECT n FROM app_budget WHERE uid=? AND operation=?', (labels[label], 'exchange')).fetchone()
        require(attempts is None or attempts[0] == 0, 'approved_operation_budget_exhausted')
        require(not cleanup.blocked(), 'operator_quarantined')
        window.begin()
        require(window.valid(), 'authorization_window_closed')
        session = req.cookies.get('cmdbox_ap_live', '')
        started = await asyncio.to_thread(life.start, labels[label], session)
        return RedirectResponse(started['authorizationUrl'], status_code=303)

    @callback.get('/oauth/callback')
    async def finish(req: Request):
        uid = actor(req)
        require(window.valid() and set(req.query_params) in ({'state', 'code'}, {'state', 'error'}), 'oauth_callback_fields_or_window_invalid')
        session = req.cookies.get('cmdbox_ap_live', '')
        if 'error' in req.query_params:
            # Denial consumes state but does not exchange a token or create a grant.
            base, lease, _ = await asyncio.to_thread(life._claim_callback, uid, session, req.query_params['state'])
            with registry.store.db() as db:
                db.execute('DELETE FROM leases WHERE uid=? AND id=? AND base=?', (uid, lease, base))
            raise GatewayError('oauth_authorization_not_completed')
        try:
            await asyncio.to_thread(life.complete, uid, session, req.query_params['state'], req.query_params['code'])
        except GatewayError:
            if life.status(uid)['cleanupPending']:
                # A consumed exchange with unknown/wrong identity must prevent
                # another approved UID from creating a second grant. Invalid
                # state before any exchange does not trigger global shutdown.
                cleanup.quarantine('connection_verification_failed')
            await asyncio.to_thread(life.attempt_cleanup, uid)
            raise
        return HTMLResponse('<h1>接続を照合しました</h1><p>通常実行・refresh・revokeの確認は親へ戻って続けます。</p>')

    return app, callback, life, window, stop
