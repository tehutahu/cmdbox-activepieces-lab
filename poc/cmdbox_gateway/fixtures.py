"""Literal dummy MOCK fixtures only. Never reads private/ or contacts actual AP."""
from dataclasses import replace
from types import SimpleNamespace
from .core import Binding, FlowPolicy, BindingRegistry, AuthorizedFlowBroker, WebJobIssuer, WorkerJobVerifier, MemoryReplayGuard, GatewayError
DUMMY_KEY = b'LITERAL_DUMMY_WEB_WORKER_INTEGRITY_KEY_MOCK_ONLY'
FLOW_A = FlowPolicy('lab_identity', 'lab_identity_a_dummy_mcp', 'DUMMY-FLOW-A', 'A_ONLY', 'A')
FLOW_B = FlowPolicy('lab_identity', 'lab_identity_b_dummy_mcp', 'DUMMY-FLOW-B', 'B_ONLY', 'B')

def payload(message='IDENTITY', session='same-chat', runner='adapter_lab'):
    return dict(runner_name=runner, user_name='ignored-client-display', session_id=session, message=message,
                call_tts=False, reasoning_effort='off', mcpserver_apikey=None, a2asv_apikey=None)

def login(uid=101, name='alice'):
    return {'signin': {'uid': uid, 'name': name}}

def context(actor, session='same-chat'):
    return SimpleNamespace(user_id=actor.adk_user_id, session=SimpleNamespace(id=session, user_id=actor.adk_user_id, app_name=actor.runner_name))

class DummyCredentials:
    def __init__(self):
        self.active = {'dummy-ref-a': 'LITERAL-DUMMY-AP-A', 'dummy-ref-b': 'LITERAL-DUMMY-AP-B'}
    async def get_active(self, reference, grant_id, generation):
        if reference not in self.active:
            raise GatewayError('reconnect_required')
        return self.active[reference]

class DummyMcpTransport:
    def __init__(self):
        self.calls = []
        self.after_call = None
    async def call(self, *, resource, headers, raw_name, arguments, cache_key):
        import asyncio
        expected = FLOW_A if headers.get('Authorization') == 'Bearer LITERAL-DUMMY-AP-A' else FLOW_B
        if raw_name != expected.raw_name or arguments != {}:
            raise GatewayError('dummy_mcp_refused')
        self.calls.append({'resource': resource, 'raw_name': raw_name, 'cache_key': cache_key})  # No credentials in evidence.
        await asyncio.sleep(0)
        if self.after_call:
            self.after_call()
        return {'marker': expected.marker, 'owner': expected.owner, 'kind': 'synthetic', 'headers': {'ignored': 'not-exposed'}}

def fixture():
    registry = BindingRegistry([FLOW_A, FLOW_B])
    registry.bind(Binding('101', 'DUMMY-AP-SUBJECT-A', 'DUMMY-PROJECT-A', 'DUMMY-GRANT-A', 'dummy-ref-a', 1, FLOW_A))
    registry.bind(Binding('202', 'DUMMY-AP-SUBJECT-B', 'DUMMY-PROJECT-B', 'DUMMY-GRANT-B', 'dummy-ref-b', 1, FLOW_B))
    credential, transport = DummyCredentials(), DummyMcpTransport()
    now = [1800000000]; nonce = [0]
    def next_nonce():
        nonce[0] += 1
        return 'LITERAL_DUMMY_NONCE_' + str(nonce[0])
    issuer = WebJobIssuer(DUMMY_KEY, clock=lambda: now[0], nonce_factory=next_nonce)
    verifier = WorkerJobVerifier(DUMMY_KEY, MemoryReplayGuard(), clock=lambda: now[0])
    return SimpleNamespace(registry=registry, credentials=credential, transport=transport,
                           broker=AuthorizedFlowBroker(registry, credential, transport), issuer=issuer, verifier=verifier, now=now)
