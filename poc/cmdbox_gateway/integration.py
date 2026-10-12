"""Explicit dependency injection for the review-only public cmdbox source patch.

No default key, credential provider, binding registry or network transport.
Install both runtimes at process bootstrap; settings are not supplied by chat input.
"""
from contextlib import nullcontext
from .core import GatewayError, require, invocation_scope

_issuer = None
_verifier = None
_broker = None

def install_web_runtime(issuer):
    global _issuer
    _issuer = issuer

def install_worker_runtime(verifier, broker):
    global _verifier, _broker
    _verifier, _broker = verifier, broker

def attach_verified_web_job(server_session, payload):
    require(_issuer is not None, 'web_identity_runtime_not_configured')
    return _issuer.attach(server_session, payload)

def verify_worker_job(payload):
    # Legacy CLI/internal jobs keep legacy tools; absence of proof never gives AP authority.
    if 'trusted_identity' not in payload:
        return None
    require(_verifier is not None, 'worker_identity_runtime_not_configured')
    return _verifier.verify(payload)

def adk_identity(actor, legacy_user_name):
    if actor is not None:
        return actor.adk_user_id
    # An unsigned legacy username must not impersonate the new UID namespace.
    require(type(legacy_user_name) is str and not legacy_user_name.startswith('cmdbox_uid_'),
            'reserved_uid_namespace_requires_signed_job')
    return legacy_user_name

def trusted_runner_scope(actor, actual_session_id):
    return invocation_scope(actor, actual_session_id) if actor is not None else nullcontext()

def approved_ap_toolset():
    require(_broker is not None, 'ap_broker_runtime_not_configured')
    alias = getattr(_broker, 'tool_alias', 'lab_identity')
    if alias == 'lab_drive_search':
        from .stock_drive import StockDriveBroker
        from .drive_adk import PreparedDriveToolset
        require(isinstance(_broker, StockDriveBroker), 'stock_broker_required')
        return PreparedDriveToolset(_broker)
    require(alias == 'lab_identity', 'uid_broker_alias_mismatch')
    from .adk_adapter import ScopedSyntheticToolset
    return ScopedSyntheticToolset(_broker)

def require_ap_connection(actor):
    require(_broker is not None, 'ap_broker_runtime_not_configured')
    _broker.require_actor_connection(actor)

def preflight_tools(configs, actor):
    from .config import validate_tool_config, UID_MODE
    for config in configs:
        if validate_tool_config(config) == UID_MODE:
            require(config['mcpserver_mcp_tools'] == [getattr(_broker, 'tool_alias', 'lab_identity')],
                    'uid_broker_alias_mismatch')
            require_ap_connection(actor)

def bootstrap(configs, *, issuer, verifier, broker, shared_replay_guard):
    from .config import validate_bootstrap
    # Validate the complete configuration before installing either runtime.
    validate_bootstrap(configs, issuer=issuer, verifier=verifier, broker=broker,
                       shared_replay_guard=shared_replay_guard)
    install_web_runtime(issuer)
    install_worker_runtime(verifier, broker)

def attach_resource_job(server_session, operation, runner_name, session_id):
    require(operation in ('session_list', 'session_del'), 'resource_operation_not_allowed')
    # Reuse the signed queue envelope and replay namespace; operation is signed too.
    payload = dict(runner_name=runner_name,user_name='server-selected',session_id=session_id,
                   message='RESOURCE:' + operation,call_tts=False,reasoning_effort='off',
                   mcpserver_apikey=None,a2asv_apikey=None)
    return attach_verified_web_job(server_session, payload)

def verify_resource_job(payload, operation):
    actor = verify_worker_job(payload)
    require(actor is not None and payload.get('message') == 'RESOURCE:' + operation, 'signed_resource_job_required')
    return actor.adk_user_id
