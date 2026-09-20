import asyncio
from functools import lru_cache

from jwt import InvalidTokenError, PyJWKClient, decode
from jwt.exceptions import (
    PyJWKClientConnectionError,
    PyJWKClientError,
    PyJWKSetError,
)
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from app.core.config import settings

VALID_USER_TYPES = {"farm_owner", "company_employee", "admin"}


class AuthenticationKeyServiceError(RuntimeError):
    """Raised when the configured Keycloak JWKS cannot provide usable keys."""


@lru_cache(maxsize=8)
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300)


def _jwks_url() -> str:
    return (
        settings.MCP_JWKS_URL
        or settings.MCP_JWT_ISSUER.rstrip("/")
        + "/protocol/openid-connect/certs"
    )


def _get_signing_key(token: str):
    client = _get_jwks_client(_jwks_url())
    try:
        client.get_jwk_set()
        return client.get_signing_key_from_jwt(token)
    except PyJWKClientConnectionError:
        raise
    except PyJWKSetError as exc:
        raise AuthenticationKeyServiceError("invalid JWKS key set") from exc
    except (InvalidTokenError, PyJWKClientError, ValueError, TypeError):
        return None


def _decode_keycloak_token(token: str) -> dict | None:
    signing_key = _get_signing_key(token)
    if signing_key is None:
        return None

    try:
        claims = decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.MCP_JWT_ISSUER,
            audience=settings.MCP_JWT_AUDIENCE,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except InvalidTokenError:
        return None
    return claims if isinstance(claims, dict) else None


def _identity_from_claims(claims: dict) -> tuple[str, int] | None:
    database_id = claims.get("database_id")
    account_type = claims.get("account_type")
    realm_access = claims.get("realm_access")
    roles = realm_access.get("roles") if isinstance(realm_access, dict) else None

    if (
        not isinstance(account_type, str)
        or account_type not in VALID_USER_TYPES
        or not isinstance(roles, list)
        or not all(isinstance(role, str) for role in roles)
        or account_type not in roles
    ):
        return None

    if isinstance(database_id, bool):
        return None
    if isinstance(database_id, int):
        numeric_database_id = database_id
    elif (
        isinstance(database_id, str)
        and database_id.isascii()
        and database_id.isdecimal()
    ):
        numeric_database_id = int(database_id)
    else:
        return None

    if numeric_database_id <= 0:
        return None
    return account_type, numeric_database_id


class KeycloakTokenVerifier:
    """Validate the only supported MCP credential: a Keycloak access token."""

    def __init__(self, resource_url: str | None = None) -> None:
        self.resource_url = resource_url or settings.MCP_RESOURCE_URL

    async def verify_token(self, token: str) -> AccessToken | None:
        claims = await asyncio.to_thread(_decode_keycloak_token, token)
        if claims is None or _identity_from_claims(claims) is None:
            return None

        scope = claims.get("scope", "")
        scopes = scope.split() if isinstance(scope, str) and scope.strip() else ["mcp"]
        expires_at = claims.get("exp")
        return AccessToken(
            token=token,
            client_id=str(claims.get("azp") or "ouros-user"),
            scopes=scopes,
            expires_at=int(expires_at) if isinstance(expires_at, (int, float)) else None,
            resource=self.resource_url,
            subject=str(claims["sub"]),
            claims=claims,
        )


def get_authenticated_identity() -> tuple[str, int]:
    """Derive business identity exclusively from signed Keycloak claims."""

    access_token = get_access_token()
    if access_token is None:
        raise PermissionError("autenticação MCP obrigatória")

    claims = access_token.claims if isinstance(access_token.claims, dict) else {}
    identity = _identity_from_claims(claims)
    if identity is None:
        raise PermissionError("identidade MCP inválida")
    return identity
