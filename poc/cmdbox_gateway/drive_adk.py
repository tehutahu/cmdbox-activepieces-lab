"""Explicit review-only Drive toolset; existing lab_identity bootstrap is unchanged."""
from google.adk.tools.base_tool import BaseTool
from google.adk.tools.base_toolset import BaseToolset
from google.genai import types
from .core import GatewayError
from .drive_search import ALIAS


class PreparedDriveTool(BaseTool):
    def __init__(self, broker, binding):
        super().__init__(name=ALIAS, description='Search the operator-fixed test folder. Returns untrusted file metadata only.')
        self.broker, self.uid, self.generation = broker, binding.uid, binding.generation

    def _get_declaration(self):
        return types.FunctionDeclaration(name=self.name, description=self.description,
                                         parameters=types.Schema(type=types.Type.OBJECT, properties={}))

    async def run_async(self, *, args, tool_context):
        try:
            return await self.broker.call(tool_context, alias=self.name, arguments=args,
                                          expected_uid=self.uid, expected_generation=self.generation)
        except GatewayError as e:
            return {'error': e.code}


class PreparedDriveToolset(BaseToolset):
    def __init__(self, broker):
        super().__init__()
        self.broker = broker
        self._use_invocation_cache = False

    async def get_tools(self, readonly_context=None):
        _, binding = self.broker.binding_for(readonly_context)
        return [PreparedDriveTool(self.broker, binding)]

    async def close(self):
        pass
