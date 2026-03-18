# backend/ld2450.py
# HLK-LD2450 binary UART frame parser.
#
# Frame structure (30 bytes total):
#   Header  : 4 bytes  — AA FF 03 00
#   Target 1: 8 bytes  — x int16, y int16, speed int16, signal uint16
#   Target 2: 8 bytes  — same format, zeroed if no target
#   Target 3: 8 bytes  — same format, zeroed if no target
#   Footer  : 2 bytes  — 55 CC
#
# Coordinate system (sensor-centric):
#   X: lateral offset in mm. Negative = left, positive = right. Range ±2400 mm.
#   Y: forward distance in mm. Always positive. Range 0–6000 mm.
#   speed: signed cm/s. Negative = approaching, positive = receding.
#   signal: unitless SNR proxy. Higher = stronger return.

import struct
import asyncio
import logging
from dataclasses import dataclass
from typing import Optional

import serial_asyncio

log = logging.getLogger(__name__)

FRAME_HEADER = b"\xaa\xff\x03\x00"
FRAME_FOOTER = b"\x55\xcc"
FRAME_LENGTH = 30   # bytes


@dataclass
class Target:
    """One detected target from a single LD2450 frame."""
    id: int             # 0, 1, or 2
    x_mm: int           # lateral mm (negative = left)
    y_mm: int           # forward mm (always positive)
    speed_cms: int      # cm/s (negative = approaching)
    signal: int         # SNR proxy

    @property
    def active(self) -> bool:
        """A target slot is empty when all fields are zero."""
        return not (self.x_mm == 0 and self.y_mm == 0 and
                    self.speed_cms == 0 and self.signal == 0)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x_mm": self.x_mm,
            "y_mm": self.y_mm,
            "speed_cms": self.speed_cms,
            "signal": self.signal,
        }


@dataclass
class Frame:
    """One complete LD2450 frame — up to three target slots."""
    targets: list[Target]   # always length 3; check target.active

    @property
    def active_targets(self) -> list[Target]:
        return [t for t in self.targets if t.active]


def parse_frame(raw: bytes) -> Optional[Frame]:
    """
    Parse a 30-byte LD2450 frame.
    Returns a Frame on success, None if the frame is malformed.
    """
    if len(raw) != FRAME_LENGTH:
        return None
    if raw[:4] != FRAME_HEADER or raw[-2:] != FRAME_FOOTER:
        return None

    targets = []
    for i in range(3):
        offset = 4 + i * 8
        chunk = raw[offset:offset + 8]
        x, y, speed, signal = struct.unpack("<hhhH", chunk)
        targets.append(Target(id=i, x_mm=x, y_mm=y,
                               speed_cms=speed, signal=signal))

    return Frame(targets=targets)


class LD2450Reader:
    """
    Async serial reader for the LD2450.
    Yields parsed Frame objects via an asyncio.Queue.
    """

    def __init__(self, port: str, baud: int, queue: asyncio.Queue):
        self.port  = port
        self.baud  = baud
        self.queue = queue
        self._buf  = bytearray()

    async def run(self):
        log.info("Opening serial port %s at %d baud", self.port, self.baud)
        try:
            reader, _ = await serial_asyncio.open_serial_connection(
                url=self.port, baudrate=self.baud
            )
        except Exception as exc:
            log.error("Failed to open serial port: %s", exc)
            raise

        log.info("LD2450 serial reader started")
        while True:
            chunk = await reader.read(64)
            if not chunk:
                await asyncio.sleep(0.001)
                continue
            self._buf.extend(chunk)
            self._drain()

    def _drain(self):
        """Extract and queue all complete frames from the internal buffer."""
        while True:
            # Find next header
            idx = self._buf.find(FRAME_HEADER)
            if idx == -1:
                # No header in buffer — discard everything except last 3 bytes
                # (partial header might straddle the next read)
                self._buf = self._buf[-3:]
                return
            if idx > 0:
                # Discard garbage before header
                self._buf = self._buf[idx:]

            # Do we have a full frame?
            if len(self._buf) < FRAME_LENGTH:
                return

            raw = bytes(self._buf[:FRAME_LENGTH])
            frame = parse_frame(raw)
            if frame is not None:
                try:
                    self._queue_nowait(frame)
                except asyncio.QueueFull:
                    log.warning("Frame queue full — dropping frame")
            else:
                # Bad frame — skip one byte and try to resync
                log.debug("Malformed frame, resyncing")
                self._buf = self._buf[1:]
                continue

            self._buf = self._buf[FRAME_LENGTH:]

    def _queue_nowait(self, frame: Frame):
        self.queue.put_nowait(frame)
