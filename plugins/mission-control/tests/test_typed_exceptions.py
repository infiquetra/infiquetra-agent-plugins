"""Tests for the typed-exception classifier (replaces fragile string matching).

`_classify_gh_error` parses gh CLI stderr ONCE and raises the appropriate
GhApiError subclass; downstream callers catch by type instead of doing
`"422" in str(e)` substring matching.
"""

import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sdlc_manager  # noqa: E402

# --- _classify_gh_error: status-code parsing -------------------------------


def test_classifies_404_as_ApiNotFound() -> None:
    exc = sdlc_manager._classify_gh_error(
        stderr="gh: Not Found (HTTP 404)\n",
        returncode=1,
    )
    assert isinstance(exc, sdlc_manager.ApiNotFound)
    assert exc.status_code == 404


def test_classifies_401_as_ApiAuthError() -> None:
    exc = sdlc_manager._classify_gh_error(
        stderr="HTTP 401: Bad credentials\n",
        returncode=1,
    )
    assert isinstance(exc, sdlc_manager.ApiAuthError)
    assert not isinstance(exc, sdlc_manager.ApiRateLimited)


def test_classifies_403_with_rate_limit_signal_as_ApiRateLimited() -> None:
    exc = sdlc_manager._classify_gh_error(
        stderr="HTTP 403: API rate limit exceeded\n",
        returncode=1,
    )
    assert isinstance(exc, sdlc_manager.ApiRateLimited)


def test_classifies_403_without_rate_limit_as_ApiAuthError() -> None:
    exc = sdlc_manager._classify_gh_error(
        stderr="HTTP 403: Forbidden — insufficient scope\n",
        returncode=1,
    )
    assert isinstance(exc, sdlc_manager.ApiAuthError)
    assert not isinstance(exc, sdlc_manager.ApiRateLimited)


def test_classifies_429_as_ApiRateLimited() -> None:
    exc = sdlc_manager._classify_gh_error(
        stderr="HTTP 429: Too Many Requests\n",
        returncode=1,
    )
    assert isinstance(exc, sdlc_manager.ApiRateLimited)


# --- _classify_gh_error: 422 disambiguation --------------------------------


def test_classifies_422_with_already_exists_as_ApiAlreadyExists() -> None:
    """Sub-issue API duplicate-link case."""
    exc = sdlc_manager._classify_gh_error(
        stderr="HTTP 422: Validation Failed\n... 'sub_issue_id': sub-issue already exists",
        returncode=1,
    )
    assert isinstance(exc, sdlc_manager.ApiAlreadyExists)
    assert exc.status_code == 422


def test_classifies_422_with_label_already_taken_as_ApiAlreadyExists() -> None:
    """Label create duplicate case (different message text but same intent)."""
    exc = sdlc_manager._classify_gh_error(
        stderr='HTTP 422: Validation Failed\n... "name has already been taken"',
        returncode=1,
    )
    assert isinstance(exc, sdlc_manager.ApiAlreadyExists)


def test_classifies_422_validation_failure_as_generic_GhApiError() -> None:
    """A 422 that's NOT a duplicate-resource case (e.g., bad field value)
    must NOT be classified as ApiAlreadyExists — it's a real validation failure
    the caller needs to handle differently."""
    exc = sdlc_manager._classify_gh_error(
        stderr="HTTP 422: Validation Failed\n... 'color': must be a 6-character hex string",
        returncode=1,
    )
    # Generic GhApiError, not ApiAlreadyExistsError
    assert isinstance(exc, sdlc_manager.GhApiError)
    assert not isinstance(exc, sdlc_manager.ApiAlreadyExistsError)
    assert exc.status_code == 422


# --- Dual-stream classifier (the DA blocker fix) ---------------------------


def test_classifies_real_label_already_exists_via_stdout_json() -> None:
    """Real `gh api --method POST repos/.../labels` for an existing label
    (verified 2026-05-04 against the actual GitHub API):
      stderr: 'gh: Validation Failed (HTTP 422)'
      stdout: '{"message":"Validation Failed","errors":[{"resource":"Label",
              "code":"already_exists","field":"name"}],"status":"422"}'

    Stderr alone has NO duplicate-resource hint. Without inspecting
    stdout, the duplicate-detection in PR #115's original implementation
    silently failed in production. This test pins that the classifier
    inspects stdout's `"code":"already_exists"` JSON marker."""
    real_stderr = "gh: Validation Failed (HTTP 422)\n"
    real_stdout = (
        '{"message":"Validation Failed",'
        '"errors":[{"resource":"Label","code":"already_exists","field":"name"}],'
        '"documentation_url":"https://docs.github.com/rest/issues/labels#create-a-label",'
        '"status":"422"}'
    )
    exc = sdlc_manager._classify_gh_error(
        stderr=real_stderr,
        returncode=1,
        stdout=real_stdout,
    )
    assert isinstance(exc, sdlc_manager.ApiAlreadyExistsError)
    assert exc.status_code == 422
    # The exception should retain BOTH streams for debugging
    assert exc.stderr == real_stderr
    assert exc.stdout == real_stdout


def test_classifies_real_404_via_stderr_summary() -> None:
    """Real `gh api repos/.../nonexistent` (verified 2026-05-04):
      stderr: 'gh: Not Found (HTTP 404)'
      stdout: '{"message":"Not Found","status":"404"}'
    Stderr has the (HTTP 404) marker; stdout has the JSON. Either is
    sufficient for status detection."""
    exc = sdlc_manager._classify_gh_error(
        stderr="gh: Not Found (HTTP 404)\n",
        returncode=1,
        stdout='{"message":"Not Found","status":"404"}',
    )
    assert isinstance(exc, sdlc_manager.ApiNotFoundError)
    assert exc.status_code == 404


def test_classifies_status_from_stdout_when_stderr_lacks_http_marker() -> None:
    """Defensive: if some future `gh` version omits the (HTTP NNN) summary
    from stderr, fall back to parsing the JSON body's `"status":"NNN"`."""
    exc = sdlc_manager._classify_gh_error(
        stderr="gh: Something went wrong\n",  # no HTTP marker
        returncode=1,
        stdout='{"message":"Not Found","status":"404"}',
    )
    assert isinstance(exc, sdlc_manager.ApiNotFoundError)
    assert exc.status_code == 404


def test_class_alias_compatibility() -> None:
    """The old class names (ApiNotFound, ApiAlreadyExists, ApiRateLimited)
    are retained as aliases for the *Error-suffixed PEP 8 names. Code that
    catches the old names continues to work; isinstance checks pass either way."""
    exc = sdlc_manager.ApiNotFoundError("test", status_code=404)
    assert isinstance(exc, sdlc_manager.ApiNotFound)  # alias
    assert isinstance(exc, sdlc_manager.ApiNotFoundError)  # canonical name
    assert sdlc_manager.ApiAlreadyExists is sdlc_manager.ApiAlreadyExistsError
    assert sdlc_manager.ApiRateLimited is sdlc_manager.ApiRateLimitedError


# --- _classify_gh_error: edge cases ----------------------------------------


def test_classifies_unparseable_stderr_as_generic_GhApiError() -> None:
    """No HTTP status in stderr → status_code is None; bare GhApiError raised."""
    exc = sdlc_manager._classify_gh_error(
        stderr="some weird subprocess error",
        returncode=2,
    )
    assert isinstance(exc, sdlc_manager.GhApiError)
    assert exc.status_code is None


def test_empty_stderr_does_not_crash_classifier() -> None:
    exc = sdlc_manager._classify_gh_error(stderr="", returncode=1)
    assert isinstance(exc, sdlc_manager.GhApiError)


# --- Integration: flow_link_sub_issue with typed exceptions ----------------


def test_flow_link_sub_issue_idempotent_via_ApiAlreadyExists() -> None:
    """The Phase C foundation refactor: link-sub-issue catches the typed
    ApiAlreadyExists, not a substring match. This test ensures the typed
    path works when the classifier raises the right type."""
    with (
        patch.object(sdlc_manager, "_rest_get") as mock_get,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_get.side_effect = [
            {"id": 12345},
            {"id": 67890, "title": "parent issue"},
        ]
        # Raise the typed exception directly — what _classify_gh_error
        # would produce on the duplicate-link 422
        mock_post.side_effect = sdlc_manager.ApiAlreadyExists(
            "gh command failed: HTTP 422 ... already exists",
            status_code=422,
            stderr="HTTP 422: Validation Failed ... already exists",
        )

        sdlc_manager.flow_link_sub_issue("campps-context-library", 1, "campps-mvp", 42, fmt="text")

        msgs = [c.args[0] for c in mock_out.call_args_list]
        assert any("Already linked" in m for m in msgs), (
            f"Expected idempotent success message; got: {msgs}"
        )


def test_flow_link_sub_issue_raises_on_non_duplicate_422() -> None:
    """A 422 that's NOT a duplicate (validation failure on the body) must
    NOT be silently treated as 'already exists' — it should propagate so
    the operator sees the real error."""
    with (
        patch.object(sdlc_manager, "_rest_get") as mock_get,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
    ):
        mock_get.side_effect = [
            {"id": 12345},
            {"id": 67890},
        ]
        # Generic GhApiError with 422 status (not ApiAlreadyExists)
        mock_post.side_effect = sdlc_manager.GhApiError(
            "gh command failed: HTTP 422 ... validation failed",
            status_code=422,
        )
        with pytest.raises(sdlc_manager.GhApiError) as exc_info:
            sdlc_manager.flow_link_sub_issue(
                "campps-context-library", 1, "campps-mvp", 42, fmt="text"
            )
        # Confirm it's not the ApiAlreadyExists subclass
        assert not isinstance(exc_info.value, sdlc_manager.ApiAlreadyExists)


# --- Integration: flow_verify_label with typed exceptions ------------------


def test_flow_verify_label_creates_via_ApiNotFound() -> None:
    """Probe raises ApiNotFound (typed 404) → fall through to create."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
        patch.object(sdlc_manager, "_out"),
    ):
        mock_gh.side_effect = sdlc_manager.ApiNotFound(
            "gh command failed: HTTP 404",
            status_code=404,
        )
        sdlc_manager.flow_verify_label(
            "campps-mvp", "high-priority", "D93F0B", "High priority", fmt="text"
        )
        mock_post.assert_called_once()


def test_flow_verify_label_propagates_ApiAuthError() -> None:
    """Probe raises ApiAuthError (typed 401/403) → must NOT silently
    create; the auth failure propagates so the operator sees it."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
    ):
        mock_gh.side_effect = sdlc_manager.ApiAuthError(
            "gh command failed: HTTP 401 Bad credentials",
            status_code=401,
        )
        with pytest.raises(sdlc_manager.ApiAuthError):
            sdlc_manager.flow_verify_label("campps-mvp", "x", None, None, fmt="text")
        mock_post.assert_not_called()


def test_flow_verify_label_handles_race_via_ApiAlreadyExists_on_post() -> None:
    """Race: two operators run verify-label simultaneously, both see 404
    on probe, both POST, second gets 422-already-exists. Our impl must
    treat that as success (idempotency contract), not propagate."""
    with (
        patch.object(sdlc_manager, "_gh") as mock_gh,
        patch.object(sdlc_manager, "_rest_post") as mock_post,
        patch.object(sdlc_manager, "_out") as mock_out,
    ):
        mock_gh.side_effect = sdlc_manager.ApiNotFound("404", status_code=404)
        mock_post.side_effect = sdlc_manager.ApiAlreadyExists(
            "name has already been taken",
            status_code=422,
        )
        # Should NOT raise
        sdlc_manager.flow_verify_label("campps-mvp", "high-priority", "D93F0B", None, fmt="text")
        msgs = [c.args[0] for c in mock_out.call_args_list]
        assert any("just created" in m or "race detected" in m for m in msgs), (
            f"Expected race-detection message; got: {msgs}"
        )
