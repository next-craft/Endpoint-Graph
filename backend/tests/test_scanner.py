import pathlib
import pytest
from analysis.scanner import find_service_folders, IGNORED_DIRS


def test_finds_service_at_depth_1(tmp_path: pathlib.Path):
    (tmp_path / "svc-a").mkdir()
    (tmp_path / "svc-a" / "main.py").touch()
    result = find_service_folders(str(tmp_path))
    assert result == [str(tmp_path / "svc-a")]


def test_finds_service_at_depth_2(tmp_path: pathlib.Path):
    (tmp_path / "backend" / "user-service").mkdir(parents=True)
    (tmp_path / "backend" / "user-service" / "app.py").touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / "backend" / "user-service") in result
    assert str(tmp_path / "backend") not in result


def test_finds_service_at_depth_3(tmp_path: pathlib.Path):
    (tmp_path / "a" / "b" / "svc").mkdir(parents=True)
    (tmp_path / "a" / "b" / "svc" / "main.py").touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / "a" / "b" / "svc") in result


def test_finds_multiple_services(tmp_path: pathlib.Path):
    (tmp_path / "svc-a").mkdir()
    (tmp_path / "svc-a" / "main.py").touch()
    (tmp_path / "svc-b").mkdir()
    (tmp_path / "svc-b" / "package.json").touch()
    result = find_service_folders(str(tmp_path))
    assert set(result) == {str(tmp_path / "svc-a"), str(tmp_path / "svc-b")}


def test_finds_service_by_openapi_yaml(tmp_path: pathlib.Path):
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "openapi.yaml").touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / "api") in result


def test_finds_service_by_openapi_json(tmp_path: pathlib.Path):
    (tmp_path / "api").mkdir()
    (tmp_path / "api" / "openapi.json").touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / "api") in result


def test_finds_service_by_package_json(tmp_path: pathlib.Path):
    (tmp_path / "frontend").mkdir()
    (tmp_path / "frontend" / "package.json").touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / "frontend") in result


def test_skips_ignored_dirs(tmp_path: pathlib.Path):
    (tmp_path / "node_modules" / "svc").mkdir(parents=True)
    (tmp_path / "node_modules" / "svc" / "main.py").touch()
    (tmp_path / ".git" / "svc").mkdir(parents=True)
    (tmp_path / ".git" / "svc" / "main.py").touch()
    result = find_service_folders(str(tmp_path))
    assert result == []


def test_service_folder_is_leaf(tmp_path: pathlib.Path):
    (tmp_path / "svc").mkdir()
    (tmp_path / "svc" / "main.py").touch()
    (tmp_path / "svc" / "nested").mkdir()
    (tmp_path / "svc" / "nested" / "main.py").touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / "svc") in result
    assert str(tmp_path / "svc" / "nested") not in result


def test_empty_root_returns_empty(tmp_path: pathlib.Path):
    result = find_service_folders(str(tmp_path))
    assert result == []


def test_no_service_folders_returns_empty(tmp_path: pathlib.Path):
    (tmp_path / "util").mkdir()
    (tmp_path / "util" / "helpers.txt").touch()
    result = find_service_folders(str(tmp_path))
    assert result == []


def test_nonexistent_root_returns_empty(tmp_path: pathlib.Path):
    result = find_service_folders(str(tmp_path / "does_not_exist"))
    assert result == []


def test_all_ignored_dir_names(tmp_path: pathlib.Path):
    for name in IGNORED_DIRS:
        d = tmp_path / name
        d.mkdir(exist_ok=True)
        (d / "main.py").touch()
    result = find_service_folders(str(tmp_path))
    assert result == []
