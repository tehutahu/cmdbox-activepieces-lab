"""Independent metadata piece alias; explicit factory injection only, default off.

No production UID configuration is changed. Review-time target registration
requires exact subject/project/flow/policy and the operator-fixed action input.
"""
from dataclasses import dataclass
import re
import unicodedata
from .core import AuthorizedFlowBroker, GatewayError, require
from .drive_search import DriveSearchPolicy
from .mcp_live import PinnedMcpTransport, parse_pinned_flow_output
from .oauth_live import OAuthConfig

ALIAS = 'lab_drive_metadata_search'
CONTRACT = 'drive-metadata-search-v2'
PACKAGE = '@cmdbox-lab/piece-drive-metadata-search'
VERSION = '0.1.0'
ACTION = 'search_folder_metadata'
SCOPE = 'https://www.googleapis.com/auth/drive.metadata.readonly'


@dataclass(frozen=True)
class MetadataPolicy(DriveSearchPolicy):
    flow_id: str
    folder_id: str
    term: str


def safe_text(value, limit):
    return type(value) is str and 0 < len(value) <= limit and not any(unicodedata.category(c) in ('Cc', 'Cs') for c in value)


def register_review_manifest(value):
    """Nonsecret review gate, not a writer/activator. No inferred live identifiers."""
    require(type(value) is dict and set(value) == {'schema', 'enabled', 'alias', 'piece', 'bindings'}, 'metadata_manifest_invalid')
    require(value['schema'] == 'metadata-drive-registration-v1' and value['enabled'] is True,
            'metadata_registration_disabled')
    require(value['alias'] == ALIAS and value['piece'] == {'name': PACKAGE, 'version': VERSION, 'action': ACTION, 'scope': SCOPE},
            'metadata_manifest_invalid')
    rows = value['bindings']
    require(type(rows) is list and 0 < len(rows) <= 100, 'metadata_manifest_invalid')
    result = []
    for row in rows:
        require(type(row) is dict and set(row) == {'uid', 'subject', 'project_id', 'flow_id', 'raw_name', 'policy_id', 'folder_id', 'term'},
                'metadata_manifest_invalid')
        require(type(row['uid']) is str and re.fullmatch(r'0|[1-9][0-9]*', row['uid']), 'metadata_manifest_invalid')
        require(all(type(row[k]) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', row[k]) for k in
                    ('subject', 'project_id', 'flow_id', 'policy_id')), 'metadata_manifest_invalid')
        require(type(row['folder_id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{5,128}', row['folder_id'])
                and row['folder_id'] not in ('root', 'MY_DRIVE', 'UNSET'), 'metadata_manifest_invalid')
        require(type(row['raw_name']) is str and re.fullmatch(r'lab_drive_metadata_search_[A-Za-z0-9_]+_mcp', row['raw_name'])
                and safe_text(row['term'], 128) and row['term'].strip(), 'metadata_manifest_invalid')
        result.append(MetadataPolicy(**row))
    require(len({p.uid for p in result}) == len(result) and len({p.raw_name for p in result}) == len(result)
            and len({p.policy_id for p in result}) == len(result), 'metadata_manifest_invalid')
    return tuple(result)


def project_metadata_result(output, policy_id):
    keys = {'contract', 'policyId', 'complete', 'incompleteSearch', 'truncated', 'stopReason', 'pagesRead', 'rowsRead', 'files'}
    require(type(output) is dict and set(output) == keys and output['contract'] == CONTRACT and output['policyId'] == policy_id,
            'metadata_result_contract_mismatch')
    require(all(type(output[k]) is bool for k in ('complete', 'incompleteSearch', 'truncated'))
            and output['complete'] == (not output['incompleteSearch'] and not output['truncated']), 'metadata_completion_invalid')
    reason = output['stopReason']
    expected = 'complete' if output['complete'] else 'incomplete_search' if not output['truncated'] else None
    require(reason == expected if expected else reason in ('row_limit', 'page_limit'), 'metadata_completion_invalid')
    require(type(output['pagesRead']) is int and 1 <= output['pagesRead'] <= 5
            and type(output['rowsRead']) is int and 0 <= output['rowsRead'] <= 20, 'metadata_result_limit_exceeded')
    require(reason != 'page_limit' or output['pagesRead'] == 5, 'metadata_completion_invalid')
    files = output['files']
    require(type(files) is list and len(files) == output['rowsRead'], 'metadata_result_limit_exceeded')
    projected, seen = [], set()
    for file in files:
        require(type(file) is dict and set(file) == {'id', 'name', 'mimeType'}, 'metadata_fields_invalid')
        require(type(file['id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', file['id']) and file['id'] not in seen,
                'metadata_file_id_invalid')
        require(safe_text(file['name'], 240) and len(file['name'].encode('utf-8')) <= 512, 'metadata_file_name_invalid')
        require(type(file['mimeType']) is str and len(file['mimeType']) <= 127
                and re.fullmatch(r'[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+', file['mimeType'])
                and file['mimeType'] != 'application/vnd.google-apps.folder', 'metadata_mime_invalid')
        seen.add(file['id'])
        projected.append(dict(file))
    return {'contract': CONTRACT, 'complete': output['complete'], 'incompleteSearch': output['incompleteSearch'],
            'truncated': output['truncated'], 'stopReason': reason, 'files': projected}


class MetadataDriveBroker(AuthorizedFlowBroker):
    def __init__(self, registry, credentials, transport, policies, *, resource):
        super().__init__(registry, credentials, transport, resource=resource)
        policies = tuple(policies)
        require(bool(policies) and all(isinstance(p, MetadataPolicy) for p in policies)
                and len({p.uid for p in policies}) == len(policies), 'metadata_policy_manifest_invalid')
        self.policies = {p.uid: p for p in policies}

    def binding_for(self, context):
        invocation, binding = super().binding_for(context)
        policy = self.policies.get(binding.uid)
        require(policy is not None and (binding.subject, binding.project_id, binding.flow.flow_id) ==
                (policy.subject, policy.project_id, policy.flow_id), 'metadata_binding_policy_mismatch')
        return invocation, binding

    async def call(self, context, *, alias, arguments, expected_uid, expected_generation):
        invocation, binding = self.binding_for(context)
        require(invocation.actor.uid == expected_uid and binding.generation == expected_generation, 'stale_or_wrong_identity_tool')
        require(alias == ALIAS, 'tool_not_allowed')
        require(type(arguments) is dict and not arguments, 'invalid_tool_arguments')
        policy = self.policies[binding.uid]
        try:
            credential = await self._credentials.get_active(binding.credential_ref, binding.grant_id, binding.generation)
        except GatewayError:
            raise GatewayError('reconnect_required') from None
        except Exception:
            raise GatewayError('credential_provider_unavailable') from None
        require(type(credential) is str and credential, 'reconnect_required')
        key = (binding.uid, invocation.actor.nonce, invocation.session_id, binding.subject,
               binding.project_id, binding.grant_id, binding.generation)
        try:
            output = await self._transport.call(resource=self._resource, headers={'Authorization': 'Bearer ' + credential},
                                                raw_name=policy.raw_name, arguments={}, cache_key=key)
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('upstream_unavailable') from None
        require(self._registry.resolve(binding.uid).generation == binding.generation, 'stale_binding_result')
        return project_metadata_result(output, policy.policy_id)


class MetadataMcpTransport(PinnedMcpTransport):
    """Same pinned SDK/reply format, empty-argument schema, metadata-sized bound."""
    def __init__(self, config, flows, httpx_client_factory):
        require(isinstance(config, OAuthConfig) and callable(httpx_client_factory), 'explicit_mcp_client_factory_required')
        self.config, self.flows, self.factory = config, frozenset(p.raw_name for p in flows), httpx_client_factory
        require(bool(self.flows) and all(re.fullmatch(r'lab_drive_metadata_search_[A-Za-z0-9_]+_mcp', n) for n in self.flows),
                'metadata_policy_manifest_invalid')

    async def _sdk_call(self, resource, headers, raw_name):
        from mcp import ClientSession
        from mcp.client.streamable_http import streamablehttp_client
        def guarded_factory(*args, **kwargs):
            client = self.factory(*args, **kwargs)
            require(client.follow_redirects is False and client.trust_env is False and client.auth is None and not client.cookies,
                    'mcp_clean_explicit_client_required')
            return client
        try:
            async with streamablehttp_client(resource, headers=headers, timeout=15, sse_read_timeout=15,
                                             terminate_on_close=False, httpx_client_factory=guarded_factory) as streams:
                async with ClientSession(streams[0], streams[1]) as session:
                    await session.initialize()
                    tools = [t for t in (await session.list_tools()).tools if t.name == raw_name]
                    require(len(tools) == 1 and tools[0].inputSchema.get('type') == 'object'
                            and tools[0].inputSchema.get('properties', {}) == {} and not tools[0].inputSchema.get('required')
                            and tools[0].inputSchema.get('additionalProperties') is not True, 'metadata_tool_schema_mismatch')
                    result = await session.call_tool(raw_name, {})
                    require(not result.isError, 'metadata_tool_failed')
                    texts = [c.text for c in result.content if c.type == 'text']
                    require(len(result.content) == 1 and len(texts) == 1 and len(texts[0]) <= 40960, 'metadata_result_invalid')
                    return parse_pinned_flow_output(texts[0])
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('mcp_upstream_unavailable') from None
