import re


def _to_regex(path_str: str) -> str:
    return re.sub(r"\{[^}]+\}", r"[^/]+", path_str)


def match_url_to_endpoint(url_path: str, known_paths: list[str]) -> str | None:
    """
    Match a raw URL path like /users/123 to a parameterized template like /users/{id}.
    Returns the first matching template from known_paths, or None if no match.
    Caller must pass a bare path — not a full URL with scheme and host.

    Tries an exact full-path match first (list order determines priority — first
    match wins). If nothing matches exactly, falls back to suffix matching: the
    call's path segments must equal a contiguous trailing slice of a known path's
    segments. This covers endpoints whose stored path carries a mount prefix (e.g.
    "/v1", composed in from APIRouter/include_router — see code_parser.compose_route_path)
    that the caller's HTTP client supplies via an opaque baseURL at runtime and never
    spells out in the literal call string. When multiple known paths suffix-match,
    the one with the fewest unaccounted leading segments (the tightest match) wins;
    ties fall back to list order.
    """
    stripped = url_path.strip("/")
    call_segments = stripped.split("/") if stripped else []
    if not call_segments:
        return None

    for path in known_paths:
        pattern = _to_regex(path.strip("/"))
        if re.fullmatch(pattern, stripped):
            return path

    best_path = None
    best_unaccounted = None
    for path in known_paths:
        known_segments = path.strip("/").split("/")
        if len(call_segments) >= len(known_segments):
            continue
        trailing = known_segments[len(known_segments) - len(call_segments):]
        pattern = _to_regex("/".join(trailing))
        if not re.fullmatch(pattern, stripped):
            continue
        unaccounted = len(known_segments) - len(call_segments)
        if best_unaccounted is None or unaccounted < best_unaccounted:
            best_path, best_unaccounted = path, unaccounted
    return best_path
