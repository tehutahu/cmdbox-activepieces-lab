"""Explicit server-owned tool configuration. No delegated/payload credential fallback."""
from .core import require
import re

UID_MODE = 'user_ap_binding'
STATIC_MODE = 'static_api_key'
COMMON = {'mcpserver_name', 'mcpserver_auth_mode', 'mcpserver_mcp_tools'}

def validate_tool_config(config):
    require(type(config) is dict, 'invalid_tool_config')
    mode = config.get('mcpserver_auth_mode')
    require(mode in (UID_MODE, STATIC_MODE), 'explicit_tool_auth_mode_required')
    allowed = COMMON if mode == UID_MODE else COMMON | {'mcpserver_url', 'mcpserver_apikey', 'mcpserver_transport'}
    require(not (set(config) - allowed), 'mixed_or_unknown_tool_config')
    if 'mcpserver_name' in config:
        require(type(config['mcpserver_name']) is str and bool(config['mcpserver_name']), 'invalid_tool_name')
    tools = config.get('mcpserver_mcp_tools')
    require(type(tools) is list and bool(tools) and len(set(x for x in tools if type(x) is str))==len(tools)
            and all(type(x) is str and re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,99}',x) for x in tools), 'explicit_tool_allowlist_required')
    if mode == UID_MODE:
        require(tools == ['lab_identity'], 'uid_flow_manifest_required')
    else:
        key = config.get('mcpserver_apikey')
        require(type(key) is str and bool(key) and not any(x.isspace() for x in key), 'static_tool_key_required')
        from urllib.parse import urlsplit
        require(type(config.get('mcpserver_url')) is str, 'static_tool_url_required')
        url = urlsplit(config.get('mcpserver_url', ''))
        require(url.scheme in ('http', 'https') and bool(url.hostname) and not url.username and not url.password and not url.query and not url.fragment,
                'static_tool_url_required')
        require(config.get('mcpserver_transport', 'streamable-http') in ('streamable-http', 'sse'), 'invalid_tool_transport')
    return mode

def static_headers(config):
    require(validate_tool_config(config) == STATIC_MODE, 'static_mode_required')
    return {'Authorization': 'Bearer ' + config['mcpserver_apikey']}

def validate_bootstrap(configs, *, issuer, verifier, broker, shared_replay_guard):
    require(type(configs) is list and bool(configs), 'tool_configuration_required')
    modes = [validate_tool_config(c) for c in configs]
    if UID_MODE in modes:
        require(callable(getattr(issuer, 'attach', None)), 'web_identity_runtime_not_configured')
        require(callable(getattr(verifier, 'verify', None)), 'worker_identity_runtime_not_configured')
        require(callable(getattr(broker, 'require_actor_connection', None)), 'ap_broker_runtime_not_configured')
        # A caller's Boolean is not evidence that replay storage is shared.
        from .core import RedisReplayGuard
        require(isinstance(shared_replay_guard, RedisReplayGuard) and getattr(verifier, '_guard', None) is shared_replay_guard,
                'shared_redis_guard_required')
    return modes
