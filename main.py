# backend/main.py
# Entry point for the mmWave radar system.
#
# Starts three concurrent asyncio tasks:
#   1. LD2450Reader  — reads serial, queues raw frames
#   2. pipeline_task — pulls frames, runs stabilisation, queues JSON
#   3. FastAPI/uvicorn — serves the UI and WebSocket endpoint
#
# Usage:
#   python3 main.py
#   python3 main.py --port /dev/ttyAMA0
#   python3 main.py --log          # enable CSV logging

import asyncio
import argparse
import json
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

import config
from ld2450 import LD2450Reader, Frame
from stabiliser import Stabiliser

# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger("main")

# ── Shared state ──────────────────────────────────────────────────────────────

raw_queue:    asyncio.Queue  # Frame objects from LD2450Reader
output_queue: asyncio.Queue  # JSON strings ready to broadcast
clients: set[WebSocket] = set()

# ── Pipeline task ─────────────────────────────────────────────────────────────

async def pipeline_task(csv_writer=None):
    """
    Pulls raw frames from raw_queue, runs the stabilisation pipeline,
    and pushes broadcast-ready JSON onto output_queue at BROADCAST_HZ.
    """
    stabiliser = Stabiliser()
    interval   = 1.0 / config.BROADCAST_HZ
    last_broadcast = 0.0

    while True:
        try:
            frame: Frame = await asyncio.wait_for(raw_queue.get(), timeout=0.1)
        except asyncio.TimeoutError:
            continue

        tracks = stabiliser.process(frame)

        now = time.monotonic()
        if now - last_broadcast < interval:
            continue
        last_broadcast = now

        # Build broadcast payload
        if tracks is None:
            # Frame was gated — broadcast a "stabilising" status so the UI
            # can show a visual indicator (e.g. dim the sweep line)
            payload = {
                "ts": int(time.time() * 1000),
                "stable": False,
                "targets": [],
            }
        else:
            payload = {
                "ts": int(time.time() * 1000),
                "stable": True,
                "targets": [t.to_dict() for t in tracks],
            }

        msg = json.dumps(payload)
        await output_queue.put(msg)

        if csv_writer and tracks:
            ts_ms = payload["ts"]
            for t in tracks:
                csv_writer.writerow([
                    ts_ms, t.id, round(t.x_mm), round(t.y_mm),
                    round(t.speed_cms, 1), t.signal
                ])


# ── Broadcast task ────────────────────────────────────────────────────────────

async def broadcast_task():
    """Pulls JSON messages from output_queue and fans out to all WS clients."""
    while True:
        msg = await output_queue.get()
        if not clients:
            continue
        dead = set()
        for ws in clients:
            try:
                await ws.send_text(msg)
            except Exception:
                dead.add(ws)
        clients.difference_update(dead)


# ── FastAPI app ───────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start background tasks when the server starts."""
    global raw_queue, output_queue

    raw_queue    = asyncio.Queue(maxsize=50)
    output_queue = asyncio.Queue(maxsize=20)

    csv_writer = None
    csv_file   = None
    if config.LOG_CSV:
        import csv
        Path(config.LOG_DIR).mkdir(exist_ok=True)
        fname = Path(config.LOG_DIR) / f"session_{int(time.time())}.csv"
        csv_file   = open(fname, "w", newline="")
        csv_writer = csv.writer(csv_file)
        csv_writer.writerow(["ts_ms", "target_id", "x_mm", "y_mm",
                              "speed_cms", "signal"])
        log.info("Logging to %s", fname)

    reader = LD2450Reader(
        port=config.SERIAL_PORT,
        baud=config.BAUD_RATE,
        queue=raw_queue,
    )

    tasks = [
        asyncio.create_task(reader.run(),          name="serial-reader"),
        asyncio.create_task(pipeline_task(csv_writer), name="pipeline"),
        asyncio.create_task(broadcast_task(),       name="broadcast"),
    ]

    log.info("Radar backend started — ws://0.0.0.0:%d/ws", config.PORT)
    log.info("UI available at http://0.0.0.0:%d", config.PORT)

    yield   # server runs here

    for t in tasks:
        t.cancel()
    if csv_file:
        csv_file.close()


app = FastAPI(lifespan=lifespan)

UI_DIR = Path(__file__).parent.parent / "ui"

# Serve static UI files
if UI_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(UI_DIR)), name="static")


@app.get("/")
async def serve_ui():
    index = UI_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return {"status": "ok", "message": "UI directory not found — place ui/ next to backend/"}


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "clients": len(clients),
        "serial_port": config.SERIAL_PORT,
    }


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    log.info("Client connected — %d total", len(clients))
    try:
        while True:
            # Keep connection alive; client sends nothing meaningful
            await ws.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        clients.discard(ws)
        log.info("Client disconnected — %d total", len(clients))


# ── CLI entrypoint ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="mmWave radar backend")
    parser.add_argument("--port", default=config.SERIAL_PORT,
                        help="Serial port (default: %(default)s)")
    parser.add_argument("--log", action="store_true",
                        help="Enable CSV data logging")
    parser.add_argument("--debug", action="store_true",
                        help="Verbose debug logging")
    args = parser.parse_args()

    if args.port:
        config.SERIAL_PORT = args.port
    if args.log:
        config.LOG_CSV = True
    if args.debug:
        logging.getLogger().setLevel(logging.DEBUG)

    uvicorn.run(
        app,
        host=config.HOST,
        port=config.PORT,
        log_level="warning",    # uvicorn is chatty; our logger handles info
        access_log=False,
    )


if __name__ == "__main__":
    main()
