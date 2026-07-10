"""
Independent tests for v2-04 recursive service discovery.
Derived from reading scanner.py directly — not from the spec's test-case list.
"""
import os
import pathlib
import pytest
from analysis.scanner import find_service_folders, IGNORED_DIRS, SERVICE_MARKERS, _is_service_folder


# ── Constants ──────────────────────────────────────────────────────────────────

def test_pycache_spelled_with_double_underscores():
    # Must be __pycache__, not pycache
    assert '__pycache__' in IGNORED_DIRS
    assert 'pycache' not in IGNORED_DIRS

def test_ignored_dirs_has_eight_entries():
    assert len(IGNORED_DIRS) == 8

def test_ignored_dirs_exact_contents():
    assert IGNORED_DIRS == {'.git', 'node_modules', '.venv', '__pycache__', 'dist', 'build', '.next', 'coverage'}

def test_service_markers_exact_contents():
    assert SERVICE_MARKERS == {'main.py', 'app.py', 'package.json', 'openapi.yaml', 'openapi.json'}


# ── _is_service_folder: happy paths (one test per marker) ─────────────────────

def test_is_service_folder_detects_main_py(tmp_path: pathlib.Path):
    (tmp_path / 'main.py').touch()
    assert _is_service_folder(str(tmp_path)) is True

def test_is_service_folder_detects_app_py(tmp_path: pathlib.Path):
    (tmp_path / 'app.py').touch()
    assert _is_service_folder(str(tmp_path)) is True

def test_is_service_folder_detects_package_json(tmp_path: pathlib.Path):
    (tmp_path / 'package.json').touch()
    assert _is_service_folder(str(tmp_path)) is True

def test_is_service_folder_detects_openapi_yaml(tmp_path: pathlib.Path):
    (tmp_path / 'openapi.yaml').touch()
    assert _is_service_folder(str(tmp_path)) is True

def test_is_service_folder_detects_openapi_json(tmp_path: pathlib.Path):
    (tmp_path / 'openapi.json').touch()
    assert _is_service_folder(str(tmp_path)) is True


# ── _is_service_folder: false / edge cases ────────────────────────────────────

def test_is_service_folder_false_when_empty(tmp_path: pathlib.Path):
    assert _is_service_folder(str(tmp_path)) is False

def test_is_service_folder_false_for_unrelated_files(tmp_path: pathlib.Path):
    (tmp_path / 'README.md').touch()
    (tmp_path / 'config.yaml').touch()
    (tmp_path / 'helpers.py').touch()
    assert _is_service_folder(str(tmp_path)) is False

def test_is_service_folder_false_for_similar_but_wrong_names(tmp_path: pathlib.Path):
    # Filenames that look close but don't match any marker
    (tmp_path / 'main.txt').touch()
    (tmp_path / 'app.pyc').touch()
    (tmp_path / 'package.json.bak').touch()
    (tmp_path / 'openapi.yml').touch()   # .yml not .yaml
    assert _is_service_folder(str(tmp_path)) is False

def test_is_service_folder_true_with_noise_alongside_marker(tmp_path: pathlib.Path):
    # Extra files must not mask the marker
    (tmp_path / 'main.py').touch()
    (tmp_path / 'utils.py').touch()
    (tmp_path / 'README.md').touch()
    assert _is_service_folder(str(tmp_path)) is True

def test_is_service_folder_returns_bool_not_truthy(tmp_path: pathlib.Path):
    # The function must return an actual bool, not just a truthy/falsy value
    (tmp_path / 'main.py').touch()
    result = _is_service_folder(str(tmp_path))
    assert result is True

    empty = tmp_path / 'empty'
    empty.mkdir()
    result2 = _is_service_folder(str(empty))
    assert result2 is False


# ── find_service_folders: return type and path format ─────────────────────────

def test_returns_list_type(tmp_path: pathlib.Path):
    result = find_service_folders(str(tmp_path))
    assert isinstance(result, list)

def test_returns_strings_not_paths(tmp_path: pathlib.Path):
    (tmp_path / 'svc').mkdir()
    (tmp_path / 'svc' / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert all(isinstance(p, str) for p in result)

def test_returns_absolute_paths(tmp_path: pathlib.Path):
    (tmp_path / 'svc').mkdir()
    (tmp_path / 'svc' / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert len(result) == 1
    assert os.path.isabs(result[0])

def test_returned_path_equals_os_path_join(tmp_path: pathlib.Path):
    # The path must be exactly os.path.join(root, "svc"), not a pathlib variant
    (tmp_path / 'svc').mkdir()
    (tmp_path / 'svc' / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert result == [os.path.join(str(tmp_path), 'svc')]


# ── find_service_folders: root-level guard clauses ───────────────────────────

def test_nonexistent_root_returns_empty():
    result = find_service_folders('/this/path/cannot/exist/ever/9z8x7y')
    assert result == []

def test_file_path_as_root_returns_empty(tmp_path: pathlib.Path):
    # Passing a file (not a dir) must return [] — os.path.isdir is False
    f = tmp_path / 'somefile.py'
    f.touch()
    result = find_service_folders(str(f))
    assert result == []

def test_root_itself_is_a_service_when_markers_live_there(tmp_path: pathlib.Path):
    # A single-service monolith repo (e.g. package.json at the repo root, no
    # services/ subfolder) must itself be detected as a service folder --
    # otherwise root-level monoliths can never be tracked at all (discovered
    # via v2-open-issues.md issue 8's airbnb-clone repro).
    (tmp_path / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert result == [str(tmp_path)]

def test_walk_skips_loose_files_without_crashing(tmp_path: pathlib.Path):
    # A loose non-marker file alongside a real service subdirectory must not
    # be mistaken for a directory to recurse into (os.path.isdir guard),
    # and must not stop the real service from being found.
    (tmp_path / 'README.md').touch()
    (tmp_path / 'svc').mkdir()
    (tmp_path / 'svc' / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert result == [str(tmp_path / 'svc')]

def test_empty_root_returns_empty(tmp_path: pathlib.Path):
    result = find_service_folders(str(tmp_path))
    assert result == []


# ── find_service_folders: IGNORED_DIRS guard ─────────────────────────────────

def test_each_ignored_dir_name_is_skipped(tmp_path: pathlib.Path):
    # For every name in IGNORED_DIRS, create a service inside it and verify
    # none appear in results
    for name in IGNORED_DIRS:
        inner = tmp_path / name / 'nested-svc'
        inner.mkdir(parents=True, exist_ok=True)
        (inner / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert result == []

def test_ignored_dir_at_depth_2_is_also_skipped(tmp_path: pathlib.Path):
    # IGNORED_DIRS check applies at every level of the walk
    (tmp_path / 'packages' / 'node_modules' / 'svc').mkdir(parents=True)
    (tmp_path / 'packages' / 'node_modules' / 'svc' / 'main.py').touch()
    (tmp_path / 'packages' / 'real-svc').mkdir(parents=True)
    (tmp_path / 'packages' / 'real-svc' / 'app.py').touch()
    result = find_service_folders(str(tmp_path))
    assert result == [str(tmp_path / 'packages' / 'real-svc')]


# ── find_service_folders: leaf semantics ─────────────────────────────────────

def test_service_folder_subdirs_not_recursed(tmp_path: pathlib.Path):
    # Once _is_service_folder returns True, walk must NOT recurse into subdirs
    (tmp_path / 'svc').mkdir()
    (tmp_path / 'svc' / 'main.py').touch()
    (tmp_path / 'svc' / 'lib').mkdir()
    (tmp_path / 'svc' / 'lib' / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / 'svc') in result
    assert str(tmp_path / 'svc' / 'lib') not in result

def test_non_service_dir_is_recursed_into(tmp_path: pathlib.Path):
    # A dir without a marker must be walked — not silently skipped
    (tmp_path / 'monorepo' / 'services' / 'api').mkdir(parents=True)
    (tmp_path / 'monorepo' / 'services' / 'api' / 'app.py').touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / 'monorepo' / 'services' / 'api') in result
    assert str(tmp_path / 'monorepo') not in result
    assert str(tmp_path / 'monorepo' / 'services') not in result


# ── find_service_folders: single-service monolith at repo root ───────────────

def test_single_service_monolith_with_subfolders_is_found_once(tmp_path: pathlib.Path):
    # Reproduces the real airbnb-clone repo shape from v2-open-issues.md
    # issue 8: package.json at the repo root, with plain (non-service)
    # subfolders like routes/ and controller/ alongside it. The whole repo
    # must be returned as exactly one service -- the root -- and none of its
    # subfolders should also show up as separate services.
    (tmp_path / 'package.json').touch()
    (tmp_path / 'app.js').touch()
    (tmp_path / 'routes').mkdir()
    (tmp_path / 'routes' / 'authRouter.js').touch()
    (tmp_path / 'controller').mkdir()
    (tmp_path / 'controller' / 'authController.js').touch()
    result = find_service_folders(str(tmp_path))
    assert result == [str(tmp_path)]


# ── find_service_folders: multi-service and depth scenarios ──────────────────

def test_finds_two_services_at_same_depth(tmp_path: pathlib.Path):
    for name in ('svc-a', 'svc-b'):
        (tmp_path / name).mkdir()
        (tmp_path / name / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert set(result) == {str(tmp_path / 'svc-a'), str(tmp_path / 'svc-b')}

def test_finds_services_at_depth_3(tmp_path: pathlib.Path):
    # Recursion must not be capped at depth 1 or 2
    (tmp_path / 'a' / 'b' / 'c').mkdir(parents=True)
    (tmp_path / 'a' / 'b' / 'c' / 'package.json').touch()
    result = find_service_folders(str(tmp_path))
    assert str(tmp_path / 'a' / 'b' / 'c') in result

def test_ignored_and_valid_dirs_coexist(tmp_path: pathlib.Path):
    # Results include the valid service and exclude anything under ignored dir
    (tmp_path / 'node_modules' / 'lib').mkdir(parents=True)
    (tmp_path / 'node_modules' / 'lib' / 'main.py').touch()
    (tmp_path / 'backend' / 'api').mkdir(parents=True)
    (tmp_path / 'backend' / 'api' / 'main.py').touch()
    result = find_service_folders(str(tmp_path))
    assert result == [str(tmp_path / 'backend' / 'api')]
