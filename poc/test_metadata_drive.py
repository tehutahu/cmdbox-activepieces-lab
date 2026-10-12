"""New alias/binding/result guard tests with official SDK and bundled action."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parent.parent
sys.path[:0] = [str(ROOT / 'runtimes/app-deps'), str(ROOT / 'poc'), str(ROOT / 'tools')]
from copy import deepcopy
from dataclasses import replace
import json
import unittest
from cmdbox_gateway.core import GatewayError, invocation_scope
from cmdbox_gateway.fixtures import fixture, login, payload, context
from cmdbox_gateway.metadata_drive import MetadataDriveBroker, MetadataMcpTransport, ALIAS, register_review_manifest, project_metadata_result
from cmdbox_gateway.metadata_adk import MetadataDriveToolset
from metadata_mock_support import DummyMetadataMcp, POLICIES, CONFIG


class MetadataTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.fx, self.mock = fixture(), DummyMetadataMcp()
        self.transport = MetadataMcpTransport(CONFIG, POLICIES, self.mock.async_client)
        self.broker = MetadataDriveBroker(self.fx.registry, self.fx.credentials, self.transport, POLICIES, resource=CONFIG.resource)

    async def call(self, uid=101, **kwargs):
        actor = self.fx.verifier.verify(self.fx.issuer.attach(login(uid), payload()))
        with invocation_scope(actor, 'same-chat'):
            return await self.broker.call(context(actor), **dict({'alias':ALIAS,'arguments':{},'expected_uid':str(uid),
                                                                'expected_generation':1}, **kwargs))

    async def test_sdk_to_actual_piece_empty_page_complete_and_incomplete_same_chat_separated(self):
        a, b = await self.call(), await self.call(202)
        self.assertEqual(a['files'][0]['id'], 'A_ONLY_SYNTHETIC_FILE')
        self.assertEqual(b['files'][0]['id'], 'B_ONLY_SYNTHETIC_FILE')
        self.assertTrue(a['complete']); self.assertFalse(b['complete'])
        self.assertEqual(b['stopReason'], 'incomplete_search')
        self.assertEqual(self.mock.piece_requests, [('101',2),('202',1)])
        self.assertNotIn('policyId', a); self.assertNotIn('pagesRead', a)

    async def test_no_query_authority_or_management_alias_before_io(self):
        for args in ({'q':'anything'},{'folderId':'OTHER'},{'uid':'202'},{'connection':'OTHER'},{'url':'https://other.invalid'}):
            with self.assertRaisesRegex(GatewayError,'invalid_tool_arguments'):
                await self.call(arguments=args)
        with self.assertRaisesRegex(GatewayError,'tool_not_allowed'):
            await self.call(alias='ap_management_dummy')
        self.assertEqual(self.mock.calls,[])

    async def test_exact_subject_project_flow_binding(self):
        original=self.fx.registry.resolve('101')
        for changes in ({'subject':'DUMMY-OTHER'}, {'project_id':'DUMMY-OTHER'},
                        {'flow':replace(self.fx.registry.resolve('101').flow,flow_id='DUMMY-OTHER')}):
            self.fx.registry._rows['101']=original
            current=original
            if 'flow' in changes:
                # A trusted control-plane row corruption must also fail closed.
                self.fx.registry._rows['101']=replace(current,**changes)
            else:
                self.fx.registry.bind(replace(current, generation=current.generation+1, **changes))
            with self.assertRaisesRegex(GatewayError,'metadata_binding_policy_mismatch'):
                await self.call()
        self.assertEqual(self.mock.calls,[])

    async def test_stale_tool_wrong_uid_and_revoke_denied_before_io(self):
        for kwargs in ({'expected_uid':'202'},{'expected_generation':2}):
            with self.assertRaisesRegex(GatewayError,'stale_or_wrong_identity_tool'):
                await self.call(**kwargs)
        self.fx.credentials.active.pop('dummy-ref-a')
        with self.assertRaisesRegex(GatewayError,'reconnect_required'):
            await self.call()
        self.assertEqual(self.mock.calls,[])

    async def test_late_generation_change_discards_piece_result(self):
        self.mock.after_call=lambda:self.fx.registry.disable('101')
        with self.assertRaises(GatewayError):await self.call()

    async def test_discovery_extra_input_property_rejected(self):
        self.mock.schema_extra=True
        # Anyio may wrap the internal schema denial; only sanitized errors escape.
        with self.assertRaises(GatewayError):await self.call()
        self.assertEqual(self.mock.calls,[])

    async def test_wrong_policy_or_hidden_credential_rejected(self):
        self.mock.override=self.mock.execute_piece(POLICIES[1])
        with self.assertRaisesRegex(GatewayError,'metadata_result_contract_mismatch'):await self.call()
        self.mock.override=self.mock.execute_piece(POLICIES[0])
        self.mock.override['files'][0]['access_token']='LITERAL-DUMMY'
        with self.assertRaisesRegex(GatewayError,'metadata_fields_invalid'):await self.call()

    async def test_contextless_tool_discovery_denied(self):
        with self.assertRaises(GatewayError):await MetadataDriveToolset(self.broker).get_tools()

    def test_default_off_manifest_and_unreviewed_fields(self):
        manifest=json.loads((ROOT/'templates/drive-metadata-registration.json').read_bytes())
        with self.assertRaisesRegex(GatewayError,'metadata_registration_disabled'):register_review_manifest(manifest)
        manifest['enabled']=True
        self.assertEqual(register_review_manifest(manifest),POLICIES)
        for mutate in (lambda v:v['piece'].update(version='9.9.9'),lambda v:v['bindings'][0].update(access_token='LITERAL-DUMMY'),
                       lambda v:v['bindings'].append(v['bindings'][0]),lambda v:v['bindings'][0].update(folder_id='root')):
            bad=deepcopy(manifest);mutate(bad)
            with self.assertRaises(GatewayError):register_review_manifest(bad)

    def test_completion_and_output_limits_fail_closed(self):
        good=self.mock.execute_piece(POLICIES[0])
        for changes in ({'complete':False},{'stopReason':'page_limit'},{'rowsRead':21},{'pagesRead':6},
                        {'incompleteSearch':True},{'nextPageToken':'LITERAL-DUMMY'}):
            bad=dict(good,**changes)
            with self.assertRaises(GatewayError):project_metadata_result(bad,POLICIES[0].policy_id)

    def test_independent_template_fixed_and_disabled(self):
        from build_drive_metadata_template import build
        prepared=build()
        self.assertEqual(prepared,json.loads((ROOT/'templates/drive-metadata-flow-preparation.json').read_bytes()))
        trigger=prepared['request']['trigger'];search=trigger['nextAction']
        self.assertEqual(trigger['settings']['input']['inputSchema'],[])
        self.assertEqual(search['settings']['pieceName'],'@cmdbox-lab/piece-drive-metadata-search')
        self.assertEqual(search['settings']['pieceVersion'],'0.1.0')
        self.assertEqual(search['settings']['input']['maxFiles'],20)
        self.assertEqual(search['settings']['input']['maxPages'],5)
        self.assertEqual(search['nextAction']['settings']['input']['response'],{'response':'{{step_1}}'})
        self.assertTrue(all(not step['valid'] for step in (trigger,search,search['nextAction'])))


if __name__ == '__main__':unittest.main()
