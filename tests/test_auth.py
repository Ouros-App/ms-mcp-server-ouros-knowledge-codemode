import unittest
from types import SimpleNamespace
from unittest.mock import Mock, patch

from app.core.config import settings
from app.services.auth import (
    KeycloakOrStaticTokenVerifier,
    StaticTokenVerifier,
    _decode_keycloak_token,
    _identity_from_claims,
    _jwks_url,
    get_authenticated_identity,
)


class AuthTests(unittest.IsolatedAsyncioTestCase):
    token = "test-static-token-with-at-least-32-characters"

    async def test_matching_static_token_returns_access_token(self) -> None:
        verifier = StaticTokenVerifier(self.token, "http://localhost:8000/mcp")

        access_token = await verifier.verify_token(self.token)

        self.assertIsNotNone(access_token)
        assert access_token is not None
        self.assertEqual(access_token.subject, "midas")
        self.assertEqual(access_token.claims, {})

    async def test_invalid_or_weak_static_token_is_rejected(self) -> None:
        verifier = StaticTokenVerifier(self.token)

        self.assertIsNone(await verifier.verify_token("wrong-token"))
        self.assertIsNone(
            await StaticTokenVerifier("short").verify_token("short")
        )

    def test_jwks_url_supports_explicit_derived_and_disabled_modes(self) -> None:
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

        with (
            patch.object(settings, "MCP_JWKS_URL", None),
            patch.object(settings, "MCP_JWT_ISSUER", None),
        ):
            self.assertIsNone(_jwks_url())

    def test_decode_keycloak_token_uses_signing_key_and_contract(self) -> None:
        signing_key = SimpleNamespace(key="public-key")
        jwks_client = Mock()
        jwks_client.get_signing_key_from_jwt.return_value = signing_key
        expected_claims = {"sub": "subject"}

        with (
            patch.object(settings, "MCP_JWKS_URL", "https://keys.example/jwks"),
            patch.object(settings, "MCP_JWT_ISSUER", "https://issuer.example"),
            patch.object(settings, "MCP_JWT_AUDIENCE", "mcp-audience"),
            patch(
                "app.services.auth._get_jwks_client",
                return_value=jwks_client,
            ),
            patch(
                "app.services.auth.decode",
                return_value=expected_claims,
            ) as decoder,
        ):
            claims = _decode_keycloak_token("signed-token")

        self.assertEqual(claims, expected_claims)
        jwks_client.get_signing_key_from_jwt.assert_called_once_with(
            "signed-token"
        )
        decoder.assert_called_once()
        self.assertEqual(decoder.call_args.kwargs["algorithms"], ["RS256"])
        self.assertEqual(
            decoder.call_args.kwargs["issuer"],
            "https://issuer.example",
        )
        self.assertEqual(
            decoder.call_args.kwargs["audience"],
            "mcp-audience",
        )

    def test_decode_keycloak_token_requires_complete_configuration(self) -> None:
        with (
            patch.object(settings, "MCP_JWKS_URL", None),
            patch.object(settings, "MCP_JWT_ISSUER", None),
            patch.object(settings, "MCP_JWT_AUDIENCE", None),
        ):
            self.assertIsNone(_decode_keycloak_token("token"))

    def test_identity_claim_validation_rejects_invalid_business_identity(
        self,
    ) -> None:
        self.assertIsNone(
            _identity_from_claims(
                {
                    "database_id": 42,
                    "account_type": "admin",
                    "realm_access": {"roles": ["farm_owner"]},
                }
            )
        )
        self.assertIsNone(
            _identity_from_claims(
                {
                    "database_id": "not-an-id",
                    "account_type": "farm_owner",
                    "realm_access": {"roles": ["farm_owner"]},
                }
            )
        )
        self.assertIsNone(
            _identity_from_claims(
                {
                    "database_id": 0,
                    "account_type": "farm_owner",
                    "realm_access": {"roles": ["farm_owner"]},
                }
            )
        )
        self.assertIsNone(
            _identity_from_claims(
                {
                    "database_id": True,
                    "account_type": "farm_owner",
                    "realm_access": {"roles": ["farm_owner"]},
                }
            )
        )
        self.assertIsNone(
            _identity_from_claims(
                {
                    "database_id": 42.9,
                    "account_type": "farm_owner",
                    "realm_access": {"roles": ["farm_owner"]},
                }
            )
        )
        self.assertIsNone(
            _identity_from_claims(
                {
                    "database_id": 42,
                    "account_type": "farm_owner",
                    "realm_access": {"roles": "farm_owner"},
                }
            )
        )
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

    async def test_keycloak_token_returns_signed_business_claims(self) -> None:
        claims = {
            "sub": "keycloak-subject",
            "database_id": 42,
            "account_type": "farm_owner",
            "realm_access": {"roles": ["farm_owner"]},
            "scope": "openid ouros-identity",
            "exp": 2_147_483_647,
        }

        with (
            patch.object(
                settings,
                "MCP_JWT_ISSUER",
                "https://ouros-keycloak.discloud.app/realms/ouros",
            ),
            patch.object(
                settings,
                "MCP_JWT_AUDIENCE",
                "ms-mcp-server-ouros-knowledge",
            ),
            patch(
                "app.services.auth._decode_keycloak_token",
                return_value=claims,
            ),
        ):
            verifier = KeycloakOrStaticTokenVerifier(static_token=None)
            access_token = await verifier.verify_token("signed-token")

        self.assertIsNotNone(access_token)
        assert access_token is not None
        self.assertEqual(access_token.subject, "keycloak-subject")
        self.assertEqual(
            access_token.scopes,
            ["openid", "ouros-identity"],
        )
        self.assertEqual(access_token.claims["database_id"], 42)

    async def test_invalid_keycloak_token_falls_back_to_static_token(
        self,
    ) -> None:
        with (
            patch.object(settings, "MCP_JWT_ISSUER", "https://issuer.example"),
            patch.object(settings, "MCP_JWT_AUDIENCE", "mcp-audience"),
            patch(
                "app.services.auth._decode_keycloak_token",
                return_value=None,
            ),
        ):
            verifier = KeycloakOrStaticTokenVerifier(
                static_token=self.token,
            )
            access_token = await verifier.verify_token(self.token)

        self.assertIsNotNone(access_token)
        assert access_token is not None
        self.assertEqual(access_token.subject, "midas")

    @patch("app.services.auth.get_access_token")
    def test_identity_is_validated_after_authentication(
        self,
        get_access_token,
    ) -> None:
        get_access_token.return_value = SimpleNamespace(claims={})

        self.assertEqual(
            get_authenticated_identity("company_employee", 7),
            ("company_employee", 7),
        )

    @patch("app.services.auth.get_access_token")
    def test_identity_is_derived_from_keycloak_claims(
        self,
        get_access_token,
    ) -> None:
        get_access_token.return_value = SimpleNamespace(
            claims={
                "database_id": 42,
                "account_type": "farm_owner",
                "realm_access": {"roles": ["farm_owner"]},
            }
        )

        self.assertEqual(
            get_authenticated_identity(),
            ("farm_owner", 42),
        )

    @patch("app.services.auth.get_access_token")
    def test_keycloak_identity_rejects_spoofed_tool_arguments(
        self,
        get_access_token,
    ) -> None:
        get_access_token.return_value = SimpleNamespace(
            claims={
                "database_id": 42,
                "account_type": "farm_owner",
                "realm_access": {"roles": ["farm_owner"]},
            }
        )

        with self.assertRaises(PermissionError):
            get_authenticated_identity("admin", 42)
        with self.assertRaises(PermissionError):
            get_authenticated_identity("farm_owner", 99)

    @patch("app.services.auth.get_access_token", return_value=None)
    def test_missing_token_requires_authentication(
        self,
        _get_access_token,
    ) -> None:
        with self.assertRaises(PermissionError):
            get_authenticated_identity("farm_owner", 42)

    @patch("app.services.auth.get_access_token")
    def test_invalid_identity_requires_authentication(
        self,
        get_access_token,
    ) -> None:
        get_access_token.return_value = SimpleNamespace(claims={})

        with self.assertRaises(PermissionError):
            get_authenticated_identity("unknown", 42)
        with self.assertRaises(PermissionError):
            get_authenticated_identity("farm_owner", 0)


if __name__ == "__main__":
    unittest.main()
