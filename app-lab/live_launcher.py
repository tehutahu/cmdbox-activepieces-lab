"""Explicit approved live bootstrap. Real use decrypts an owner-ACL protected root.

No state/PKCE/Authorize request at startup. Native worker and two localhost listeners
wait for the human's local entry button. No AP consent button is automated.
"""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'runtimes/app-deps'), str(ROOT / 'app-lab/cmdbox-public'), str(ROOT / 'poc'), str(ROOT / 'app-lab')]
import argparse
import asyncio
import json
import logging
import os
import secrets
import subprocess
import socket
import httpx
import uvicorn
from cmdbox_gateway.core import FlowPolicy, require
from cmdbox_gateway.oauth_live import OAuthConfig, OAuthHttpClient
from cmdbox_gateway.vault_live import EncryptedStore, WindowsDpapiSealer
from cmdbox_gateway.lifecycle_live import LiveBindings, Target
from cmdbox_gateway.mcp_live import PinnedMcpTransport
from live_app import create_apps


def verify_owner_root(root):
    require(root.is_dir() and root.is_relative_to((ROOT / 'private').resolve()), 'approved_private_root_required')
    # Read only. Never create/change ACL here or inspect a different directory.
    # Use the .NET ACL reader directly; no Security-module autoload/PSModulePath dependency.
    command = "$ErrorActionPreference='Stop';[Console]::OutputEncoding=[System.Text.UTF8Encoding]::new($false);$p=$env:CMDBOX_APPROVED_PRIVATE_ROOT;$a=[System.IO.Directory]::GetAccessControl($p);$u=[System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value;$r=@($a.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier])|ForEach-Object {@{sid=$_.IdentityReference.Value;type=[string]$_.AccessControlType;rights=[string]$_.FileSystemRights;inherited=$_.IsInherited}});@{protected=$a.AreAccessRulesProtected;user=$u;rules=$r}|ConvertTo-Json -Depth 4 -Compress"
    result = subprocess.run(['powershell.exe', '-NoProfile', '-NonInteractive', '-Command', command],
                            env={**os.environ, 'CMDBOX_APPROVED_PRIVATE_ROOT': str(root)}, capture_output=True,
                            text=True, encoding='utf-8', errors='replace', check=True, creationflags=subprocess.CREATE_NO_WINDOW)
    acl = json.loads(result.stdout)
    require(acl['protected'] is True and len(acl['rules']) == 2 and {r['sid'] for r in acl['rules']} == {acl['user'], 'S-1-5-18'}
            and all(r['type'] == 'Allow' and r['rights'] == 'FullControl' and not r['inherited'] for r in acl['rules']), 'owner_only_private_acl_required')


def actual(root, *, resume_pre_authorize=False):
    root = root.resolve()
    verify_owner_root(root)
    sealer = WindowsDpapiSealer()
    settings = json.loads(sealer.open((root / 'settings.dpapi').read_bytes(), b'approved-settings-v1'))
    require(settings['mode'] == 'APPROVED-LOCAL-AP' and settings['oauth']['issuer'] == 'http://localhost:18088'
            and settings['oauth']['redirect_uri'] == 'http://localhost:18089/oauth/callback', 'approved_endpoint_manifest_required')
    config = OAuthConfig(**settings['oauth'])
    targets = [Target(t['uid'], t['subject'], t['project'], FlowPolicy(**t['flow'])) for t in settings['targets']]
    store = EncryptedStore(root, sealer)
    registry = LiveBindings(store, targets)
    policies = None
    if 'stock_drive' in settings:
        from cmdbox_gateway.stock_drive import verified_settings
        require(not resume_pre_authorize, 'stock_fresh_approved_run_required')
        policies = verified_settings(settings, registry.targets, actual=True)
        require(not (root / 'cleanup-settings.dpapi').exists(), 'stock_fresh_approved_run_required')
        require(not (root / 'native-data').exists() and not (root / 'retention-status.json').exists(),
                'stock_fresh_approved_run_required')
        with store.db() as db:
            require(all(db.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
                        for table in ('records', 'pending', 'cleanup', 'leases')), 'stock_fresh_approved_run_required')
    if 'flow_budget_private_root' in settings:
        require(policies is not None, 'stock_shared_budget_required')
        budget_root = Path(settings['flow_budget_private_root']).resolve()
        require(budget_root != root, 'existing_canonical_budget_required')
        verify_owner_root(budget_root)
        budget_store = EncryptedStore(budget_root, sealer)
        with budget_store.db() as db:
            rows = dict(db.execute("SELECT uid,n FROM app_budget WHERE operation='flow'").fetchall())
        require(set(rows) == set(registry.targets) and all(n == 1 for n in rows.values()),
                'remaining_one_search_budget_required')
        registry.flow_budget_store = budget_store
    client = httpx.Client(trust_env=False, follow_redirects=False, timeout=5)
    provider = OAuthHttpClient(config, client)
    if resume_pre_authorize:
        # Reuse the already verified idle preparation during local code upgrades.
        # No new AP operation or application secret. Never resume after consent.
        proof = json.loads((root / 'ready-proof.json').read_text(encoding='utf-8'))
        require(proof['status'] == 'READY-BEFORE-HUMAN-AUTHORIZE' and not proof['humanAuthorizeStarted'],
                'existing_idle_preparation_required')
        with store.db() as db:
            require(all(db.execute('SELECT count(*) FROM ' + table).fetchone()[0] == 0
                        for table in ('records', 'pending', 'cleanup', 'leases', 'app_window', 'app_budget')),
                    'no_resume_after_authorization')
    else:
        provider.discover()  # Two normal public GETs only, no client mutation.
    def factory(headers=None, timeout=None, auth=None):
        require(auth is None, 'public_mcp_bearer_only')
        return httpx.AsyncClient(headers=headers, timeout=timeout, trust_env=False, follow_redirects=False)
    if policies:
        from cmdbox_gateway.stock_mcp import StockMcpTransport
        transport = StockMcpTransport(config, policies, factory)
    else:
        transport = PinnedMcpTransport(config, [t.flow for t in targets], factory)
    data = root / 'native-data'
    data.mkdir(exist_ok=True)
    return settings, registry, provider, transport, secrets.token_bytes, data, client, sealer


def mock(root, *, test_clock=False, revoke_failure=False, stock=False):
    from mock_live_support import fixture, LiteralEntropy
    import base64
    import starsessions.session
    entropy = LiteralEntropy(root.name)
    # Tests do not generate actual session/PKCE/signing secrets.
    starsessions.session.generate_session_id = lambda: 'LITERAL_DUMMY_NATIVE_SESSION_' + base64.urlsafe_b64encode(entropy(24)).decode().rstrip('=')
    import time
    from mock_live_support import LiteralSealer
    clock_file = root / 'mock-clock.json'
    if test_clock:
        clock_file.write_text(json.dumps({'now': int(time.time())}), encoding='utf-8')
    def clock():
        return json.loads(clock_file.read_text(encoding='utf-8'))['now'] if test_clock else time.time()
    backend, config, client, registry, life = fixture(root / 'literal-vault', clock=clock)
    if stock:
        from stock_mock_support import configure_stock_backend
        registry, bundle = configure_stock_backend(backend, registry)
    backend.revoke_failure = revoke_failure
    original = backend.handle
    started = {}
    class MockOAuth(OAuthHttpClient):
        def authorization_url(self, state, challenge):
            started[state] = challenge
            return super().authorization_url(state, challenge)
    def response(request):
        if request.url.path == '/token':
            from urllib.parse import parse_qs
            form = {k: v[0] for k, v in parse_qs(request.content.decode()).items()}
            if form.get('grant_type') == 'authorization_code':
                _, uid, state = form['code'].split(':')
                backend.codes[form['code']] = (uid, started[state])
        result = original(request)
        # Only dummy grant metadata, never access/refresh/session material. Allows
        # the fake AP UI to remain inspectable after the app's deadline shutdown.
        values = []
        for _, (uid, grant, revoked) in backend.refreshes.items():
            claims = next(c for _, g, c in backend.accepted_access.values() if g == grant)
            values.append({'id': grant, 'clientKey': 'unknown', 'clientName': config.client_name,
                           'projectId': claims['projectId'], 'projectName': 'Literal project',
                           'member': {'id': claims['sub'], 'email': 'a@example.invalid' if uid == '101' else 'b@example.invalid'},
                           'created': __import__('datetime').datetime.fromtimestamp(claims['iat'], __import__('datetime').timezone.utc).isoformat(),
                           'lastUsedAt': None, 'revoked': revoked})
        (root / 'mock-grant-ledger.json').write_text(json.dumps(values), encoding='utf-8')
        return result
    backend.handle = response
    client.close()
    client = httpx.Client(transport=httpx.MockTransport(response), trust_env=False, follow_redirects=False, timeout=5)
    provider = MockOAuth(config, client, clock=clock)
    provider.test_clock = clock
    provider.discover()
    settings = {'mode': 'MOCK-LOCAL-AP', 'oauth': __import__('dataclasses').asdict(config),
                'targets': [{'uid': t.uid, 'subject': t.subject, 'project': t.project, 'flow': __import__('dataclasses').asdict(t.flow)} for t in registry.targets.values()],
                'passwords': {'A': 'LITERAL_DUMMY_PASSWORD', 'B': 'LITERAL_DUMMY_PASSWORD'},
                'job_key': base64.b64encode(b'J' * 32).decode(), 'session_secret': base64.b64encode(b'S' * 32).decode()}
    if stock:
        settings.update(stock_drive=bundle['manifest'], stock_flow_receipts=bundle['flows'])
    data = root / 'native-data'
    data.mkdir()
    sealer = LiteralSealer()
    (root / 'settings.dpapi').write_bytes(sealer.seal(json.dumps(settings).encode(), b'approved-settings-v1'))
    if stock:
        from cmdbox_gateway.stock_drive import parse_manifest
        from cmdbox_gateway.stock_mcp import StockMcpTransport
        transport = StockMcpTransport(config, parse_manifest(settings['stock_drive']), backend.async_client)
    else:
        transport = PinnedMcpTransport(config, [t.flow for t in registry.targets.values()], backend.async_client)
    return settings, registry, provider, transport, entropy, data, client, sealer


async def serve(parts, root):
    settings, registry, provider, transport, entropy, data, client, sealer = parts
    servers = []
    def expired():
        # Secrets used only for application authority are no longer retained.
        if sealer:
            minimal = {'mode': 'CLEANUP-ONLY', 'oauth': settings['oauth'], 'targets': settings['targets']}
            temporary = root / 'cleanup-settings.dpapi'
            try:
                temporary.write_bytes(sealer.seal(json.dumps(minimal).encode(), b'approved-settings-v1'))
            finally:
                (root / 'settings.dpapi').unlink(missing_ok=True)
        for server in servers:
            server.should_exit = True
    app, callback, life, window, stop = create_apps(settings, registry, provider, transport, entropy, data, on_expired=expired, clock=getattr(provider, 'test_clock', __import__('time').time))
    for surface, port in [(app, 18090), (callback, 18089)]:
        servers.append(uvicorn.Server(uvicorn.Config(surface, host='127.0.0.1', port=port, ws='wsproto',
                                                     log_level='warning', access_log=False, lifespan='on' if port == 18090 else 'off')))
    async def control():
        while not stop.is_set():
            await asyncio.sleep(1)
            if (root / 'stop-request').exists():
                await app.state.shutdown_approved('operator_stop')
    watcher = asyncio.create_task(control())
    try:
        await asyncio.gather(*(server.serve() for server in servers))
    finally:
        if 'stock_drive' in settings:
            await app.state.shutdown_approved('server_exit')
            from cmdbox_gateway.stock_retention import retain_owned_metadata
            result = retain_owned_metadata(data, root, registry.targets) if app.state.worker_stopped else {
                'metadataRemoved': False, 'metadataRetained': True, 'operatorReviewRequired': True}
            result.update(app.state.retention_tokens)
            result.update(workerStopped=app.state.worker_stopped, remoteGoogleCleanupConfirmed=False)
            (root / 'retention-status.json').write_text(json.dumps(result), encoding='utf-8')
        stop.set()
        watcher.cancel()
        client.close()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--private-root', type=Path)
    parser.add_argument('--mock-root', type=Path)
    parser.add_argument('--resume-pre-authorize', action='store_true')
    parser.add_argument('--mock-stock-drive', action='store_true')
    parser.add_argument('--mock-test-clock', action='store_true')
    parser.add_argument('--mock-revoke-failure', action='store_true')
    args = parser.parse_args()
    require(bool(args.private_root) != bool(args.mock_root), 'one_explicit_bootstrap_mode_required')
    require(not args.resume_pre_authorize or args.private_root, 'private_resume_only')
    require(not (args.mock_test_clock or args.mock_revoke_failure or args.mock_stock_drive) or args.mock_root, 'mock_test_flags_only')
    root = (args.private_root or args.mock_root).resolve()
    if args.mock_root:
        require(root.is_relative_to(ROOT / 'app-lab/data') and not root.exists(), 'fresh_ignored_mock_root_required')
        root.mkdir(parents=True)
    for port in (18089, 18090):
        with socket.socket() as check:
            require(check.connect_ex(('127.0.0.1', port)) != 0, 'owned_listener_port_conflict')
    for name in ('GOOGLE_API_KEY', 'GEMINI_API_KEY', 'OPENAI_API_KEY', 'GOOGLE_APPLICATION_CREDENTIALS'):
        os.environ.pop(name, None)
    os.environ.update(OTEL_SDK_DISABLED='true', LITELLM_LOCAL_MODEL_COST_MAP='true', HF_HUB_OFFLINE='1',
                      CUSTOM_TIKTOKEN_CACHE_DIR=str(ROOT / 'app-lab/tokenizer-cache'))
    for name in ('httpx', 'httpcore', 'mcp'):
        logging.getLogger(name).setLevel(logging.ERROR)
    asyncio.run(serve(mock(root, test_clock=args.mock_test_clock, revoke_failure=args.mock_revoke_failure, stock=args.mock_stock_drive) if args.mock_root
                      else actual(root, resume_pre_authorize=args.resume_pre_authorize), root))
