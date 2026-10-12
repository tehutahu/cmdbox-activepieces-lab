"""Stock production registration contracts; literal provider/SDK only."""
from pathlib import Path
import sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT/'runtimes/app-deps'),str(ROOT/'poc')]
from copy import deepcopy
import json
import tempfile
import unittest
from contextlib import closing
from cmdbox_gateway.core import GatewayError, invocation_scope
from cmdbox_gateway.fixtures import fixture as identity_fixture, login, payload, context
from cmdbox_gateway.config import validate_tool_config, validate_bootstrap
from cmdbox_gateway import integration
from cmdbox_gateway.stock_drive import dummy_bundle, parse_manifest, verify_prepared_flow, verified_settings, StockDriveBroker
from cmdbox_gateway.stock_mcp import StockMcpTransport
from cmdbox_gateway.stock_retention import purge_local_tokens, purge_owned_metadata
from cmdbox_gateway.lifecycle_live import LiveLifecycle
from mock_live_support import fixture, LiteralEntropy, connect
from stock_mock_support import configure_stock_backend
from drive_mock_support import result_for


class WindowFixture:
    def __init__(self): self.open=True;self.count={}
    def valid(self): return self.open
    def spend(self,uid,operation,maximum):
        from cmdbox_gateway.core import require
        require(self.open,'authorization_window_closed')
        key=(uid,operation);n=self.count.get(key,0)
        require(n<maximum,'approved_operation_budget_exhausted');self.count[key]=n+1


class StockTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(dir=ROOT/'app-lab/data',prefix='stock-unit-')
        self.root=Path(self.temp.name)
        self.backend,self.config,self.client,registry,_=fixture(self.root/'literal-vault')
        self.registry,self.bundle=configure_stock_backend(self.backend,registry)
        from cmdbox_gateway.oauth_live import OAuthHttpClient
        import httpx
        self.client.close()
        self.client=httpx.Client(transport=httpx.MockTransport(self.backend.handle),trust_env=False,follow_redirects=False)
        self.provider=OAuthHttpClient(self.config,self.client);self.provider.discover()
        self.life=LiveLifecycle(self.registry,self.provider,LiteralEntropy())
        connect(self.backend,self.life,'101');connect(self.backend,self.life,'202')
        self.policies=parse_manifest(self.bundle['manifest']);self.window=WindowFixture()
        self.broker=StockDriveBroker(self.registry,self.life,StockMcpTransport(self.config,self.policies,self.backend.async_client),
                                    self.policies,resource=self.config.resource,window=self.window)
        self.fx=identity_fixture()
        self.saved=(integration._issuer,integration._verifier,integration._broker)
    def tearDown(self):
        integration._issuer,integration._verifier,integration._broker=self.saved
        self.client.close();self.temp.cleanup()
    async def call(self,uid=101,**overrides):
        actor=self.fx.verifier.verify(self.fx.issuer.attach(login(uid),payload()))
        kwargs=dict(alias='lab_drive_search',arguments={},expected_uid=str(uid),expected_generation=self.registry.resolve(str(uid)).generation)
        kwargs.update(overrides)
        with invocation_scope(actor,'same-chat'):
            return await self.broker.call(context(actor),**kwargs)

    async def test_sdk_same_chat_uid_and_minimum_metadata(self):
        a,b=await self.call(),await self.call(202)
        self.assertIn('A_ONLY',a['files'][0]['id']);self.assertIn('B_ONLY',b['files'][0]['id'])
        self.assertEqual(set(a['files'][0]),{'id','name','mimeType'})
        self.assertEqual([uid for uid,_ in self.backend.raw_calls],['101','202'])
        self.assertEqual(a['completion'],'unverified-by-stock-piece')
    async def test_selected_toolset_uses_production_factory(self):
        integration.install_worker_runtime(self.fx.verifier,self.broker)
        from cmdbox_gateway.drive_adk import PreparedDriveToolset
        self.assertIsInstance(integration.approved_ap_toolset(),PreparedDriveToolset)
        integration.install_worker_runtime(self.fx.verifier,self.fx.broker)
        from cmdbox_gateway.adk_adapter import ScopedSyntheticToolset
        self.assertIsInstance(integration.approved_ap_toolset(),ScopedSyntheticToolset)
    async def test_arguments_management_wrong_uid_and_stale_generation_no_io(self):
        for overrides in ({'arguments':{'q':'other'}},{'alias':'ap_management_dummy'},
                          {'expected_uid':'202'},{'expected_generation':2}):
            with self.subTest(overrides=overrides),self.assertRaises(GatewayError):await self.call(**overrides)
        self.assertEqual(self.backend.raw_calls,[]);self.assertEqual(self.window.count,{})
    async def test_refresh_changes_generation_and_revoke_stops_tool(self):
        await self.call();self.life.renew('101',1,force=True)
        with self.assertRaises(GatewayError):await self.call(expected_generation=1)
        self.assertIn('A_ONLY',(await self.call())['files'][0]['id'])
        self.life.revoke('101')
        with self.assertRaises(GatewayError):await self.call()
        self.assertEqual(len(self.backend.raw_calls),2)
    async def test_closed_window_rejects_before_refresh_or_sdk(self):
        self.window.open=False
        with self.assertRaisesRegex(GatewayError,'authorization_window_closed'):await self.call()
        self.assertEqual(self.backend.raw_calls,[])
    async def test_manifest_binding_mismatch_before_io(self):
        from dataclasses import replace
        self.broker.policies['101']=replace(self.policies[0],flow_id='DUMMY-OTHER-FLOW')
        with self.assertRaisesRegex(GatewayError,'stock_binding_manifest_mismatch'):await self.call()
        self.assertEqual(self.backend.raw_calls,[])
    async def test_sdk_schema_change_refuses_call(self):
        self.backend.stock_tool_schema={'type':'object','properties':{'q':{'type':'string'}}}
        with self.assertRaises(GatewayError):await self.call()
        self.assertEqual(self.backend.raw_calls,[])
        self.assertEqual(self.life.status('101')['status'],'RECONNECT_REQUIRED')
    async def test_result_over_reply_cap_revokes_only_owner(self):
        body=result_for(self.policies[0]);body['files']*=21;self.backend.stock_override=body
        with self.assertRaisesRegex(GatewayError,'drive_result_limit_exceeded'):await self.call()
        self.assertEqual(self.life.status('101')['status'],'RECONNECT_REQUIRED')
        self.assertEqual(self.life.status('202')['status'],'ACTIVE')
    async def test_wrong_policy_reply_refused(self):
        self.backend.stock_override=result_for(self.policies[1])
        with self.assertRaisesRegex(GatewayError,'drive_result_contract_mismatch'):await self.call()
    async def test_late_revoke_discards_response(self):
        self.backend.stock_after_call=lambda:self.life.revoke('101')
        with self.assertRaises(GatewayError):await self.call()
    def test_manifest_requires_fixed_safe_inputs_disabled_and_dummy_actual_rejected(self):
        with self.assertRaises(GatewayError):parse_manifest(dummy_bundle()['manifest'])
        with self.assertRaises(GatewayError):parse_manifest(self.bundle['manifest'],actual=True)
        for term in ("x' or 'x",'x\\y','x\n', '日本語',''):
            bad=deepcopy(self.bundle['manifest']);bad['bindings'][0]['term']=term
            with self.subTest(term=term),self.assertRaises(GatewayError):parse_manifest(bad)
        bad=deepcopy(self.bundle['manifest']);bad['limits']['googlePages']=5
        with self.assertRaises(GatewayError):parse_manifest(bad)
    def test_receipt_tamper_and_target_collision_denied(self):
        for p in self.policies:verify_prepared_flow(self.bundle['flows'][p.uid],p)
        bad=deepcopy(self.bundle['flows']['101']);bad['request']['trigger']['nextAction']['settings']['input']['value']='OTHER'
        with self.assertRaises(GatewayError):verify_prepared_flow(bad,self.policies[0])
        bad=deepcopy(self.bundle['manifest']);bad['bindings'][1]['uid']='101'
        with self.assertRaises(GatewayError):parse_manifest(bad)
        settings={'stock_drive':self.bundle['manifest'],'stock_flow_receipts':self.bundle['flows']}
        self.assertEqual(verified_settings(settings,self.registry.targets),self.policies)
    def test_schema_preflight_and_bootstrap_mismatch_fail_closed(self):
        config={'mcpserver_auth_mode':'user_ap_binding','mcpserver_mcp_tools':['lab_drive_search']}
        self.assertEqual(validate_tool_config(config),'user_ap_binding')
        with self.assertRaises(GatewayError):validate_tool_config({**config,'mcpserver_apikey':'LITERAL_DUMMY'})
        with self.assertRaisesRegex(GatewayError,'uid_broker_alias_mismatch'):
            validate_bootstrap([config],issuer=self.fx.issuer,verifier=self.fx.verifier,broker=self.fx.broker,shared_replay_guard=None)
        integration.install_worker_runtime(self.fx.verifier,self.fx.broker)
        with self.assertRaisesRegex(GatewayError,'uid_broker_alias_mismatch'):integration.preflight_tools([config],None)
    def test_failed_revoke_retains_only_formal_cleanup_metadata(self):
        self.backend.revoke_failure=True
        self.life.revoke('101');self.life.revoke('202')
        with self.registry.store.db() as db:db.execute("INSERT INTO leases VALUES ('999',999,0,0)")
        with self.assertRaisesRegex(GatewayError,'stock_retention_scope_mismatch'):purge_local_tokens(self.registry)
        with self.registry.store.db() as db:
            self.assertEqual(db.execute("SELECT count(*) FROM leases WHERE uid='999'").fetchone()[0],1)
            db.execute("DELETE FROM leases WHERE uid='999'")
        self.assertTrue(purge_local_tokens(self.registry)['localTokenMaterialRemoved'])
        with self.registry.store.db() as db:
            for uid in ('101','202'):self.assertIsNone(self.registry.store.row(db,uid)[2]['tokens'])
            rows=db.execute('SELECT * FROM cleanup').fetchall();self.assertEqual(len(rows),2)
            for row in rows:
                item=self.registry.store.decode('cleanup',row['id'],row['envelope'])
                self.assertIsNone(item['refresh']);self.assertFalse(item['submitted']);self.assertTrue(item['grant'])
    def test_retention_refuses_unowned_database_rows(self):
        import sqlite3
        data=self.root/'native-data';data.mkdir()
        with closing(sqlite3.connect(data/'history.sqlite')) as db, db:
            db.execute('CREATE TABLE sessions(app_name TEXT,user_id TEXT)')
            db.execute("INSERT INTO sessions VALUES ('other_app','cmdbox_uid_101')")
        self.assertFalse(purge_owned_metadata(data,self.root,['101'])['metadataRemoved'])
        with closing(sqlite3.connect(data/'history.sqlite')) as db:self.assertEqual(db.execute('SELECT count(*) FROM sessions').fetchone()[0],1)
    def test_read_only_retention_keeps_owned_and_unowned_rows(self):
        import sqlite3
        from cmdbox_gateway.stock_retention import retain_owned_metadata
        data=self.root/'native-data';data.mkdir()
        path=data/'history.sqlite'
        with closing(sqlite3.connect(path)) as db, db:
            db.execute('CREATE TABLE sessions(app_name TEXT,user_id TEXT)')
            db.execute("INSERT INTO sessions VALUES ('adapter_lab','cmdbox_uid_101')")
        before=path.read_bytes()
        result=retain_owned_metadata(data,self.root,['101'])
        self.assertTrue(result['metadataRetained'] and result['metadataScopeVerified'])
        self.assertFalse(result['metadataRemoved'] or result['permanentDeletionPerformed'])
        self.assertEqual(path.read_bytes(),before)
        with closing(sqlite3.connect(path)) as db, db:
            db.execute("INSERT INTO sessions VALUES ('other_app','cmdbox_uid_999')")
        before=path.read_bytes()
        result=retain_owned_metadata(data,self.root,['101'])
        self.assertTrue(result['operatorReviewRequired'])
        self.assertFalse(result['metadataScopeVerified'])
        self.assertEqual(path.read_bytes(),before)
    def test_schema27_whole_step_is_rejected_and_output_array_passes(self):
        from cmdbox_gateway.drive_search import project_result
        policy=self.policies[0];body=result_for(policy)
        old=deepcopy(body)
        old['files']={'input':{},'output':body['files'],'status':'SUCCEEDED'}
        with self.assertRaisesRegex(GatewayError,'drive_result_limit_exceeded'):
            project_result(old,policy.policy_id)
        self.assertEqual(len(project_result(body,policy.policy_id)['files']),len(body['files']))
        for flow in self.bundle['flows'].values():
            reply=flow['request']['trigger']['nextAction']['nextAction']['settings']['input']
            self.assertEqual(reply['response']['response']['files'],"{{step_1['output']}}")
    def test_public_template_disabled_and_reproducible(self):
        self.assertEqual(json.loads((ROOT/'templates/stock-drive-runtime.json').read_text()),dummy_bundle())

if __name__=='__main__':unittest.main()
