"""Explicit metadata alias factory; never registered by identity-only bootstrap."""
from .drive_adk import PreparedDriveTool, PreparedDriveToolset
from .metadata_drive import ALIAS


class MetadataDriveTool(PreparedDriveTool):
    def __init__(self, broker, binding):
        super().__init__(broker, binding)
        self.name = ALIAS
        self.description = 'Search the operator-fixed direct folder. Returns untrusted names/IDs/MIME types and bounded completion status.'


class MetadataDriveToolset(PreparedDriveToolset):
    async def get_tools(self, readonly_context=None):
        _, binding = self.broker.binding_for(readonly_context)
        return [MetadataDriveTool(self.broker, binding)]
