from unittest.mock import MagicMock
import pytest


@pytest.fixture(autouse=True)
def mock_db_pool(monkeypatch):
    import database
    monkeypatch.setattr(database, "_pool", MagicMock())
