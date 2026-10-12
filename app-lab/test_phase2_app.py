"""Native Web/password/Redis/worker/ADK plus phase2 mocked OAuth/MCP protocol."""
from pathlib import Path
from datetime import datetime, timezone
import os
import sys
import json
import asyncio
import subprocess
import time
import socket
import httpx

ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / ('phase2-native-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
assert not DATA.exists()
os.environ['CMDBOX_LAB_DATA_ROOT'] = str(DATA)
sys.path.insert(0, str(ROOT))
import environment
import test_app_path as native


def start():
    with socket.socket() as check:
        assert check.connect_ex(('127.0.0.1', 18090)) != 0, 'Do not replace an existing listener'
    log = (ROOT.parent / 'local-review' / (DATA.name + '.log')).open('x', encoding='utf-8')
    process = subprocess.Popen([sys.executable, str(ROOT / 'phase2_mock_server.py')], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=log, stderr=log, text=True, encoding='utf-8',
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    native.processes.append((process, log))
    with httpx.Client(base_url=native.BASE, trust_env=False, timeout=1) as client:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            assert process.poll() is None, 'Inspect owned phase2 mock log for bootstrap failure'
            try:
                if client.get('/lab/status').json()['workerReady']:
                    return process
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            time.sleep(0.25)
    raise RuntimeError('Phase2 native mock boot timeout')


async def exercise():
    users = []
    try:
        start()
        a, b = native.login('alice'), native.login('bob')
        users = [a, b]
        headers = {'X-Lab-Intent': 'LITERAL-DUMMY-CONNECTION'}
        for client in users:
            begun = client.post('/lab/api/connection/start', json={}, headers=headers).json()
            assert 'verifier' not in begun
            assert client.post('/lab/api/connection/callback', json={'state': begun['state'], 'code': begun['fakeCode']}, headers=headers).json()['status'] == 'ACTIVE'
        async def markers():
            for client, own, other in [(a, 'A_ONLY', 'B_ONLY'), (b, 'B_ONLY', 'A_ONLY')]:
                text, _ = await native.turn(client)
                assert own in text and other not in text
        await markers()
        native.outcomes.append({'name': 'Native password/Web/Redis/worker/actual ADK -> official MCP SDK MockTransport; A/B same-chat separation', 'status': 'pass'})
        old = a.get('/lab/api/connection').json()['generation']
        renewed = a.post('/lab/api/connection/refresh', json={'generation': old}, headers=headers).json()
        assert renewed['generation'] == old + 1
        await markers()
        native.outcomes.append({'name': 'Native connection refresh uses mocked normal token/userinfo protocol and newer generation', 'status': 'pass'})
        revoked = a.post('/lab/api/connection/revoke', json={}, headers=headers).json()
        assert revoked['status'] == 'RECONNECT_REQUIRED' and revoked['cleanupPending']
        text, _ = await native.turn(a)
        assert 'reconnect_required' in text and 'A_ONLY' not in text
        text, _ = await native.turn(b)
        assert 'B_ONLY' in text and 'A_ONLY' not in text
        native.outcomes.append({'name': 'Native revoke immediately blocks A; B continues; HTTP200 leaves formal cleanup pending', 'status': 'pass'})
    finally:
        for client in users:
            client.close()
        for process, log in native.processes:
            if process.poll() is None:
                native.stop_server(process)
            log.close()


if __name__ == '__main__':
    status = 'fail'
    try:
        asyncio.run(exercise())
        rows = [json.loads(x) for x in native.trace_file.read_text(encoding='utf-8').splitlines()[native.trace_start:]]
        assert {x['uid'] for x in rows if x['stage'] == 'phase2_mock_sdk_identity'} == {'101', '202'}
        assert all(x['blockedSocketAttempts'] == 0 and x['workerStopped'] for x in rows if x['stage'] == 'local_mock_shutdown')
        native.outcomes.append({'name': 'Native trace handoffs, zero forbidden socket attempts and clean owned-process shutdown', 'status': 'pass'})
        status = 'pass'
    finally:
        result = {'status': status, 'mode': 'PHASE2-NATIVE-MOCK-PROTOCOL', 'outcomes': native.outcomes,
                  'actualApContacted': False, 'actualCredentialOrGrantCreated': False, 'dpapiExecuted': False,
                  'allOwnedProcessesStopped': all(p.poll() is not None for p, _ in native.processes)}
        path = ROOT.parent / 'local-review' / (DATA.name + '-results.json')
        path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result))
    sys.exit(0 if status == 'pass' else 1)
