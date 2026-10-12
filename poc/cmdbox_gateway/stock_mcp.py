"""Stock-flow official SDK adapter: empty arguments and bounded reply only.

These app reply limits do not stop the stock Google action's upstream pagination.
"""
import re
from .core import GatewayError, require
from .mcp_live import PinnedMcpTransport, parse_pinned_flow_output
from .oauth_live import OAuthConfig


class StockMcpTransport(PinnedMcpTransport):
    def __init__(self, config, policies, factory):
        require(isinstance(config, OAuthConfig) and callable(factory), 'explicit_mcp_client_factory_required')
        self.config, self.factory = config, factory
        self.flows = frozenset(p.raw_name for p in policies)
        require(bool(self.flows) and all(re.fullmatch(r'lab_drive_search_[A-Za-z0-9_]+_mcp', n) for n in self.flows),
                'stock_manifest_invalid')

    async def _sdk_call(self, resource, headers, raw_name):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        def clean(*args, **kwargs):
            client = self.factory(*args, **kwargs)
            require(not client.follow_redirects and not client.trust_env and client.auth is None and not client.cookies,
                    'mcp_clean_explicit_client_required')
            return client
        try:
            async with streamablehttp_client(resource, headers=headers, timeout=5, sse_read_timeout=5,
                                             terminate_on_close=False, httpx_client_factory=clean) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    tools = [t for t in (await session.list_tools()).tools if t.name == raw_name]
                    require(len(tools) == 1 and tools[0].inputSchema.get('type') == 'object'
                            and tools[0].inputSchema.get('properties', {}) == {} and not tools[0].inputSchema.get('required')
                            and tools[0].inputSchema.get('additionalProperties') is not True, 'stock_tool_schema_mismatch')
                    result = await session.call_tool(raw_name, {})
                    require(not result.isError and len(result.content) == 1 and result.content[0].type == 'text'
                            and len(result.content[0].text) <= 40960, 'stock_tool_reply_invalid')
                    return parse_pinned_flow_output(result.content[0].text)
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('mcp_upstream_unavailable') from None
