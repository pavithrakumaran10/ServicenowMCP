"""Tests for guardrails and client retry logic.

Run: pip install -e ".[dev]" && pytest
"""
import pytest
import responses

from servicenow_mcp import ServiceNowClient, ServiceNowError
from servicenow_mcp.client import ServiceNowClient, ServiceNowError
from servicenow_mcp.guardrails import (
    GuardrailError,
    assert_writable,
    dry_run_echo,
)

BASE = "https://dev123.service-now.com"


# ---- guardrails ----
def test_allowlist_permits_incident():
    assert_writable("incident")  # no raise


def test_blocklist_rejects_sys_user():
    with pytest.raises(GuardrailError):
        assert_writable("sys_user")


def test_unknown_table_rejected():
    with pytest.raises(GuardrailError):
        assert_writable("u_random_table")


def test_dry_run_echo_mentions_action():
    msg = dry_run_echo("INSERT", "incident", {"short_description": "x"})
    assert "DRY RUN" in msg and "incident" in msg


# ---- client ----
@responses.activate
def test_query_returns_result_list():
    responses.add(
        responses.GET,
        f"{BASE}/api/now/table/incident",
        json={"result": [{"number": "INC001"}]},
        status=200,
    )
    c = ServiceNowClient(BASE, user="admin", password="pw")
    rows = c.query("incident", limit=1)
    assert rows[0]["number"] == "INC001"


@responses.activate
def test_error_raises_servicenow_error():
    responses.add(
        responses.GET,
        f"{BASE}/api/now/table/incident",
        json={"error": {"message": "ACL failure"}},
        status=403,
    )
    c = ServiceNowClient(BASE, user="admin", password="pw", max_retries=1)
    with pytest.raises(ServiceNowError) as exc:
        c.query("incident")
    assert exc.value.status == 403
