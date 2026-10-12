"""Explicit official MCP SDK streamable-HTTP transport, no default client/cache.

Each invocation gets a fresh SDK session and configured raw identity tool only.
The current phase supplies an httpx.MockTransport factory, never a real socket.
"""
import asyncio
import json
import re
from .core import GatewayError, require
from .oauth_live import OAuthConfig, token_text


def parse_pinned_flow_output(text):
    # AP0.92.2 mcp-server-builder wraps WebhookResponse in one JSON code block.
    # No arbitrary recursive key search, prompt parsing or header passthrough.
    match = re.fullmatch(r'✅ Successfully executed flow [^\r\n]{1,200}\n\nOutput:\n```json\n(.*)\n```', text, flags=re.DOTALL)
    require(match is not None, 'mcp_pinned_result_format_mismatch')
    try:
        envelope = json.loads(match[1])
        require(type(envelope) is dict and type(envelope.get('status')) is int and 200 <= envelope['status'] < 300,
                'mcp_flow_response_invalid')
        body = envelope.get('body')
        if type(body) is str:
            body = json.loads(body)
        require(type(body) is dict, 'mcp_flow_response_invalid')
        # The pinned DynamicProperties reply prop is {response: {...}}. Accept
        # that single explicit wrapper, not recursive searching for a marker.
        if set(body) == {'response'}:
            body = body['response']
            require(type(body) is dict and 'response' not in body, 'mcp_flow_response_invalid')
        return body
    except GatewayError:
        raise
    except Exception:
        raise GatewayError('mcp_flow_response_invalid') from None


class PinnedMcpTransport:
    def __init__(self, config, flows, httpx_client_factory):
        require(isinstance(config, OAuthConfig) and callable(httpx_client_factory), 'explicit_mcp_client_factory_required')
        self.config, self.flows, self.factory = config, frozenset(f.raw_name for f in flows), httpx_client_factory
        require(bool(self.flows) and all(x.endswith('_mcp') and not x.startswith('ap_') for x in self.flows), 'synthetic_mcp_manifest_required')

    async def call(self, *, resource, headers, raw_name, arguments, cache_key):
        require(resource == self.config.resource and raw_name in self.flows and arguments == {}, 'mcp_call_manifest_mismatch')
        require(type(headers) is dict and set(headers) == {'Authorization'} and headers['Authorization'].startswith('Bearer ')
                and token_text(headers['Authorization'].removeprefix('Bearer '))
                and type(cache_key) is tuple and len(cache_key) == 7, 'mcp_trusted_call_required')
        # ADK invokes tools inside streaming generator tasks. Keep SDK/anyio
        # task-group cancellation scoped to its own loop, with no session cache.
        return await asyncio.to_thread(lambda: asyncio.run(self._sdk_call(resource, headers, raw_name)))

    async def _sdk_call(self, resource, headers, raw_name):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        def guarded_factory(*args, **kwargs):
            client = self.factory(*args, **kwargs)
            require(client.follow_redirects is False and client.trust_env is False and client.auth is None
                    and not client.cookies, 'mcp_clean_explicit_client_required')
            return client
        try:
            async with streamablehttp_client(resource, headers=headers, timeout=5, sse_read_timeout=5,
                                             terminate_on_close=False, httpx_client_factory=guarded_factory) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    listing = await session.list_tools()
                    tools = [x for x in listing.tools if x.name == raw_name]
                    require(len(tools) == 1 and tools[0].inputSchema.get('type') == 'object'
                            and not tools[0].inputSchema.get('required'), 'mcp_identity_tool_schema_mismatch')
                    result = await session.call_tool(raw_name, {})
                    require(not result.isError, 'mcp_identity_tool_failed')
                    text = [x.text for x in result.content if x.type == 'text']
                    require(len(text) == 1 and len(text[0]) <= 4096, 'mcp_identity_result_invalid')
                    return parse_pinned_flow_output(text[0])
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('mcp_upstream_unavailable') from None
