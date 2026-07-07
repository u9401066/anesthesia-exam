#!/usr/bin/env python3
"""Small user-space reverse proxy for Streamlit + OpenClaw Gateway.

This keeps the public site on one externally-forwarded port:

- /            -> Streamlit
- /openclaw/   -> OpenClaw Gateway Control UI/WebChat

It intentionally lives in the repo because this host currently has no nginx or
caddy available without sudo.
"""

from __future__ import annotations

import asyncio
import os
from contextlib import suppress

from aiohttp import ClientSession, ClientTimeout, WSMsgType, web

HOP_BY_HOP_HEADERS = {
    "connection",
    "keep-alive",
    "proxy-authenticate",
    "proxy-authorization",
    "te",
    "trailer",
    "transfer-encoding",
    "upgrade",
}
WEBSOCKET_HANDSHAKE_HEADERS = {
    "host",
    "sec-websocket-accept",
    "sec-websocket-extensions",
    "sec-websocket-key",
    "sec-websocket-protocol",
    "sec-websocket-version",
}


def _env(name: str, default: str) -> str:
    return str(os.getenv(name) or default).strip()


STREAMLIT_BASE = _env("OPENCLAW_PROXY_STREAMLIT", "http://127.0.0.1:8502").rstrip("/")
GATEWAY_BASE = _env("OPENCLAW_PROXY_GATEWAY", "http://127.0.0.1:18789").rstrip("/")
PUBLIC_BIND = _env("OPENCLAW_PROXY_BIND", "0.0.0.0")
PUBLIC_PORT = int(_env("OPENCLAW_PROXY_PORT", "8501"))


def _filtered_headers(headers) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in HOP_BY_HOP_HEADERS
    }


def _websocket_protocols(request: web.Request) -> list[str]:
    protocols: list[str] = []
    for header in request.headers.getall("Sec-WebSocket-Protocol", []):
        for protocol in header.split(","):
            value = protocol.strip()
            if value:
                protocols.append(value)
    return protocols


def _target_for(request: web.Request) -> str:
    raw_path_qs = request.rel_url.raw_path_qs
    if request.path == "/openclaw":
        raw_path_qs = "/openclaw/"
    if request.path == "/openclaw" or request.path.startswith("/openclaw/"):
        return f"{GATEWAY_BASE}{raw_path_qs}"
    return f"{STREAMLIT_BASE}{raw_path_qs}"


def _is_openclaw_request(request: web.Request) -> bool:
    return request.path == "/openclaw" or request.path.startswith("/openclaw/")


def _with_forwarded_headers(request: web.Request) -> dict[str, str]:
    headers = _filtered_headers(request.headers)
    peer = request.transport.get_extra_info("peername") if request.transport else None
    if peer:
        headers["X-Forwarded-For"] = str(peer[0])
    headers["X-Forwarded-Host"] = request.headers.get("Host", "")
    headers["X-Forwarded-Proto"] = request.scheme
    return headers


async def _proxy_websocket(request: web.Request, session: ClientSession) -> web.WebSocketResponse:
    protocols = _websocket_protocols(request)
    client_ws = web.WebSocketResponse(protocols=protocols)
    await client_ws.prepare(request)

    stripped_headers = set(WEBSOCKET_HANDSHAKE_HEADERS)
    if not _is_openclaw_request(request):
        stripped_headers.add("origin")
    headers = {
        key: value
        for key, value in _with_forwarded_headers(request).items()
        if key.lower() not in stripped_headers
    }
    target = _target_for(request)

    async with session.ws_connect(target, headers=headers, protocols=protocols, heartbeat=30) as upstream_ws:
        async def client_to_upstream() -> None:
            async for msg in client_ws:
                if msg.type == WSMsgType.TEXT:
                    await upstream_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await upstream_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.PING:
                    await upstream_ws.ping()
                elif msg.type == WSMsgType.PONG:
                    await upstream_ws.pong()
                elif msg.type == WSMsgType.CLOSE:
                    await upstream_ws.close()

        async def upstream_to_client() -> None:
            async for msg in upstream_ws:
                if msg.type == WSMsgType.TEXT:
                    await client_ws.send_str(msg.data)
                elif msg.type == WSMsgType.BINARY:
                    await client_ws.send_bytes(msg.data)
                elif msg.type == WSMsgType.PING:
                    await client_ws.ping()
                elif msg.type == WSMsgType.PONG:
                    await client_ws.pong()
                elif msg.type == WSMsgType.CLOSE:
                    await client_ws.close()

        tasks = [
            asyncio.create_task(client_to_upstream()),
            asyncio.create_task(upstream_to_client()),
        ]
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            task.result()
        with suppress(Exception):
            await upstream_ws.close()
        with suppress(Exception):
            await client_ws.close()

    return client_ws


async def _proxy_http(request: web.Request, session: ClientSession) -> web.StreamResponse:
    if request.path == "/openclaw":
        raise web.HTTPPermanentRedirect("/openclaw/")

    target = _target_for(request)
    body = await request.read()
    headers = _with_forwarded_headers(request)

    async with session.request(
        request.method,
        target,
        data=body,
        headers=headers,
        allow_redirects=False,
    ) as upstream:
        response = web.StreamResponse(
            status=upstream.status,
            reason=upstream.reason,
            headers=_filtered_headers(upstream.headers),
        )
        await response.prepare(request)
        async for chunk in upstream.content.iter_chunked(65536):
            await response.write(chunk)
        await response.write_eof()
        return response


async def _handle(request: web.Request) -> web.StreamResponse:
    session: ClientSession = request.app["client_session"]
    if request.headers.get("Upgrade", "").lower() == "websocket":
        return await _proxy_websocket(request, session)
    return await _proxy_http(request, session)


async def _startup(app: web.Application) -> None:
    app["client_session"] = ClientSession(timeout=ClientTimeout(total=None))


async def _cleanup(app: web.Application) -> None:
    await app["client_session"].close()


def main() -> None:
    app = web.Application(client_max_size=1024**3)
    app.on_startup.append(_startup)
    app.on_cleanup.append(_cleanup)
    app.router.add_route("*", "/{path_info:.*}", _handle)
    web.run_app(app, host=PUBLIC_BIND, port=PUBLIC_PORT)


if __name__ == "__main__":
    main()
