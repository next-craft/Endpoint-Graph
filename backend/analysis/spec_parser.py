import os
import yaml


def find_openapi_file(service_dir: str) -> str | None:
    for filename in ("openapi.yaml", "openapi.json"):
        path = os.path.join(service_dir, filename)
        if os.path.isfile(path):
            return path
    return None


def parse_openapi_file(file_path: str) -> dict:
    with open(file_path, "r", encoding="utf-8") as f:
        result = yaml.safe_load(f)
    if not isinstance(result, dict):
        raise ValueError(f"OpenAPI file did not parse to a dict: {file_path}")
    return result


def extract_service_name(spec: dict) -> str:
    info = spec.get("info")
    if not isinstance(info, dict):
        return "unknown"
    return info.get("title", "unknown")


_ALLOWED_METHODS = {"get", "post", "put", "delete", "patch"}


def extract_endpoints(spec: dict) -> list[dict]:
    paths = spec.get("paths")
    if not paths:
        return []

    endpoints = []
    for path_str, path_item in paths.items():
        if path_item is None:
            continue
        for key in path_item:
            if key in _ALLOWED_METHODS:
                endpoints.append({
                    "method": key.upper(),
                    "path": path_str,
                    "spec_source": "openapi",
                })
    return endpoints


def parse_service(service_dir: str) -> dict | None:
    file_path = find_openapi_file(service_dir)
    if file_path is None:
        return None

    spec = parse_openapi_file(file_path)
    return {
        "service_name": extract_service_name(spec),
        "endpoints": extract_endpoints(spec),
    }
