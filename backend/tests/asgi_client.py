"""Minimal in-process HTTP client for ASGI apps (no network, no httpx needed).

Requests are encoded with `requests` (so files=, data=, json=, params= work the
usual way) and sent straight to the app as ASGI messages.
"""
from __future__ import annotations

import asyncio
import json as jsonlib
from typing import Any
from urllib.parse import unquote, urlsplit

import requests
from requests.structures import CaseInsensitiveDict


class Response:
    def __init__(self, status_code: int, headers: CaseInsensitiveDict, content: bytes):
        self.status_code = status_code
        self.headers = headers
        self.content = content

    @property
    def text(self) -> str:
        return self.content.decode("utf-8", errors="replace")

    def json(self) -> Any:
        return jsonlib.loads(self.content)


class ASGIClient:
    def __init__(self, app: Any, client_ip: str = "127.0.0.1"):
        self.app = app
        self.client_ip = client_ip

    def request(self, method: str, path: str, *, params: Any = None, json: Any = None, data: Any = None,
                files: Any = None, headers: dict[str, str] | None = None) -> Response:
        prepared = requests.Request(method, "http://testserver" + path, params=params, json=json, data=data,
                                    files=files, headers=headers).prepare()
        url = urlsplit(prepared.url)
        body = prepared.body or b""
        if isinstance(body, str):
            body = body.encode("utf-8")
        hdrs = [(k.lower().encode("latin-1"), str(v).encode("latin-1")) for k, v in prepared.headers.items()]
        if not any(k == b"host" for k, _ in hdrs):
            hdrs.append((b"host", b"testserver"))
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1", "method": method.upper(),
            "scheme": "http", "path": unquote(url.path), "raw_path": url.path.encode(), "root_path": "",
            "query_string": url.query.encode(), "headers": hdrs, "client": (self.client_ip, 50000),
            "server": ("testserver", 80), "extensions": {},
        }
        return asyncio.run(self._run(scope, body))

    async def _run(self, scope: dict[str, Any], body: bytes) -> Response:
        sent_body = False
        done = asyncio.Event()
        status = 0
        headers: CaseInsensitiveDict = CaseInsensitiveDict()
        chunks: list[bytes] = []

        async def receive() -> dict[str, Any]:
            nonlocal sent_body
            if not sent_body:
                sent_body = True
                return {"type": "http.request", "body": body, "more_body": False}
            await done.wait()
            return {"type": "http.disconnect"}

        async def send(message: dict[str, Any]) -> None:
            nonlocal status
            if message["type"] == "http.response.start":
                status = message["status"]
                for k, v in message.get("headers", []):
                    key = k.decode("latin-1")
                    headers[key] = (headers[key] + ", " if key in headers else "") + v.decode("latin-1")
            elif message["type"] == "http.response.body":
                chunks.append(message.get("body", b""))
                if not message.get("more_body", False):
                    done.set()

        try:
            await self.app(scope, receive, send)
        except Exception:
            # Starlette re-raises after sending a 500 response; behave like a real server.
            if not status:
                raise
        done.set()
        return Response(status, headers, b"".join(chunks))

    def get(self, path: str, **kw: Any) -> Response:
        return self.request("GET", path, **kw)

    def post(self, path: str, **kw: Any) -> Response:
        return self.request("POST", path, **kw)
