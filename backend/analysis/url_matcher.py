import re


def match_url_to_endpoint(url_path: str, known_paths: list[str]) -> str | None:
    """
    Match a raw URL path like /users/123 to a parameterized template like /users/{id}.
    Returns the first matching template from known_paths, or None if no match.
    Caller must pass a bare path — not a full URL with scheme and host.
    List order determines priority: first match wins.
    """
    stripped = url_path.strip("/")
    for path in known_paths:
        pattern = re.sub(r"\{[^}]+\}", r"[^/]+", path.strip("/"))
        if re.fullmatch(pattern, stripped):
            return path
    return None
