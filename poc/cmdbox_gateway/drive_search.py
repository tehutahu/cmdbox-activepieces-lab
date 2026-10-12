"""Review-only fixed Drive search contract; not installed by production bootstrap.

Uses the existing verified UID/session/binding and generation checks. No arbitrary
query, folder, URL, Connection reference or management tool reaches the model.
"""
from dataclasses import dataclass
import re
from .core import AuthorizedFlowBroker, GatewayError, require

CONTRACT = 'drive-search-metadata-v1'
COMPLETION = 'unverified-by-stock-piece'
ALIAS = 'lab_drive_search'


@dataclass(frozen=True)
class DriveSearchPolicy:
    uid: str
    subject: str
    project_id: str
    raw_name: str
    policy_id: str


def project_result(output, policy_id):
    require(type(output) is dict and set(output) == {'contract', 'policyId', 'completion', 'files'}
            and output['contract'] == CONTRACT and output['policyId'] == policy_id
            and output['completion'] == COMPLETION, 'drive_result_contract_mismatch')
    files = output['files']
    require(type(files) is list and len(files) <= 20, 'drive_result_limit_exceeded')
    projected, seen = [], set()
    for file in files:
        require(type(file) is dict and {'id', 'name', 'mimeType'} <= set(file)
                and set(file) <= {'id', 'name', 'mimeType', 'createdTime', 'modifiedTime'},
                'drive_metadata_fields_invalid')
        require(type(file['id']) is str and re.fullmatch(r'[A-Za-z0-9_-]{1,128}', file['id'])
                and file['id'] not in seen, 'drive_file_id_invalid')
        require(type(file['name']) is str and 0 < len(file['name']) <= 240
                and not any(ord(c) < 32 for c in file['name']), 'drive_file_name_invalid')
        require(type(file['mimeType']) is str and re.fullmatch(r'[A-Za-z0-9.+_-]+/[A-Za-z0-9.+_-]+', file['mimeType'])
                and file['mimeType'] != 'application/vnd.google-apps.folder', 'drive_mime_invalid')
        for field in ('createdTime', 'modifiedTime'):
            if field in file:
                require(type(file[field]) is str and re.fullmatch(r'\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d{1,9})?Z', file[field]),
                        'drive_timestamp_invalid')
        seen.add(file['id'])
        projected.append({key: file[key] for key in ('id', 'name', 'mimeType')})
    return {'contract': CONTRACT, 'completion': COMPLETION, 'files': projected}


class PreparedDriveBroker(AuthorizedFlowBroker):
    def __init__(self, registry, credentials, transport, policies, *, resource):
        super().__init__(registry, credentials, transport, resource=resource)
        policies = tuple(policies)
        require(bool(policies) and all(isinstance(p, DriveSearchPolicy) for p in policies)
                and len({p.uid for p in policies}) == len(policies), 'drive_policy_manifest_invalid')
        require(all(re.fullmatch(r'lab_drive_search_[A-Za-z0-9_]+_mcp', p.raw_name)
                    and re.fullmatch(r'[A-Za-z0-9_-]{1,80}', p.policy_id) for p in policies),
                'drive_policy_manifest_invalid')
        self.policies = {p.uid: p for p in policies}

    def binding_for(self, context):
        invocation, binding = super().binding_for(context)
        policy = self.policies.get(binding.uid)
        require(policy is not None and (binding.subject, binding.project_id) == (policy.subject, policy.project_id),
                'drive_binding_policy_mismatch')
        return invocation, binding

    async def call(self, context, *, alias, arguments, expected_uid, expected_generation):
        invocation, binding = self.binding_for(context)
        require(invocation.actor.uid == expected_uid and binding.generation == expected_generation,
                'stale_or_wrong_identity_tool')
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
        cache_key = (binding.uid, invocation.actor.nonce, invocation.session_id, binding.subject,
                     binding.project_id, binding.grant_id, binding.generation)
        try:
            output = await self._transport.call(resource=self._resource, headers={'Authorization': 'Bearer ' + credential},
                                                raw_name=policy.raw_name, arguments={}, cache_key=cache_key)
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('upstream_unavailable') from None
        require(self._registry.resolve(binding.uid).generation == binding.generation, 'stale_binding_result')
        return project_result(output, policy.policy_id)
