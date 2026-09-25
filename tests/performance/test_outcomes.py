import pytest

from src.experiments.outcomes import OUTCOMES, SERVER_OUTCOMES, classify, native_outcome
from src.experiments.sanitize import sanitize_document


@pytest.mark.parametrize(
    "native,expected",
    [
        ("completed_normally", "Completed normally"),
        ("completed_after_retry", "Completed after retry"),
        ("api_timeout", "API timeout"),
        ("database_command_timeout", "Database command timeout"),
        ("database_connection_timeout", "Database transient error"),
        ("database_transient_error", "Database transient error"),
        ("database_nontransient_error", "Database nontransient error"),
        ("connection_pool_timeout", "Connection-pool timeout"),
        ("api_load_shed", "API load-shed response"),
        ("circuit_breaker_rejection", "Circuit-breaker rejection"),
        ("deadlock_victim", "Deadlock victim"),
        ("cancelled_request", "Cancelled request"),
        ("unknown", "Unknown and requiring investigation"),
        ("invalid_request", "Unknown and requiring investigation"),
        ("not_found", "Unknown and requiring investigation"),
        ("business_failure", "Unknown and requiring investigation"),
    ],
)
def test_exact_native_mapping_and_safe_publication_preserve_subtype(native, expected):
    assert classify(200, native, 3) == expected
    assert native_outcome(native) == native
    public = sanitize_document(
        "error-summary.json",
        {
            "outcome": expected,
            "native_outcome": native,
        },
    )
    assert public["native_outcome"] == native


@pytest.mark.parametrize("status", [None, 200, 204, 302, 400, 429, 500, 503, 504])
def test_http_status_and_retry_metadata_never_invent_missing_final_outcome(status):
    assert classify(status, None, 0) == OUTCOMES[-1]
    assert classify(status, None, 3) == OUTCOMES[-1]
    assert classify(status, "unrecognized", 3) == OUTCOMES[-1]


@pytest.mark.parametrize("header", ["client_timeout", "Client-side timeout", "Completed normally"])
def test_client_timeout_cannot_be_forged_by_any_server_header(header):
    assert classify(504, header, 0) == OUTCOMES[-1]
    assert native_outcome(header) is None
    assert classify(504, header, 0, client_timeout=True) == "Client-side timeout"


def test_unrecognized_outcome_text_is_not_retained_in_private_or_public_records():
    assert native_outcome("sensitive arbitrary server message") is None
    assert native_outcome(None) is None
    assert "Client-side timeout" not in SERVER_OUTCOMES.values()
