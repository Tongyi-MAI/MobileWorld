#!/usr/bin/env python3
"""WebSocket-to-ADB TCP proxy for web-scrcpy.

Proxies raw bytes between a WebSocket client and an ADB daemon over TCP.
Optionally serves static files (for the built web-scrcpy frontend).

Usage:
    # Local testing (frontend served by Vite dev server):
    python ws_adb_proxy.py --adb-port 5555 --port 8000

    # Docker (serve built frontend + proxy):
    python ws_adb_proxy.py --adb-port 5555 --port 7860 --static /app/web-scrcpy
"""
import asyncio
import argparse
import logging
from pathlib import Path

try:
    from aiohttp import web, WSMsgType
except ImportError:
    print("ERROR: aiohttp is required. Install with: pip install aiohttp")
    raise SystemExit(1)

logger = logging.getLogger(__name__)


async def websocket_handler(request):
    ws = web.WebSocketResponse(max_msg_size=0)
    await ws.prepare(request)

    adb_host = request.app["adb_host"]
    adb_port = request.app["adb_port"]

    try:
        reader, writer = await asyncio.open_connection(adb_host, adb_port)
    except (ConnectionRefusedError, OSError) as exc:
        logger.error("ADB connect to %s:%d failed: %s", adb_host, adb_port, exc)
        await ws.close(code=1011, message=b"ADB daemon unreachable")
        return ws

    logger.info("Proxying WebSocket -> ADB %s:%d", adb_host, adb_port)

    async def ws_to_tcp():
        try:
            async for msg in ws:
                if msg.type == WSMsgType.BINARY:
                    writer.write(msg.data)
                    await writer.drain()
                elif msg.type in (WSMsgType.CLOSE, WSMsgType.ERROR):
                    break
        except Exception as exc:
            logger.debug("ws->tcp ended: %s", exc)
        finally:
            writer.close()

    async def tcp_to_ws():
        try:
            while True:
                data = await reader.read(16384)
                if not data:
                    break
                await ws.send_bytes(data)
        except Exception as exc:
            logger.debug("tcp->ws ended: %s", exc)
        finally:
            if not ws.closed:
                await ws.close()

    done, pending = await asyncio.wait(
        [asyncio.create_task(ws_to_tcp()), asyncio.create_task(tcp_to_ws())],
        return_when=asyncio.FIRST_COMPLETED,
    )
    for task in pending:
        task.cancel()

    logger.info("WebSocket client disconnected")
    return ws


def create_app(adb_host, adb_port, static_dir=None):
    app = web.Application()
    app["adb_host"] = adb_host
    app["adb_port"] = adb_port

    app.router.add_get("/adb", websocket_handler)

    if static_dir:
        static_path = Path(static_dir)
        if not static_path.exists():
            logger.warning("Static dir %s does not exist", static_dir)
        else:
            # Serve index.html at root
            async def index_handler(_request):
                return web.FileResponse(static_path / "index.html")

            app.router.add_get("/", index_handler)
            app.router.add_static("/", static_path)
            logger.info("Serving static files from %s", static_dir)

    return app


def main():
    parser = argparse.ArgumentParser(description="WebSocket ADB proxy for web-scrcpy")
    parser.add_argument("--adb-host", default="127.0.0.1", help="ADB daemon host")
    parser.add_argument("--adb-port", type=int, default=5555, help="ADB daemon port")
    parser.add_argument("--port", type=int, default=8000, help="Listen port")
    parser.add_argument("--static", default=None, help="Static files directory")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    app = create_app(args.adb_host, args.adb_port, args.static)
    web.run_app(app, host="0.0.0.0", port=args.port)


if __name__ == "__main__":
    main()
