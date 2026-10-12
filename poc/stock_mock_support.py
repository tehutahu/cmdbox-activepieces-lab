"""Literal mock stock MCP output. Never executes Google or a stock AP package."""
import json
import httpx
from cmdbox_gateway.stock_drive import dummy_bundle, parse_manifest
from cmdbox_gateway.lifecycle_live import LiveBindings, Target
from drive_mock_support import result_for


def configure_stock_backend(backend, registry):
    bundle = dummy_bundle(enabled=True)
    policies = {p.uid:p for p in parse_manifest(bundle['manifest'])}
    registry = LiveBindings(registry.store, [Target(p.uid,p.subject,p.project_id,p.flow()) for p in policies.values()])
    original = backend.handle
    def handle(request):
        if request.url.path != '/mcp':
            return original(request)
        assert request.url.host == 'mock-ap.invalid'
        access = request.headers.get('Authorization','').removeprefix('Bearer ')
        if access not in backend.accepted_access:
            return httpx.Response(401)
        uid, grant, _ = backend.accepted_access[access]
        if any(g == grant and revoked for _,g,revoked in backend.refreshes.values()):
            return httpx.Response(401)
        if request.method == 'GET':
            return httpx.Response(405)
        rpc = json.loads(request.content)
        if 'id' not in rpc:
            return httpx.Response(202)
        policy = policies[uid]
        method = rpc['method']
        if method == 'initialize':
            result = {'protocolVersion':rpc['params']['protocolVersion'],'capabilities':{'tools':{}},
                      'serverInfo':{'name':'LITERAL-MOCK-STOCK-CONTRACT','version':'0.92.2-contract'}}
        elif method == 'tools/list':
            result = {'tools':[{'name':policy.raw_name,'inputSchema':getattr(backend,'stock_tool_schema',{'type':'object','properties':{}})},
                               {'name':'ap_management_dummy','inputSchema':{'type':'object'}}]}
        elif method == 'tools/call':
            assert rpc['params'] == {'name':policy.raw_name,'arguments':{}}
            backend.raw_calls.append((uid,policy.raw_name))
            envelope = {'status':200,'headers':{},'body':{'response':getattr(backend,'stock_override',result_for(policy))}}
            if getattr(backend,'stock_after_call',None):
                backend.stock_after_call()
            text = '\u2705 Successfully executed flow Literal stock contract\n\nOutput:\n```json\n'+json.dumps(envelope)+'\n```'
            result = {'content':[{'type':'text','text':text}],'isError':False}
        else:
            raise AssertionError('Unapproved mock MCP operation')
        return httpx.Response(200,json={'jsonrpc':'2.0','id':rpc['id'],'result':result})
    backend.handle = handle
    return registry, bundle
