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
    from .adk_adapter import ScopedSyntheticToolset
    return ScopedSyntheticToolset(_broker)

def require_ap_connection(actor):
    require(_broker is not None, 'ap_broker_runtime_not_configured')
    _broker.require_actor_connection(actor)
