import unittest
from cmdbox_gateway.config import validate_tool_config, static_headers, validate_bootstrap
from cmdbox_gateway.core import GatewayError
from cmdbox_gateway.fixtures import fixture

UID = {'mcpserver_auth_mode':'user_ap_binding','mcpserver_mcp_tools':['lab_identity']}
STATIC = {'mcpserver_auth_mode':'static_api_key','mcpserver_mcp_tools':['shared_marker'],
          'mcpserver_url':'https://static-tool.invalid/mcp','mcpserver_apikey':'LITERAL-DUMMY-COMMON'}

class ConfigTests(unittest.TestCase):
    def test_explicit_paths_and_static_headers(self):
        self.assertEqual(validate_tool_config(UID), 'user_ap_binding')
        self.assertEqual(static_headers(STATIC), {'Authorization':'Bearer LITERAL-DUMMY-COMMON'})
    def test_mixed_missing_and_unknown_configs_fail(self):
        for config in ({}, {**UID,'mcpserver_apikey':'LITERAL-DUMMY'},
                       {**STATIC,'mcpserver_delegated_auth':True}, {**STATIC,'mcpserver_apikey':''},
                       {**STATIC,'mcpserver_transport':'unknown'}, {**UID,'mcpserver_mcp_tools':[]},
                       {**STATIC,'mcpserver_mcp_tools':['*']}, {**STATIC,'mcpserver_mcp_tools':['shared_marker','shared_marker']},
                       {**STATIC,'mcpserver_apikey':'LITERAL-DUMMY\nHEADER'}):
            with self.subTest(config=config), self.assertRaises(GatewayError): validate_tool_config(config)
    def test_missing_runtime_and_memory_guard_cannot_bootstrap_uid(self):
        f = fixture()
        for issuer,verifier,broker in ((None,f.verifier,f.broker),(f.issuer,None,f.broker),(f.issuer,f.verifier,None),(f.issuer,f.verifier,f.broker)):
            with self.assertRaises(GatewayError):
                validate_bootstrap([UID],issuer=issuer,verifier=verifier,broker=broker,shared_replay_guard=f.verifier._guard)
    def test_static_only_bootstrap_does_not_require_uid_broker(self):
        self.assertEqual(validate_bootstrap([STATIC],issuer=None,verifier=None,broker=None,shared_replay_guard=None), ['static_api_key'])
