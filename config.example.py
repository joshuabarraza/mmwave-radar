# backend/config.example.py
# Copy this file to config.py and edit. config.py is gitignored.

SERIAL_PORT            = "/dev/ttyAMA0"
BAUD_RATE              = 256000
MAX_RANGE_MM           = 4000
HOST                   = "0.0.0.0"
PORT                   = 8000
BROADCAST_HZ           = 10
MOTION_THRESHOLD_MM    = 150
MOTION_VARIANCE_MAX_MM = 80
SETTLE_FRAMES          = 5
EMA_ALPHA              = 0.3
CONFIRM_FRAMES         = 3
ENABLE_IMU             = False
IMU_I2C_BUS            = 1
IMU_ADDRESS            = 0x68
LOG_CSV                = False
LOG_DIR                = "data"
