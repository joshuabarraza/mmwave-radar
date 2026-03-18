# backend/config.py
# Central configuration for the mmWave radar system.
# Copy config.example.py to config.py and edit here — config.py is gitignored.

# ── Serial / sensor ──────────────────────────────────────────────────────────
# Pi 4B: use /dev/ttyAMA0 after disabling Bluetooth (see README wiring section)
# Fallback: /dev/ttyS0 (mini-UART, less reliable at high baud)
SERIAL_PORT   = "/dev/ttyAMA0"
BAUD_RATE     = 256000          # LD2450 fixed baud rate — do not change

# ── Radar geometry ────────────────────────────────────────────────────────────
MAX_RANGE_MM  = 4000            # Detection radius used to scale display (mm)
                                # LD2450 max is 6000mm but 4000 is practical

# ── WebSocket server ──────────────────────────────────────────────────────────
HOST          = "0.0.0.0"       # Bind to all interfaces (LAN accessible)
PORT          = 8000
BROADCAST_HZ  = 10              # Target broadcast rate to UI clients

# ── Motion stabiliser — Layer 1: sensor motion detection ─────────────────────
# If the mean displacement of ALL active targets in one frame exceeds this
# threshold AND the variance between targets is low, the frame is flagged as
# sensor motion rather than target motion.
MOTION_THRESHOLD_MM    = 150    # mm — coherent jump needed to flag (lower = more sensitive)
MOTION_VARIANCE_MAX_MM = 80     # mm — max spread between targets to still call it coherent

# ── Motion stabiliser — Layer 2: frame gating ────────────────────────────────
# Frames flagged as sensor motion are dropped. The system also gates for a
# short window after motion stops to let the sensor restabilise.
SETTLE_FRAMES = 5               # frames to suppress after motion flag clears

# ── Motion stabiliser — Layer 3: per-target EMA filter ───────────────────────
EMA_ALPHA      = 0.3            # Smoothing factor: 0 = frozen, 1 = raw sensor
                                # 0.3 gives good lag/noise tradeoff at 10 Hz
CONFIRM_FRAMES = 3              # A new target must appear for this many consecutive
                                # frames before its blip is shown on the radar

# ── IMU compensation — Layer 4 (optional) ────────────────────────────────────
ENABLE_IMU           = False    # Set True to enable MPU-6050 compensation
IMU_I2C_BUS          = 1       # Pi 4B I2C bus (GPIO2/3 = bus 1)
IMU_ADDRESS          = 0x68    # Default MPU-6050 I2C address (AD0 low)
                                # Change to 0x69 if AD0 pin is pulled high

# ── Data logging ──────────────────────────────────────────────────────────────
LOG_CSV       = False           # Enable CSV logging to data/ directory
LOG_DIR       = "data"          # Relative to project root
