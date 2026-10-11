"""Explicit LOCAL MOCK bootstrap. No private/ reads and no actual AP/provider tokens."""
import os
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent
RUNTIME_ROOT = Path(os.environ.get('CMDBOX_LAB_RUNTIME_ROOT', ROOT.parent / 'runtimes')).resolve()
APP_DEPS = RUNTIME_ROOT / 'app-deps'
sys.path[:0] = [str(APP_DEPS), str(ROOT / 'cmdbox-public'), str(ROOT.parent / 'poc')]
os.environ['DATA_DIR'] = str(ROOT / 'data')
os.environ['REDIS_HOST'] = '127.0.0.1'
os.environ['REDIS_PORT'] = '18091'
os.environ['REDIS_PASSWORD'] = ''
os.environ['SVNAME'] = 'cmdboxlab'
os.environ['OTEL_SDK_DISABLED'] = 'true'
os.environ['GOOGLE_API_USE_CLIENT_CERTIFICATE'] = 'false'
os.environ['LITELLM_LOCAL_MODEL_COST_MAP'] = 'true'
os.environ['HF_HUB_OFFLINE'] = '1'
os.environ['CUSTOM_TIKTOKEN_CACHE_DIR'] = str(ROOT / 'tokenizer-cache')
os.environ['NO_PROXY'] = '127.0.0.1,localhost,::1'
for name in ('GOOGLE_API_KEY','GEMINI_API_KEY','OPENAI_API_KEY','GOOGLE_APPLICATION_CREDENTIALS'):
    os.environ.pop(name, None)

def install_socket_policy():
    """Only this lab's Web/Redis and Windows asyncio self-pipe; AP18088 is excluded."""
    import socket
    import traceback
    original, original_ex = socket.socket.connect, socket.socket.connect_ex
    blocked = []
    def authorized(address):
        if not isinstance(address, tuple): return False
        if address[0] not in ('127.0.0.1','localhost','::1'): return False
        if address[1] in (18090,18091): return True
        # Python implements socketpair over ephemeral loopback on Windows.
        return any(x.name == 'socketpair' and Path(x.filename).resolve() == Path(socket.__file__).resolve()
                   for x in traceback.extract_stack())
    def guard(self, address):
        if not authorized(address):
            blocked.append('disallowed-socket')
            raise RuntimeError('This cmdbox lab permits only its own Web and Redis sockets')
        return original(self, address)
    def guard_ex(self, address):
        if not authorized(address):
            blocked.append('disallowed-socket')
            raise RuntimeError('This cmdbox lab permits only its own Web and Redis sockets')
        return original_ex(self, address)
    socket.socket.connect, socket.socket.connect_ex = guard, guard_ex
    return blocked
