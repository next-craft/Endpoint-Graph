import os
import tempfile
from unittest.mock import patch, MagicMock

import pytest

from analysis.cloner import clone_repo, delete_repo


def test_clone_repo_strips_https():
    with patch("analysis.cloner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        clone_repo("https://github.com/user/repo", "fake-token")
        cmd = mock_run.call_args[0][0]
        assert cmd[4] == "https://fake-token@github.com/user/repo"


def test_clone_repo_strips_http():
    with patch("analysis.cloner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        clone_repo("http://github.com/user/repo", "fake-token")
        cmd = mock_run.call_args[0][0]
        assert cmd[4] == "https://fake-token@github.com/user/repo"


def test_clone_repo_strips_whitespace():
    with patch("analysis.cloner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        clone_repo("  https://github.com/user/repo  ", "fake-token")
        cmd = mock_run.call_args[0][0]
        assert cmd[4] == "https://fake-token@github.com/user/repo"


def test_clone_invalid_url_no_github():
    with pytest.raises(ValueError, match="Invalid GitHub URL"):
        clone_repo("gitlab.com/user/repo", "fake-token")


def test_clone_invalid_url_empty():
    with pytest.raises(ValueError, match="Invalid GitHub URL"):
        clone_repo("", "fake-token")


def test_clone_failure_raises_runtime_error():
    with patch("analysis.cloner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=128, stderr="fatal: repo not found")
        with pytest.raises(RuntimeError, match="Clone failed"):
            clone_repo("github.com/user/repo", "fake-token")


def test_clone_success_returns_tmp_dir():
    with patch("analysis.cloner.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0)
        result = clone_repo("github.com/user/repo", "fake-token")
        assert result
        assert result.startswith(tempfile.gettempdir())


def test_delete_repo_removes_directory():
    tmp_dir = os.path.join(tempfile.gettempdir(), "cloner-test-delete")
    os.makedirs(tmp_dir, exist_ok=True)
    assert os.path.exists(tmp_dir)
    delete_repo(tmp_dir)
    assert not os.path.exists(tmp_dir)


def test_delete_repo_safe_on_nonexistent_path():
    path = os.path.join(tempfile.gettempdir(), "nonexistent-cloner-test-path")
    delete_repo(path)  # must not raise
