"""Actual ADK2.8 BaseToolset, with default-deny filtering and checks again at execution."""
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types
from .core import GatewayError

class GuardedIdentityTool(BaseTool):
    def __init__(self, broker, binding):
        super().__init__(name='lab_identity', description='Read your connected synthetic project marker.')
        self._broker, self._uid, self._generation = broker, binding.uid, binding.generation

    def _get_declaration(self):
        return types.FunctionDeclaration(name=self.name, description=self.description,
                                         parameters=types.Schema(type=types.Type.OBJECT, properties={}))

    async def run_async(self, *, args, tool_context):
        try:
            return await self._broker.call(tool_context, alias=self.name, arguments=args,
                                           expected_uid=self._uid, expected_generation=self._generation)
        except GatewayError as e:
            return {'error': e.code}  # No credential, binding record or arbitrary upstream body.

class ScopedSyntheticToolset(BaseToolset):
    def __init__(self, broker):
        super().__init__()
        self._broker = broker
        self._use_invocation_cache = False  # Contextless/cached discovery must re-check authority.

    async def get_tools(self, readonly_context=None):
        _, binding = self._broker.binding_for(readonly_context)
        return [GuardedIdentityTool(self._broker, binding)]

    async def close(self):
        pass  # Transport lifecycle is managed by the server-side provider, not an LLM tool.
