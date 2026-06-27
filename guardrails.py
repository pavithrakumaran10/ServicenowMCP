"""Guardrails for write actions.

This module is the part interviewers care about: it shows agentic tool design
with safety rails rather than handing an LLM unrestricted write access.
"""
from __future__ import annotations

import logging

from .client import ServiceNowClient, ServiceNowError

logger = logging.getLogger("servicenow_mcp.guardrails")

# Only dev artifacts may be written. Security/identity tables are never writable
# through this server, even if a tool is asked to touch them.
WRITABLE_TABLES: frozenset[str] = frozenset(
    {
        "incident",
        "sys_script_include",
        "sys_script",          # business rules
        "sys_ui_action",
        "sc_req_item",
        "task",
    }
)

BLOCKED_TABLES: frozenset[str] = frozenset(
    {
        "sys_user",
        "sys_user_group",
        "sys_security_acl",
        "sys_user_role",
        "sys_properties",
    }
)


class GuardrailError(Exception):
    pass


def assert_writable(table: str) -> None:
    if table in BLOCKED_TABLES:
        raise GuardrailError(f"Table '{table}' is explicitly blocked from writes.")
    if table not in WRITABLE_TABLES:
        raise GuardrailError(
            f"Table '{table}' is not on the writable allowlist. "
            f"Allowed: {', '.join(sorted(WRITABLE_TABLES))}"
        )


def ensure_update_set(client: ServiceNowClient, name: str) -> str:
    """Find-or-create an in-progress Update Set and return its sys_id.

    Every write the server performs should land in a named, reviewable Update Set,
    never in Default.
    """
    existing = client.query(
        "sys_update_set",
        query=f"name={name}^state=in progress",
        limit=1,
        fields="sys_id,name",
    )
    if existing:
        return existing[0]["sys_id"]
    created = client.insert("sys_update_set", {"name": name, "state": "in progress"})
    logger.info("Created update set %s (%s)", name, created.get("sys_id"))
    return created.get("sys_id", "")


def dry_run_echo(action: str, table: str, payload: dict) -> str:
    """Return a human-readable description of what *would* happen."""
    fields = ", ".join(f"{k}={v}" for k, v in payload.items())
    return f"[DRY RUN] Would {action} on '{table}' with: {fields}"
