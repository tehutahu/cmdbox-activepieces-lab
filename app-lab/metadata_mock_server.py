"""Native mock bootstrap for the actual local metadata piece action.

Reuses the frozen Drive harness's socket restrictions and scripted ADK model.
No live bootstrap, Connection, AP, Google or external LLM is activated.
"""
import sys
import threading
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
import drive_mock_server as harness
from cmdbox_gateway import integration
from cmdbox_gateway.metadata_drive import MetadataDriveBroker, MetadataMcpTransport, ALIAS
from cmdbox_gateway.metadata_adk import MetadataDriveToolset
from metadata_mock_support import DummyMetadataMcp, CONFIG, POLICIES
import uvicorn

server = harness.server


class TracedMetadataMcp(MetadataMcpTransport):
    async def call(self, **kwargs):
        result = await super().call(**kwargs)
        key = kwargs['cache_key']
        server.trace('metadata_mock_sdk_search', uid=key[0], session_id=key[2], generation=key[6],
                     pagesRead=result['pagesRead'], complete=result['complete'], stopReason=result['stopReason'])
        return result


mock = DummyMetadataMcp()
server.broker = MetadataDriveBroker(server.registry, server.lifecycle,
    TracedMetadataMcp(CONFIG, POLICIES, mock.async_client), POLICIES, resource=CONFIG.resource)
harness.ALIAS = ALIAS  # Changes this process's scripted fixture declaration only.
integration.approved_ap_toolset = lambda: MetadataDriveToolset(server.broker)

if __name__ == '__main__':
    http = uvicorn.Server(uvicorn.Config(server.app, host='127.0.0.1', port=server.PORT,
                                       ws='wsproto', log_level='warning', access_log=False))
    def control():
        for line in sys.stdin:
            if line.strip() == 'STOP':
                http.should_exit = True
                return
    threading.Thread(target=control, daemon=True).start()
    http.run()
