import pytest
from analysis.spec_parser import (
    find_openapi_file,
    parse_openapi_file,
    extract_service_name,
    extract_endpoints,
    parse_service,
)

SAMPLE_OPENAPI = """
openapi: "3.0.0"
info:
  title: "User Service"
  version: "1.0.0"
paths:
  /users/{id}:
    get:
      summary: Get user by ID
    post:
      summary: Update user
  /users/profile:
    get:
      summary: Get current user profile
"""


# ── find_openapi_file ──────────────────────────────────────────────────────────

def test_find_openapi_file_yaml(tmp_path):
    f = tmp_path / "openapi.yaml"
    f.write_text("openapi: '3.0.0'")
    assert find_openapi_file(str(tmp_path)) == str(f)


def test_find_openapi_file_json(tmp_path):
    f = tmp_path / "openapi.json"
    f.write_text('{"openapi": "3.0.0"}')
    assert find_openapi_file(str(tmp_path)) == str(f)


def test_find_openapi_file_yaml_takes_priority(tmp_path):
    yaml_f = tmp_path / "openapi.yaml"
    yaml_f.write_text("openapi: '3.0.0'")
    json_f = tmp_path / "openapi.json"
    json_f.write_text('{"openapi": "3.0.0"}')
    assert find_openapi_file(str(tmp_path)) == str(yaml_f)


def test_find_openapi_file_missing(tmp_path):
    assert find_openapi_file(str(tmp_path)) is None


# ── parse_openapi_file ─────────────────────────────────────────────────────────

def test_parse_openapi_file_valid(tmp_path):
    f = tmp_path / "openapi.yaml"
    f.write_text(SAMPLE_OPENAPI)
    result = parse_openapi_file(str(f))
    assert isinstance(result, dict)


def test_parse_openapi_file_empty(tmp_path):
    f = tmp_path / "openapi.yaml"
    f.write_text("")
    with pytest.raises(ValueError):
        parse_openapi_file(str(f))


def test_parse_openapi_file_non_dict(tmp_path):
    f = tmp_path / "openapi.yaml"
    f.write_text("- item1\n- item2\n")
    with pytest.raises(ValueError):
        parse_openapi_file(str(f))


# ── extract_service_name ───────────────────────────────────────────────────────

def test_extract_service_name_present():
    assert extract_service_name({"info": {"title": "Order Service"}}) == "Order Service"


def test_extract_service_name_missing_info():
    assert extract_service_name({}) == "unknown"


def test_extract_service_name_missing_title():
    assert extract_service_name({"info": {}}) == "unknown"


def test_extract_service_name_info_is_none():
    assert extract_service_name({"info": None}) == "unknown"


# ── extract_endpoints ──────────────────────────────────────────────────────────

def test_extract_endpoints_basic():
    spec = {"paths": {"/users/{id}": {"get": {}, "post": {}}}}
    result = extract_endpoints(spec)
    assert len(result) == 2
    methods = {e["method"] for e in result}
    assert methods == {"GET", "POST"}
    for e in result:
        assert e["path"] == "/users/{id}"
        assert e["spec_source"] == "openapi"


def test_extract_endpoints_filters_non_methods():
    spec = {"paths": {"/users/{id}": {"summary": "A path", "parameters": [], "get": {}}}}
    result = extract_endpoints(spec)
    assert len(result) == 1
    assert result[0]["method"] == "GET"


def test_extract_endpoints_excludes_options_and_head():
    spec = {"paths": {"/ping": {"options": {}, "head": {}, "get": {}}}}
    result = extract_endpoints(spec)
    assert len(result) == 1
    assert result[0]["method"] == "GET"


def test_extract_endpoints_null_path_item():
    spec = {"paths": {"/users/{id}": None}}
    result = extract_endpoints(spec)
    assert result == []


def test_extract_endpoints_empty_paths():
    assert extract_endpoints({"paths": {}}) == []


def test_extract_endpoints_missing_paths():
    assert extract_endpoints({}) == []


def test_extract_endpoints_methods_uppercase():
    spec = {"paths": {"/items": {"get": {}, "post": {}}}}
    result = extract_endpoints(spec)
    for e in result:
        assert e["method"] == e["method"].upper()


def test_extract_endpoints_spec_source():
    spec = {"paths": {"/items": {"get": {}}}}
    result = extract_endpoints(spec)
    for e in result:
        assert e["spec_source"] == "openapi"


# ── parse_service ──────────────────────────────────────────────────────────────

def test_parse_service_returns_none_when_no_file(tmp_path):
    assert parse_service(str(tmp_path)) is None


def test_parse_service_malformed_file(tmp_path):
    f = tmp_path / "openapi.yaml"
    f.write_text("")
    with pytest.raises(ValueError):
        parse_service(str(tmp_path))


def test_parse_service_full_flow(tmp_path):
    f = tmp_path / "openapi.yaml"
    f.write_text(SAMPLE_OPENAPI)
    result = parse_service(str(tmp_path))
    assert result is not None
    assert result["service_name"] == "User Service"
    assert len(result["endpoints"]) == 3
    paths = {e["path"] for e in result["endpoints"]}
    assert "/users/{id}" in paths
    assert "/users/profile" in paths
