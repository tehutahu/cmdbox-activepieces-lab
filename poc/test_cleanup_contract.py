"""Fake AP UI, owner-witness validation, purpose/CAS cleanup and quarantine."""
from pathlib import Path
import sys
LAB = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(LAB / 'runtimes/app-deps'), str(LAB / 'poc')]
from datetime import datetime, timezone
import copy
import unittest
from cmdbox_gateway.core import GatewayError
from cmdbox_gateway.cleanup_live import CleanupOperator, TrustedUiGrantChecker, discover_revoke_target
from mock_live_support import fixture, connect

ROOT = LAB / 'app-lab/data' / ('cleanup-unit-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f'))


def user(spec):
    return {'url': spec.issuer + '/api/v1/users/' + spec.subject, 'status': 200,
            'body': {'id': spec.subject, 'platformRole': 'MEMBER'}}


def row(spec, grant=None):
    return {'id': grant or spec.grant, 'clientKey': 'unknown', 'clientName': spec.client_name,
            'projectId': spec.project, 'projectName': 'Literal project',
            'member': {'id': spec.subject, 'email': 'a@example.invalid', 'firstName': 'Literal', 'lastName': 'A'},
            'created': datetime.fromtimestamp(spec.attempted_at or 1800000000, timezone.utc).isoformat(),
            'lastUsedAt': None}


def pages(spec, rows=None, cursor=None, next_cursor=None):
    url = spec.issuer + '/api/v1/mcp-oauth/grants?limit=10'
    if cursor:
        url += '&cursor=' + cursor
    return [{'url': url, 'status': 200, 'body': {'data': rows or [], 'next': next_cursor, 'previous': None}}]


def checker(spec, *, before=None, after=None):
    return TrustedUiGrantChecker(spec, user(spec), before, after or pages(spec), owner_ack='AP-UI ' + spec.subject)


class CleanupTests(unittest.TestCase):
    def setUp(self):
        self.now = [1800000000]
        self.mock, self.cfg, self.client, self.registry, self.life = fixture(ROOT / self._testMethodName, clock=lambda: self.now[0])
        self.op = CleanupOperator(self.registry, self.cfg, clock=lambda: self.now[0])
        connect(self.mock, self.life)
        self.life.revoke('101')
        self.spec = self.op.spec('101', self.op.rows('101')[0])

    def tearDown(self):
        self.client.close()

    def test_normal_ui_witness_proof_apply_and_audit(self):
        self.assertTrue(self.life.status('101')['cleanupPending'])
        proof = self.op.publish(checker(self.spec))
        self.assertGreater(proof, 0)
        self.assertEqual(self.op.apply(), 1)
        self.assertFalse(self.life.status('101')['cleanupPending'])
        self.assertEqual(self.op.summary()['formalUiConfirmedCount'], 1)
        self.assertNotIn(self.spec.grant, str(self.op.summary()))

    def test_target_hidden_on_second_page_is_not_cleared(self):
        after = pages(self.spec, next_cursor='NEXT') + pages(self.spec, [row(self.spec)], cursor='NEXT')
        with self.assertRaisesRegex(GatewayError, 'formal_grant_still_active'):
            checker(self.spec, after=after)
        self.assertTrue(self.life.status('101')['cleanupPending'])

    def test_all_pages_after_absent_target_are_required(self):
        unrelated = row(self.spec, 'DUMMY-OTHER-GRANT')
        after = pages(self.spec, [unrelated], next_cursor='NEXT') + pages(self.spec, cursor='NEXT')
        self.op.publish(checker(self.spec, after=after))
        self.assertEqual(self.op.apply(), 1)

    def test_incomplete_cursor_filter_http_or_origin_fail(self):
        cases = [pages(self.spec, next_cursor='NEXT')]
        for key, value in [('url', self.spec.issuer + '/api/v1/mcp-oauth/grants?projectIds=DUMMY-PROJECT-A'),
                           ('url', 'https://other.invalid/api/v1/mcp-oauth/grants'), ('status', 401), ('status', 503)]:
            item = pages(self.spec)
            item[0][key] = value
            cases.append(item)
        for after in cases:
            with self.assertRaises(GatewayError):
                checker(self.spec, after=after)
        self.assertEqual(self.op.summary()['formalProofPendingCount'], 0)

    def test_wrong_current_user_and_missing_owner_witness(self):
        wrong = user(self.spec)
        wrong['body']['id'] = 'DUMMY-OTHER-SUBJECT'
        for who, ack in [(wrong, 'AP-UI ' + self.spec.subject), (user(self.spec), 'yes')]:
            with self.assertRaises(GatewayError):
                TrustedUiGrantChecker(self.spec, who, None, pages(self.spec), owner_ack=ack)

    def test_token_header_har_material_rejected_without_values(self):
        for key in ('token', 'Authorization', 'cookies', 'har'):
            who = user(self.spec)
            who['body'][key] = 'LITERAL-DUMMY-SENSITIVE-INPUT'
            with self.assertRaisesRegex(GatewayError, '^credential_material_refused$'):
                TrustedUiGrantChecker(self.spec, who, None, pages(self.spec), owner_ack='AP-UI ' + self.spec.subject)

    def test_wrong_known_grant_project_member_or_client(self):
        for key, value in [('projectId', 'DUMMY-OTHER-PROJECT'), ('clientName', 'Literal wrong client'),
                           ('member', {'id': 'DUMMY-OTHER-SUBJECT'})]:
            target = row(self.spec)
            target[key] = value
            with self.assertRaisesRegex(GatewayError, 'formal_grant_target_mismatch'):
                checker(self.spec, before=pages(self.spec, [target]))

    def test_ui_revoke_can_confirm_after_normal_revoke_failure(self):
        connect(self.mock, self.life)
        self.mock.revoke_failure = True
        self.life.revoke('101')
        spec = self.op.spec('101', self.op.rows('101')[-1])
        # Simulated owner UI deletes only this dummy grant; no USER credential.
        for refresh, (uid, grant, revoked) in list(self.mock.refreshes.items()):
            if grant == spec.grant:
                self.mock.refreshes[refresh] = uid, grant, True
        self.op.publish(checker(spec, before=pages(spec, [row(spec)])))
        self.op.apply()
        self.assertNotIn(spec.row, self.op.rows('101'))

    def test_unknown_exchange_grant_is_discovered_unique_then_ui_revoked(self):
        self.mock.fault = 'redirect'
        with self.assertRaises(GatewayError):
            connect(self.mock, self.life)
        spec = self.op.spec('101', self.op.rows('101')[-1])
        self.assertIsNone(spec.grant)
        grant = list(self.mock.refreshes.values())[-1][1]
        self.op.publish(checker(spec, before=pages(spec, [row(spec, grant)])))
        self.assertEqual(self.op.apply(), 1)

    def test_unknown_empty_or_duplicate_candidate_stays_quarantined(self):
        self.mock.fault = 'redirect'
        with self.assertRaises(GatewayError):
            connect(self.mock, self.life)
        spec = self.op.spec('101', self.op.rows('101')[-1])
        for before in [pages(spec), pages(spec, [row(spec, 'DUMMY-ONE'), row(spec, 'DUMMY-TWO')])]:
            with self.assertRaisesRegex(GatewayError, 'unknown_grant_ambiguous_or_unresolved'):
                checker(spec, before=before)
        self.assertTrue(self.life.status('101')['cleanupPending'])

    def test_stale_generation_proof_quarantines_all_local_authority(self):
        connect(self.mock, self.life, '202', 'LITERAL_DUMMY_WEBSESSION_B')
        self.op.publish(checker(self.spec))
        self.life.revoke('101')
        methods_before = len(self.mock.methods)
        with self.assertRaisesRegex(GatewayError, 'formal_review_quarantined'):
            self.op.apply()
        self.assertTrue(self.op.blocked())
        self.assertEqual(len(self.mock.methods), methods_before)
        self.assertEqual(self.life.status('202')['status'], 'RECONNECT_REQUIRED')
        self.assertTrue(self.life.status('202')['cleanupPending'])

    def test_expired_or_corrupt_proof_does_not_clear_cleanup(self):
        self.op.publish(checker(self.spec))
        self.now[0] += 301
        with self.assertRaises(GatewayError):
            self.op.apply()
        self.assertTrue(self.life.status('101')['cleanupPending'])
        self.assertTrue(self.op.blocked())

    def test_corrupt_purpose_and_boolean_proof_fail_closed(self):
        with self.assertRaises(GatewayError):
            self.op.publish(True)
        number = self.op.publish(checker(self.spec))
        with self.registry.store.db() as db:
            blob = db.execute('SELECT envelope FROM formal_proofs WHERE id=?', (number,)).fetchone()[0]
            replacement = copy.copy(blob[:-1] + b'X')
            db.execute('UPDATE formal_proofs SET envelope=? WHERE id=?', (replacement, number))
        with self.assertRaises(GatewayError):
            self.op.apply()
        self.assertTrue(self.life.status('101')['cleanupPending'])

    def test_ui_mutation_target_is_verified_before_revoke_instruction(self):
        before = pages(self.spec, [row(self.spec)])
        self.assertEqual(discover_revoke_target(self.spec, user(self.spec), before), self.spec.grant)
        wrong = user(self.spec)
        wrong['body']['id'] = 'DUMMY-OTHER-SUBJECT'
        for who, data in [(wrong, before), (user(self.spec), pages(self.spec)),
                          (user(self.spec), pages(self.spec, [row(self.spec, 'DUMMY-OTHER-GRANT')]))]:
            with self.assertRaises(GatewayError):
                discover_revoke_target(self.spec, who, data)

    def test_cycle_cursor_chain_is_rejected(self):
        after = pages(self.spec, next_cursor='NEXT') + pages(self.spec, cursor='NEXT', next_cursor='NEXT') + pages(self.spec, cursor='NEXT')
        with self.assertRaisesRegex(GatewayError, 'grant_cursor_chain_incomplete'):
            checker(self.spec, after=after)

    def test_parallel_console_watcher_consumption_is_idempotent(self):
        import threading
        from concurrent.futures import ThreadPoolExecutor
        self.op.publish(checker(self.spec))
        barrier = threading.Barrier(2)
        original = self.registry.store.decode
        def decode(purpose, number, envelope):
            value = original(purpose, number, envelope)
            if purpose == 'formal-proof':
                barrier.wait(10)
            return value
        self.registry.store.decode = decode
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(lambda _: self.op.apply(), range(2)))
        self.assertEqual(sum(values), 1)
        self.assertFalse(self.op.blocked())
        self.assertEqual(self.op.summary()['formalUiConfirmedCount'], 1)

    def test_noninteractive_console_rejects_before_private_context(self):
        from unittest.mock import patch
        sys.path.insert(0, str(LAB / 'app-lab'))
        import cleanup_operator
        with patch.object(sys.stdin, 'isatty', return_value=False), patch.object(cleanup_operator, 'context') as context:
            with self.assertRaisesRegex(GatewayError, 'interactive_owner_console_required'):
                cleanup_operator.main(ROOT, 'A')
            context.assert_not_called()

    def test_owner_console_interrupt_keeps_cleanup_and_blocks_all_uids(self):
        import io
        from unittest.mock import patch
        sys.path.insert(0, str(LAB / 'app-lab'))
        import cleanup_operator
        connect(self.mock, self.life, '202', 'LITERAL_DUMMY_WEBSESSION_B')
        class OwnerConsole(io.StringIO):
            def isatty(self):
                return True
        with patch.object(sys, 'stdin', OwnerConsole()), patch.object(sys, 'stdout', OwnerConsole()), \
             patch.object(cleanup_operator, 'context', return_value=self.op), \
             patch('builtins.input', side_effect=KeyboardInterrupt):
            with self.assertRaisesRegex(GatewayError, 'manual_review_quarantined'):
                cleanup_operator.main(ROOT, 'A')
        self.assertTrue(self.op.blocked())
        self.assertTrue(self.life.status('101')['cleanupPending'])
        self.assertEqual(self.life.status('202')['status'], 'RECONNECT_REQUIRED')

    def test_operator_failure_cancels_lease_state_and_retains_cleanup(self):
        connect(self.mock, self.life, '202', 'LITERAL_DUMMY_WEBSESSION_B')
        self.life.start('202', 'LITERAL_DUMMY_WEBSESSION_B')
        self.op.quarantine('manual_review_failed')
        with self.registry.store.db() as db:
            self.assertEqual(db.execute('SELECT count(*) FROM pending').fetchone()[0], 0)
            self.assertEqual(db.execute('SELECT count(*) FROM leases').fetchone()[0], 0)
        self.assertEqual(self.life.status('202')['status'], 'RECONNECT_REQUIRED')
        self.assertTrue(self.life.status('202')['cleanupPending'])


if __name__ == '__main__':
    unittest.main(verbosity=2)
