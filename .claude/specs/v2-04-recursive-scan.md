# Spec v2-04 — Recursive Service Discovery

## Goal
Replace the current shallow one-level service folder scan in `analyze.py` with a recursive walker that has no depth limit and is bounded only by `IGNORED_DIRS`.

## Depends on
v2-01 (DB migration), v2-02 (backend auth), v2-03 (upsert) — the analyze route uses all of those. This spec only changes how service folders are located, not the DB writes.

## Context
The current discovery logic in `analyze.py` (lines 54–59) does a single `os.listdir()` on the cloned repo root and checks immediate children. This misses monorepos where services live at depth 2 or deeper (e.g. `repo/backend/user-service/`). The fix is a recursive walker that descends into any folder that is not itself a service folder, stops when it finds one, and skips a fixed set of noise directories. The walker becomes a standalone function so it can be unit-tested independently.

## Files to create
- `backend/analysis/scanner.py` — `IGNORED_DIRS` set + `find_service_folders(root)` + `_is_service_folder(path)` helper
- `backend/tests/test_scanner.py` — unit tests for `find_service_folders` using `pytest`'s `tmp_path` fixture

## Files to edit
- `backend/routers/analyze.py` — replace the inline shallow scan (lines 54–59) and the `_is_service_folder` helper with an import of `find_service_folders` from `scanner.py`

## Implementation details

### backend/analysis/scanner.py

```python
IGNORED_DIRS = {
    '.git', 'node_modules', '.venv', '__pycache__',
    'dist', 'build', '.next', 'coverage',
}
```

Note: the user description wrote `pycache` but the correct Python cache directory name is `__pycache__`. Use `__pycache__`.

---

`_is_service_folder(folder_path: str) -> bool`

Returns `True` if the folder contains any of these files (exact filename match, not glob):
- `main.py`
- `app.py`
- `package.json`
- `openapi.yaml`
- `openapi.json`

Implementation:
```python
SERVICE_MARKERS = {'main.py', 'app.py', 'package.json', 'openapi.yaml', 'openapi.json'}

def _is_service_folder(folder_path: str) -> bool:
    try:
        entries = set(os.listdir(folder_path))
    except PermissionError:
        return False
    return bool(entries & SERVICE_MARKERS)
```

---

`find_service_folders(root: str) -> list[str]`

Recursively walks `root` to find all service folders.

Rules:
1. For each entry in a directory: skip if it is not a directory, or if its name is in `IGNORED_DIRS`.
2. If the entry is a directory and `_is_service_folder(entry)` is `True`: append `entry` to results. **Do not recurse into it** — it is a leaf.
3. If the entry is a directory and `_is_service_folder(entry)` is `False`: recurse into it.
4. The root itself is never returned — only subdirectories are candidates.
5. If `root` does not exist or is not a directory, return `[]`.

Implementation structure:
```python
def find_service_folders(root: str) -> list[str]:
    results = []

    def walk(path: str) -> None:
        try:
            entries = os.listdir(path)
        except PermissionError:
            return
        for entry in entries:
            full = os.path.join(path, entry)
            if not os.path.isdir(full):
                continue
            if entry in IGNORED_DIRS:
                continue
            if _is_service_folder(full):
                results.append(full)
            else:
                walk(full)

    if not os.path.isdir(root):
        return []
    walk(root)
    return results
```

---

### backend/routers/analyze.py

Remove the `_is_service_folder` function (lines 16–22) and the inline service folder scan (lines 54–59).

Add import at the top:
```python
from analysis.scanner import find_service_folders
```

Replace the inline scan:
```python
# OLD (lines 54–59):
service_folders = [
    os.path.join(tmp_dir, entry)
    for entry in os.listdir(tmp_dir)
    if os.path.isdir(os.path.join(tmp_dir, entry))
    and _is_service_folder(os.path.join(tmp_dir, entry))
]

# NEW (one line):
service_folders = find_service_folders(tmp_dir)
```

No other changes to `analyze.py`.

---

### backend/tests/test_scanner.py

Use `pytest`'s built-in `tmp_path` fixture (type `pathlib.Path`) — it is automatically cleaned up after each test. Create directories and files with `pathlib` methods (`tmp_path.mkdir(parents=True)`, `(tmp_path / "file").touch()`). Pass `str(tmp_path)` to `find_service_folders` since the function signature takes `str`, and compare returned paths against `str(tmp_path / "subdir")`.

`PermissionError` handling in `walk()` and `_is_service_folder()` is intentionally not tested — reliably triggering it cross-platform (particularly Windows) requires OS-level permission manipulation that is out of scope for this spec.

## Test cases

All tests live in `backend/tests/test_scanner.py`. Import `find_service_folders` and `IGNORED_DIRS` from `analysis.scanner`. Every test receives `tmp_path: pathlib.Path` as a fixture parameter. Paths returned by `find_service_folders` are absolute strings; compare with `str(tmp_path / "subdir")`.

- `test_finds_service_at_depth_1` — create `tmp_path / "svc-a" / "main.py"`; assert `find_service_folders(str(tmp_path)) == [str(tmp_path / "svc-a")]`

- `test_finds_service_at_depth_2` — create `tmp_path / "backend" / "user-service" / "app.py"`; assert `str(tmp_path / "backend" / "user-service") in result` and `str(tmp_path / "backend") not in result`

- `test_finds_service_at_depth_3` — create `tmp_path / "a" / "b" / "svc" / "main.py"`; assert `str(tmp_path / "a" / "b" / "svc") in result` — directly validates that recursion is not capped at depth 2

- `test_finds_multiple_services` — create `tmp_path / "svc-a" / "main.py"` and `tmp_path / "svc-b" / "package.json"`; assert `set(result) == {str(tmp_path / "svc-a"), str(tmp_path / "svc-b")}`

- `test_finds_service_by_openapi_yaml` — create `tmp_path / "api" / "openapi.yaml"`; assert `str(tmp_path / "api") in result`

- `test_finds_service_by_openapi_json` — create `tmp_path / "api" / "openapi.json"`; assert `str(tmp_path / "api") in result`

- `test_finds_service_by_package_json` — create `tmp_path / "frontend" / "package.json"`; assert `str(tmp_path / "frontend") in result`

- `test_skips_ignored_dirs` — create `tmp_path / "node_modules" / "svc" / "main.py"` and `tmp_path / ".git" / "svc" / "main.py"`; assert `find_service_folders(str(tmp_path)) == []`

- `test_service_folder_is_leaf` — create `tmp_path / "svc" / "main.py"` and `tmp_path / "svc" / "nested" / "main.py"`; assert `str(tmp_path / "svc") in result` and `str(tmp_path / "svc" / "nested") not in result`

- `test_empty_root_returns_empty` — pass `str(tmp_path)` with no child dirs; assert result is `[]`

- `test_no_service_folders_returns_empty` — create `tmp_path / "util" / "helpers.txt"` (a file, not a service marker); assert `find_service_folders(str(tmp_path)) == []`

- `test_nonexistent_root_returns_empty` — pass `str(tmp_path / "does_not_exist")`; assert result is `[]`

- `test_all_ignored_dir_names` — for each name in `IGNORED_DIRS`, create `tmp_path / name / "main.py"`; assert `find_service_folders(str(tmp_path)) == []`

## Done when

- [ ] `backend/analysis/scanner.py` exists with `IGNORED_DIRS`, `_is_service_folder`, and `find_service_folders`
- [ ] `__pycache__` (not `pycache`) is in `IGNORED_DIRS`
- [ ] `backend/routers/analyze.py` imports `find_service_folders` from `analysis.scanner`
- [ ] The inline shallow scan and `_is_service_folder` helper have been removed from `analyze.py`
- [ ] All 13 test cases in `backend/tests/test_scanner.py` pass (including `test_finds_service_at_depth_3`)
- [ ] No hardcoded credentials anywhere
- [ ] No TypeScript — not applicable (backend only spec)
- [ ] Follows conventions from CLAUDE.md (no ORM, raw Python stdlib only for file ops)
