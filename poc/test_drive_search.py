"""New Drive preparation only: dummy MCP SDK I/O and verified UID contracts."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'runtimes' / 'app-deps'), str(ROOT / 'poc'), str(ROOT / 'tools')]
from copy import deepcopy
from dataclasses import replace
import unittest
from cmdbox_gateway.core import GatewayError, invocation_scope
from cmdbox_gateway.fixtures import fixture, login, payload, context
from cmdbox_gateway.drive_search import PreparedDriveBroker, project_result, ALIAS
from cmdbox_gateway.mcp_live import PinnedMcpTransport
from drive_mock_support import DummyDriveMcp, POLICIES, CONFIG, result_for
from build_drive_search_template import build


class DriveContractTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fx = fixture()
        self.mock = DummyDriveMcp()
        transport = PinnedMcpTransport(CONFIG, POLICIES, self.mock.async_client)
        self.broker = PreparedDriveBroker(self.fx.registry, self.fx.credentials, transport, POLICIES, resource=CONFIG.resource)

    async def call(self, uid=101, alias=ALIAS, arguments=None, expected_uid=None, generation=1):
        actor = self.fx.verifier.verify(self.fx.issuer.attach(login(uid), payload()))
        with invocation_scope(actor, 'same-chat'):
            return await self.broker.call(context(actor), alias=alias, arguments={} if arguments is None else arguments,
                                          expected_uid=str(uid) if expected_uid is None else expected_uid,
                                          expected_generation=generation)

    async def test_actual_sdk_same_chat_uids_separated(self):
        a, b = await self.call(), await self.call(202)
        self.assertIn('A_ONLY', a['files'][0]['id'])
        self.assertIn('B_ONLY', b['files'][0]['id'])
        self.assertEqual([uid for uid, _ in self.mock.calls], ['101', '202'])
        self.assertNotIn('policyId', a)
        self.assertNotIn('modifiedTime', a['files'][0])

    async def test_model_cannot_supply_authority_or_query(self):
        for args in ({'q': 'anything'}, {'folder': 'OTHER'}, {'uid': '202'}, {'connection': 'OTHER'}, {'url': 'https://other.invalid'}):
            with self.subTest(args=args), self.assertRaises(GatewayError):
                await self.call(arguments=args)
        self.assertEqual(self.mock.calls, [])

    async def test_management_alias_denied_before_io(self):
        with self.assertRaisesRegex(GatewayError, 'tool_not_allowed'):
            await self.call(alias='ap_management_dummy')
        self.assertEqual(self.mock.calls, [])

    async def test_stale_tool_wrong_uid_denied_before_io(self):
        for kwargs in ({'expected_uid': '202'}, {'generation': 2}):
            with self.assertRaisesRegex(GatewayError, 'stale_or_wrong_identity_tool'):
                await self.call(**kwargs)
        self.assertEqual(self.mock.calls, [])

    async def test_project_policy_mismatch_denied(self):
        self.fx.registry.bind(replace(self.fx.registry.resolve('101'), project_id='DUMMY-OTHER-PROJECT', generation=2))
        with self.assertRaisesRegex(GatewayError, 'drive_binding_policy_mismatch'):
            await self.call(generation=2)
        self.assertEqual(self.mock.calls, [])

    async def test_revoked_credential_denied(self):
        self.fx.credentials.active.pop('dummy-ref-a')
        with self.assertRaisesRegex(GatewayError, 'reconnect_required'):
            await self.call()
        self.assertEqual(self.mock.calls, [])

    async def test_late_revoke_discards_result(self):
        self.mock.after_call = lambda: self.fx.registry.bind(replace(self.fx.registry.resolve('101'), generation=2, status='RECONNECT_REQUIRED'))
        with self.assertRaises(GatewayError):
            await self.call()

    async def test_other_uid_reply_policy_denied(self):
        self.mock.override = result_for(POLICIES[1])
        with self.assertRaisesRegex(GatewayError, 'drive_result_contract_mismatch'):
            await self.call()

    async def test_credential_field_denied_in_sdk_reply(self):
        self.mock.override = result_for(POLICIES[0])
        self.mock.override['files'][0]['access_token'] = 'LITERAL-DUMMY-NOT-A-TOKEN'
        with self.assertRaisesRegex(GatewayError, 'drive_metadata_fields_invalid'):
            await self.call()

    async def test_contextless_discovery_denied(self):
        from cmdbox_gateway.drive_adk import PreparedDriveToolset
        with self.assertRaises(GatewayError):
            await PreparedDriveToolset(self.broker).get_tools()

    def test_output_shape_limits_and_no_completeness_claim(self):
        good = result_for(POLICIES[0])
        bad_cases = []
        bad = deepcopy(good); bad['completion'] = 'complete'; bad_cases.append(bad)
        bad = deepcopy(good); bad['files'] *= 21; bad_cases.append(bad)
        bad = deepcopy(good); bad['files'] *= 2; bad_cases.append(bad)
        bad = deepcopy(good); bad['files'][0]['name'] = 'line\nbreak'; bad_cases.append(bad)
        bad = deepcopy(good); bad['files'][0]['mimeType'] = 'application/vnd.google-apps.folder'; bad_cases.append(bad)
        bad = deepcopy(good); bad['files'][0]['modifiedTime'] = 'invalid'; bad_cases.append(bad)
        bad = deepcopy(good); bad['files'][0]['id'] = '../file'; bad_cases.append(bad)
        bad = deepcopy(good); bad['headers'] = {}; bad_cases.append(bad)
        for bad in bad_cases:
            with self.subTest(bad=bad), self.assertRaises(GatewayError):
                project_result(bad, POLICIES[0].policy_id)
        good['files'] = []
        self.assertEqual(project_result(good, POLICIES[0].policy_id)['files'], [])

    def test_prepared_template_fixed_and_unvalidated(self):
        import json
        prepared = build()
        self.assertEqual(prepared, json.loads((ROOT / 'templates' / 'drive-search-preparation.json').read_text()))
        trigger = prepared['request']['trigger']
        self.assertEqual(trigger['settings']['input']['inputSchema'], [])
        search = trigger['nextAction']
        self.assertFalse(trigger['valid'])
        self.assertFalse(search['valid'])
        self.assertEqual(search['settings']['pieceVersion'], '0.11.0')
        self.assertEqual(search['settings']['input']['value'], 'CMDBOX_LAB_ONLY')
        self.assertFalse(search['settings']['input']['include_team_drives'])


if __name__ == '__main__':
    unittest.main()
