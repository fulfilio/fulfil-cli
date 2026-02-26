"""OAuth 2.0 authentication with PKCE (RFC 8252) for native apps."""

from __future__ import annotations

import hashlib
import secrets
import threading
import time
import webbrowser
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

import httpx
import orjson

OAUTH_CLIENT_ID = "fulfil-cli"
OAUTH_SCOPES = "openid profile email offline_access"
CALLBACK_TIMEOUT = 120  # seconds


@dataclass
class OAuthTokens:
    """OAuth token set with expiry tracking."""

    access_token: str
    refresh_token: str | None
    expires_at: float  # Unix timestamp

    @property
    def is_expired(self) -> bool:
        """Check if the access token is expired (with 30s buffer)."""
        return time.time() >= (self.expires_at - 30)

    def to_json(self) -> bytes:
        return orjson.dumps(
            {
                "access_token": self.access_token,
                "refresh_token": self.refresh_token,
                "expires_at": self.expires_at,
            }
        )

    @classmethod
    def from_json(cls, data: bytes | str) -> OAuthTokens:
        parsed = orjson.loads(data)
        return cls(
            access_token=parsed["access_token"],
            refresh_token=parsed.get("refresh_token"),
            expires_at=parsed["expires_at"],
        )

    @classmethod
    def from_token_response(cls, data: dict) -> OAuthTokens:
        return cls(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_at=time.time() + data.get("expires_in", 3600),
        )


def discover_oidc(workspace: str) -> dict:
    """Fetch OpenID Connect discovery document for the workspace."""
    url = f"https://{workspace}/.well-known/openid-configuration"
    response = httpx.get(url, timeout=10)
    response.raise_for_status()
    return response.json()


def register_client(registration_endpoint: str, redirect_uri: str) -> None:
    """Register the CLI as a native app client via RFC 7591 dynamic registration.

    For the reserved client_id "fulfil-cli", the server treats this as a public
    native app: no secret, loopback redirects only, deduplicates if already registered.
    Safe to call on every login.
    """
    response = httpx.post(
        registration_endpoint,
        json={
            "client_id": OAUTH_CLIENT_ID,
            "client_name": OAUTH_CLIENT_ID,
            "redirect_uris": [redirect_uri],
        },
        timeout=10,
    )
    response.raise_for_status()


def generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256).

    Returns (code_verifier, code_challenge).
    """
    code_verifier = secrets.token_urlsafe(32)
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    # Base64url encode without padding
    import base64

    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


def build_authorization_url(
    authorization_endpoint: str,
    redirect_uri: str,
    state: str,
    code_challenge: str,
) -> str:
    """Build the authorization URL with PKCE parameters."""
    params = {
        "response_type": "code",
        "client_id": OAUTH_CLIENT_ID,
        "redirect_uri": redirect_uri,
        "scope": OAUTH_SCOPES,
        "state": state,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    return f"{authorization_endpoint}?{urlencode(params)}"


def exchange_code(
    token_endpoint: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> OAuthTokens:
    """Exchange authorization code for tokens."""
    response = httpx.post(
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "client_id": OAUTH_CLIENT_ID,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        },
        timeout=10,
    )
    response.raise_for_status()
    return OAuthTokens.from_token_response(response.json())


def refresh_access_token(
    token_endpoint: str,
    refresh_token: str,
) -> OAuthTokens:
    """Use a refresh token to get new tokens."""
    response = httpx.post(
        token_endpoint,
        data={
            "grant_type": "refresh_token",
            "client_id": OAUTH_CLIENT_ID,
            "refresh_token": refresh_token,
        },
        timeout=10,
    )
    response.raise_for_status()
    return OAuthTokens.from_token_response(response.json())


def _build_callback_html(*, error: str | None = None) -> str:
    """Build a branded callback page (self-contained, no external deps)."""
    if error:
        icon_class = "icon-error"
        icon_svg = (
            '<svg viewBox="0 0 24 24" fill="none" stroke="#DC2626"'
            ' stroke-width="2.5" stroke-linecap="round"'
            ' stroke-linejoin="round">'
            '<line x1="18" y1="6" x2="6" y2="18"/>'
            '<line x1="6" y1="6" x2="18" y2="18"/></svg>'
        )
        title = "Authentication Failed - Fulfil CLI"
        heading = "Authentication failed"
        message = f"Something went wrong: {error}"
        hint = "Please return to the terminal and try again."
    else:
        icon_class = "icon-success"
        icon_svg = (
            '<svg viewBox="0 0 24 24" fill="none" stroke="#059669"'
            ' stroke-width="2.5" stroke-linecap="round"'
            ' stroke-linejoin="round">'
            '<polyline points="20 6 9 17 4 12"/></svg>'
        )
        title = "Authenticated - Fulfil CLI"
        heading = "Authentication successful"
        message = "You have been logged in to Fulfil CLI."
        hint = "You can close this window and return to the terminal."

    # Fulfil logo SVG paths (inline to avoid external deps)
    p1 = (
        "M5.44 63.75H5.38V71.64H13.83C18.46 71.64 22.23"
        " 68.12 22.23 63.8V55.96H13.83C9.23 55.96 5.47"
        " 59.46 5.44 63.75Z"
    )
    p2 = (
        "M5.38 41.26C5.38 46.15 9.63 50.07 14.82"
        " 50.07H22.18V55.97H29.63C34.77 55.97 38.97"
        " 52.05 38.97 47.25V32.45H14.82C9.63 32.45"
        " 5.38 36.37 5.38 41.26Z"
    )
    p3 = (
        "M14.82 8.93C9.63 8.93 5.38 12.89 5.38"
        " 17.78C5.38 22.67 9.58 26.59 14.82"
        " 26.59H38.97V32.45H46.43C51.57 32.45 55.77"
        " 28.53 55.77 23.73V8.93H14.82Z"
    )

    return f"""\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>
<style>
*,*::before,*::after{{margin:0;padding:0;box-sizing:border-box}}
body{{
  font-family:Inter,system-ui,-apple-system,sans-serif;
  background:#F5F3F0;color:#374151;min-height:100vh;
  display:flex;align-items:center;justify-content:center;
  -webkit-font-smoothing:antialiased
}}
.card{{
  background:rgba(255,255,255,.80);
  backdrop-filter:blur(20px) saturate(180%);
  -webkit-backdrop-filter:blur(20px) saturate(180%);
  border:1px solid rgba(229,231,235,.6);
  border-radius:24px;
  box-shadow:0 10px 15px -3px rgba(0,0,0,.06),
             0 4px 6px -4px rgba(0,0,0,.04);
  max-width:440px;width:100%;margin:24px;
  padding:48px 40px;text-align:center
}}
.logo{{margin-bottom:32px}}
.icon{{
  width:56px;height:56px;border-radius:16px;
  display:inline-flex;align-items:center;
  justify-content:center;margin-bottom:24px
}}
.icon-success{{
  background:linear-gradient(to bottom right,#d1fae5,#a7f3d0)
}}
.icon-error{{
  background:linear-gradient(to bottom right,#fee2e2,#fecaca)
}}
.icon svg{{width:28px;height:28px}}
h1{{
  font-size:24px;font-weight:600;color:#1F2937;
  letter-spacing:-0.02em;line-height:1.3;margin-bottom:12px
}}
p{{font-size:16px;line-height:1.625;color:#6B7280}}
.hint{{
  margin-top:32px;padding-top:24px;
  border-top:1px solid #E5E7EB;
  font-size:14px;color:#9CA3AF
}}
</style>
</head>
<body>
<div class="card">
  <div class="logo">
    <svg width="120" height="40" viewBox="0 0 165 78"
         fill="none" xmlns="http://www.w3.org/2000/svg"
         role="img" aria-label="Fulfil">
      <g transform="translate(0,18) scale(.5)" clip-path="url(#lc)">
        <path opacity=".5" d="{p1}" fill="#171717"/>
        <path opacity=".8" d="{p2}" fill="#171717"/>
        <path d="{p3}" fill="#171717"/>
      </g>
      <text x="36" y="54"
            font-family="Inter,system-ui,sans-serif"
            font-size="44" font-weight="600"
            letter-spacing="-.02em"
            fill="#171717">Fulfil</text>
      <defs>
        <clipPath id="lc">
          <rect width="50.39" height="64.78" fill="white"
                transform="translate(5.38 7.91)"/>
        </clipPath>
      </defs>
    </svg>
  </div>
  <div class="icon {icon_class}">{icon_svg}</div>
  <h1>{heading}</h1>
  <p>{message}</p>
  <p class="hint">{hint}</p>
</div>
</body>
</html>"""


class _CallbackHandler(BaseHTTPRequestHandler):
    """HTTP handler that captures the OAuth callback."""

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        self.server.callback_code = params.get("code", [None])[0]  # type: ignore[attr-defined]
        self.server.callback_state = params.get("state", [None])[0]  # type: ignore[attr-defined]
        self.server.callback_error = params.get("error", [None])[0]  # type: ignore[attr-defined]

        error = self.server.callback_error  # type: ignore[attr-defined]
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        self.wfile.write(_build_callback_html(error=error).encode("utf-8"))

    def log_message(self, format: str, *args: object) -> None:
        """Suppress default HTTP logging."""


class CallbackServer:
    """Local HTTP server to receive OAuth callbacks on loopback interface."""

    def __init__(self) -> None:
        self._server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
        self._server.callback_code = None  # type: ignore[attr-defined]
        self._server.callback_state = None  # type: ignore[attr-defined]
        self._server.callback_error = None  # type: ignore[attr-defined]
        self._thread: threading.Thread | None = None

    @property
    def port(self) -> int:
        return self._server.server_address[1]

    @property
    def redirect_uri(self) -> str:
        return f"http://127.0.0.1:{self.port}/callback"

    def start(self) -> None:
        """Start the server in a background thread."""
        self._thread = threading.Thread(target=self._server.handle_request, daemon=True)
        self._thread.start()

    def wait(self, timeout: float = CALLBACK_TIMEOUT) -> tuple[str | None, str | None, str | None]:
        """Wait for the callback. Returns (code, state, error)."""
        if self._thread:
            self._thread.join(timeout=timeout)
        return (
            self._server.callback_code,  # type: ignore[attr-defined]
            self._server.callback_state,  # type: ignore[attr-defined]
            self._server.callback_error,  # type: ignore[attr-defined]
        )

    def shutdown(self) -> None:
        self._server.server_close()


def run_oauth_flow(workspace: str) -> OAuthTokens:
    """Run the full OAuth authorization code + PKCE flow.

    Opens the browser, waits for callback, exchanges code for tokens.
    Raises RuntimeError on failure.
    """
    # 1. Discover OIDC endpoints
    oidc_config = discover_oidc(workspace)
    authorization_endpoint = oidc_config["authorization_endpoint"]
    token_endpoint = oidc_config["token_endpoint"]
    registration_endpoint = oidc_config.get("registration_endpoint")

    # 2. Generate PKCE and state
    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(16)

    # 3. Start local callback server
    server = CallbackServer()
    server.start()

    try:
        # 4. Register client with the server (registers loopback redirect URI)
        if registration_endpoint:
            register_client(registration_endpoint, server.redirect_uri)

        # 5. Build authorization URL and open browser
        auth_url = build_authorization_url(
            authorization_endpoint=authorization_endpoint,
            redirect_uri=server.redirect_uri,
            state=state,
            code_challenge=code_challenge,
        )
        webbrowser.open(auth_url)

        # 6. Wait for callback
        code, callback_state, error = server.wait()
    finally:
        server.shutdown()

    if error:
        raise RuntimeError(f"OAuth error: {error}")

    if not code:
        raise RuntimeError("Did not receive authorization code. The login may have timed out.")

    if callback_state != state:
        raise RuntimeError("OAuth state mismatch — possible CSRF attack.")

    # 7. Exchange code for tokens
    return exchange_code(
        token_endpoint=token_endpoint,
        code=code,
        code_verifier=code_verifier,
        redirect_uri=server.redirect_uri,
    )
