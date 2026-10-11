"""Test factory injected at the native MCPToolset construction seam; no socket."""
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types
from cmdbox_gateway.core import require, actor_for_adk

class SharedMarker(BaseTool):
    def __init__(self, headers):
        super().__init__(name='shared_marker',description='Read the shared dummy tool marker.')
        self.headers = headers
    def _get_declaration(self):
        return types.FunctionDeclaration(name=self.name,description=self.description,
                                         parameters=types.Schema(type=types.Type.OBJECT,properties={}))
    async def run_async(self, *, args, tool_context):
        actor_for_adk(tool_context)
        require(args == {} and self.headers(tool_context) == {'Authorization':'Bearer LITERAL-DUMMY-COMMON'},
                'static_dummy_refused')
        return {'marker':'COMMON_ONLY','kind':'synthetic'}

class StaticMockToolset(BaseToolset):
    def __init__(self, *, connection_params, tool_filter, header_provider, **kwargs):
        super().__init__()
        require(connection_params.url == 'https://static-tool.invalid/mcp' and tool_filter == ['shared_marker'],
                'static_dummy_config_required')
        self.headers = header_provider
        self._use_invocation_cache = False
    async def get_tools(self, readonly_context=None):
        actor_for_adk(readonly_context)
        return [SharedMarker(self.headers)]
    async def close(self): pass
