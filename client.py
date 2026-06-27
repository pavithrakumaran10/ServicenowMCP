"""ServiceNow REST client.

Thin wrapper over the Table API with:
- OAuth2 (client_credentials / password) OR Basic auth fallback
- automatic retry with backoff on 429 / 5xx
- structured exceptions instead of raw dict access that crashes on errors
"""
from __future__ import annotations

import logging
import time
from typing import Any

import requests

logger = logging.getLogger("servicenow_mcp.client")


class ServiceNowError(Exception):
    """Raised when ServiceNow returns a non-success status."""

    def __init__(self, status: int, message: str, detail: str = "") -> None:
        self.status = status
        self.detail = detail
        super().__init__(f"[{status}] {message}{f' :: {detail}' if detail else ''}")


class ServiceNowClient:
    def __init__(
        self,
        instance_url: str,
        *,
        user: str | None = None,
        password: str | None = None,
        client_id: str | None = None,
        client_secret: str | None = None,
        timeout: int = 30,
        max_retries: int = 3,
    ) -> None:
        self.base = instance_url.rstrip("/")
        self.timeout = timeout
        self.max_retries = max_retries
        self._session = requests.Session()
        self._token: str | None = None
        self._user = user
        self._password = password
        self._client_id = client_id
        self._client_secret = client_secret
        self._use_oauth = bool(client_id and client_secret and user and password)

    # ---- auth ---------------------------------------------------------
    def _ensure_oauth_token(self) -> None:
        if self._token:
            return
        resp = self._session.post(
            f"{self.base}/oauth_token.do",
            data={
                "grant_type": "password",
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "username": self._user,
                "password": self._password,
            },
            timeout=self.timeout,
        )
        if resp.status_code != 200:
            raise ServiceNowError(resp.status_code, "OAuth token request failed", resp.text[:300])
        self._token = resp.json()["access_token"]
        logger.info("Obtained OAuth access token")

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "Content-Type": "application/json"}
        if self._use_oauth:
            self._ensure_oauth_token()
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _auth(self):
        return None if self._use_oauth else (self._user, self._password)

    # ---- core request with retry -------------------------------------
    def _request(self, method: str, path: str, **kwargs: Any) -> dict:
        url = f"{self.base}{path}"
        last_exc: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                resp = self._session.request(
                    method,
                    url,
                    headers=self._headers(),
                    auth=self._auth(),
                    timeout=self.timeout,
                    **kwargs,
                )
            except requests.RequestException as exc:
                last_exc = exc
                logger.warning("Network error (attempt %s): %s", attempt, exc)
                time.sleep(2 ** attempt)
                continue

            if resp.status_code == 401 and self._use_oauth:
                self._token = None  # force re-auth once
                continue
            if resp.status_code in (429, 500, 502, 503, 504):
                wait = int(resp.headers.get("Retry-After", 2 ** attempt))
                logger.warning("Throttled/5xx %s, retrying in %ss", resp.status_code, wait)
                time.sleep(wait)
                continue
            if not resp.ok:
                detail = ""
                try:
                    detail = resp.json().get("error", {}).get("message", "")
                except Exception:
                    detail = resp.text[:300]
                raise ServiceNowError(resp.status_code, f"{method} {path} failed", detail)
            return resp.json() if resp.content else {}

        raise ServiceNowError(0, f"{method} {path} exhausted retries", str(last_exc))

    # ---- table api convenience ---------------------------------------
    def query(self, table: str, *, query: str = "", limit: int = 10, fields: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"sysparm_limit": limit}
        if query:
            params["sysparm_query"] = query
        if fields:
            params["sysparm_fields"] = fields
        params["sysparm_display_value"] = "true"
        return self._request("GET", f"/api/now/table/{table}", params=params).get("result", [])

    def get(self, table: str, sys_id: str) -> dict:
        return self._request("GET", f"/api/now/table/{table}/{sys_id}").get("result", {})

    def insert(self, table: str, payload: dict) -> dict:
        return self._request("POST", f"/api/now/table/{table}", json=payload).get("result", {})

    def update(self, table: str, sys_id: str, payload: dict) -> dict:
        return self._request("PATCH", f"/api/now/table/{table}/{sys_id}", json=payload).get("result", {})
