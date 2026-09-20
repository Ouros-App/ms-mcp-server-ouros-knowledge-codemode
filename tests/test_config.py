import unittest

from pydantic import ValidationError

from app.core.config import Settings


class ConfigAuthTests(unittest.TestCase):
    def test_keycloak_jwt_can_be_disabled_for_local_static_auth(self) -> None:
        config = Settings(
            _env_file=None,
            MCP_JWT_ISSUER=None,
            MCP_JWT_AUDIENCE=None,
            MCP_JWKS_URL=None,
        )

        self.assertIsNone(config.MCP_JWT_ISSUER)
        self.assertIsNone(config.MCP_JWT_AUDIENCE)

    def test_partial_keycloak_jwt_config_is_rejected(self) -> None:
        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                MCP_JWT_ISSUER="https://ouros-keycloak.discloud.app/realms/ouros",
                MCP_JWT_AUDIENCE=None,
            )

        with self.assertRaises(ValidationError):
            Settings(
                _env_file=None,
                MCP_JWT_ISSUER=None,
                MCP_JWT_AUDIENCE=None,
                MCP_JWKS_URL=(
                    "https://ouros-keycloak.discloud.app/realms/ouros/"
                    "protocol/openid-connect/certs"
                ),
            )


if __name__ == "__main__":
    unittest.main()
