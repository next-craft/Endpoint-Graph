from unittest.mock import MagicMock
import pytest


@pytest.fixture(autouse=True)
def mock_db_pool(monkeypatch):
    import database
    monkeypatch.setattr(database, "_pool", MagicMock())


@pytest.fixture(autouse=True)
def override_get_current_user_id():
    from main import app
    from auth import get_current_user_id
    app.dependency_overrides[get_current_user_id] = lambda: "test-user-id"
    yield
    app.dependency_overrides.pop(get_current_user_id, None)


@pytest.fixture
def real_auth():
    """Temporarily restore real get_current_user_id for auth-testing scenarios."""
    from main import app
    from auth import get_current_user_id
    app.dependency_overrides.pop(get_current_user_id, None)
    yield
    app.dependency_overrides[get_current_user_id] = lambda: "test-user-id"
