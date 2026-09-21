import unittest
from types import SimpleNamespace
from unittest.mock import Mock, call, patch

from jwt.exceptions import PyJWKClientError

from app.core.config import settings
from app.services.auth import (
    AuthenticationKeyServiceError,
    KeycloakTokenVerifier,
    _decode_keycloak_token,
    _identity_from_claims,
    _jwks_url,
    get_authenticated_identity,
)


class AuthTests(unittest.IsolatedAsyncioTestCase):
    def test_jwks_url_supports_explicit_and_derived_modes(self) -> None:
        with (
            patch.object(settings, "MCP_JWKS_URL", "https://keys.example/jwks"),
            patch.object(settings, "MCP_JWT_ISSUER", "https://issuer.example"),
        ):
            self.assertEqual(_jwks_url(), "https://keys.example/jwks")
        with (
            patch.object(settings, "MCP_JWKS_URL", None),
            patch.object(settings, "MCP_JWT_ISSUER", "https://issuer.example/"),
        ):
            self.assertEqual(
                _jwks_url(),
                "https://issuer.example/protocol/openid-connect/certs",
            )

    def test_decode_keycloak_token_uses_rs256_contract(self) -> None:
        signing_key = SimpleNamespace(key="public-key", key_id="kid-1")
        jwks_client = Mock()
        jwks_client.get_signing_keys.return_value = [signing_key]
        claims = {"sub": "subject"}

        with (
            patch.object(settings, "MCP_JWKS_URL", "https://keys.example/jwks"),
            patch.object(settings, "MCP_JWT_ISSUER", "https://issuer.example"),
            patch.object(settings, "MCP_JWT_AUDIENCE", "codemode-audience"),
            patch("app.services.auth._get_jwks_client", return_value=jwks_client),
            patch("app.services.auth.get_unverified_header", return_value={"kid": "kid-1"}),
            patch("app.services.auth.decode", return_value=claims) as decoder,
        ):
            self.assertEqual(_decode_keycloak_token("signed-token"), claims)

        jwks_client.get_signing_keys.assert_called_once_with(refresh=False)
        self.assertEqual(decoder.call_args.kwargs["algorithms"], ["RS256"])
        self.assertEqual(decoder.call_args.kwargs["issuer"], "https://issuer.example")
        self.assertEqual(decoder.call_args.kwargs["audience"], "codemode-audience")

    def test_unknown_kid_is_invalid_token_not_jwks_outage(self) -> None:
        jwks_client = Mock()
        jwks_client.get_signing_keys.return_value = [
            SimpleNamespace(key="public-key", key_id="known-kid")
        ]
        with (
            patch("app.services.auth._get_jwks_client", return_value=jwks_client),
            patch("app.services.auth.get_unverified_header", return_value={"kid": "unknown"}),
        ):
            self.assertIsNone(_decode_keycloak_token("signed-token"))

        self.assertEqual(
            jwks_client.get_signing_keys.call_args_list,
            [call(refresh=False), call(refresh=True)],
        )

    def test_malformed_jwks_is_infrastructure_failure(self) -> None:
        jwks_client = Mock()
        jwks_client.get_signing_keys.side_effect = PyJWKClientError("invalid JWKS")
        with (
            patch("app.services.auth._get_jwks_client", return_value=jwks_client),
            patch("app.services.auth.get_unverified_header", return_value={"kid": "kid-1"}),
            self.assertRaises(AuthenticationKeyServiceError),
        ):
            _decode_keycloak_token("signed-token")

    def test_identity_claim_validation(self) -> None:
        self.assertEqual(
            _identity_from_claims(
                {
                    "database_id": 7,
                    "account_type": "company_employee",
                    "realm_access": {"roles": ["company_employee"]},
                }
            ),
            ("company_employee", 7),
        )
        self.assertIsNone(
            _identity_from_claims(
                {
                    "database_id": 42,
                    "account_type": "admin",
                    "realm_access": {"roles": ["farm_owner"]},
                }
            )
        )

    async def test_keycloak_verifier_returns_signed_identity(self) -> None:
        claims = {
            "sub": "keycloak-subject",
            "database_id": 42,
            "account_type": "farm_owner",
            "realm_access": {"roles": ["farm_owner"]},
            "scope": "openid ouros-identity",
            "exp": 2_147_483_647,
        }
        with patch("app.services.auth._decode_keycloak_token", return_value=claims):
            access_token = await KeycloakTokenVerifier().verify_token("signed-token")

        self.assertIsNotNone(access_token)
        assert access_token is not None
        self.assertEqual(access_token.subject, "keycloak-subject")
        self.assertEqual(access_token.claims["database_id"], 42)

    async def test_invalid_token_has_no_static_fallback(self) -> None:
        with patch("app.services.auth._decode_keycloak_token", return_value=None):
            self.assertIsNone(await KeycloakTokenVerifier().verify_token("invalid"))

    @patch("app.services.auth.get_access_token")
    def test_identity_is_derived_only_from_claims(self, get_access_token) -> None:
        get_access_token.return_value = SimpleNamespace(
            claims={
                "database_id": 42,
                "account_type": "farm_owner",
                "realm_access": {"roles": ["farm_owner"]},
            }
        )
        self.assertEqual(get_authenticated_identity(), ("farm_owner", 42))

    @patch("app.services.auth.get_access_token", return_value=None)
    def test_missing_token_is_rejected(self, _get_access_token) -> None:
        with self.assertRaises(PermissionError):
            get_authenticated_identity()


if __name__ == "__main__":
    unittest.main()
