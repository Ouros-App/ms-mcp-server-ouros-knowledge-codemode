from typing import Any, Literal

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from app.core.config import settings
from app.services.auth import KeycloakOrStaticTokenVerifier, get_authenticated_identity
from app.services.database import (
    get_user_context as get_database_user_context,
)
from app.services.database import (
    get_user_farm_data as get_database_user_farm_data,
)
from app.services.database import (
    postgres_status as get_postgres_status,
)
from app.services.knowledge import (
    qdrant_status as get_qdrant_status,
)
from app.services.knowledge import (
    search_knowledge as search_qdrant,
)

mcp = FastMCP(
    name=settings.PROJECT_NAME,
    host="0.0.0.0",
    stateless_http=True,
    json_response=True,
    streamable_http_path="/",
    auth=AuthSettings(
        issuer_url=settings.MCP_JWT_ISSUER,
        resource_server_url=settings.MCP_RESOURCE_URL,
    ),
    token_verifier=KeycloakOrStaticTokenVerifier(),
)


@mcp.tool()
def search_knowledge(
    query: str, limit: int = settings.SEARCH_TOP_K
) -> list[dict[str, Any]]:
    """Search Qdrant using NVIDIA embeddings.

    Args:
        query: Natural-language question or search phrase.
        limit: Number of matches to return, from 1 to 20.
    """
    if not query.strip():
        raise ValueError("query não pode ser vazio")
    if not 1 <= limit <= 20:
        raise ValueError("limit deve estar entre 1 e 20")
    return search_qdrant(query.strip(), limit)


@mcp.tool()
def qdrant_status() -> dict[str, Any]:
    """Check whether the configured Qdrant collection is reachable."""
    return get_qdrant_status()


@mcp.tool()
def postgres_status() -> dict[str, Any]:
    """Check whether the MIDAS read-only PostgreSQL connection is reachable."""
    return get_postgres_status()


@mcp.tool()
def get_user_context(
    user_type: Literal["farm_owner", "company_employee", "admin"], user_id: int
) -> dict[str, Any]:
    """Load a user's profile and linked farms for personalized answers.

    Args:
        user_type: `farm_owner`, `company_employee`, or `admin`.
        user_id: Positive MIDAS user ID to scope the database queries.

    The identity is validated after the shared MCP token authenticates the client.
    """
    user_type, user_id = get_authenticated_identity(user_type, user_id)
    return get_database_user_context(user_type, user_id)


@mcp.tool()
def get_user_farm_data(
    user_type: Literal["farm_owner", "company_employee", "admin"],
    user_id: int,
    limit: int = 20,
) -> dict[str, Any]:
    """Load bounded farm data for the requested MIDAS user.

    Args:
        user_type: `farm_owner`, `company_employee`, or `admin`.
        user_id: Positive MIDAS user ID to scope the database queries.
        limit: Maximum number of records per data group, from 1 to 100.
    """
    user_type, user_id = get_authenticated_identity(user_type, user_id)
    return get_database_user_farm_data(user_type, user_id, limit)
