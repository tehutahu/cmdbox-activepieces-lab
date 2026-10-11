"""No socket or real AP: exercise signed queue handoff and per-invocation policy."""
import asyncio
from copy import deepcopy
from dataclasses import replace
import hashlib
import hmac
import json
import unittest
from cmdbox_gateway.core import *
from cmdbox_gateway.fixtures import *

class CoreTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.f = fixture()

    def actor(self, uid=101, name='alice', **kwargs):
        job = json.loads(json.dumps(self.f.issuer.attach(login(uid, name), payload(**kwargs))))
        return self.f.verifier.verify(job)

    def reject(self, code, action):
        with self.assertRaises(GatewayError) as caught:
            action()
        self.assertEqual(caught.exception.code, code)

    async def call(self, actor, **kwargs):
        binding = self.f.registry.resolve(actor.uid)
        opts = dict(alias='lab_identity', arguments={}, expected_uid=actor.uid, expected_generation=binding.generation)
        opts.update(kwargs)
        with invocation_scope(actor, 'same-chat'):
            return await self.f.broker.call(context(actor), **opts)

    async def test_verified_login_uid_not_client_display(self):
        actor = self.actor()
        self.assertEqual((actor.uid, actor.display_name, actor.adk_user_id), ('101', 'alice', 'cmdbox_uid_101'))
        renamed = self.actor(name='renamed')
        self.assertEqual(renamed.adk_user_id, actor.adk_user_id)
        session = login(); session['signin']['password'] = 'LITERAL_DUMMY_PASSWORD'
        encoded = json.dumps(self.f.issuer.attach(session, payload()))
        self.assertNotIn('password', encoded)
        self.assertNotIn('LITERAL_DUMMY_PASSWORD', encoded)

    async def test_missing_negative_boolean_or_string_uid_rejected(self):
        for source in ({}, {'signin': None}, None, login(-1), login(True), login('101')):
            self.reject('authenticated_login_uid_required', lambda: self.f.issuer.attach(source, payload()))

    async def test_body_uid_project_or_credential_ref_not_accepted(self):
        for field in ('uid', 'project_id', 'credential_ref', 'trusted_identity'):
            job = payload(); job[field] = '202'
            self.reject('unsupported_job_fields', lambda: self.f.issuer.attach(login(), job))

    async def test_no_unsigned_worker_identity(self):
        self.reject('signed_web_identity_required', lambda: self.f.verifier.verify(payload()))

    async def test_payload_tamper_rejected(self):
        for field, value in (('message', 'modified'), ('session_id', 'other'), ('user_name', 'bob'), ('mcpserver_apikey', 'DUMMY')):
            job = self.f.issuer.attach(login(), payload()); job[field] = value
            self.reject('queued_payload_modified', lambda: self.f.verifier.verify(job))

    async def test_identity_claim_tamper_rejected(self):
        job = self.f.issuer.attach(login(), payload()); job['trusted_identity']['claims']['uid'] = '202'
        self.reject('invalid_identity_signature', lambda: self.f.verifier.verify(job))

    async def test_expired_and_future_proofs_rejected(self):
        job = self.f.issuer.attach(login(), payload()); self.f.now[0] += 120
        self.reject('identity_expired_or_future', lambda: self.f.verifier.verify(job))
        job = self.f.issuer.attach(login(), payload()); self.f.now[0] -= 6
        self.reject('identity_expired_or_future', lambda: self.f.verifier.verify(job))

    async def test_audience_checked_even_with_valid_test_signature(self):
        job = self.f.issuer.attach(login(), payload())
        proof = job['trusted_identity']; proof['claims']['aud'] = 'other-worker'
        proof['signature'] = hmac.new(DUMMY_KEY, canonical(proof['claims']), hashlib.sha256).hexdigest()
        self.reject('identity_audience_mismatch', lambda: self.f.verifier.verify(job))

    async def test_replay_guard_shared_across_workers(self):
        guard = MemoryReplayGuard()
        a = WorkerJobVerifier(DUMMY_KEY, guard, clock=lambda: self.f.now[0])
        b = WorkerJobVerifier(DUMMY_KEY, guard, clock=lambda: self.f.now[0])
        job = self.f.issuer.attach(login(), payload()); a.verify(job)
        self.reject('identity_replay', lambda: b.verify(job))

    async def test_redis_guard_uses_atomic_nx_ttl_and_fail_closed(self):
        from threading import Lock
        class DummyRedis:
            def __init__(self):
                self.keys = {}; self.lock = Lock()
            def set(self, key, value, *, nx, ex):
                assert nx is True and value == '1' and 0 < ex <= 120
                assert key.startswith('cmdbox:ap-job:nonce:v1:') and len(key.rsplit(':', 1)[-1]) == 64
                with self.lock:
                    if key in self.keys: return None
                    self.keys[key] = value; return True
        shared = DummyRedis()
        first, second = RedisReplayGuard(shared), RedisReplayGuard(shared)
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(2) as pool:
            checks = list(pool.map(lambda g: g.claim('LITERAL_DUMMY_NONCE', 1800000120, 1800000000), [first, second]))
        self.assertEqual(sorted(checks), [False, True])
        class BrokenRedis:
            def set(self, *args, **kwargs): raise RuntimeError('LITERAL_DUMMY_CREDENTIAL')
        self.reject('replay_store_unavailable', lambda: RedisReplayGuard(BrokenRedis()).claim('DUMMY', 10, 0))

    async def test_context_required_and_reset_after_exception(self):
        actor = self.actor()
        self.reject('verified_invocation_required', lambda: actor_for_adk(context(actor)))
        with self.assertRaises(ValueError):
            with invocation_scope(actor, 'same-chat'):
                self.assertEqual(actor_for_adk(context(actor)).actor, actor)
                raise ValueError('synthetic')
        self.reject('verified_invocation_required', lambda: actor_for_adk(context(actor)))

    async def test_adk_identity_session_and_app_checks(self):
        actor = self.actor()
        with invocation_scope(actor, 'same-chat'):
            wrong = context(actor); wrong.user_id = 'cmdbox_uid_202'
            self.reject('adk_identity_mismatch', lambda: actor_for_adk(wrong))
            wrong = context(actor); wrong.session.user_id = 'cmdbox_uid_202'
            self.reject('adk_identity_mismatch', lambda: actor_for_adk(wrong))
            for attr in ('id', 'app_name'):
                wrong = context(actor); setattr(wrong.session, attr, 'other')
                self.reject('adk_session_mismatch', lambda: actor_for_adk(wrong))
            self.reject('adk_identity_mismatch', lambda: actor_for_adk(object()))
        self.reject('worker_session_mismatch', lambda: invocation_scope(actor, 'other').__enter__())

    async def test_parallel_same_chat_users_keep_distinct_binding_and_cache(self):
        a, b = self.actor(), self.actor(202, 'bob')
        outputs = await asyncio.gather(self.call(a), self.call(b))
        self.assertEqual([x['marker'] for x in outputs], ['A_ONLY', 'B_ONLY'])
        keys = [x['cache_key'] for x in self.f.transport.calls]
        self.assertEqual({x[0] for x in keys}, {'101', '202'})
        self.assertNotEqual(keys[0], keys[1])
        self.assertTrue(all(x['resource'] == RESOURCE for x in self.f.transport.calls))
        self.assertTrue(all(set(x) == {'marker', 'owner', 'kind'} for x in outputs))

    async def test_management_and_wildcard_policy_not_constructible(self):
        for name in ('ap_list_connections', 'ap_delete_flow', '*'):
            policy = replace(FLOW_A, raw_name=name)
            self.reject('invalid_synthetic_policy', lambda: BindingRegistry([policy]))

    async def test_alias_and_extra_arguments_denied(self):
        actor = self.actor()
        for alias in ('ap_list_flows', '*', FLOW_B.raw_name):
            with self.assertRaisesRegex(GatewayError, '^tool_not_allowed$'):
                await self.call(actor, alias=alias)
        for args in ({'uid': '202'}, {'project_id': 'DUMMY-PROJECT-B'}, {'tool': 'ap_list_connections'}):
            with self.assertRaisesRegex(GatewayError, '^invalid_tool_arguments$'):
                await self.call(actor, arguments=args)
        self.assertEqual(self.f.transport.calls, [])

    async def test_missing_binding_or_disabled_requires_reconnect(self):
        actor = self.actor(303)
        with invocation_scope(actor, 'same-chat'):
            self.reject('reconnect_required', lambda: self.f.broker.binding_for(context(actor)))
        self.f.registry.disable('101')
        self.reject('reconnect_required', lambda: self.f.registry.resolve('101'))

    async def test_no_credential_fallback(self):
        actor = self.actor(); self.f.credentials.active.clear()
        with self.assertRaisesRegex(GatewayError, '^reconnect_required$'):
            await self.call(actor)
        self.assertEqual(self.f.transport.calls, [])

    async def test_generation_cannot_rollback_or_reuse(self):
        row = self.f.registry.resolve('101')
        self.reject('binding_generation_must_increase', lambda: self.f.registry.bind(row))
        self.f.registry.bind(replace(row, generation=2))
        with self.assertRaisesRegex(GatewayError, '^stale_or_wrong_identity_tool$'):
            await self.call(self.actor(), expected_generation=1)

    async def test_wrong_cached_uid_rejected(self):
        with self.assertRaisesRegex(GatewayError, '^stale_or_wrong_identity_tool$'):
            await self.call(self.actor(202), expected_uid='101')
        self.assertEqual(self.f.transport.calls, [])

    async def test_disable_during_await_rejects_result(self):
        self.f.transport.after_call = lambda: self.f.registry.disable('101')
        with self.assertRaisesRegex(GatewayError, '^reconnect_required$'):
            await self.call(self.actor())

    async def test_change_generation_during_await_rejects_result(self):
        row = self.f.registry.resolve('101')
        self.f.transport.after_call = lambda: self.f.registry.bind(replace(row, generation=2))
        with self.assertRaisesRegex(GatewayError, '^stale_binding_result$'):
            await self.call(self.actor())

    async def test_remote_wrong_owner_and_error_text_not_exposed(self):
        async def wrong(**kwargs):
            return {'marker': 'B_ONLY', 'owner': 'B', 'kind': 'synthetic'}
        self.f.transport.call = wrong
        with self.assertRaisesRegex(GatewayError, '^unexpected_synthetic_result$'):
            await self.call(self.actor())
        async def fail(**kwargs):
            raise RuntimeError('LITERAL_DUMMY_SECRET_IN_REMOTE_BODY')
        self.f.transport.call = fail
        with self.assertRaisesRegex(GatewayError, '^upstream_unavailable$'):
            await self.call(self.actor())

if __name__ == '__main__':
    unittest.main()
