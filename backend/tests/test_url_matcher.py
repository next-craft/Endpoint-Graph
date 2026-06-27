from analysis.url_matcher import match_url_to_endpoint


def test_simple_id_match():
    assert match_url_to_endpoint("/users/123", ["/users/{id}"]) == "/users/{id}"


def test_slug_match():
    assert match_url_to_endpoint("/orders/abc-456", ["/orders/{id}"]) == "/orders/{id}"


def test_literal_segment_matches_param():
    # "profile" satisfies [^/]+ just like an ID does — it matches the param template
    assert match_url_to_endpoint("/users/profile", ["/users/{id}"]) == "/users/{id}"


def test_extra_segment_no_match():
    assert match_url_to_endpoint("/users/123/orders", ["/users/{id}"]) is None


def test_multi_segment_params():
    result = match_url_to_endpoint(
        "/orders/42/items/7",
        ["/orders/{order_id}/items/{item_id}"],
    )
    assert result == "/orders/{order_id}/items/{item_id}"


def test_literal_path_preferred_over_param():
    # Literal path listed first — it wins before the param template is tried
    result = match_url_to_endpoint(
        "/payments/charge",
        ["/payments/charge", "/payments/{id}"],
    )
    assert result == "/payments/charge"


def test_no_leading_slash():
    # Stripping handles the missing leading slash
    assert match_url_to_endpoint("users/123", ["/users/{id}"]) == "/users/{id}"


def test_empty_path():
    assert match_url_to_endpoint("", ["/users/{id}"]) is None


def test_empty_known_paths():
    assert match_url_to_endpoint("/users/123", []) is None


def test_no_match_returns_none():
    assert match_url_to_endpoint("/unknown/route", ["/users/{id}", "/orders/{id}"]) is None


def test_uuid_segment():
    uuid = "550e8400-e29b-41d4-a716-446655440000"
    assert match_url_to_endpoint(f"/users/{uuid}", ["/users/{id}"]) == "/users/{id}"
