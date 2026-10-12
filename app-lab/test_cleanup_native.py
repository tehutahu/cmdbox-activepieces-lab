"""Native Web/Redis/ADK + mock AP UI operator, deadline and quarantine closure."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtimes/app-deps'), str(ROOT / 'poc'), str(ROOT / 'app-lab')]
from datetime import datetime, timezone
import asyncio
import builtins
import io
import json
import socket
import subprocess
import time
import httpx
import cleanup_operator as console
from test_live_ui import turn
from cmdbox_gateway.core import FlowPolicy, GatewayError
from cmdbox_gateway.cleanup_live import CleanupOperator
from cmdbox_gateway.lifecycle_live import LiveBindings, Target
from cmdbox_gateway.oauth_live import OAuthConfig
from cmdbox_gateway.vault_live import EncryptedStore
from mock_live_support import LiteralSealer

outcomes, processes = [], []


def operator(root):
    sealer = LiteralSealer()
    file = root / ('cleanup-settings.dpapi' if (root / 'cleanup-settings.dpapi').exists() else 'settings.dpapi')
    cfg = json.loads(sealer.open(file.read_bytes(), b'approved-settings-v1'))
    registry = LiveBindings(EncryptedStore(root / 'literal-vault', sealer),
        [Target(t['uid'], t['subject'], t['project'], FlowPolicy(**t['flow'])) for t in cfg['targets']])
    clock_file = root / 'mock-clock.json'
    return CleanupOperator(registry, OAuthConfig(**cfg['oauth']),
                           clock=lambda: json.loads(clock_file.read_text())['now'])


def ui_page(root, spec):
    ledger = json.loads((root / 'mock-grant-ledger.json').read_text())
    data = [{k: v for k, v in r.items() if k != 'revoked'} for r in ledger
            if not r['revoked'] and r['member']['id'] == spec.subject]
    return {'data': data, 'next': None, 'previous': None}


def manual_ui_revoke(root, grant):
    file = root / 'mock-grant-ledger.json'
    ledger = json.loads(file.read_text())
    matches = [r for r in ledger if r['id'] == grant]
    assert len(matches) == 1
    matches[0]['revoked'] = True
    file.write_text(json.dumps(ledger), encoding='utf-8')


class OwnerConsole(io.StringIO):
    def isatty(self):
        return True


def witness(root, label, *, revoke_ok=True):
    op = operator(root)
    uid = {'A': '101', 'B': '202'}[label]
    spec = op.spec(uid, op.rows(uid)[0])
    # Same production console code, simulated OS-owner input/context only. The
    # real CLI has no mock/context argument and enforces CurrentUser ACL+DPAPI.
    before = ui_page(root, spec)
    active = any(r['id'] == spec.grant for r in before['data'])
    values = [spec.issuer + '/api/v1/users/' + spec.subject, json.dumps({'id': spec.subject}), 'END',
              'yes' if active else 'no']
    url = spec.issuer + '/api/v1/mcp-oauth/grants?limit=10'
    if active:
        values += [url, json.dumps(before), 'END', 'REVOKED']
        if revoke_ok:
            manual_ui_revoke(root, spec.grant)
    values += [url, json.dumps(ui_page(root, spec)), 'END', 'AP-UI ' + spec.subject]
    original_input, original_context = builtins.input, console.context
    original_in, original_out = sys.stdin, sys.stdout
    iterator, captured = iter(values), OwnerConsole()
    try:
        builtins.input = lambda *args: next(iterator)
        console.context = lambda ignored: op
        sys.stdin, sys.stdout = OwnerConsole(), captured
        console.main(root, label)
        assert 'FORMAL-UI-CONFIRMED' in captured.getvalue()
    finally:
        builtins.input, console.context = original_input, original_context
        sys.stdin, sys.stdout = original_in, original_out
    return op


def start(root, failure):
    for port in (18089, 18090):
        with socket.socket() as sock:
            assert sock.connect_ex(('127.0.0.1', port)) != 0, 'Do not replace a listener'
    log = (ROOT / 'local-review' / (root.name + '.log')).open('x', encoding='utf-8')
    command = [sys.executable, str(ROOT / 'app-lab/live_launcher.py'), '--mock-root', str(root), '--mock-test-clock']
    if failure:
        command += ['--mock-revoke-failure']
    proc = subprocess.Popen(command, cwd=ROOT, stdout=log, stderr=log, creationflags=subprocess.CREATE_NO_WINDOW)
    processes.append((proc, log))
    for _ in range(160):
        assert proc.poll() is None, 'Inspect owned mock boot log'
        try:
            if httpx.get('http://localhost:18090/status', trust_env=False, timeout=1).json()['ready']:
                return proc
        except (httpx.HTTPError, ValueError, KeyError):
            pass
        time.sleep(.25)
    raise AssertionError('Owned mock runtime not ready')


def authorize(label, uid, *, expect_status=200):
    from urllib.parse import parse_qs, urlsplit
    import re
    client = httpx.Client(base_url='http://localhost:18090', trust_env=False, follow_redirects=False, timeout=30)
    assert client.post('/dosignin/connect', data={'name': 'alice' if label == 'A' else 'bob',
                                                'password': 'LITERAL_DUMMY_PASSWORD'}).headers['signin'] == 'success'
    page = client.get('/connect/' + label).text
    csrf = re.search(r'name="csrf" value="([a-f0-9]+)"', page)[1]
    begun = client.post('/connect/' + label, data={'csrf': csrf}, headers={'Origin': 'http://localhost:18090'})
    state = parse_qs(urlsplit(begun.headers['location']).query)['state'][0]
    assert client.get('http://localhost:18089/oauth/callback', params={'state': state,
           'code': 'LITERAL:' + uid + ':' + state}).status_code == expect_status
    return client


def operation(client, name):
    status = client.get('/connection').json()
    body = {'csrf': status['csrf']}
    if name == 'refresh':
        body['generation'] = status['generation']
    response = client.post('/connection/' + name, json=body, headers={'Origin': 'http://localhost:18090'})
    assert response.status_code == 200
    return response.json()


def run_case(root, failure):
    clients = []
    proc = start(root, failure)
    try:
        a, b = authorize('A', '101'), authorize('B', '202')
        clients = [a, b]
        assert 'A_ONLY' in asyncio.run(turn(a))
        assert 'B_ONLY' in asyncio.run(turn(b))
        assert a.post('/operator/proof', json={'confirmed': True}).status_code in (404, 405)
        if not failure:
            assert operation(a, 'refresh')['generation'] == 2
            assert 'A_ONLY' in asyncio.run(turn(a))
        assert operation(a, 'revoke')['cleanupPending']
        if failure:
            try:
                witness(root, 'A', revoke_ok=False)
                raise AssertionError('Failed UI revoke must not confirm cleanup')
            except GatewayError as error:
                assert error.code == 'manual_review_quarantined'
            # The operator immediately disables both local records. Native watch
            # then attempts revoke and stops worker/listeners despite mock 503.
            op = operator(root)
            assert op.blocked() and op.summary()['cleanupPendingCount'] == 2
            assert all(op.registry.get_record(uid).status == 'RECONNECT_REQUIRED' for uid in ('101', '202'))
            proc.wait(20)
            assert not (root / 'settings.dpapi').exists()
            witness(root, 'A')
            witness(root, 'B')
            op = operator(root)
            assert op.summary()['cleanupPendingCount'] == 0 and op.blocked()
            assert all(r['revoked'] for r in json.loads((root / 'mock-grant-ledger.json').read_text()))
            outcomes.append({'name': 'Native failed revoke/witness -> immediate all-UID isolation -> listener/worker stop -> offline owner UI recovery', 'status': 'pass'})
        else:
            witness(root, 'A')
            assert not a.get('/status').json()['connections']['A']['cleanupPending']
            op = operator(root)
            assert op.summary()['formalUiConfirmedCount'] == 1
            status = a.get('/status').json()
            (root / 'mock-clock.json').write_text(json.dumps({'now': status['authorizationStartedAt'] + 7201}), encoding='utf-8')
            proc.wait(20)
            assert not (root / 'settings.dpapi').exists()
            minimal = json.loads(LiteralSealer().open((root / 'cleanup-settings.dpapi').read_bytes(), b'approved-settings-v1'))
            assert set(minimal) == {'mode', 'oauth', 'targets'}
            op = operator(root)
            assert op.registry.get_record('202').status == 'RECONNECT_REQUIRED'
            assert op.summary()['cleanupPendingCount'] == 1
            witness(root, 'B')
            assert operator(root).summary()['cleanupPendingCount'] == 0
            outcomes.append({'name': 'Native ADK/refresh/revoke -> interactive console proof -> 2h fake-clock stop -> application-key removal -> post-deadline formal cleanup', 'status': 'pass'})
        for port in (18089, 18090):
            with socket.socket() as sock:
                assert sock.connect_ex(('127.0.0.1', port)) != 0
        import redis
        redis_client = redis.Redis(host='127.0.0.1', port=18091)
        assert not redis_client.exists('hb-cmdboxlive-approved-worker')
        assert not redis_client.hexists('mem-cmdboxlive', 'signin_file_data')
        redis_client.close()
        outcomes.append({'name': 'Owned native listeners/worker heartbeat/signin cache removed; no pending cleanup after owner witness', 'status': 'pass'})
    finally:
        for client in clients:
            client.close()
        if proc.poll() is None:
            (root / 'stop-request').write_text('MOCK-ONLY', encoding='utf-8')
            try:
                proc.wait(20)
            except subprocess.TimeoutExpired:
                proc.terminate()
                proc.wait(5)


def run_failed_identity(root):
    proc = start(root, False)
    client = None
    try:
        # Native UID A receives a valid mock AP token for approved subject B.
        # No fault injection into the production app or actual AP is needed.
        client = authorize('A', '202', expect_status=409)
        op = operator(root)
        assert op.blocked() and op.summary()['cleanupPendingCount'] == 1
        with op.store.db() as db:
            for uid in ('101', '202'):
                _, status, record = op.store.row(db, uid)
                assert status == 'RECONNECT_REQUIRED' and not record.get('tokens')
        proc.wait(20)
        assert not (root / 'settings.dpapi').exists()
        spec = op.spec('101', op.rows('101')[0])
        assert spec.subject == 'DUMMY-AP-SUBJECT-B' and spec.project == 'DUMMY-PROJECT-B'
        witness(root, 'A')  # The operator requires AP subject B, not native label A.
        assert operator(root).summary()['cleanupPendingCount'] == 0
        assert len(json.loads((root / 'mock-grant-ledger.json').read_text())) == 1
        for port in (18089, 18090):
            with socket.socket() as sock:
                assert sock.connect_ex(('127.0.0.1', port)) != 0
        outcomes.append({'name': 'Wrong AP subject on native callback -> all-UID stop before another grant -> actual cleanup identity owner witness', 'status': 'pass'})
    finally:
        if client:
            client.close()
        if proc.poll() is None:
            (root / 'stop-request').write_text('MOCK-ONLY', encoding='utf-8')
            proc.wait(20)


if __name__ == '__main__':
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')
    status = 'fail'
    try:
        run_case(ROOT / 'app-lab/data' / ('cleanup-native-normal-' + stamp), False)
        run_case(ROOT / 'app-lab/data' / ('cleanup-native-failure-' + stamp), True)
        run_failed_identity(ROOT / 'app-lab/data' / ('cleanup-native-identity-' + stamp))
        status = 'pass'
    finally:
        for proc, log in processes:
            log.close()
        result = {'status': status, 'outcomes': outcomes, 'actualApContacted': False,
                  'actualCredentialOrGrantCreated': False, 'actualDpapiExecuted': False,
                  'allOwnedProcessesStopped': all(p.poll() is not None for p, _ in processes)}
        (ROOT / 'local-review' / ('cleanup-native-' + stamp + '-results.json')).write_text(json.dumps(result, indent=2), encoding='utf-8')
        print(json.dumps(result))
    sys.exit(0 if status == 'pass' else 1)
