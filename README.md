# 📡 mmWave Radar Display

A CoD-style movement radar built with an HLK-LD2450 mmWave sensor and a Raspberry Pi 4B. Tracks up to 3 targets in real time with X/Y position and velocity, rendered as a sweeping blip display in any browser on your local network.

![Status](https://img.shields.io/badge/status-in%20development-yellow)
![Platform](https://img.shields.io/badge/platform-Raspberry%20Pi%204B-red)
![Sensor](https://img.shields.io/badge/sensor-HLK--LD2450-teal)
![Language](https://img.shields.io/badge/language-Python%203-blue)

---

## How It Works

```
LD2450 ──UART──► Pi 4B ──WebSocket──► Browser
 (raw radar)     (parse, filter,       (canvas
                  stabilise, serve)     renderer)
```

1. The LD2450 outputs binary UART frames at 256000 baud — X/Y position, speed, and signal for up to 3 targets at ~10 Hz.
2. A Python `asyncio` service decodes frames, runs motion stabilisation (sensor-motion detection → frame gating → EMA smoothing), and broadcasts JSON over a WebSocket.
3. A browser page served by the Pi connects to the WebSocket and renders a sweep animation with fading blip trails on an HTML canvas.

---

## Signal Processing Pipeline

Raw LD2450 data is noisy and completely unaware of sensor motion. Four processing stages clean it up:

```
Raw frames
    │
    ▼
[1] Sensor motion detection   — all targets shifted coherently? flag the frame
    │
    ▼
[2] Frame gating              — drop flagged frames + N-frame settle window
    │                           hold last-known-good positions during blackout
    ▼
[3] Per-target EMA filter     — exponential moving average smooths jitter
    │                           minimum N-frame confirm before blip appears
    ▼
[4] IMU compensation          — subtract platform rotation/acceleration (optional)
    │                           requires MPU-6050 on I2C
    ▼
Stable target stream → WebSocket → renderer
```

Layers 1–3 are active by default and handle the vast majority of motion artifacts with zero extra hardware. Layer 4 is opt-in and only needed if the sensor is mounted on something that moves during use.

---

## Parts List

Optimised for Pi 4B. Target: **~$30–40 USD** minus the Pi.

| # | Part | Notes | Est. Price |
|---|---|---|---|
| 1 | **HLK-LD2450** | Main radar sensor | ~$8–12 |
| 2 | Raspberry Pi 4B | Already have one | $75 |
| 3 | microSD card (16 GB+) | -- | ~$5–8 |
| 4 | 5V 3A USB-C power supply | Pi 4B needs 3A; cheap supplies cause instability | ~$8–10 |
| 5 | Female-to-female jumper wires | GPIO UART wiring | ~$1–2 |
| *(opt)* | **MPU-6050** IMU breakout | Layer 4 motion compensation; I2C, ~$2 on AliExpress | ~$2–4 |
| *(opt)* | HDMI display | Fullscreen local kiosk mode | -- |
| *(opt)* | Enclosure / 3D print | Mount sensor + Pi together | ~$3–8 |

---

## Wiring

### LD2450 → Pi 4B GPIO

```
LD2450          Pi 4B GPIO (BCM)
------          ----------------
  VCC  ──────►  Pin 2   (5V)
  GND  ──────►  Pin 6   (GND)
   TX  ──────►  Pin 10  (GPIO15 / RXD0)
   RX  ──────►  Pin 8   (GPIO14 / TXD0)
```

> LD2450 logic is 3.3V — directly compatible with Pi GPIO. No level shifter needed.

### MPU-6050 → Pi 4B (optional, Layer 4)

```
MPU-6050        Pi 4B GPIO
--------        ----------
  VCC  ──────►  Pin 1   (3.3V)
  GND  ──────►  Pin 9   (GND)
  SDA  ──────►  Pin 3   (GPIO2 / SDA1)
  SCL  ──────►  Pin 5   (GPIO3 / SCL1)
```

### Enable hardware UART on the Pi 4B

On Pi 4B, `/dev/ttyAMA0` is claimed by Bluetooth by default. Two options:

**Option A — Disable Bluetooth (What this project does):**
```bash
# Add to /boot/firmware/config.txt (Pi OS Bookworm) or /boot/config.txt (Bullseye):
dtoverlay=disable-bt
sudo systemctl disable hciuart
sudo reboot
# UART now available at /dev/ttyAMA0
```

**Option B — Use the mini-UART (less stable, no config change needed):**
```bash
# Use /dev/ttyS0 instead of /dev/ttyAMA0
# Mini-UART is tied to the CPU clock and can lose bytes at high baud — not ideal at 256000
```

**Then in `raspi-config`:**
```bash
sudo raspi-config
# Interface Options → Serial Port
# Login shell over serial? → No
# Serial port hardware enabled? → Yes
sudo reboot
```

Verify: `ls -l /dev/ttyAMA0` — should exist and be owned by `dialout` group.

Add your user to the dialout group if not already:
```bash
sudo usermod -a -G dialout $USER
# Log out and back in for this to take effect
```

---

## Repo Structure

```
mmwave-radar/
├── backend/
│   ├── main.py              # asyncio entry point
│   ├── ld2450.py            # UART frame parser
│   ├── radar.py             # Coordinate transform + target tracking
│   ├── stabiliser.py        # Motion detection, frame gating, EMA filter
│   ├── imu.py               # Optional MPU-6050 Layer 4 compensation
│   ├── logger.py            # CSV data logger
│   ├── playback.py          # Replay recorded sessions
│   └── requirements.txt
├── ui/
│   ├── index.html           # Browser radar UI (served by Pi)
│   ├── radar.js             # Canvas renderer + WebSocket client
│   └── style.css
├── systemd/
│   └── radar.service        # Autostart on boot
├── docs/
│   ├── wiring.md
│   └── ld2450-protocol.md
├── data/                    # git-ignored — CSV logs land here
├── .gitignore
└── README.md
```

---

## Getting Started

### 1. OS setup

Flash **Raspberry Pi OS Lite (64-bit, Bookworm)** using Raspberry Pi Imager. In the Imager's advanced settings, enable SSH and configure your WiFi before writing.

```bash
ssh pi@radar.local   # or use the IP from your router

sudo apt update && sudo apt upgrade -y
sudo apt install python3-pip python3-venv git -y
```

### 2. Clone and install

```bash
git clone https://github.com/YOUR_USERNAME/mmwave-radar.git
cd mmwave-radar

python3 -m venv venv
source venv/bin/activate
pip install -r backend/requirements.txt
```

### 3. Configure

```bash
cp backend/config.example.py backend/config.py
# Edit config.py — set SERIAL_PORT, MAX_RANGE_MM, ENABLE_IMU, etc.
```

### 4. Run

```bash
python3 backend/main.py
```

Open `http://radar.local:8000` in any browser on your network. The UI is served directly by the Pi.

### 5. Autostart on boot (optional)

```bash
sudo cp systemd/radar.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable radar
sudo systemctl start radar
```

---

## Configuration Reference

All tuneable parameters live in `backend/config.py`:

| Parameter | Default | Description |
|---|---|---|
| `SERIAL_PORT` | `/dev/ttyAMA0` | LD2450 serial device |
| `BAUD_RATE` | `256000` | Do not change |
| `MAX_RANGE_MM` | `4000` | Radar display radius in mm |
| `BROADCAST_HZ` | `10` | WebSocket update rate |
| `MOTION_THRESHOLD_MM` | `150` | Min coherent jump to flag sensor motion |
| `SETTLE_FRAMES` | `5` | Frames to gate after motion clears |
| `EMA_ALPHA` | `0.3` | EMA smoothing (0=frozen, 1=raw) |
| `CONFIRM_FRAMES` | `3` | Frames before a new blip appears |
| `ENABLE_IMU` | `False` | Enable MPU-6050 Layer 4 compensation |
| `LOG_CSV` | `False` | Log target data to data/ |

---

## Data Logging and Playback

```bash
# Log a session
python3 backend/main.py --log

# Replay without sensor connected
python3 backend/playback.py --file data/session_20250601_143022.csv
```

CSV format: `timestamp_ms, target_id, x_mm, y_mm, speed_cms, signal`

---

## LD2450 Protocol

Binary frames at 256000 baud, 8N1.

| Field | Bytes | Value |
|---|---|---|
| Header | 4 | `AA FF 03 00` |
| Target 1–3 | 8 each | X int16 (mm), Y int16 (mm), speed int16 (cm/s), signal uint16 |
| Footer | 2 | `55 CC` |

X: ±2400 mm lateral (negative = left). Y: 0–6000 mm forward (always positive). FOV: ±60°.

See `docs/ld2450-protocol.md` for full frame spec.

---

## Roadmap

- [x] LD2450 UART frame parser
- [x] asyncio serial → WebSocket pipeline
- [x] Sensor motion detection + frame gating
- [x] Per-target EMA filter + confirmation threshold
- [x] Canvas radar renderer with sweep animation
- [ ] Blip trail alpha fade
- [ ] Zone masking (ignore regions)
- [ ] CSV logger + playback mode
- [ ] IMU Layer 4 compensation (MPU-6050)
- [ ] systemd autostart unit
- [ ] Kiosk mode (Chromium fullscreen on boot)
- [ ] 3D printable enclosure

---

## References

- [HLK-LD2450 product page](https://www.hlktech.net/)
- [ESPHome LD2450 component](https://esphome.io/components/sensor/ld2450.html) — good protocol reference
- [FastAPI WebSockets](https://fastapi.tiangolo.com/advanced/websockets/)
- [Pi 4B GPIO pinout](https://pinout.xyz/)

---

## License

MIT
