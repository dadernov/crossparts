"""Small signed-cookie session middleware without an extra deployment dependency."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
from http.cookies import SimpleCookie


class SignedSessionMiddleware:
    def __init__(self, app, secret_key: str, cookie_name: str = "crossparts_session"):
        self.app, self.secret, self.cookie_name = app, secret_key.encode(), cookie_name

    def _decode(self, value: str | None) -> dict:
        if not value or "." not in value:
            return {}
        raw, signature = value.rsplit(".", 1)
        expected = hmac.new(self.secret, raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, signature):
            return {}
        try:
            return json.loads(base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)))
        except (ValueError, json.JSONDecodeError):
            return {}

    def _encode(self, session: dict) -> str:
        raw = base64.urlsafe_b64encode(json.dumps(session, separators=(",", ":")).encode()).decode().rstrip("=")
        return raw + "." + hmac.new(self.secret, raw.encode(), hashlib.sha256).hexdigest()

    async def __call__(self, scope, receive, send):
        if scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return
        cookies = SimpleCookie()
        cookies.load(dict(scope.get("headers", [])).get(b"cookie", b"").decode())
        original = self._decode(cookies.get(self.cookie_name).value if self.cookie_name in cookies else None)
        scope["session"] = original.copy()

        async def send_with_session(message):
            if message["type"] == "http.response.start" and scope["session"] != original:
                headers = list(message.get("headers", []))
                if scope["session"]:
                    cookie = f"{self.cookie_name}={self._encode(scope['session'])}; Path=/; HttpOnly; SameSite=Lax"
                else:
                    cookie = f"{self.cookie_name}=; Path=/; Max-Age=0; HttpOnly; SameSite=Lax"
                headers.append((b"set-cookie", cookie.encode()))
                message = {**message, "headers": headers}
            await send(message)
        await self.app(scope, receive, send_with_session)
