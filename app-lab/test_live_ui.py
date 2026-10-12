"""Real native local entry/callback/session/Redis/ADK app; all AP I/O is mocked."""
from pathlib import Path
from datetime import datetime, timezone
import asyncio
import httpx
import json
import os
import re
import socket
import subprocess
import sys
import time
from urllib.parse import parse_qs, urlsplit
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtimes/app-deps'), str(ROOT / 'poc')]
from websockets.asyncio.client import connect


async def turn(client):
    cookie = '; '.join(k + '=' + v for k, v in client.cookies.items())
    result = []
    async with connect('ws://localhost:18090/lab/chat/ws/adapter_lab/same-chat', additional_headers={'Cookie': cookie}, open_timeout=20) as ws:
        assert 'success' in json.loads(await asyncio.wait_for(ws.recv(), 20))
        await ws.send('call_tts_off')
        await ws.send('IDENTITY')
        for _ in range(20):
            value = json.loads(await asyncio.wait_for(ws.recv(), 30))
            result.append(value)
            if value.get('end'):
                break
        else:
            raise AssertionError('Native streaming did not finish')
    return json.dumps(result)


def main():
    data = ROOT / 'app-lab/data' / ('phase2-live-ui-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))
    assert not data.exists()
    for port in (18089, 18090):
        with socket.socket() as check:
            assert check.connect_ex(('127.0.0.1', port)) != 0, 'Do not replace an existing listener'
    log = (ROOT / 'local-review' / (data.name + '.log')).open('x', encoding='utf-8')
    process = subprocess.Popen([sys.executable, str(ROOT / 'app-lab/live_launcher.py'), '--mock-root', str(data)],
                              cwd=ROOT, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
    outcomes = []
    status = 'fail'
    clients = []
    try:
        for _ in range(160):
            assert process.poll() is None, 'Inspect owned mock bootstrap log'
            try:
                response = httpx.get('http://localhost:18089/status', trust_env=False, timeout=1)
                if response.json()['ready']:
                    break
            except (httpx.HTTPError, ValueError, KeyError):
                pass
            time.sleep(0.25)
        else:
            raise AssertionError('Mock UI boot timeout')
        ready = response.json()
        assert ready['pendingStateCount'] == 0 and ready['authorizationStartedAt'] is None
        assert all(x['generation'] == 0 for x in ready['connections'].values())
        outcomes.append({'name': 'Dual localhost Web/callback status ready; no OAuth state or clock before human entry', 'status': 'pass'})
        for label, uid in [('A', '101'), ('B', '202')]:
            client = httpx.Client(base_url='http://localhost:18090', follow_redirects=False, trust_env=False, timeout=30)
            clients.append(client)
            assert client.get('/connect/' + label).status_code == 409
            assert client.post('/dosignin/connect', data={'name': 'alice' if label == 'A' else 'bob', 'password': 'LITERAL_DUMMY_PASSWORD'}).headers['signin'] == 'success'
            token = client.get('/connection').json()['csrf']
            handoff = client.post('/handoff/' + label, json={'csrf': token}, headers={'Origin': 'http://localhost:18090'}).json()['url']
            assert client.get(handoff).status_code == 303
            assert client.get(handoff).status_code == 409
            entry = client.get('/connect/' + label)
            proof = re.search(r'name="csrf" value="([a-f0-9]+)"', entry.text)[1]
            assert client.get('/status').json()['pendingStateCount'] == 0
            rejected = client.post('/connect/' + label, data={'csrf': proof})
            assert rejected.status_code == 409
            begun = client.post('/connect/' + label, data={'csrf': proof}, headers={'Origin': 'http://localhost:18090'})
            assert begun.status_code == 303 and urlsplit(begun.headers['location']).hostname == 'mock-ap.invalid'
            query = parse_qs(urlsplit(begun.headers['location']).query)
            assert query['scope'] == ['mcp'] and query['code_challenge_method'] == ['S256']
            state = query['state'][0]
            # Simulated provider code only. No real browser/Authorize operation.
            callback = client.get('http://localhost:18089/oauth/callback', params={'state': state, 'code': 'LITERAL:' + uid + ':' + state})
            assert callback.status_code == 200, callback.text
        outcomes.append({'name': 'Same-origin CSRF, native password login, cookie across ports, fresh S256 state, mocked callback A/B binding', 'status': 'pass'})
        a, b = clients
        for client, marker, other in [(a, 'A_ONLY', 'B_ONLY'), (b, 'B_ONLY', 'A_ONLY')]:
            text = asyncio.run(turn(client))
            assert marker in text and other not in text, text
        outcomes.append({'name': 'New live-shaped bootstrap native Web -> Redis -> worker -> actual ADK -> mocked official MCP SDK', 'status': 'pass'})
        connection = a.get('/connection').json()
        refreshed = a.post('/connection/refresh', json={'csrf': connection['csrf'], 'generation': connection['generation']}, headers={'Origin': 'http://localhost:18090'})
        assert refreshed.status_code == 200 and refreshed.json()['generation'] == 2
        text = asyncio.run(turn(a))
        assert 'A_ONLY' in text and 'B_ONLY' not in text
        text = asyncio.run(turn(a))
        assert 'approved_operation_budget_exhausted' in text and 'A_ONLY' not in text
        connection = a.get('/connection').json()
        revoked = a.post('/connection/revoke', json={'csrf': connection['csrf']}, headers={'Origin': 'http://localhost:18090'})
        assert revoked.status_code == 200 and revoked.json()['cleanupPending'] and revoked.json()['status'] == 'RECONNECT_REQUIRED'
        outcomes.append({'name': 'One-refresh/two-flow budget, generation refresh and revoke with formal cleanup pending', 'status': 'pass'})
        status = 'pass'
    finally:
        for client in clients:
            client.close()
        if process.poll() is None:
            (data / 'stop-request').write_text('MOCK-ONLY-STOP', encoding='utf-8')
            try:
                process.wait(20)
            except subprocess.TimeoutExpired:
                process.terminate()
                process.wait(5)
        log.close()
        result = {'status': status, 'mode': 'PHASE2-NATIVE-LIVE-UI-MOCK', 'outcomes': outcomes,
                  'actualApContacted': False, 'actualCredentialOrGrantCreated': False, 'dpapiExecuted': False,
                  'allOwnedProcessesStopped': process.poll() is not None}
        (ROOT / 'local-review' / (data.name + '-results.json')).write_text(json.dumps(result, indent=2) + '\n', encoding='utf-8')
        print(json.dumps(result))
    return 0 if status == 'pass' else 1


if __name__ == '__main__':
    sys.exit(main())
