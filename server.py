"""ServiceNow Developer Actions MCP server.

Connects an MCP client (e.g. Claude Desktop) to a ServiceNow instance, exposing
read tools (incidents, CMDB, schema) and guarded write tools (create incident,
create script include) that run inside a scoped Update Set with dry-run support.

Run:  python -m servicenow_mcp.server
"""
from __future__ import annotations

import logging
import os

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .client import ServiceNowClient, ServiceNowError
from .guardrails import (
    GuardrailError,
    assert_writable,
    dry_run_echo,
    ensure_update_set,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("servicenow_mcp")

mcp = FastMCP("ServiceNow Developer Actions")

UPDATE_SET_NAME = os.getenv("SN_UPDATE_SET", "MCP Automated Changes")


def _client() -> ServiceNowClient:
    url = os.environ["SN_URL"]
    return ServiceNowClient(
        url,
        user=os.getenv("SN_USER"),
        password=os.getenv("SN_PASS"),
        client_id=os.getenv("SN_CLIENT_ID"),
        client_secret=os.getenv("SN_CLIENT_SECRET"),
    )


# ---- READ TOOLS -------------------------------------------------------
@mcp.tool()
def get_incidents(
    limit: int = Field(5, description="Max records to return", ge=1, le=50),
    only_active: bool = Field(True, description="Restrict to active incidents"),
) -> str:
    """Fetch incidents from ServiceNow, newest first."""
    try:
        q = "active=true^ORDERBYDESCsys_created_on" if only_active else "ORDERBYDESCsys_created_on"
        rows = _client().query("incident", query=q, limit=limit,
                               fields="number,short_description,priority,state")
        if not rows:
            return "No incidents found."
        return "\n".join(
            f"{r['number']} [{r.get('priority','?')}] {r['short_description']} ({r.get('state','')})"
            for r in rows
        )
    except ServiceNowError as e:
        return f"ServiceNow error: {e}"


@mcp.tool()
def query_table(
    table: str = Field(..., description="Table name, e.g. 'cmdb_ci_server'"),
    encoded_query: str = Field("", description="Encoded query string"),
    limit: int = Field(10, ge=1, le=50),
) -> str:
    """Run a read-only query against any table (GlideRecord-style)."""
    try:
        rows = _client().query(table, query=encoded_query, limit=limit)
        if not rows:
            return f"No records in '{table}' for that query."
        keys = list(rows[0].keys())[:5]
        out = [" | ".join(keys)]
        for r in rows:
            out.append(" | ".join(str(r.get(k, "")) for k in keys))
        return "\n".join(out)
    except ServiceNowError as e:
        return f"ServiceNow error: {e}"


@mcp.tool()
def describe_table(
    table: str = Field(..., description="Table to inspect, e.g. 'incident'"),
) -> str:
    """Inspect a table's fields via sys_dictionary before writing code against it."""
    try:
        rows = _client().query(
            "sys_dictionary",
            query=f"name={table}^element!=NULL",
            limit=50,
            fields="element,internal_type,column_label",
        )
        if not rows:
            return f"No dictionary entries for '{table}'."
        return "\n".join(
            f"{r['element']} ({r.get('internal_type','')}) - {r.get('column_label','')}"
            for r in rows
        )
    except ServiceNowError as e:
        return f"ServiceNow error: {e}"


@mcp.tool()
def get_cmdb_cis(
    ci_class: str = Field("cmdb_ci_server", description="CMDB CI class table"),
    limit: int = Field(10, ge=1, le=50),
) -> str:
    """List configuration items from a given CMDB class."""
    try:
        rows = _client().query(ci_class, query="ORDERBYname", limit=limit,
                               fields="name,sys_class_name,operational_status")
        if not rows:
            return f"No CIs found in '{ci_class}'."
        return "\n".join(
            f"{r['name']} [{r.get('sys_class_name','')}] status={r.get('operational_status','')}"
            for r in rows
        )
    except ServiceNowError as e:
        return f"ServiceNow error: {e}"


# ---- GUARDED WRITE TOOLS ---------------------------------------------
@mcp.tool()
def create_incident(
    short_description: str = Field(..., description="Incident summary"),
    urgency: str = Field("3", description="1=High, 2=Medium, 3=Low"),
    dry_run: bool = Field(False, description="Preview without writing"),
) -> str:
    """Create an incident inside the scoped Update Set. Honors dry_run."""
    table, payload = "incident", {"short_description": short_description, "urgency": urgency}
    try:
        assert_writable(table)
        if dry_run:
            return dry_run_echo("INSERT", table, payload)
        client = _client()
        ensure_update_set(client, UPDATE_SET_NAME)
        rec = client.insert(table, payload)
        return f"Created {rec.get('number')} (sys_id={rec.get('sys_id')})"
    except (GuardrailError, ServiceNowError) as e:
        return f"Blocked: {e}"


@mcp.tool()
def create_script_include(
    name: str = Field(..., description="Script Include name"),
    script: str = Field(..., description="ES5 script body"),
    description: str = Field("", description="Optional description"),
    dry_run: bool = Field(True, description="Defaults to preview for safety"),
) -> str:
    """Create a Script Include. Defaults to dry_run=True given the write risk."""
    table = "sys_script_include"
    payload = {"name": name, "script": script, "description": description,
               "api_name": name, "access": "package_private"}
    try:
        assert_writable(table)
        if dry_run:
            return dry_run_echo("INSERT", table, {"name": name, "lines": script.count(chr(10)) + 1})
        client = _client()
        ensure_update_set(client, UPDATE_SET_NAME)
        rec = client.insert(table, payload)
        return f"Created Script Include '{name}' (sys_id={rec.get('sys_id')})"
    except (GuardrailError, ServiceNowError) as e:
        return f"Blocked: {e}"


def main() -> None:
    mcp.run()


if __name__ == "__main__":
    main()
