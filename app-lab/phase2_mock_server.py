"""Native application harness for phase2; ALL OAuth/MCP I/O is MockTransport.

Original phase1 server is reused without source edits. No DPAPI, actual endpoint,
credentials, session entropy or ACL operation is permitted in this harness.
"""
from pathlib import Path
import os
import sys
import threading
import socket
import traceback
sys.path.insert(0, str(Path(__file__).resolve().parent))
os.environ['CMDBOX_LAB_FAKE_LIFECYCLE'] = '1'
import environment
import server
from mock_live_support import fixture
from cmdbox_gateway.core import AuthorizedFlowBroker
from cmdbox_gateway.mcp_live import PinnedMcpTransport
from cmdbox_gateway.fixtures import FLOW_A, FLOW_B
import uvicorn

def phase2_socket_policy():
    # Embedded Python's stdlib frames use archive-relative co_filename values.
    # Match the actual stdlib function object, not a guessed filesystem path.
    original, original_ex = socket.socket.connect, socket.socket.connect_ex
    pair = getattr(socket, '_fallback_socketpair', socket.socketpair)
    frame = (pair.__name__, pair.__code__.co_filename)
    blocked = []
    def allowed(address):
        if not isinstance(address, tuple) or address[0] not in ('127.0.0.1', 'localhost', '::1'):
            return False
        return address[1] in (18090, 18091, 18092) or any((f.name, f.filename) == frame for f in traceback.extract_stack())
    def guard(self, address):
        if not allowed(address):
            blocked.append('disallowed-socket')
            raise RuntimeError('Mock-only socket policy')
        return original(self, address)
    def guard_ex(self, address):
        if not allowed(address):
            blocked.append('disallowed-socket')
            raise RuntimeError('Mock-only socket policy')
        return original_ex(self, address)
    socket.socket.connect, socket.socket.connect_ex = guard, guard_ex
    return blocked

server.environment.install_socket_policy = phase2_socket_policy

mock, config, client, registry, lifecycle = fixture(environment.DATA / 'phase2-literal-vault')

class MockOnlyUi:
    def start(self, uid, session):
        started = lifecycle.start(uid, session)
        started['fakeCode'] = mock.register(uid, started)
        return started

    def __getattr__(self, name):
        return getattr(lifecycle, name)

class TracedMockProtocol(PinnedMcpTransport):
    async def call(self, **kwargs):
        result = await super().call(**kwargs)
        server.trace('phase2_mock_sdk_identity', uid=kwargs['cache_key'][0], marker=result['marker'])
        return result

server.registry = registry
server.lifecycle = MockOnlyUi()
server.broker = AuthorizedFlowBroker(registry, lifecycle,
    TracedMockProtocol(config, [FLOW_A, FLOW_B], mock.async_client), resource=config.resource)

if __name__ == '__main__':
    http = uvicorn.Server(uvicorn.Config(server.app, host='127.0.0.1', port=server.PORT,
                                       ws='wsproto', log_level='warning', access_log=False))
    def control():
        for line in sys.stdin:
            if line.strip() == 'STOP':
                http.should_exit = True
                return
    threading.Thread(target=control, daemon=True).start()
    try:
        http.run()
    finally:
        client.close()
