import os
import re
import glob
from urllib.parse import urlparse
from fastapi import APIRouter, Depends, HTTPException
from database import get_pool
from auth import get_github_token, get_current_user_id, set_rls_context
from models import AnalyzeRequest, AnalyzeResponse
from analysis.cloner import clone_repo, delete_repo
from analysis.scanner import find_service_folders, IGNORED_DIRS
from analysis.spec_parser import parse_service
from analysis.code_parser import (
    extract_route_decorators,
    extract_http_calls,
    extract_js_routes,
    extract_js_http_calls,
    extract_router_local_prefix,
    extract_include_router_mounts,
    compose_route_path,
    detect_service_language,
)
from analysis.url_matcher import match_url_to_endpoint


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


def _is_in_ignored_dir(file_path: str, root: str) -> bool:
    """Return True if any path component between root and file_path is in IGNORED_DIRS."""
    rel = os.path.relpath(file_path, root)
    return any(part in IGNORED_DIRS for part in rel.split(os.sep))


UPSERT_EDGE_SQL = """INSERT INTO consumer_edges
    (caller_service_id, endpoint_id, last_seen_at, call_count, source, caller_file_path, caller_function_name)
VALUES ($1, $2, NOW(), 1, $3, $4, $5)
ON CONFLICT (caller_service_id, endpoint_id, caller_file_path, caller_function_name)
DO UPDATE SET call_count = consumer_edges.call_count + 1,
              last_seen_at = NOW(), source = EXCLUDED.source,
              caller_file_path = EXCLUDED.caller_file_path,
              caller_function_name = EXCLUDED.caller_function_name"""

router = APIRouter()


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

        service_folders = find_service_folders(tmp_dir)

        pool = await get_pool()

        async with pool.acquire() as conn:
            async with conn.transaction():
                await set_rls_context(conn, user_id)
                for folder_path in service_folders:
                    service_name = os.path.basename(folder_path)

                    result = parse_service(folder_path)
                    if result is not None:
                        discovered = [
                            {**ep, "file_path": None, "function_name": None}
                            for ep in result["endpoints"]
                        ]
                    else:
                        discovered = []
                        py_files = [
                            p for p in glob.glob(os.path.join(folder_path, "**", "*.py"), recursive=True)
                            if _safe_path(p, tmp_dir) and not _is_in_ignored_dir(p, folder_path)
                        ]

                        # A route's real path is prefix_from_include_router + prefix_from_APIRouter +
                        # its own decorator path (e.g. "/v1" + "/colleges" + "/{slug}"). Both prefixes
                        # can live in files other than the one declaring the route, so resolve them
                        # across the whole service folder before extracting any decorators.
                        router_prefix_by_file = {p: extract_router_local_prefix(p) for p in py_files}
                        mount_prefix_by_module = {}
                        for p in py_files:
                            for mount in extract_include_router_mounts(p):
                                if mount["module_name"]:
                                    mount_prefix_by_module[mount["module_name"]] = mount["prefix"]

                        # Python route decorators
                        for py_file in py_files:
                            rel_path = os.path.relpath(py_file, folder_path).replace(os.sep, "/")
                            module_name = os.path.splitext(os.path.basename(py_file))[0]
                            mount_prefix = mount_prefix_by_module.get(module_name, "")
                            router_prefix = router_prefix_by_file.get(py_file) or ""
                            for ep in extract_route_decorators(py_file):
                                discovered.append({
                                    "method": ep["method"],
                                    "path": compose_route_path(mount_prefix, router_prefix, ep["path"]),
                                    "spec_source": "decorator",
                                    "file_path": rel_path,
                                    "function_name": ep.get("function_name"),
                                })
                        # JS/TS route decorators and Next.js file-based routes
                        for pattern in ("**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"):
                            for js_file in glob.glob(os.path.join(folder_path, pattern), recursive=True):
                                if not _safe_path(js_file, tmp_dir):
                                    continue
                                if _is_in_ignored_dir(js_file, folder_path):
                                    continue
                                rel_path = os.path.relpath(js_file, folder_path).replace(os.sep, "/")
                                for ep in extract_js_routes(js_file):
                                    ep["file_path"] = rel_path
                                    discovered.append(ep)

                    lang = detect_service_language(folder_path)
                    row = await conn.fetchrow(
                        """INSERT INTO services (name, language, repo_url, user_id, repo_id, last_analyzed_at)
                           VALUES ($1, $2, $3, $4, $5, NOW())
                           ON CONFLICT (user_id, repo_id, name)
                           DO UPDATE SET last_analyzed_at = NOW(), language = EXCLUDED.language
                           RETURNING id""",
                        service_name, lang, request.repo_url, user_id, repo_id,
                    )
                    service_id = row["id"]
                    services_count += 1

                    service_records.append((service_name, service_id, folder_path))

                    for endpoint in discovered:
                        ep_row = await conn.fetchrow(
                            """INSERT INTO endpoints (service_id, method, path, spec_source, file_path, function_name)
                               VALUES ($1, $2, $3, $4, $5, $6)
                               ON CONFLICT (service_id, method, path)
                               DO UPDATE SET file_path = EXCLUDED.file_path, function_name = EXCLUDED.function_name
                               RETURNING id""",
                            service_id, endpoint["method"], endpoint["path"], endpoint["spec_source"],
                            endpoint.get("file_path"), endpoint.get("function_name"),
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

        async with pool.acquire() as conn:
            async with conn.transaction():
                await set_rls_context(conn, user_id)
                for service_name, service_id, folder_path in service_records:
                    # Python HTTP calls
                    for py_file in glob.glob(os.path.join(folder_path, "**", "*.py"), recursive=True):
                        if not _safe_path(py_file, tmp_dir):
                            continue
                        if _is_in_ignored_dir(py_file, folder_path):
                            continue
                        for call in extract_http_calls(py_file):
                            url_path = _extract_path(call["url"])
                            if not url_path:
                                continue
                            candidates = [e for e in known_endpoints if e["method"] == call.get("method")]
                            matched_path = match_url_to_endpoint(url_path, [e["path"] for e in candidates])
                            if matched_path is None:
                                continue
                            matched_endpoint = next(
                                (e for e in candidates if e["path"] == matched_path), None
                            )
                            if matched_endpoint is None or matched_endpoint["service_id"] == service_id:
                                continue
                            caller_rel_path = os.path.relpath(py_file, folder_path).replace(os.sep, "/")
                            await conn.execute(
                                UPSERT_EDGE_SQL, service_id, matched_endpoint["id"], "static",
                                caller_rel_path, call.get("caller_function_name"),
                            )
                            edges_count += 1
                    # JS/TS HTTP calls (extract_js_http_calls returns list[dict] with url/file_path/caller_function_name)
                    for pattern in ("**/*.js", "**/*.jsx", "**/*.ts", "**/*.tsx"):
                        for js_file in glob.glob(os.path.join(folder_path, pattern), recursive=True):
                            if not _safe_path(js_file, tmp_dir):
                                continue
                            if _is_in_ignored_dir(js_file, folder_path):
                                continue
                            for call in extract_js_http_calls(js_file):
                                url_path = _extract_path(call["url"])
                                if not url_path:
                                    continue
                                candidates = [e for e in known_endpoints if e["method"] == call.get("method")]
                                matched_path = match_url_to_endpoint(url_path, [e["path"] for e in candidates])
                                if matched_path is None:
                                    continue
                                matched_endpoint = next(
                                    (e for e in candidates if e["path"] == matched_path), None
                                )
                                if matched_endpoint is None or matched_endpoint["service_id"] == service_id:
                                    continue
                                caller_rel_path = os.path.relpath(call["file_path"], folder_path).replace(os.sep, "/")
                                await conn.execute(
                                    UPSERT_EDGE_SQL, service_id, matched_endpoint["id"], "static",
                                    caller_rel_path, call.get("caller_function_name"),
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
