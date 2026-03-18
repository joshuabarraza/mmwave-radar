# backend/stabiliser.py
# Motion stabilisation pipeline for the LD2450 radar.
#
# The LD2450 has no concept of its own motion — it reports target positions
# relative to itself. When the sensor moves, all targets appear to shift
# coherently, producing ghost tracks and jumping blips. This module runs four
# layers of cleanup:
#
#   Layer 1 — Sensor motion detection
#     Compares target displacement between frames. If all active targets shift
#     by a large, coherent vector in the same direction, the frame is flagged
#     as sensor motion (not target motion).
#
#   Layer 2 — Frame gating
#     Drops flagged frames and holds a short settle window after motion stops,
#     giving the sensor time to restabilise before resuming output.
#
#   Layer 3 — Per-target EMA filter
#     Exponential moving average smooths per-target position jitter. A new
#     target must appear for CONFIRM_FRAMES consecutive frames before its blip
#     is surfaced to the UI.
#
#   Layer 4 — IMU compensation (see imu.py)
#     Runs upstream of this module; subtracts platform motion from raw frames
#     before they arrive here.

import math
import time
import logging
from dataclasses import dataclass, field
from typing import Optional

from ld2450 import Frame, Target
import config

log = logging.getLogger(__name__)


@dataclass
class TrackedTarget:
    """Smoothed, confirmed state for one logical target track."""
    id: int
    x_mm: float
    y_mm: float
    speed_cms: float
    signal: int
    confirm_count: int = 0      # frames seen consecutively
    confirmed: bool = False     # True once confirm_count >= CONFIRM_FRAMES
    last_seen: float = field(default_factory=time.monotonic)

    def update(self, raw: Target):
        α = config.EMA_ALPHA
        self.x_mm     = α * raw.x_mm     + (1 - α) * self.x_mm
        self.y_mm     = α * raw.y_mm     + (1 - α) * self.y_mm
        self.speed_cms = α * raw.speed_cms + (1 - α) * self.speed_cms
        self.signal   = raw.signal
        self.confirm_count += 1
        if self.confirm_count >= config.CONFIRM_FRAMES:
            self.confirmed = True
        self.last_seen = time.monotonic()

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "x_mm": round(self.x_mm),
            "y_mm": round(self.y_mm),
            "speed_cms": round(self.speed_cms, 1),
            "signal": self.signal,
        }


class Stabiliser:
    """
    Runs the four-layer stabilisation pipeline on each incoming Frame.
    Call process(frame) and receive either a list of stable TrackedTargets
    or None if the frame was gated.
    """

    def __init__(self):
        self._tracks: dict[int, TrackedTarget] = {}   # id → TrackedTarget
        self._prev_positions: dict[int, tuple[int, int]] = {}  # id → (x, y)
        self._settle_remaining = 0                    # frames left in gate
        self._motion_flag = False

    # ── Public API ────────────────────────────────────────────────────────────

    def process(self, frame: Frame) -> Optional[list[TrackedTarget]]:
        """
        Process one raw Frame through the stabilisation pipeline.
        Returns the current list of confirmed TrackedTargets, or None if
        the frame was gated (during detected sensor motion or settle window).
        """
        active = frame.active_targets

        # Layer 1: detect sensor motion
        self._motion_flag = self._detect_motion(active)

        # Layer 2: frame gating
        if self._motion_flag:
            self._settle_remaining = config.SETTLE_FRAMES
            log.debug("Sensor motion detected — gating frame")
            self._update_prev(active)
            return None

        if self._settle_remaining > 0:
            self._settle_remaining -= 1
            log.debug("Settle window — gating frame (%d remaining)",
                      self._settle_remaining)
            self._update_prev(active)
            return None

        # Layer 3: EMA update + track confirmation
        self._update_tracks(active)
        self._update_prev(active)

        confirmed = [t for t in self._tracks.values() if t.confirmed]
        return confirmed

    @property
    def is_stable(self) -> bool:
        return not self._motion_flag and self._settle_remaining == 0

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _detect_motion(self, active: list[Target]) -> bool:
        """
        Layer 1: sensor motion detection.

        Strategy: compute the displacement of each target between this frame
        and the previous frame. If all targets shift by a large, coherent
        vector (low variance, high mean magnitude), the sensor moved.

        Edge cases:
          - No previous positions yet (first frame) → not motion
          - Only one active target → can't distinguish target motion from
            sensor motion; use a higher threshold as a heuristic
          - Targets appear/disappear between frames → only compare targets
            present in both frames
        """
        if not self._prev_positions or not active:
            return False

        deltas = []
        for t in active:
            if t.id in self._prev_positions:
                px, py = self._prev_positions[t.id]
                dx = t.x_mm - px
                dy = t.y_mm - py
                deltas.append((dx, dy))

        if not deltas:
            return False

        # Mean displacement vector
        mean_dx = sum(d[0] for d in deltas) / len(deltas)
        mean_dy = sum(d[1] for d in deltas) / len(deltas)
        mean_mag = math.hypot(mean_dx, mean_dy)

        if mean_mag < config.MOTION_THRESHOLD_MM:
            return False

        # Variance — how much do the deltas spread around the mean?
        if len(deltas) == 1:
            # Single target: use a tighter threshold since we have no variance
            return mean_mag > config.MOTION_THRESHOLD_MM * 1.5

        variance = sum(
            math.hypot(d[0] - mean_dx, d[1] - mean_dy) for d in deltas
        ) / len(deltas)

        if variance > config.MOTION_VARIANCE_MAX_MM:
            # High variance → targets moved independently → not sensor motion
            return False

        log.debug(
            "Motion: mean_mag=%.0f mm, variance=%.0f mm, targets=%d",
            mean_mag, variance, len(deltas)
        )
        return True

    def _update_prev(self, active: list[Target]):
        self._prev_positions = {t.id: (t.x_mm, t.y_mm) for t in active}

    def _update_tracks(self, active: list[Target]):
        """Layer 3: EMA filter and track confirmation."""
        seen_ids = set()

        for t in active:
            seen_ids.add(t.id)
            if t.id in self._tracks:
                self._tracks[t.id].update(t)
            else:
                # New track — initialise at raw position, not yet confirmed
                self._tracks[t.id] = TrackedTarget(
                    id=t.id,
                    x_mm=float(t.x_mm),
                    y_mm=float(t.y_mm),
                    speed_cms=float(t.speed_cms),
                    signal=t.signal,
                    confirm_count=1,
                )

        # Reset confirmation counter for tracks not seen this frame
        for tid in list(self._tracks):
            if tid not in seen_ids:
                track = self._tracks[tid]
                track.confirm_count = 0
                track.confirmed = False
                # Remove track if unseen for > 1 second
                if time.monotonic() - track.last_seen > 1.0:
                    del self._tracks[tid]
