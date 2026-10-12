"""Native actual-piece metadata mock-path check; never repeats actual AP or Google tests."""
from pathlib import Path
from datetime import datetime, timezone
import os
import sys
import json
import asyncio
import subprocess
import socket
import time
ROOT = Path(__file__).resolve().parent
DATA = ROOT / 'data' / ('metadata-native-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
assert not DATA.exists()
os.environ['CMDBOX_LAB_DATA_ROOT'] = str(DATA)
sys.path.insert(0, str(ROOT))
import environment
import test_app_path as native
import httpx


def start():
    with socket.socket() as check:
        assert check.connect_ex(('127.0.0.1', 18090)) != 0, 'Do not replace an existing listener'
    log = (ROOT.parent / 'local-review' / (DATA.name + '.log')).open('x', encoding='utf-8')
    process = subprocess.Popen([sys.executable, str(ROOT / 'metadata_mock_server.py')], cwd=ROOT,
        stdin=subprocess.PIPE, stdout=log, stderr=log, text=True, encoding='utf-8',
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == 'win32' else 0)
    native.processes.append((process, log))
    with httpx.Client(base_url=native.BASE, trust_env=False, timeout=1) as client:
        deadline = time.monotonic() + 40
        while time.monotonic() < deadline:
            assert process.poll() is None, 'Inspect owned Drive mock log'
            try:
                if client.get('/lab/status').json()['workerReady']:
                    return
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            time.sleep(0.25)
    raise RuntimeError('Drive mock bootstrap timeout')


async def exercise():
    users = []
    try:
        start()
        a, b = native.login('alice'), native.login('bob')
        users = [a, b]
        headers = {'X-Lab-Intent': 'LITERAL-DUMMY-CONNECTION'}
        for client in users:
            begun = client.post('/lab/api/connection/start', json={}, headers=headers).json()
            assert client.post('/lab/api/connection/callback', json={'state': begun['state'], 'code': begun['fakeCode']}, headers=headers).json()['status'] == 'ACTIVE'
        for client, own, other in ((a, 'A_ONLY_SYNTHETIC_FILE', 'B_ONLY_SYNTHETIC_FILE'), (b, 'B_ONLY_SYNTHETIC_FILE', 'A_ONLY_SYNTHETIC_FILE')):
            text, _ = await native.turn(client)
            assert own in text and other not in text and 'drive-metadata-search-v2' in text
        native.outcomes.append({'name': 'Password/WebSocket/Redis/native worker/actual ADK/official MCP SDK -> actual bundled action -> fake Google pages; same-chat A/B separated', 'status': 'pass'})
        old = a.get('/lab/api/connection').json()['generation']
        assert a.post('/lab/api/connection/refresh', json={'generation': old}, headers=headers).json()['generation'] == old + 1
        text, _ = await native.turn(a)
        assert 'A_ONLY_SYNTHETIC_FILE' in text and 'B_ONLY_SYNTHETIC_FILE' not in text
        native.outcomes.append({'name': 'New search uses refreshed dummy binding generation', 'status': 'pass'})
        assert a.post('/lab/api/connection/revoke', json={}, headers=headers).json()['status'] == 'RECONNECT_REQUIRED'
        text, _ = await native.turn(a)
        assert 'reconnect_required' in text and 'A_ONLY_SYNTHETIC_FILE' not in text
        text, _ = await native.turn(b)
        assert 'B_ONLY_SYNTHETIC_FILE' in text and 'A_ONLY_SYNTHETIC_FILE' not in text
        native.outcomes.append({'name': 'Dummy revoke blocks A search before I/O; B remains separated', 'status': 'pass'})
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
        calls = [x for x in rows if x['stage'] == 'metadata_mock_sdk_search']
        assert len(calls) == 4 and {x['uid'] for x in calls} == {'101', '202'}
        assert sum(x['pagesRead'] for x in calls) == 6
        assert all(x['complete'] == (x['uid'] == '101') for x in calls)
        assert all(x['stopReason'] == ('complete' if x['uid'] == '101' else 'incomplete_search') for x in calls)
        assert all(x['tools'] == ['lab_drive_metadata_search'] for x in rows if x['stage'] == 'drive_mock_declared_tools')
        assert all(x['blockedSocketAttempts'] == 0 and x['workerStopped'] for x in rows if x['stage'] == 'local_mock_shutdown')
        native.outcomes.append({'name': 'New MCP calls/alias/generation trace and clean owned shutdown; zero forbidden socket attempts', 'status': 'pass'})
        status = 'pass'
    finally:
        result = {'status': status, 'mode': 'METADATA-PIECE-NATIVE-MOCK', 'outcomes': native.outcomes,
                  'actualApContacted': False, 'googleContacted': False, 'actualCredentialOrGrantCreated': False,
                  'stockDrivePieceExecuted': False, 'actualLocalPieceActionExecuted': status == 'pass',
                  'archiveInstalledIntoAp': False, 'externalLlmContacted': False, 'productionConfigChanged': False,
                  'allOwnedProcessesStopped': all(p.poll() is not None for p, _ in native.processes)}
        path = ROOT.parent / 'local-review' / (DATA.name + '-results.json')
        path.write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result))
    sys.exit(0 if status == 'pass' else 1)
