import unittest
from cmdbox_gateway import integration as i
from cmdbox_gateway.core import GatewayError, actor_for_adk
from cmdbox_gateway.fixtures import fixture, login, payload, context

class IntegrationTests(unittest.TestCase):
    def setUp(self):
        i.install_web_runtime(None); i.install_worker_runtime(None, None)
    def tearDown(self):
        i.install_web_runtime(None); i.install_worker_runtime(None, None)
    def test_no_default_runtime_or_signing_key(self):
        with self.assertRaisesRegex(GatewayError, '^web_identity_runtime_not_configured$'):
            i.attach_verified_web_job(login(), payload())
        with self.assertRaisesRegex(GatewayError, '^ap_broker_runtime_not_configured$'):
            i.approved_ap_toolset()
    def test_unsigned_legacy_job_has_no_trusted_actor(self):
        self.assertIsNone(i.verify_worker_job(payload()))
        with i.trusted_runner_scope(None, 'same-chat'):
            with self.assertRaisesRegex(GatewayError, '^verified_invocation_required$'):
                actor_for_adk(None)
    def test_configured_signed_job_uid_handoff(self):
        f = fixture(); i.install_web_runtime(f.issuer); i.install_worker_runtime(f.verifier, f.broker)
        actor = i.verify_worker_job(i.attach_verified_web_job(login(), payload()))
        self.assertEqual(i.adk_identity(actor, 'arbitrary-display'), 'cmdbox_uid_101')
        with i.trusted_runner_scope(actor, 'same-chat'):
            self.assertEqual(actor_for_adk(context(actor)).actor.uid, '101')
    def test_signed_job_without_worker_config_fails_closed(self):
        f = fixture()
        with self.assertRaisesRegex(GatewayError, '^worker_identity_runtime_not_configured$'):
            i.verify_worker_job(f.issuer.attach(login(), payload()))
    def test_preflight_reconnect_before_runner(self):
        f = fixture(); i.install_worker_runtime(f.verifier, f.broker)
        actor = i.verify_worker_job(f.issuer.attach(login(303), payload()))
        with self.assertRaisesRegex(GatewayError, '^reconnect_required$'):
            i.require_ap_connection(actor)
        with self.assertRaisesRegex(GatewayError, '^signed_web_identity_required$'):
            i.require_ap_connection(None)
    def test_unsigned_legacy_name_cannot_impersonate_uid_namespace(self):
        self.assertEqual(i.adk_identity(None, 'legacy-alice'), 'legacy-alice')
        with self.assertRaisesRegex(GatewayError, '^reserved_uid_namespace_requires_signed_job$'):
            i.adk_identity(None, 'cmdbox_uid_101')
