from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    PROJECT_NAME: str = "Ouros Knowledge MCP"
    DESCRIPTION: str = "FastAPI and MCP server for Qdrant knowledge retrieval."
    VERSION: str = "0.1.0"
    APP_PORT: int = 8000
    APP_NAME: str = "ouros_knowledge_mcp"
    QDRANT_URL: str = "http://localhost:6333"
    QDRANT_API_KEY: str | None = None
    QDRANT_COLLECTION_NAME: str = "ouros_knowledge"
    NVIDIA_API_KEY: str | None = None
    NVIDIA_BASE_URL: str = "https://integrate.api.nvidia.com/v1"
    NVIDIA_EMBEDDING_MODEL: str = "nvidia/llama-nemotron-embed-1b-v2"
    SEARCH_TOP_K: int = 5
    MIDAS_DATABASE_URL: str | None = None
    MIDAS_DB_CONNECT_TIMEOUT: int = 10
    MCP_AUTH_TOKEN: str | None = None
    MCP_RESOURCE_URL: str = "http://localhost:8000/mcp"
    MCP_JWT_ISSUER: str | None = None
    MCP_JWT_AUDIENCE: str | None = None
    MCP_JWKS_URL: str | None = None

    @model_validator(mode="after")
    def validate_keycloak_jwt_config(self) -> "Settings":
        issuer = bool(self.MCP_JWT_ISSUER)
        audience = bool(self.MCP_JWT_AUDIENCE)
        if issuer != audience:
            raise ValueError("MCP_JWT_ISSUER e MCP_JWT_AUDIENCE devem ser configurados juntos")
        if self.MCP_JWKS_URL and not (issuer and audience):
            raise ValueError("MCP_JWKS_URL exige MCP_JWT_ISSUER e MCP_JWT_AUDIENCE")
        return self

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


settings = Settings()
