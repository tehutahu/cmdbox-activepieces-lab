"""Literal mock protocol provider; never use this backend or sealer with credentials."""
import base64
import hashlib
import json
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs
import httpx
from cmdbox_gateway.fixtures import FLOW_A, FLOW_B
from cmdbox_gateway.oauth_live import OAuthConfig, OAuthHttpClient
from cmdbox_gateway.vault_live import EncryptedStore
from cmdbox_gateway.lifecycle_live import LiveBindings, LiveLifecycle, Target


class LiteralEntropy:
    def __init__(self, label='LITERAL-MOCK-ENTROPY'):
        self.label = 'LITERAL-MOCK-ENTROPY-' + label
        self.n = 0
        self.lock = threading.Lock()

    def __call__(self, size):
        with self.lock:
            self.n += 1
            label = (self.label + '-' + str(self.n)).encode()
        return (hashlib.sha256(label).digest() + hashlib.sha256(label + b'-2').digest())[:size]


class LiteralSealer:
    """Purpose-bound base64 fixture, NOT encryption or a DPAPI security test."""
    def seal(self, value, purpose):
        return b'LITERAL_MOCK_NOT_ENCRYPTED:' + hashlib.sha256(purpose).hexdigest().encode() + b':' + base64.b64encode(value)

    def open(self, value, purpose):
        marker, digest, data = value.split(b':', 2)
        assert marker == b'LITERAL_MOCK_NOT_ENCRYPTED' and digest == hashlib.sha256(purpose).hexdigest().encode()
        return base64.b64decode(data)


class MockAP:
    def __init__(self, *, clock=time.time):
        self.clock = clock
        self.codes, self.refreshes, self.accepted_access = {}, {}, {}
        self.methods, self.raw_calls = [], []
        self.lock, self.n = threading.Lock(), 0
        self.fault = None
        self.refresh_entered = threading.Event()
        self.refresh_release = None
        self.revoke_failure = False

    def register(self, uid, started):
        code = 'LITERAL-DUMMY-CODE-' + uid + '-' + started['state'][:12]
        self.codes[code] = (uid, started['challenge'])
        return code

    def token(self, uid, grant):
        now = int(self.clock())
        encode = lambda x: base64.urlsafe_b64encode(json.dumps(x, separators=(',', ':')).encode()).decode().rstrip('=')
        claims = {'sub': 'DUMMY-AP-SUBJECT-' + ('A' if uid == '101' else 'B'),
                  'projectId': 'DUMMY-PROJECT-' + ('A' if uid == '101' else 'B'),
                  'grantId': grant, 'clientId': 'LITERAL-DUMMY-CLIENT', 'scopes': ['mcp'],
                  'type': 'mcp_oauth', 'aud': 'MCP_OAUTH_ACCESS', 'iat': now, 'exp': now + 900}
        if self.fault == 'project':
            claims['projectId'] = 'DUMMY-PROJECT-OTHER'
        if self.fault == 'client':
            claims['clientId'] = 'LITERAL-DUMMY-OTHER-CLIENT'
        access = encode({'alg': 'HS256', 'typ': 'JWT'}) + '.' + encode(claims) + '.LITERAL_DUMMY_NOT_A_SIGNATURE'
        self.accepted_access[access] = (uid, grant, claims)
        return access

    def handle(self, request):
        self.methods.append((request.method, request.url.path))
        assert request.url.host == 'mock-ap.invalid', 'Mock protocol only'
        path = request.url.path
        issuer = 'https://mock-ap.invalid'
        if path == '/.well-known/oauth-authorization-server':
            meta = {'issuer': issuer, 'authorization_endpoint': issuer + '/authorize', 'token_endpoint': issuer + '/token',
                    'userinfo_endpoint': issuer + '/userinfo', 'revocation_endpoint': issuer + '/revoke',
                    'response_types_supported': ['code'], 'grant_types_supported': ['authorization_code', 'refresh_token'],
                    'code_challenge_methods_supported': ['S256'], 'token_endpoint_auth_methods_supported': ['none'],
                    'scopes_supported': ['mcp', 'openid', 'email', 'profile']}
            if self.fault == 'metadata':
                meta['token_endpoint'] = 'https://other.invalid/token'
            return httpx.Response(200, json=meta)
        if path == '/.well-known/oauth-protected-resource/mcp':
            return httpx.Response(200, json={'resource': issuer + '/mcp', 'authorization_servers': [issuer], 'scopes_supported': ['mcp']})
        if path == '/token':
            body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            assert body['client_id'] == 'LITERAL-DUMMY-CLIENT' and body['resource'] == issuer + '/mcp'
            assert 'client_secret' not in body and not request.headers.get('authorization')
            if body['grant_type'] == 'authorization_code':
                if body['code'] not in self.codes:
                    return httpx.Response(400, json={'error': 'invalid_grant', 'description': 'LITERAL-MOCK-ERROR-BODY'})
                uid, expected = self.codes.pop(body['code'])
                challenge = base64.urlsafe_b64encode(hashlib.sha256(body['code_verifier'].encode()).digest()).decode().rstrip('=')
                if challenge != expected:
                    return httpx.Response(400, json={'error': 'invalid_grant'})
                with self.lock:
                    self.n += 1
                    grant = 'DUMMY-GRANT-' + uid + '-' + str(self.n)
                refresh = 'LITERAL-DUMMY-REFRESH-' + grant
                self.refreshes[refresh] = (uid, grant, False)
            else:
                self.refresh_entered.set()
                if self.refresh_release is not None:
                    assert self.refresh_release.wait(5), 'Mock refresh release timeout'
                refresh = body['refresh_token']
                if self.fault == 'refresh' or refresh not in self.refreshes or self.refreshes[refresh][2]:
                    return httpx.Response(400, json={'error': 'invalid_grant'})
                uid, grant, _ = self.refreshes[refresh]
                if self.fault == 'grant':
                    grant += '-OTHER'
            value = {'access_token': self.token(uid, grant), 'refresh_token': refresh, 'token_type': 'Bearer', 'expires_in': 900}
            if self.fault == 'scope':
                value['scope'] = 'mcp profile'
            if self.fault == 'redirect':
                return httpx.Response(307, headers={'Location': 'https://other.invalid/token'})
            return httpx.Response(200, json=value)
        if path == '/userinfo':
            access = request.headers.get('Authorization', '').removeprefix('Bearer ')
            if access not in self.accepted_access or self.fault == 'userinfo':
                return httpx.Response(401, json={'error': 'invalid_token'})
            uid, grant, claims = self.accepted_access[access]
            if any(g == grant and revoked for _, g, revoked in self.refreshes.values()):
                return httpx.Response(401, json={'error': 'invalid_token'})
            return httpx.Response(200, json={'sub': claims['sub']})
        if path == '/revoke':
            if self.revoke_failure:
                return httpx.Response(503, json={'error': 'LITERAL-MOCK-REVOKE-FAILURE'})
            body = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            assert body['client_id'] == 'LITERAL-DUMMY-CLIENT' and body['token_type_hint'] == 'refresh_token'
            if body['token'] in self.refreshes:
                uid, grant, _ = self.refreshes[body['token']]
                self.refreshes[body['token']] = (uid, grant, True)
            return httpx.Response(200, json={})
        if path == '/mcp':
            access = request.headers.get('Authorization', '').removeprefix('Bearer ')
            if access not in self.accepted_access:
                return httpx.Response(401)
            uid, grant, _ = self.accepted_access[access]
            if any(g == grant and revoked for _, g, revoked in self.refreshes.values()):
                return httpx.Response(401)
            if request.method == 'GET':
                return httpx.Response(405)
            rpc = json.loads(request.content)
            method = rpc['method']
            if 'id' not in rpc:
                return httpx.Response(202)
            if method == 'initialize':
                result = {'protocolVersion': rpc['params']['protocolVersion'], 'capabilities': {'tools': {}},
                          'serverInfo': {'name': 'LITERAL-MOCK-AP', 'version': '0.92.2-contract'}}
            elif method == 'tools/list':
                flow = FLOW_A if uid == '101' else FLOW_B
                result = {'tools': [{'name': flow.raw_name, 'description': 'Literal identity', 'inputSchema': {'type': 'object', 'properties': {}}},
                                    {'name': 'ap_management_dummy', 'inputSchema': {'type': 'object'}}]}
            elif method == 'tools/call':
                flow = FLOW_A if uid == '101' else FLOW_B
                assert rpc['params'] == {'name': flow.raw_name, 'arguments': {}}
                self.raw_calls.append((uid, flow.raw_name))
                envelope = {'status': 200, 'body': {'response': {'marker': flow.marker, 'owner': flow.owner, 'kind': 'synthetic'}}, 'headers': {'ignored': 'not-exposed'}}
                text = '✅ Successfully executed flow Literal identity\n\nOutput:\n```json\n' + json.dumps(envelope, indent=2) + '\n```'
                result = {'content': [{'type': 'text', 'text': text}], 'isError': False}
            else:
                raise AssertionError('Unexpected mocked MCP operation')
            return httpx.Response(200, json={'jsonrpc': '2.0', 'id': rpc['id'], 'result': result})
        raise AssertionError('No mock route for request')

    def async_client(self, headers=None, timeout=None, auth=None):
        assert auth is None
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), headers=headers, timeout=timeout,
                                 trust_env=False, follow_redirects=False)


def fixture(root, *, clock=time.time):
    root = Path(root)
    root.mkdir(parents=True, exist_ok=False)
    mock = MockAP(clock=clock)
    config = OAuthConfig('https://mock-ap.invalid', 'LITERAL-DUMMY-CLIENT', 'Literal mock public client',
                         'http://localhost:18089/oauth/callback', 'https://mock-ap.invalid/mcp')
    client = httpx.Client(transport=httpx.MockTransport(mock.handle), trust_env=False, follow_redirects=False, timeout=5)
    provider = OAuthHttpClient(config, client, clock=clock)
    provider.discover()
    store = EncryptedStore(root, LiteralSealer())
    targets = [Target('101', 'DUMMY-AP-SUBJECT-A', 'DUMMY-PROJECT-A', FLOW_A),
               Target('202', 'DUMMY-AP-SUBJECT-B', 'DUMMY-PROJECT-B', FLOW_B)]
    registry = LiveBindings(store, targets)
    life = LiveLifecycle(registry, provider, LiteralEntropy(), clock=clock)
    return mock, config, client, registry, life


def connect(mock, life, uid='101', session='LITERAL_DUMMY_WEBSESSION_PHASE2_A'):
    started = life.start(uid, session)
    code = mock.register(uid, started)
    return life.complete(uid, session, started['state'], code)
