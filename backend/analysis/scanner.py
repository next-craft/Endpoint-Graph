import os

IGNORED_DIRS = {
    '.git', 'node_modules', '.venv', '__pycache__',
    'dist', 'build', '.next', 'coverage',
}

SERVICE_MARKERS = {'main.py', 'app.py', 'package.json', 'openapi.yaml', 'openapi.json'}


def _is_service_folder(folder_path: str) -> bool:
    try:
        entries = set(os.listdir(folder_path))
    except PermissionError:
        return False
    return bool(entries & SERVICE_MARKERS)


def find_service_folders(root: str) -> list[str]:
    if not os.path.isdir(root):
        return []

    # A single-service repo (e.g. a monolith with package.json at the repo
    # root, no separate services/ subfolder) is itself a service folder --
    # without this check it would never be found, since the walk below only
    # ever inspects root's subdirectories.
    if _is_service_folder(root):
        return [root]

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

    walk(root)
    return results
