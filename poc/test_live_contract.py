"""Phase2 fake-only protocol/vault/lifecycle tests. Never invokes DPAPI or sockets."""
import asyncio
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import sys
import threading
import unittest
LAB = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(LAB / 'runtimes/app-deps'), str(LAB / 'poc')]
import httpx
from cmdbox_gateway.cleanup_live import CleanupOperator, TrustedUiGrantChecker
from cmdbox_gateway.core import GatewayError, AuthorizedFlowBroker, invocation_scope
from cmdbox_gateway.fixtures import fixture as actor_fixture, payload, login, context, FLOW_A, FLOW_B
from cmdbox_gateway.oauth_live import OAuthConfig, OAuthHttpClient
from cmdbox_gateway.mcp_live import PinnedMcpTransport, parse_pinned_flow_output
from cmdbox_gateway.vault_live import WindowsDpapiSealer
from mock_live_support import fixture, connect

from datetime import datetime, timezone
ROOT = Path(__file__).resolve().parents[1] / 'app-lab' / 'data' / ('phase2-unit-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))


class ContractTests(unittest.TestCase):
    def setUp(self):
        self.now = [1800000000]
        self.root = ROOT / self._testMethodName
        assert not self.root.exists(), 'Use a fresh phase2 candidate run directory'
        self.mock, self.config, self.client, self.registry, self.life = fixture(self.root, clock=lambda: self.now[0])

    def tearDown(self):
        self.client.close()

    def formal_witness(self, uid, grant):
        # Dummy provider ledger is the fake browser authority. No USER token.
        self.assertTrue(any(g == grant and revoked for _, g, revoked in self.mock.refreshes.values()))
        op = CleanupOperator(self.registry, self.config, clock=lambda: self.now[0])
        spec = op.spec(uid, op.rows(uid)[0])
        self.assertEqual(spec.grant, grant)
        user = {'url': spec.issuer + '/api/v1/users/' + spec.subject,
                'status': 200, 'body': {'id': spec.subject}}
        after = [{'url': spec.issuer + '/api/v1/mcp-oauth/grants?limit=10', 'status': 200,
                  'body': {'data': [], 'next': None, 'previous': None}}]
        return TrustedUiGrantChecker(spec, user, None, after, owner_ack='AP-UI ' + spec.subject)

    def refuse_boolean_checker(self, value):
        with self.assertRaisesRegex(GatewayError, 'trusted_ui_checker_required'):
            self.life.confirm_cleanup('101', lambda *args: value)
        self.assertTrue(self.life.status('101')['cleanupPending'])

    def test_strict_metadata_endpoint(self):
        self.mock.fault = 'metadata'
        with self.assertRaisesRegex(GatewayError, 'oauth_metadata_mismatch'):
            self.life.provider.discover()
        self.assertNotIn(('POST', '/token'), self.mock.methods)

    def test_config_and_client_boundaries(self):
        for issuer in ('http://public.invalid', 'https://mock-ap.invalid/path', 'https://a:b@mock-ap.invalid'):
            with self.assertRaises(GatewayError):
                OAuthConfig(issuer, 'LITERAL-ID', 'Literal', self.config.redirect_uri, issuer + '/mcp')
        with httpx.Client(transport=httpx.MockTransport(self.mock.handle), trust_env=False, follow_redirects=True) as wrong:
            with self.assertRaises(GatewayError):
                OAuthHttpClient(self.config, wrong)

    def test_pkce_consumption_and_session_uid_binding(self):
        session = 'LITERAL_DUMMY_WEBSESSION_PHASE2_A'
        started = self.life.start('101', session)
        self.assertNotIn('verifier', started)
        self.assertEqual(len(started['state']), 43)
        code = self.mock.register('101', started)
        for uid, wrong in [('202', session), ('101', session + '_OTHER')]:
            with self.assertRaises(GatewayError):
                self.life.complete(uid, wrong, started['state'], code)
        result = self.life.complete('101', session, started['state'], code)
        self.assertEqual(result['generation'], 1)
        with self.assertRaises(GatewayError):
            self.life.complete('101', session, started['state'], code)
        self.assertEqual(self.mock.methods.count(('POST', '/token')), 1)

    def test_expired_state_consumed_without_exchange(self):
        started = self.life.start('101', 'LITERAL_DUMMY_WEBSESSION_PHASE2_A')
        self.now[0] += 121
        with self.assertRaises(GatewayError):
            self.life.complete('101', 'LITERAL_DUMMY_WEBSESSION_PHASE2_A', started['state'], 'LITERAL-CODE')
        self.assertNotIn(('POST', '/token'), self.mock.methods)

    def test_unexpected_subject_project_client_and_userinfo(self):
        for fault in ('project', 'client', 'userinfo', 'scope'):
            self.mock.fault = fault
            with self.assertRaisesRegex(GatewayError, '^oauth_connect_failed$'):
                connect(self.mock, self.life)
            self.assertEqual(self.life.status('101')['status'], 'RECONNECT_REQUIRED')
            self.assertTrue(self.life.status('101')['cleanupPending'])
        self.assertNotIn(('POST', '/register'), self.mock.methods)

    def test_redirect_never_followed(self):
        self.mock.fault = 'redirect'
        with self.assertRaises(GatewayError):
            connect(self.mock, self.life)
        self.assertEqual(self.life.status('101')['status'], 'RECONNECT_REQUIRED')
        self.assertTrue(self.life.status('101')['cleanupPending'])
        self.refuse_boolean_checker(True)

    def test_mock_envelope_binding_and_restart(self):
        connect(self.mock, self.life)
        raw = self.registry.store.path.read_bytes()
        self.assertNotIn(b'LITERAL-DUMMY-REFRESH', raw)
        self.assertNotIn(b'LITERAL_DUMMY_WEBSESSION', raw)
        binding = self.registry.resolve('101')
        with self.assertRaises(GatewayError):
            self.registry.bind(binding)
        value = self.registry.get_record('101')
        self.assertEqual(value, binding)
        self.assertEqual(self.life.status('101')['generation'], 1)
        # Purpose substitution must fail even for the noncryptographic fixture.
        store = self.registry.store
        with self.assertRaises(GatewayError):
            store.decode('record', '202', store.encode('record', '101', {'literal': True}))

    def test_refresh_same_token_generation_and_cached_tool(self):
        connect(self.mock, self.life)
        old = self.registry.resolve('101')
        result = self.life.renew('101', old.generation, force=True)
        self.assertEqual(result['generation'], old.generation + 1)
        self.assertEqual(len(self.mock.refreshes), 1)
        self.assertEqual(self.life.renew('101', old.generation, force=True)['generation'], 2)
        with self.assertRaises(GatewayError):
            asyncio.run(self.life.get_active(old.credential_ref, old.grant_id, old.generation))

    def test_concurrent_refresh_single_network_winner(self):
        connect(self.mock, self.life)
        self.mock.refresh_release = threading.Event()
        def renewal():
            try:
                return self.life.renew('101', 1, force=True)['status']
            except GatewayError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(renewal)
            self.assertTrue(self.mock.refresh_entered.wait(2))
            second = pool.submit(renewal)
            self.assertEqual(second.result(2), 'connection_busy')
            self.mock.refresh_release.set()
            self.assertEqual(first.result(2), 'ACTIVE')
        self.assertEqual(self.mock.methods.count(('POST', '/token')), 2)

    def test_refresh_revoke_race_no_resurrection(self):
        connect(self.mock, self.life)
        grant = self.registry.resolve('101').grant_id
        self.mock.refresh_release = threading.Event()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(self.life.renew, '101', 1, force=True)
            self.assertTrue(self.mock.refresh_entered.wait(2))
            self.life.revoke('101')  # Must not be blocked by the external refresh call.
            self.mock.refresh_release.set()
            with self.assertRaises(GatewayError):
                future.result(2)
        self.assertEqual(self.life.status('101')['status'], 'RECONNECT_REQUIRED')
        self.life.attempt_cleanup('101')
        self.assertFalse(self.life.confirm_cleanup('101', self.formal_witness('101', grant))['cleanupPending'])

    def test_revoke_200_is_not_formal_confirmation_and_retry(self):
        connect(self.mock, self.life)
        grant = self.registry.resolve('101').grant_id
        self.mock.revoke_failure = True
        self.assertTrue(self.life.revoke('101')['cleanupPending'])
        self.refuse_boolean_checker(True)
        self.mock.revoke_failure = False
        self.assertTrue(self.life.attempt_cleanup('101')['cleanupPending'])
        self.refuse_boolean_checker(False)
        self.assertFalse(self.life.confirm_cleanup('101', self.formal_witness('101', grant))['cleanupPending'])

    def test_refresh_fail_closed_and_retention_cutoff(self):
        connect(self.mock, self.life)
        self.mock.fault = 'refresh'
        with self.assertRaises(GatewayError):
            self.life.renew('101', 1, force=True)
        self.assertEqual(self.life.status('101')['status'], 'RECONNECT_REQUIRED')
        self.assertTrue(self.life.status('101')['cleanupPending'])
        self.mock.fault = None
        connect(self.mock, self.life)
        self.now[0] += 7201
        with self.assertRaises(GatewayError):
            self.life.renew('101', self.life.status('101')['generation'])

    def test_official_mcp_sdk_broker_allowlist_and_uid(self):
        connect(self.mock, self.life, '101')
        connect(self.mock, self.life, '202', 'LITERAL_DUMMY_WEBSESSION_PHASE2_B')
        transport = PinnedMcpTransport(self.config, [FLOW_A, FLOW_B], self.mock.async_client)
        broker = AuthorizedFlowBroker(self.registry, self.life, transport, resource=self.config.resource)
        actor_source = actor_fixture()
        actor = actor_source.verifier.verify(actor_source.issuer.attach(login(), payload()))
        async def call():
            with invocation_scope(actor, 'same-chat'):
                return await broker.call(context(actor), alias='lab_identity', arguments={}, expected_uid='101', expected_generation=1)
        self.assertEqual(asyncio.run(call())['marker'], 'A_ONLY')
        self.assertEqual(self.mock.raw_calls, [('101', FLOW_A.raw_name)])
        with self.assertRaises(GatewayError):
            asyncio.run(transport.call(resource=self.config.resource, headers={'Authorization': 'Bearer LITERAL'},
                        raw_name='ap_management_dummy', arguments={}, cache_key=('x',) * 7))

    def test_dpapi_backend_not_executed(self):
        # Constructing the backend creates no key, ACL, encrypted file or Win32 call.
        self.assertTrue(callable(WindowsDpapiSealer().seal))

    def test_pinned_dynamic_reply_body_shape(self):
        import json
        body = {'marker': 'A_ONLY', 'owner': 'A', 'kind': 'synthetic'}
        def wrapped(value):
            return '✅ Successfully executed flow literal\n\nOutput:\n```json\n' + json.dumps({'status': 200, 'body': value}) + '\n```'
        self.assertEqual(parse_pinned_flow_output(wrapped({'response': body})), body)
        with self.assertRaises(GatewayError):
            parse_pinned_flow_output(wrapped({'response': {'response': body}}))

    def test_pinned_result_parser_rejects_error_and_unwrapped_json(self):
        for text in ('{"marker":"A_ONLY"}', '❌ Error executing flow literal',
                     '✅ Successfully executed flow literal\n\nOutput:\n```json\n{"status":500,"body":{"marker":"A_ONLY"}}\n```'):
            with self.assertRaises(GatewayError):
                parse_pinned_flow_output(text)


if __name__ == '__main__':
    unittest.main(verbosity=2)
