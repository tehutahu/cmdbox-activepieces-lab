"""New Drive preparation through native cmdbox; all MCP replies are synthetic.

Toolset/model injection is confined to this harness. No production config, prior
phase2 module, actual AP, Google credential or OAuth lifecycle is changed.
"""
from pathlib import Path
import os
import sys
import socket
import threading
import traceback
import json
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ['CMDBOX_LAB_FAKE_LIFECYCLE'] = '1'
import environment
import server
from cmdbox_gateway import integration
from cmdbox_gateway.drive_search import PreparedDriveBroker, ALIAS
from cmdbox_gateway.drive_adk import PreparedDriveToolset
from cmdbox_gateway.mcp_live import PinnedMcpTransport
from drive_mock_support import DummyDriveMcp, CONFIG, POLICIES
from google.adk.models.llm_response import LlmResponse
from google.genai import types
import uvicorn


def mock_socket_policy():
    original, original_ex = socket.socket.connect, socket.socket.connect_ex
    pair = getattr(socket, '_fallback_socketpair', socket.socketpair)
    frame = (pair.__name__, pair.__code__.co_filename)
    blocked = []
    def allowed(address):
        return isinstance(address, tuple) and address[0] in ('127.0.0.1', 'localhost', '::1') and (
            address[1] in (18090, 18091, 18092) or any((f.name, f.filename) == frame for f in traceback.extract_stack()))
    def guard(self, address):
        if not allowed(address):
            blocked.append('disallowed-socket')
            raise RuntimeError('Drive mock-only socket policy')
        return original(self, address)
    def guard_ex(self, address):
        if not allowed(address):
            blocked.append('disallowed-socket')
            raise RuntimeError('Drive mock-only socket policy')
        return original_ex(self, address)
    socket.socket.connect, socket.socket.connect_ex = guard, guard_ex
    return blocked


class TracedDriveMcp(PinnedMcpTransport):
    async def call(self, **kwargs):
        result = await super().call(**kwargs)
        key = kwargs['cache_key']
        server.trace('drive_mock_sdk_search', uid=key[0], session_id=key[2], generation=key[6])
        return result


class DriveScriptedLlm(server.LocalScriptedLlm):
    async def generate_content_async(self, llm_request, stream=False):
        responses = [p.function_response for p in llm_request.contents[-1].parts or [] if p.function_response]
        if responses:
            content = types.Content(role='model', parts=[types.Part(text=json.dumps({'message': json.dumps(responses[-1].response)}))])
        else:
            names = list(llm_request.tools_dict)
            if names != [ALIAS]:
                raise RuntimeError('Only the prepared fixed search alias may be declared')
            server.trace('drive_mock_declared_tools', tools=names)
            content = types.Content(role='model', parts=[types.Part(function_call=types.FunctionCall(name=ALIAS, args={}))])
        yield LlmResponse(content=content, usage_metadata=types.GenerateContentResponseUsageMetadata(
            prompt_token_count=0, candidates_token_count=0, total_token_count=0))


mock = DummyDriveMcp()
server.environment.install_socket_policy = mock_socket_policy
server.broker = PreparedDriveBroker(server.registry, server.lifecycle,
    TracedDriveMcp(CONFIG, POLICIES, mock.async_client), POLICIES, resource=CONFIG.resource)
server.LocalScriptedLlm = DriveScriptedLlm
# The existing UID config remains identity-only. This explicit test factory
# injection exercises the patched native ADK hook; it is not a live activation.
integration.approved_ap_toolset = lambda: PreparedDriveToolset(server.broker)


if __name__ == '__main__':
    http = uvicorn.Server(uvicorn.Config(server.app, host='127.0.0.1', port=server.PORT,
                                       ws='wsproto', log_level='warning', access_log=False))
    def control():
        for line in sys.stdin:
            if line.strip() == 'STOP':
                http.should_exit = True
                return
    threading.Thread(target=control, daemon=True).start()
    http.run()
