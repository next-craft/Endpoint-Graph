import os
import re
import glob
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import AnalyzeRequest, AnalyzeResponse
from analysis.cloner import clone_repo, delete_repo
from analysis.spec_parser import parse_service
from analysis.code_parser import extract_route_decorators, extract_http_calls
from analysis.url_matcher import match_url_to_endpoint

router = APIRouter()


def repo_id_from_url(repo_url: str) -> str:
    """Return 'owner/name' from any GitHub URL form.

    Accepts:
      https://github.com/owner/name
      https://github.com/owner/name.git
      github.com/owner/name

    Raises ValueError if the URL is not a github.com URL or cannot be parsed.
    """
    url = repo_url.strip().rstrip('/')
    url = re.sub(r'^https?://', '', url)
    if not url.startswith('github.com/'):
        raise ValueError(f"Cannot derive repo_id from URL: {repo_url!r}")
    url = url.removeprefix('github.com/')
    url = url.removesuffix('.git')
    parts = url.split('/')
    if len(parts) < 2 or not parts[0] or not parts[1]:
        raise ValueError(f"Cannot derive repo_id from URL: {repo_url!r}")
    return f"{parts[0]}/{parts[1]}"


def _is_service_folder(folder_path: str) -> bool:
    has_openapi = (
        os.path.exists(os.path.join(folder_path, "openapi.yaml")) or
        os.path.exists(os.path.join(folder_path, "openapi.json"))
    )
    has_python = bool(glob.glob(os.path.join(folder_path, "*.py")))
    return has_openapi or has_python


def _safe_path(file_path: str, tmp_dir: str) -> bool:
    """Return True only if file_path resolves inside tmp_dir (no symlink escapes)."""
    real_file = os.path.realpath(file_path)
    real_root = os.path.realpath(tmp_dir)
    return real_file.startswith(real_root + os.sep) or real_file == real_root


def _extract_path(url: str) -> str | None:
    if not url:
        return None
    parsed = urlparse(url)
    return parsed.path if parsed.path else None


@router.post("/analyze", response_model=AnalyzeResponse)
async def analyze(
    request: AnalyzeRequest,
    token: str = Depends(get_github_token),
    user_id: str = Depends(get_current_user_id),
):
    try:
        repo_id = repo_id_from_url(request.repo_url)
    except ValueError:
        raise HTTPException(status_code=422, detail="Invalid repo URL")

    services_count = 0
    endpoints_count = 0
    edges_count = 0
    service_records = []

    tmp_dir = None
    try:
        tmp_dir = clone_repo(request.repo_url, token)

        service_folders = [
            os.path.join(tmp_dir, entry)
            for entry in os.listdir(tmp_dir)
            if os.path.isdir(os.path.join(tmp_dir, entry))
            and _is_service_folder(os.path.join(tmp_dir, entry))
        ]

        pool = await get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                await set_rls_context(conn, user_id)
                for folder_path in service_folders:
                    service_name = os.path.basename(folder_path)

                    result = parse_service(folder_path)
                    if result is not None:
                        discovered = result["endpoints"]
                    else:
                        discovered = []
                        for py_file in glob.glob(os.path.join(folder_path, "*.py")):
                            if not _safe_path(py_file, tmp_dir):
                                continue
                            for ep in extract_route_decorators(py_file):
                                discovered.append({
                                    "method": ep["method"],
                                    "path": ep["path"],
                                    "spec_source": "decorator",
                                })

                    row = await conn.fetchrow(
                        """INSERT INTO services (name, language, repo_url, user_id, repo_id, last_analyzed_at)
                           VALUES ($1, $2, $3, $4, $5, NOW())
                           ON CONFLICT (user_id, repo_id, name)
                           DO UPDATE SET last_analyzed_at = NOW(), language = EXCLUDED.language
                           RETURNING id""",
                        service_name, "python", request.repo_url, user_id, repo_id,
                    )
                    service_id = row["id"]
                    services_count += 1

                    service_records.append((service_name, service_id, folder_path))

                    for endpoint in discovered:
                        ep_row = await conn.fetchrow(
                            """INSERT INTO endpoints (service_id, method, path, spec_source)
                               VALUES ($1, $2, $3, $4)
                               ON CONFLICT (service_id, method, path)
                               DO NOTHING
                               RETURNING id""",
                            service_id, endpoint["method"], endpoint["path"], endpoint["spec_source"],
                        )
                        if ep_row is None:
                            # DO NOTHING returns no row — fetch the existing id
                            ep_row = await conn.fetchrow(
                                "SELECT id FROM endpoints WHERE service_id=$1 AND method=$2 AND path=$3",
                                service_id, endpoint["method"], endpoint["path"],
                            )
                        endpoints_count += 1

        async with pool.acquire() as conn:
            async with conn.transaction():
                await set_rls_context(conn, user_id)
                rows = await conn.fetch("SELECT id, method, path, service_id FROM endpoints")

        known_endpoints = [
            {"id": r["id"], "method": r["method"], "path": r["path"], "service_id": r["service_id"]}
            for r in rows
        ]
        known_paths = [e["path"] for e in known_endpoints]

        async with pool.acquire() as conn:
            async with conn.transaction():
                await set_rls_context(conn, user_id)
                for service_name, service_id, folder_path in service_records:
                    py_files = glob.glob(os.path.join(folder_path, "*.py"))
                    for py_file in py_files:
                        if not _safe_path(py_file, tmp_dir):
                            continue
                        calls = extract_http_calls(py_file)
                        for call in calls:
                            url_path = _extract_path(call["url"])
                            if not url_path:
                                continue
                            matched_path = match_url_to_endpoint(url_path, known_paths)
                            if matched_path is None:
                                continue
                            # If multiple endpoints share the same path (different methods),
                            # the first match is used — v1 tracks service-level dependencies.
                            matched_endpoint = next(
                                (e for e in known_endpoints if e["path"] == matched_path), None
                            )
                            if matched_endpoint is None:
                                continue
                            endpoint_id = matched_endpoint["id"]
                            if matched_endpoint["service_id"] == service_id:
                                continue
                            await conn.execute(
                                """INSERT INTO consumer_edges
                                       (caller_service_id, endpoint_id, last_seen_at, call_count, source)
                                   VALUES ($1, $2, NOW(), 1, $3)
                                   ON CONFLICT (caller_service_id, endpoint_id)
                                   DO UPDATE SET last_seen_at = NOW(), source = EXCLUDED.source""",
                                service_id, endpoint_id, 'static',
                            )
                            edges_count += 1

    except ValueError:
        raise HTTPException(
            status_code=422,
            detail="Invalid repository URL or could not parse OpenAPI spec."
        )
    except RuntimeError:
        # Do not forward str(e) — git stderr can contain the authenticated
        # URL with the OAuth token embedded (e.g. on DNS or auth failures).
        raise HTTPException(
            status_code=400,
            detail="Repository could not be cloned. Check the URL and that you have access."
        )
    finally:
        if tmp_dir:
            delete_repo(tmp_dir)

    return AnalyzeResponse(
        status="ok",
        services=services_count,
        endpoints=endpoints_count,
        edges=edges_count
    )
