"""
API integration tests.

These test the full HTTP request/response cycle using FastAPI's
TestClient. They verify:
- Request validation (Pydantic rejects bad input)
- Response schemas (correct shape and types)
- Error handling (404s, structured error responses)
- Endpoint routing

DECISION: TestClient (sync) over AsyncClient for API tests
  FastAPI's TestClient wraps httpx and runs the ASGI app synchronously.
  Simpler test code, no async fixtures needed for basic API tests.
  For tests that need real DB access, we'd use AsyncClient + test DB.

NOTE: These tests use the real app but mock the database layer.
  No PostgreSQL needed to run these tests.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from fastapi.testclient import TestClient


class TestHealthEndpoint:
    """Tests for GET /health."""

    def test_health_returns_200(self):
        """Health endpoint should always return 200 (even if degraded)."""
        with patch("app.main.engine") as mock_engine:
            # Mock the DB check to avoid needing a real Postgres
            mock_conn = AsyncMock()
            mock_conn.execute = AsyncMock(return_value=MagicMock(scalar=lambda: 1))
            mock_engine.begin.return_value.__aenter__ = AsyncMock(return_value=mock_conn)
            mock_engine.begin.return_value.__aexit__ = AsyncMock(return_value=False)

            from app.main import app
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/health")

            assert response.status_code == 200
            data = response.json()
            assert "status" in data
            assert "database" in data
            assert "knowledge_base" in data

    def test_health_response_shape(self):
        """Health response must match the HealthStatus schema."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/health")

        # Even if DB is down, the endpoint itself should return 200
        assert response.status_code == 200
        data = response.json()
        required_keys = {"status", "database", "ollama", "knowledge_base", "version"}
        assert required_keys.issubset(set(data.keys()))


class TestModelConfigEndpoint:
    """Tests for GET /config/model."""

    def test_returns_active_provider(self):
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)
        response = client.get("/config/model")

        assert response.status_code == 200
        data = response.json()
        assert "active_provider" in data
        assert "active_model" in data
        assert "available_providers" in data
        assert isinstance(data["available_providers"], list)
        assert len(data["available_providers"]) == 3


class TestSessionEndpoints:
    """Tests for session CRUD endpoints."""

    def test_create_session_validation(self):
        """POST /api/v1/sessions should accept valid input."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        # This will likely fail with a DB error (no Postgres in tests)
        # but should NOT fail with a validation error
        response = client.post(
            "/api/v1/sessions",
            json={"title": "Test Session", "metadata": {"key": "value"}},
        )
        # Either 201 (DB available) or 500 (DB unavailable) — not 422
        assert response.status_code != 422

    def test_create_session_without_body(self):
        """POST /api/v1/sessions should work with no body."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.post("/api/v1/sessions")
        # Should not be a validation error
        assert response.status_code != 422

    def test_get_session_invalid_uuid(self):
        """GET /api/v1/sessions/{id} with bad UUID should return 422."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/sessions/not-a-uuid")
        assert response.status_code == 422

    def test_list_sessions_pagination(self):
        """GET /api/v1/sessions should accept pagination params."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/sessions?limit=5&offset=0")
        # 200 if DB available, 500 if not — never 422
        assert response.status_code != 422

    def test_list_sessions_invalid_limit(self):
        """Limit > 100 should be rejected."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/sessions?limit=999")
        assert response.status_code == 422


class TestChatEndpoints:
    """Tests for chat message endpoints."""

    def test_chat_empty_content_rejected(self):
        """Chat with empty content should fail validation."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        session_id = str(uuid4())
        response = client.post(
            f"/api/v1/sessions/{session_id}/chat",
            json={"content": ""},
        )
        assert response.status_code == 422

    def test_chat_too_long_content_rejected(self):
        """Chat with >10000 chars should fail validation."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        session_id = str(uuid4())
        response = client.post(
            f"/api/v1/sessions/{session_id}/chat",
            json={"content": "x" * 10001},
        )
        assert response.status_code == 422

    def test_chat_valid_content_not_validation_error(self):
        """Valid chat content should pass validation (may fail on DB)."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        session_id = str(uuid4())
        response = client.post(
            f"/api/v1/sessions/{session_id}/chat",
            json={"content": "What is product-market fit?"},
        )
        # Should not be a validation error — 404 (session not found) or 500 (DB)
        assert response.status_code != 422


class TestKnowledgeEndpoints:
    """Tests for knowledge base endpoints."""

    def test_search_requires_query(self):
        """GET /api/v1/knowledge/search without q should fail."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/knowledge/search")
        assert response.status_code == 422

    def test_search_validates_top_k(self):
        """top_k > 20 should be rejected."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/knowledge/search?q=test&top_k=50")
        assert response.status_code == 422

    def test_search_valid_query_not_validation_error(self):
        """Valid search query should pass validation."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/knowledge/search?q=product+market+fit&top_k=3")
        assert response.status_code != 422


class TestErrorHandling:
    """Tests for error handling behavior."""

    def test_unknown_route_returns_404(self):
        """Non-existent routes should return 404."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.get("/api/v1/nonexistent")
        assert response.status_code in (404, 405)

    def test_wrong_method_returns_405(self):
        """Using wrong HTTP method should return 405."""
        from app.main import app
        client = TestClient(app, raise_server_exceptions=False)

        response = client.delete("/health")
        assert response.status_code == 405


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
