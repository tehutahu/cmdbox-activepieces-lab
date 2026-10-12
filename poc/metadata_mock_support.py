"""Official SDK fake MCP -> actual bundled action -> fake Google pages.

No AP/Google socket or real credential. The Node runner replaces native fetch.
"""
from pathlib import Path
import json
import os
import subprocess
import httpx
from cmdbox_gateway.metadata_drive import register_review_manifest
from cmdbox_gateway.core import GatewayError, require
from drive_mock_support import CONFIG

ROOT = Path(__file__).resolve().parent.parent
manifest = json.loads((ROOT / 'templates/drive-metadata-registration.json').read_bytes())
manifest['enabled'] = True  # Only this explicit synthetic harness enables the gate.
POLICIES = register_review_manifest(manifest)


class DummyMetadataMcp:
    def __init__(self):
        self.calls, self.piece_requests = [], []
        self.override = self.after_call = None
        self.schema_extra = False

    def execute_piece(self, policy):
        node, bundle = os.environ.get('CMDBOX_LAB_NODE_PATH'), os.environ.get('CMDBOX_LAB_METADATA_BUNDLE')
        require(node and bundle and Path(bundle).resolve().is_relative_to(ROOT / 'local-review'), 'explicit_local_piece_bundle_required')
        label = 'A' if policy.uid == '101' else 'B'
        executed = subprocess.run([node, str(ROOT / 'pieces/drive-metadata-search/test/run-piece-fixture.cjs')],
            input=json.dumps({'label': label, 'bundle': bundle}), capture_output=True, text=True, encoding='utf-8',
            timeout=15, check=True, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        fixture = json.loads(executed.stdout)
        require(set(fixture) == {'result', 'requests'}, 'piece_fixture_result_invalid')
        self.piece_requests.append((policy.uid, len(fixture['requests'])))
        return fixture['result']

    def handle(self, request):
        assert request.url.host == 'mock-drive-ap.invalid' and request.url.path == '/mcp'
        policy = next((p for p in POLICIES if request.headers.get('Authorization') ==
                       'Bearer LITERAL-DUMMY-AP-' + ('A' if p.uid == '101' else 'B')), None)
        if policy is None:
            return httpx.Response(401)
        if request.method == 'GET':
            return httpx.Response(405)
        rpc = json.loads(request.content)
        if 'id' not in rpc:
            return httpx.Response(202)
        if rpc['method'] == 'initialize':
            result = {'protocolVersion': rpc['params']['protocolVersion'], 'capabilities': {'tools': {}},
                      'serverInfo': {'name': 'LITERAL-DUMMY-METADATA-PIECE', 'version': '0.92.2-contract'}}
        elif rpc['method'] == 'tools/list':
            schema = {'type': 'object', 'properties': {}, 'additionalProperties': False}
            if self.schema_extra:
                schema['properties'] = {'q': {'type': 'string'}}
            result = {'tools': [{'name': policy.raw_name, 'inputSchema': schema},
                                {'name': 'ap_management_dummy', 'inputSchema': {'type': 'object'}}]}
        elif rpc['method'] == 'tools/call':
            if rpc['params'] != {'name': policy.raw_name, 'arguments': {}}:
                raise GatewayError('metadata_dummy_call_refused')
            self.calls.append((policy.uid, policy.raw_name))
            output = self.override if self.override is not None else self.execute_piece(policy)
            if self.after_call:
                self.after_call()
            text = '\u2705 Successfully executed flow Literal metadata search\n\nOutput:\n```json\n' + json.dumps(
                {'status': 200, 'headers': {}, 'body': {'response': output}}, ensure_ascii=False) + '\n```'
            result = {'content': [{'type': 'text', 'text': text}], 'isError': False}
        else:
            raise AssertionError('No other mock MCP operation permitted')
        return httpx.Response(200, json={'jsonrpc': '2.0', 'id': rpc['id'], 'result': result})

    def async_client(self, headers=None, timeout=None, auth=None):
        assert auth is None
        return httpx.AsyncClient(transport=httpx.MockTransport(self.handle), headers=headers, timeout=timeout,
                                 trust_env=False, follow_redirects=False)
