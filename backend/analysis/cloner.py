import subprocess
import tempfile
import uuid
import shutil
import re
import os


def clone_repo(repo_url: str, github_token: str) -> str:
    repo_url = repo_url.strip()
    repo_url = re.sub(r'^https?://', '', repo_url)
    if not repo_url.startswith('github.com/'):
        raise ValueError(f"Invalid GitHub URL: {repo_url}")

    auth_url = f"https://{github_token}@{repo_url}"
    tmp_dir = os.path.join(tempfile.gettempdir(), str(uuid.uuid4()))

    result = subprocess.run(
        ["git", "clone", "--depth", "1", auth_url, tmp_dir],
        capture_output=True,
        text=True
    )

    if result.returncode != 0:
        raise RuntimeError(f"Clone failed: {result.stderr}")

    return tmp_dir


def delete_repo(tmp_dir: str) -> None:
    shutil.rmtree(tmp_dir, ignore_errors=True)
