"""
Central configuration for the Rubik's Cube Solver.
Edit values here to tune hardware, vision, and motion parameters.
"""

# ---------------------------------------------------------------------------
# Serial / Servo bus
# ---------------------------------------------------------------------------
SERIAL_PORT = "/dev/ttyUSB0"       # CP210x on Waveshare board (Serial Forwarding)
SERIAL_BAUD = 1_000_000            # SC09 default bus baud rate
SERIAL_TIMEOUT = 0.05              # seconds – read timeout per packet

SERVO_IDS = list(range(1, 7))      # IDs 1–6
SERVO_RETRY = 2                    # retries on failed packet

# ---------------------------------------------------------------------------
# SC09 register addresses  (SCS-series / Feetech-compatible)
# ---------------------------------------------------------------------------
class Reg:
    # EEPROM (persistent – write only when servo is unlocked)
    ID              = 5
    BAUD_RATE       = 6
    MIN_ANGLE_L     = 9      # 2 bytes
    MAX_ANGLE_L     = 11     # 2 bytes
    MODE            = 33     # 0=position, 1=speed(motor)

    # SRAM (volatile – normal runtime writes)
    TORQUE_ENABLE   = 40     # 0=off, 1=on
    ACCELERATION    = 41
    GOAL_POSITION_L = 42     # 2 bytes
    RUNNING_TIME_L  = 44     # 2 bytes
    RUNNING_SPEED_L = 46     # 2 bytes
    LOCK            = 48     # 1=lock EEPROM writes

    PRESENT_POSITION_L  = 56  # 2 bytes  (read-only)
    PRESENT_SPEED_L     = 58  # 2 bytes
    PRESENT_LOAD_L      = 60  # 2 bytes
    PRESENT_VOLTAGE     = 62  # 1 byte
    PRESENT_TEMPERATURE = 63  # 1 byte
    MOVING              = 66  # 1 byte
    PRESENT_CURRENT_L   = 69  # 2 bytes

# ---------------------------------------------------------------------------
# Position-mode tuning (units 0-1023 ≈ 0-300°)
# ---------------------------------------------------------------------------
POS_HOME         = 512          # center
POS_QUARTER_CW   = 307         # ~ 90° in position units
POS_QUARTER_CCW  = -307
POS_HALF         = 614         # ~ 180°
MOVE_SPEED       = 400         # default speed for position moves (units/s)
MOVE_SETTLE_MS   = 300         # extra settle time after move (ms)

# ---------------------------------------------------------------------------
# Face → servo ID mapping
# ---------------------------------------------------------------------------
FACE_SERVO = {
    "U": 1,
    "R": 2,
    "F": 3,
    "D": 4,
    "L": 5,
    "B": 6,
}

# ---------------------------------------------------------------------------
# Vision / cameras
# ---------------------------------------------------------------------------
CAMERA_INDICES = [0, 1]         # /dev/video0, /dev/video1
CAMERA_WIDTH   = 640
CAMERA_HEIGHT  = 480

# ROI grid per camera: list of (face_label, row, col, x, y, w, h)
# These are placeholder rectangles – calibrate for your rig.
ROI_CAM0 = []   # will be auto-generated if empty  (see vision/roi.py)
ROI_CAM1 = []

# Faces visible to each camera (for auto-ROI generation)
CAM0_FACES = ["U", "F", "R"]
CAM1_FACES = ["D", "B", "L"]

ROI_SIZE = 30    # width=height of each ROI square (pixels)

# HSV colour thresholds  {color_name: (H_low, S_low, V_low, H_high, S_high, V_high)}
COLOR_RANGES = {
    "W": (0,   0,   160, 180, 60,  255),   # white
    "Y": (20,  100, 100, 35,  255, 255),   # yellow
    "R": (0,   120, 70,  10,  255, 255),   # red (wraps – handle in code)
    "O": (10,  120, 70,  20,  255, 255),   # orange
    "B": (100, 120, 70,  130, 255, 255),   # blue
    "G": (35,  80,  50,  85,  255, 255),   # green
}

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
