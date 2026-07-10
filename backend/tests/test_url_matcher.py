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


# ── Issue 12: suffix-match fallback for baseURL-supplied mount prefixes ────────

def test_suffix_match_with_mount_prefix():
    # The caller's literal string never spells out "/v1" -- its axios baseURL
    # supplies it at runtime -- but the stored endpoint path has it composed in
    # (from APIRouter(prefix="/v1")). Exact match fails; suffix match must catch it.
    assert match_url_to_endpoint("/users/me", ["/v1/users/me"]) == "/v1/users/me"


def test_suffix_match_with_param_in_known_path():
    assert match_url_to_endpoint("/users/123", ["/v1/users/{id}"]) == "/v1/users/{id}"


def test_suffix_match_prefers_fewest_unaccounted_segments():
    # Both candidates suffix-match "/users/me" -- the /v1 one is the tighter fit.
    result = match_url_to_endpoint("/users/me", ["/v2/api/users/me", "/v1/users/me"])
    assert result == "/v1/users/me"


def test_exact_match_still_wins_over_suffix_match():
    # An exact match must never be skipped in favor of a fallback suffix match,
    # even when a shorter/prefixed candidate is listed first.
    result = match_url_to_endpoint("/users/me", ["/v1/users/me", "/users/me"])
    assert result == "/users/me"


def test_suffix_match_requires_contiguous_trailing_segments():
    # "/v1/me" is not the trailing 2 segments of "/v1/users/me" ("users/me" is) --
    # a match here would mean segments are being matched positionally-anywhere
    # rather than as a genuine trailing slice.
    assert match_url_to_endpoint("/v1/me", ["/v1/users/me"]) is None


def test_no_suffix_match_when_call_has_more_segments_than_known():
    assert match_url_to_endpoint("/users/123/extra", ["/v1/users/{id}"]) is None


def test_no_suffix_match_when_trailing_segments_dont_align():
    assert match_url_to_endpoint("/orders/me", ["/v1/users/me"]) is None
