"""Review candidate for the pinned AP0.92.2 public-client OAuth contract.

No default endpoint, HTTP client, entropy, client registration or provider account.
Tests inject httpx.MockTransport and literal entropy. Real use needs approval first.
"""
import base64
from dataclasses import dataclass, field
import hashlib
import json
import re
import time
from urllib.parse import urlencode, urlsplit
from .core import GatewayError, require


def checked_url(value, *, origin=False):
    require(type(value) is str, 'configured_oauth_url_required')
    p = urlsplit(value)
    require(p.scheme in ('http', 'https') and p.hostname and not p.username and not p.password
            and not p.query and not p.fragment, 'configured_oauth_url_required')
    require(p.scheme == 'https' or p.hostname in ('localhost', '127.0.0.1', '::1'), 'oauth_https_or_loopback_required')
    require(not origin or p.path in ('', '/'), 'oauth_issuer_origin_required')
    return value.rstrip('/') if origin else value


@dataclass(frozen=True)
class OAuthConfig:
    issuer: str
    client_id: str
    client_name: str
    redirect_uri: str
    resource: str

    def __post_init__(self):
        require(self.issuer == checked_url(self.issuer, origin=True), 'canonical_issuer_required')
        checked_url(self.redirect_uri)
        require(self.resource == self.issuer + '/mcp', 'project_mcp_resource_required')
        require(all(type(x) is str and 0 < len(x) <= 200 and not any(c.isspace() for c in x)
                    for x in (self.client_id,)), 'public_client_id_required')
        require(type(self.client_name) is str and bool(self.client_name), 'public_client_name_required')

    def endpoint(self, name):
        require(name in ('authorize', 'token', 'userinfo', 'revoke'), 'oauth_endpoint_not_allowed')
        return self.issuer + '/' + name


@dataclass(frozen=True, repr=False)
class Tokens:
    access: str = field(repr=False)
    refresh: str = field(repr=False)
    expires: int


@dataclass(frozen=True)
class TokenIdentity:
    subject: str
    project: str
    grant: str
    client: str


class IssuedTokenRejected(GatewayError):
    """Keep an issued refresh token for encrypted cleanup, never in error text."""
    def __init__(self, refresh):
        super().__init__('oauth_token_response_invalid')
        self.refresh = refresh


def token_text(value):
    return type(value) is str and 0 < len(value) <= 20000 and not any(c.isspace() for c in value)


def pkce(entropy):
    # Caller supplies an approved entropy source; tests supply public literal bytes.
    state_bytes, verifier_bytes = entropy(32), entropy(64)
    require(type(state_bytes) is bytes and len(state_bytes) == 32 and type(verifier_bytes) is bytes
            and len(verifier_bytes) == 64, 'oauth_entropy_contract_required')
    encode = lambda x: base64.urlsafe_b64encode(x).decode('ascii').rstrip('=')
    state, verifier = encode(state_bytes), encode(verifier_bytes)
    return state, verifier, encode(hashlib.sha256(verifier.encode('ascii')).digest())


class OAuthHttpClient:
    def __init__(self, config, client, *, clock=time.time):
        require(isinstance(config, OAuthConfig), 'trusted_oauth_config_required')
        require(client.follow_redirects is False and client.trust_env is False, 'oauth_no_redirect_or_env_proxy_required')
        require(not client.cookies and not client.headers.get('Authorization') and client.auth is None,
                'oauth_clean_explicit_client_required')
        self.config, self.client, self.clock = config, client, clock

    def _request(self, method, url, *, data=None, headers=None, empty=False):
        # Fixed destination only; metadata cannot introduce a new endpoint.
        allowed = {self.config.endpoint(x) for x in ('token', 'userinfo', 'revoke')}
        allowed |= {self.config.issuer + '/.well-known/oauth-authorization-server',
                    self.config.issuer + '/.well-known/oauth-protected-resource/mcp'}
        require(url in allowed and not self.client.cookies, 'oauth_destination_or_cookie_refused')
        try:
            response = self.client.request(method, url, data=data, headers=headers)
            require(response.status_code == 200 and len(response.content) <= 65536, 'oauth_upstream_rejected')
            if empty:
                return None
            value = response.json()
            require(type(value) is dict, 'oauth_response_invalid')
            return value
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('oauth_upstream_unavailable') from None
        finally:
            self.client.cookies.clear()

    def discover(self):
        meta = self._request('GET', self.config.issuer + '/.well-known/oauth-authorization-server')
        require(meta.get('issuer') == self.config.issuer, 'oauth_metadata_mismatch')
        for key, name in [('authorization_endpoint', 'authorize'), ('token_endpoint', 'token'),
                          ('userinfo_endpoint', 'userinfo'), ('revocation_endpoint', 'revoke')]:
            require(meta.get(key) == self.config.endpoint(name), 'oauth_metadata_mismatch')
        for key, wanted in [('response_types_supported', 'code'), ('grant_types_supported', 'authorization_code'),
                            ('grant_types_supported', 'refresh_token'), ('code_challenge_methods_supported', 'S256'),
                            ('token_endpoint_auth_methods_supported', 'none'), ('scopes_supported', 'mcp')]:
            require(type(meta.get(key)) is list and wanted in meta[key], 'oauth_metadata_mismatch')
        resource = self._request('GET', self.config.issuer + '/.well-known/oauth-protected-resource/mcp')
        require(resource.get('resource') == self.config.resource and resource.get('authorization_servers') == [self.config.issuer]
                and 'mcp' in resource.get('scopes_supported', []), 'oauth_resource_metadata_mismatch')

    def authorization_url(self, state, challenge):
        return self.config.endpoint('authorize') + '?' + urlencode({
            'response_type': 'code', 'client_id': self.config.client_id, 'redirect_uri': self.config.redirect_uri,
            'scope': 'mcp', 'resource': self.config.resource, 'state': state,
            'code_challenge': challenge, 'code_challenge_method': 'S256'})

    def _tokens(self, value, *, old_refresh=None):
        refresh = value.get('refresh_token', old_refresh)
        try:
            require(token_text(refresh) and token_text(value.get('access_token')) and value.get('token_type') == 'Bearer',
                    'oauth_token_response_invalid')
            ttl = value.get('expires_in')
            require(type(ttl) is int and 0 < ttl <= 900 and value.get('scope', 'mcp') == 'mcp'
                    and value.get('resource', self.config.resource) == self.config.resource, 'oauth_token_response_invalid')
            return Tokens(value['access_token'], refresh, int(self.clock()) + ttl)
        except GatewayError:
            if token_text(refresh):
                raise IssuedTokenRejected(refresh) from None
            raise

    def exchange(self, code, verifier):
        require(token_text(code) and type(verifier) is str and re.fullmatch(r'[A-Za-z0-9_-]{43,128}', verifier), 'oauth_code_or_verifier_invalid')
        return self._tokens(self._request('POST', self.config.endpoint('token'), data={
            'grant_type': 'authorization_code', 'client_id': self.config.client_id, 'code': code,
            'redirect_uri': self.config.redirect_uri, 'code_verifier': verifier, 'resource': self.config.resource}))

    def refresh(self, refresh):
        require(token_text(refresh), 'oauth_refresh_required')
        return self._tokens(self._request('POST', self.config.endpoint('token'), data={
            'grant_type': 'refresh_token', 'client_id': self.config.client_id,
            'refresh_token': refresh, 'resource': self.config.resource}), old_refresh=refresh)

    def authenticate(self, tokens):
        # AP verifies signature/audience/revocation in /userinfo. Only then inspect
        # claims of that SAME token obtained from the fixed trusted token endpoint.
        # This is not local HS256 verification or authority from caller-supplied JWTs.
        user = self._request('GET', self.config.endpoint('userinfo'), headers={'Authorization': 'Bearer ' + tokens.access})
        try:
            parts = tokens.access.split('.')
            require(len(parts) == 3, 'oauth_token_claims_invalid')
            decode = lambda p: json.loads(base64.urlsafe_b64decode(p + '=' * (-len(p) % 4)))
            header, claims = decode(parts[0]), decode(parts[1])
            require(type(header) is dict and header.get('alg') == 'HS256' and type(claims) is dict,
                    'oauth_token_claims_invalid')
            require(claims.get('type') == 'mcp_oauth' and claims.get('aud') == 'MCP_OAUTH_ACCESS'
                    and claims.get('scopes') == ['mcp'] and claims.get('clientId') == self.config.client_id,
                    'oauth_token_claims_invalid')
            now = int(self.clock())
            require(type(claims.get('iat')) is int and type(claims.get('exp')) is int
                    and claims['iat'] <= now + 5 and now < claims['exp'] <= now + 905,
                    'oauth_token_claims_invalid')
            require(user.get('sub') == claims.get('sub') and all(type(claims.get(k)) is str and bool(claims[k])
                    for k in ('sub', 'projectId', 'grantId')), 'oauth_token_identity_invalid')
            return TokenIdentity(claims['sub'], claims['projectId'], claims['grantId'], claims['clientId'])
        except GatewayError:
            raise
        except Exception:
            raise GatewayError('oauth_token_claims_invalid') from None

    def revoke(self, refresh):
        require(token_text(refresh), 'oauth_refresh_required')
        self._request('POST', self.config.endpoint('revoke'), data={
            'client_id': self.config.client_id, 'token': refresh, 'token_type_hint': 'refresh_token'}, empty=True)
        # HTTP200 means submitted, not formal grant-list confirmation.
