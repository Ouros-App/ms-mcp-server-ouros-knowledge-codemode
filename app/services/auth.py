import asyncio
import secrets
from functools import lru_cache

from jwt import InvalidTokenError, PyJWKClient, decode
from jwt.exceptions import PyJWKClientError
from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from app.core.config import settings

VALID_USER_TYPES = {"farm_owner", "company_employee", "admin"}
STATIC_TOKEN_EXPIRY = 2_147_483_647


@lru_cache(maxsize=8)
def _get_jwks_client(jwks_url: str) -> PyJWKClient:
    """Reuse the JWKS client so Keycloak signing keys stay cached."""

    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300)


def _jwks_url() -> str | None:
    """Resolve the configured JWKS endpoint or derive it from the issuer."""

    if settings.MCP_JWKS_URL:
        return settings.MCP_JWKS_URL
    if not settings.MCP_JWT_ISSUER:
        return None
    return (
        settings.MCP_JWT_ISSUER.rstrip("/")
        + "/protocol/openid-connect/certs"
    )


def _decode_keycloak_token(token: str) -> dict | None:
    """Validate a Keycloak JWT signature, issuer, audience and lifetime."""

    issuer = settings.MCP_JWT_ISSUER
    audience = settings.MCP_JWT_AUDIENCE
    jwks_url = _jwks_url()
    if not issuer or not audience or not jwks_url:
        return None

    try:
        signing_key = _get_jwks_client(jwks_url).get_signing_key_from_jwt(token)
        claims = decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=issuer,
            audience=audience,
            options={
                "require": ["exp", "iat", "iss", "aud", "sub"],
            },
        )
    except (InvalidTokenError, PyJWKClientError, ValueError):
        return None
    return claims if isinstance(claims, dict) else None


def _identity_from_claims(claims: dict) -> tuple[str, int] | None:
    """Extract the signed Ouros business identity from Keycloak claims."""

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


class StaticTokenVerifier:
    """Validate one shared bearer token configured for the MCP server."""

    def __init__(
        self,
        token: str | None = None,
        resource_url: str | None = None,
    ) -> None:
        """Load the shared token used to authenticate the MCP client."""
        self.token = token if token is not None else settings.MCP_AUTH_TOKEN
        self.resource_url = resource_url or settings.MCP_RESOURCE_URL

    async def verify_token(self, token: str) -> AccessToken | None:
        """Return access information when the bearer token matches exactly."""
        if not self.token or len(self.token) < 32:
            return None
        if not secrets.compare_digest(token, self.token):
            return None

        return AccessToken(
            token=token,
            client_id="midas",
            scopes=["mcp"],
            expires_at=STATIC_TOKEN_EXPIRY,
            resource=self.resource_url,
            subject="midas",
            claims={},
        )


class KeycloakOrStaticTokenVerifier:
    """Prefer Keycloak JWT validation and keep the static token for rollout."""

    def __init__(
        self,
        static_token: str | None = None,
        resource_url: str | None = None,
    ) -> None:
        self.resource_url = resource_url or settings.MCP_RESOURCE_URL
        self.static_verifier = StaticTokenVerifier(
            static_token,
            self.resource_url,
        )

    async def verify_token(self, token: str) -> AccessToken | None:
        """Validate a Keycloak JWT or fall back to the legacy shared token."""

        if settings.MCP_JWT_ISSUER and settings.MCP_JWT_AUDIENCE:
            claims = await asyncio.to_thread(_decode_keycloak_token, token)
            if claims is not None and _identity_from_claims(claims) is not None:
                subject = claims.get("sub")
                expires_at = claims.get("exp")
                scope = claims.get("scope", "")
                scopes = (
                    scope.split()
                    if isinstance(scope, str) and scope.strip()
                    else ["mcp"]
                )
                return AccessToken(
                    token=token,
                    client_id=str(claims.get("azp") or "ouros-user"),
                    scopes=scopes,
                    expires_at=(
                        int(expires_at)
                        if isinstance(expires_at, (int, float))
                        else None
                    ),
                    resource=self.resource_url,
                    subject=str(subject),
                    claims=claims,
                )

        return await self.static_verifier.verify_token(token)


def get_authenticated_identity(
    user_type: str | None = None,
    user_id: int | None = None,
) -> tuple[str, int]:
    """Derive identity from signed claims, with static-token compatibility."""

    access_token = get_access_token()
    if access_token is None:
        raise PermissionError("autenticação MCP obrigatória")

    claims = access_token.claims if isinstance(access_token.claims, dict) else {}
    claimed_identity = _identity_from_claims(claims)
    if claimed_identity is not None:
        claimed_type, claimed_id = claimed_identity
        if user_type is not None and user_type != claimed_type:
            raise PermissionError("user_type não corresponde ao JWT autenticado")
        if user_id is not None and user_id != claimed_id:
            raise PermissionError("user_id não corresponde ao JWT autenticado")
        return claimed_type, claimed_id

    if (
        not isinstance(user_type, str)
        or user_type not in VALID_USER_TYPES
        or not isinstance(user_id, int)
        or user_id <= 0
    ):
        raise PermissionError("identidade MCP inválida")
    return user_type, user_id
