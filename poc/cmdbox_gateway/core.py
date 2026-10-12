"""Trusted Web -> Redis identity, server-side binding and an explicit synthetic-flow policy."""
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
import hashlib
import hmac
import json
import re
import secrets
from threading import Lock
import time

RESOURCE = 'http://mock-ap.invalid/mcp'  # Identifier only: dummy transport never connects.
LEGACY_FIELDS = frozenset(('runner_name', 'user_name', 'session_id', 'message', 'call_tts', 'reasoning_effort', 'mcpserver_apikey', 'a2asv_apikey'))

class GatewayError(Exception):
    def __init__(self, code):
        self.code = code
        super().__init__(code)  # Never include a payload, credential or remote error body.

def require(condition, code):
    if not condition:
        raise GatewayError(code)

def canonical_uid(value):
    require(type(value) is int and value >= 0, 'authenticated_login_uid_required')
    return str(value)

def canonical(data):
    return json.dumps(data, sort_keys=True, separators=(',', ':'), ensure_ascii=False, allow_nan=False).encode('utf8')

def validate_payload(payload):
    require(type(payload) is dict and set(payload) == LEGACY_FIELDS, 'unsupported_job_fields')
    require(type(payload['runner_name']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', payload['runner_name']), 'invalid_runner')
    require(payload['session_id'] is None or (type(payload['session_id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', payload['session_id'])), 'invalid_session')
    require(type(payload['user_name']) is str and 0 < len(payload['user_name']) <= 128, 'invalid_display_name')
    require(type(payload['message']) is str and len(payload['message']) <= 100000, 'invalid_message')
    require(type(payload['call_tts']) is bool and type(payload['reasoning_effort']) is str, 'invalid_job_options')
    for name in ('mcpserver_apikey', 'a2asv_apikey'):
        require(payload[name] is None or type(payload[name]) is str, 'invalid_legacy_key')

@dataclass(frozen=True)
class Actor:
    uid: str
    display_name: str
    runner_name: str
    requested_session_id: str | None
    nonce: str

    @property
    def adk_user_id(self):
        return 'cmdbox_uid_' + self.uid

class MemoryReplayGuard:
    """MOCK/single-process guard. Production Redis workers need shared atomic claim + TTL."""
    def __init__(self):
        self._seen = {}
        self._lock = Lock()

    def claim(self, nonce, expires, now):
        with self._lock:
            self._seen = {k: v for k, v in self._seen.items() if v > now}
            if nonce in self._seen:
                return False
            self._seen[nonce] = expires
            return True

class RedisReplayGuard:
    """Injected synchronous Redis client; SET NX EX is shared/atomic across workers.

    Construct with the existing application's configured authenticated Redis client.
    This class does not create a connection, key or Redis credential.
    """
    def __init__(self, redis_client):
        self._redis = redis_client
        require(callable(getattr(redis_client, 'set', None)), 'shared_redis_guard_required')

    def claim(self, nonce, expires, now):
        digest = hashlib.sha256(nonce.encode('ascii')).hexdigest()
        try:
            return bool(self._redis.set('cmdbox:ap-job:nonce:v1:' + digest, '1', nx=True, ex=max(1, expires - now)))
        except Exception:
            raise GatewayError('replay_store_unavailable') from None

class WebJobIssuer:
    """Caller must pass the SERVER session after cmdbox check_signin, never request JSON.

    Signing key is injected infrastructure configuration; this module does not create/store one.
    Do not reuse the shared tool API key for this proof.
    """
    def __init__(self, signing_key, *, clock=time.time, nonce_factory=lambda: secrets.token_urlsafe(24)):
        require(type(signing_key) is bytes and len(signing_key) >= 32, 'configured_web_worker_integrity_key_required')
        self._key, self._clock, self._nonce = signing_key, clock, nonce_factory

    def attach(self, verified_server_session, legacy_payload):
        require(type(verified_server_session) is dict, 'authenticated_login_uid_required')
        login = verified_server_session.get('signin', {})
        require(type(login) is dict, 'authenticated_login_uid_required')
        uid = canonical_uid(login.get('uid'))
        require(type(login.get('name')) is str and login['name'], 'authenticated_login_name_required')
        payload = dict(legacy_payload)
        payload['user_name'] = login['name']
        validate_payload(payload)
        now = int(self._clock())
        claims = {'v': 1, 'iss': 'cmdbox-web', 'aud': 'cmdbox-agent-worker', 'uid': uid,
                  'iat': now, 'exp': now + 120, 'nonce': self._nonce(),
                  'payload_sha256': hashlib.sha256(canonical(payload)).hexdigest()}
        signature = hmac.new(self._key, canonical(claims), hashlib.sha256).hexdigest()
        return {**payload, 'trusted_identity': {'claims': claims, 'signature': signature}}

class WorkerJobVerifier:
    def __init__(self, signing_key, replay_guard, *, clock=time.time):
        require(type(signing_key) is bytes and len(signing_key) >= 32, 'configured_web_worker_integrity_key_required')
        require(callable(getattr(replay_guard, 'claim', None)), 'replay_guard_required')
        self._key, self._guard, self._clock = signing_key, replay_guard, clock

    def verify(self, queued_payload):
        require(type(queued_payload) is dict and set(queued_payload) == LEGACY_FIELDS | {'trusted_identity'}, 'signed_web_identity_required')
        payload = {key: queued_payload[key] for key in LEGACY_FIELDS}
        validate_payload(payload)
        proof = queued_payload['trusted_identity']
        require(type(proof) is dict and set(proof) == {'claims', 'signature'}, 'invalid_identity_proof')
        claims = proof['claims']
        require(type(claims) is dict and set(claims) == {'v', 'iss', 'aud', 'uid', 'iat', 'exp', 'nonce', 'payload_sha256'}, 'invalid_identity_claims')
        signature = proof['signature']
        require(type(signature) is str and re.fullmatch(r'[0-9a-f]{64}', signature), 'invalid_identity_signature')
        require(hmac.compare_digest(signature, hmac.new(self._key, canonical(claims), hashlib.sha256).hexdigest()), 'invalid_identity_signature')
        now = int(self._clock())
        require(type(claims['v']) is int and claims['v'] == 1 and claims['iss'] == 'cmdbox-web' and claims['aud'] == 'cmdbox-agent-worker', 'identity_audience_mismatch')
        require(type(claims['iat']) is int and type(claims['exp']) is int and 0 < claims['exp'] - claims['iat'] <= 120 and claims['iat'] <= now + 5 and claims['exp'] > now, 'identity_expired_or_future')
        require(type(claims['uid']) is str and re.fullmatch(r'0|[1-9][0-9]*', claims['uid']), 'invalid_identity_uid')
        require(type(claims['nonce']) is str and re.fullmatch(r'[A-Za-z0-9_-]{16,100}', claims['nonce']), 'invalid_identity_nonce')
        require(claims['payload_sha256'] == hashlib.sha256(canonical(payload)).hexdigest(), 'queued_payload_modified')
        require(self._guard.claim(claims['nonce'], claims['exp'], now), 'identity_replay')
        return Actor(claims['uid'], payload['user_name'], payload['runner_name'], payload['session_id'], claims['nonce'])

@dataclass(frozen=True)
class Invocation:
    actor: Actor
    session_id: str

_invocation = ContextVar('cmdbox_ap_trusted_invocation', default=None)

@contextmanager
def invocation_scope(actor, actual_session_id):
    require(isinstance(actor, Actor), 'verified_worker_actor_required')
    require(type(actual_session_id) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,100}', actual_session_id), 'invalid_session')
    require(actor.requested_session_id is None or actual_session_id == actor.requested_session_id, 'worker_session_mismatch')
    token = _invocation.set(Invocation(actor, actual_session_id))
    try:
        yield
    finally:
        _invocation.reset(token)

def actor_for_adk(context):
    current = _invocation.get()
    require(current is not None and context is not None, 'verified_invocation_required')
    session = getattr(context, 'session', None)
    require(getattr(context, 'user_id', None) == current.actor.adk_user_id and getattr(session, 'user_id', None) == current.actor.adk_user_id,
            'adk_identity_mismatch')
    require(getattr(session, 'id', None) == current.session_id and getattr(session, 'app_name', None) == current.actor.runner_name, 'adk_session_mismatch')
    return current

@dataclass(frozen=True)
class FlowPolicy:
    alias: str
    raw_name: str
    flow_id: str
    marker: str
    owner: str

@dataclass(frozen=True)
class Binding:
    uid: str
    subject: str
    project_id: str
    grant_id: str
    credential_ref: str
    generation: int
    flow: FlowPolicy
    status: str = 'ACTIVE'

class BindingRegistry:
    """Trusted control-plane input only; not a browser/body/LLM-owned configuration store."""
    def __init__(self, approved_flows):
        self._approved = frozenset(approved_flows)
        require(all((x.alias == 'lab_identity' and not x.raw_name.startswith('ap_') and x.raw_name.endswith('_mcp'))
                    or (x.alias == 'lab_drive_search' and re.fullmatch(r'lab_drive_search_[A-Za-z0-9_]+_mcp', x.raw_name))
                    for x in self._approved), 'invalid_synthetic_policy')
        self._rows = {}

    def bind(self, binding):
        require(isinstance(binding, Binding) and binding.flow in self._approved and type(binding.generation) is int and binding.generation > 0, 'binding_not_approved')
        require(all(type(x) is str and x for x in (binding.uid, binding.subject, binding.project_id, binding.grant_id, binding.credential_ref)), 'invalid_binding')
        require(re.fullmatch(r'0|[1-9][0-9]*', binding.uid) and binding.status in ('ACTIVE', 'RECONNECT_REQUIRED'), 'invalid_binding')
        previous = self._rows.get(binding.uid)
        require(previous is None or binding.generation > previous.generation, 'binding_generation_must_increase')
        self._rows[binding.uid] = binding

    def resolve(self, uid):
        binding = self._rows.get(uid)
        require(binding is not None and binding.status == 'ACTIVE', 'reconnect_required')
        return binding

    def disable(self, uid):
        binding = self._rows.get(uid)
        if binding:
            from dataclasses import replace
            self._rows[uid] = replace(binding, status='RECONNECT_REQUIRED', generation=binding.generation + 1)

class AuthorizedFlowBroker:
    tool_alias = 'lab_identity'
    """No registry mutation, AP management tools, refresh fallback or credential persistence."""
    def __init__(self, registry, credential_provider, transport, *, resource=RESOURCE):
        require(type(resource) is str and bool(resource), "configured_resource_required")
        self._registry, self._credentials, self._transport = registry, credential_provider, transport
        self._resource = resource

    def binding_for(self, context):
        invocation = actor_for_adk(context)
        return invocation, self._registry.resolve(invocation.actor.uid)

    def require_actor_connection(self, actor):
        # Worker calls immediately after verification and before starting ADK.
        require(isinstance(actor, Actor), 'signed_web_identity_required')
        binding = self._registry.resolve(actor.uid)
        ensure = getattr(self._credentials, 'ensure_active', None)
        if ensure:
            ensure(binding)

    async def call(self, context, *, alias, arguments, expected_uid, expected_generation):
        invocation, binding = self.binding_for(context)
        require(invocation.actor.uid == expected_uid and binding.generation == expected_generation, 'stale_or_wrong_identity_tool')
        require(alias == 'lab_identity' and alias == binding.flow.alias and not alias.startswith('ap_'), 'tool_not_allowed')
        require(type(arguments) is dict and not arguments, 'invalid_tool_arguments')
        try:
            credential = await self._credentials.get_active(binding.credential_ref, binding.grant_id, binding.generation)
        except GatewayError:
            raise GatewayError('reconnect_required') from None
        except Exception:
            raise GatewayError('credential_provider_unavailable') from None
        require(type(credential) is str and credential, 'reconnect_required')
        cache_key = (binding.uid, invocation.actor.nonce, invocation.session_id, binding.subject, binding.project_id, binding.grant_id, binding.generation)
        try:
            output = await self._transport.call(resource=self._resource, headers={'Authorization': 'Bearer ' + credential},
                                                raw_name=binding.flow.raw_name, arguments={}, cache_key=cache_key)
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('upstream_unavailable') from None
        require(self._registry.resolve(binding.uid).generation == binding.generation, 'stale_binding_result')
        require(type(output) is dict and output.get('marker') == binding.flow.marker and output.get('owner') == binding.flow.owner
                and output.get('kind') == 'synthetic', 'unexpected_synthetic_result')
        return {'marker': output['marker'], 'owner': output['owner'], 'kind': 'synthetic'}
