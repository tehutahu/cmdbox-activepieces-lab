"""Synthetic MCP reply fixture. No Google client, account or actual AP connection."""
import json
import httpx
from cmdbox_gateway.drive_search import DriveSearchPolicy, CONTRACT, COMPLETION
from cmdbox_gateway.core import GatewayError
from cmdbox_gateway.oauth_live import OAuthConfig

POLICIES = tuple(DriveSearchPolicy(uid, 'DUMMY-AP-SUBJECT-' + label, 'DUMMY-PROJECT-' + label,
                                  'lab_drive_search_' + label.lower() + '_dummy_mcp', 'DUMMY-DRIVE-POLICY-' + label)
                 for uid, label in (('101', 'A'), ('202', 'B')))
CONFIG = OAuthConfig('https://mock-drive-ap.invalid', 'LITERAL-DUMMY-CLIENT', 'Literal Drive mock',
                     'http://localhost:18089/oauth/callback', 'https://mock-drive-ap.invalid/mcp')


def result_for(policy):
    label = 'A' if policy.uid == '101' else 'B'
    return {'contract': CONTRACT, 'policyId': policy.policy_id, 'completion': COMPLETION,
            'files': [{'id': label + '_ONLY_SYNTHETIC_FILE', 'name': 'CMDBOX_LAB_ONLY_' + label + '.txt',
                       'mimeType': 'text/plain', 'modifiedTime': '2026-01-01T00:00:00Z'}]}


class DummyDriveMcp:
    def __init__(self):
        self.calls = []
        self.override = None
        self.after_call = None

    def handle(self, request):
        assert request.url.host == 'mock-drive-ap.invalid' and request.url.path == '/mcp'
        bearer = request.headers.get('Authorization')
        policy = next((p for p in POLICIES if bearer == 'Bearer LITERAL-DUMMY-AP-' + ('A' if p.uid == '101' else 'B')), None)
        if policy is None:
            return httpx.Response(401)
        if request.method == 'GET':
            return httpx.Response(405)
        rpc = json.loads(request.content)
        if 'id' not in rpc:
            return httpx.Response(202)
        method = rpc['method']
        if method == 'initialize':
            result = {'protocolVersion': rpc['params']['protocolVersion'], 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'LITERAL-DUMMY-DRIVE-FLOW', 'version': '0.92.2-contract'}}
        elif method == 'tools/list':
            result = {'tools': [{'name': policy.raw_name, 'inputSchema': {'type': 'object', 'properties': {}}},
                                {'name': 'ap_management_dummy', 'inputSchema': {'type': 'object'}}]}
        elif method == 'tools/call':
            if rpc['params'] != {'name': policy.raw_name, 'arguments': {}}:
                raise GatewayError('dummy_drive_call_refused')
            self.calls.append((policy.uid, policy.raw_name))
            body = self.override if self.override is not None else result_for(policy)
            if self.after_call:
                self.after_call()
            text = '\u2705 Successfully executed flow Literal Drive search\n\nOutput:\n```json\n' + json.dumps(
                {'status': 200, 'headers': {}, 'body': {'response': body}}) + '\n```'
            result = {'content': [{'type': 'text', 'text': text}], 'isError': False}
        else:
            raise AssertionError('No other mock MCP operation is permitted')
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': rpc['id'], 'result': result})

    def async_client(self, headers=None, timeout=None, auth=None):
        assert auth is None
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), headers=headers, timeout=timeout,
                                 trust_env=False, follow_redirects=False)
