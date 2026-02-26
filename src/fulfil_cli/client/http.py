"""JSON-RPC 2.0 HTTP client for the Fulfil v3 API."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import httpx
from rich.console import Console

from fulfil_cli import __version__
from fulfil_cli.client.errors import (
    AuthError,
    NetworkError,
    ServerError,
    error_from_jsonrpc,
)

_debug_console = Console(stderr=True)


class FulfilClient:
    """JSON-RPC 2.0 client for the Fulfil v3 API."""

    def __init__(
        self,
        workspace: str,
        api_key: str | None = None,
        *,
        access_token: str | None = None,
        token_refresher: Callable[[], str] | None = None,
        base_url: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.workspace = workspace
        self._token_refresher = token_refresher
        if base_url:
            self.url = f"{base_url.rstrip('/')}/api/v3/jsonrpc"
        else:
            self.url = f"https://{workspace}/api/v3/jsonrpc"
        self._request_id = 0

        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "User-Agent": f"fulfil-cli/{__version__}",
        }
        if access_token:
            headers["Authorization"] = f"Bearer {access_token}"
        elif api_key:
            headers["X-API-KEY"] = api_key

        self._client = httpx.Client(headers=headers, timeout=timeout)

    def call(self, method: str, *args: Any, **params: Any) -> Any:
        """Make a single JSON-RPC call. Returns the result or raises.

        Positional args are sent as a JSON array; keyword args as a JSON object.
        If both are provided, positional args take precedence (per JSON-RPC 2.0).
        """
        self._request_id += 1
        payload = {
            "jsonrpc": "2.0",
            "method": method,
            "params": list(args) if args else params,
            "id": self._request_id,
        }
        return self._send(payload)

    def batch(self, calls: list[tuple[str, dict[str, Any]]]) -> list[Any]:
        """Send a batch of JSON-RPC requests. Returns results in order."""
        payloads = []
        for method, params in calls:
            self._request_id += 1
            payloads.append(
                {
                    "jsonrpc": "2.0",
                    "method": method,
                    "params": params,
                    "id": self._request_id,
                }
            )
        return self._send(payloads)

    def _send(self, payload: dict | list) -> Any:
        from fulfil_cli.cli.state import is_debug

        debug = is_debug()
        if debug:
            method = payload.get("method", "?") if isinstance(payload, dict) else "batch"
            _debug_console.print(f"[dim]DEBUG → POST {self.url} method={method}[/dim]")

        try:
            response = self._client.post(self.url, json=payload)
        except httpx.ConnectError as exc:
            raise NetworkError(
                message=f"Cannot connect to {self.url}",
                hint=f"Check that workspace '{self.workspace}' is correct.",
            ) from exc
        except httpx.TimeoutException as exc:
            raise NetworkError(message="Request timed out") from exc
        except httpx.HTTPError as exc:
            raise NetworkError(message=str(exc)) from exc

        if debug:
            _debug_console.print(
                f"[dim]DEBUG ← {response.status_code} "
                f"{response.headers.get('content-type', '')}[/dim]"
            )

        if response.status_code == 401:
            if self._token_refresher and not getattr(self, "_retrying", False):
                new_token = self._token_refresher()
                self._client.headers["Authorization"] = f"Bearer {new_token}"
                self._retrying = True
                try:
                    return self._send(payload)
                finally:
                    self._retrying = False
            raise AuthError(
                message="Invalid or expired credentials",
                hint="Run 'fulfil auth login' to re-authenticate.",
            )
        if response.status_code == 403:
            raise AuthError(message="Access forbidden")
        if response.status_code == 404:
            raise ServerError(
                message=f"API endpoint not found ({self.url})",
                hint=f"Check that workspace '{self.workspace}' is correct.",
            )
        if response.status_code >= 500:
            # Try to extract detail from the response body
            detail = ""
            try:
                body = response.json()
                if isinstance(body, dict):
                    detail = body.get("message", "") or body.get("error", "")
                    if isinstance(detail, dict):
                        detail = detail.get("message", "")
            except Exception:
                pass
            message = f"Server error ({response.status_code})"
            if detail:
                message = f"{message}: {detail}"
            raise ServerError(message=message)

        content_type = response.headers.get("content-type", "")
        if "json" not in content_type:
            raise ServerError(
                message=f"Unexpected response (HTTP {response.status_code}, {content_type})",
                hint=f"Check that workspace '{self.workspace}' is correct.",
            )

        try:
            result = response.json()
        except Exception as exc:
            raise ServerError(message="Invalid JSON response from server") from exc

        # Handle batch responses
        if isinstance(result, list):
            results = []
            for item in result:
                if "error" in item:
                    raise error_from_jsonrpc(item["error"])
                results.append(item.get("result"))
            return results

        # Handle single response
        if "error" in result:
            raise error_from_jsonrpc(result["error"])
        return result.get("result")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> FulfilClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
