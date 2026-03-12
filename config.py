"""
Central configuration for the Rubik's Cube Solver.
Edit values here to tune hardware, vision, and motion parameters.
"""

# ---------------------------------------------------------------------------
# Serial / Servo bus
# ---------------------------------------------------------------------------
SERIAL_PORT = "auto"                 # "auto" = detect CP2102 at startup; or e.g. "/dev/ttyUSB0"
SERIAL_BAUD = 115200            # SC09 default bus baud rate
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
# Position-mode tuning (units 0-1023)
#
# SC09 datasheet claims 300°/1024 but these servos empirically produce
# ~0.586°/step (~600° over the full 0-1023 range).
#
# Robot home is at position 358 (~210° physical from 0).
# This gives room for −90°, +90°, and +180° with wide margins:
#
#   home − 90°  = 204   (margin: 204 counts from 0)
#   home + 90°  = 512
#   home +180°  = 665   (margin: 358 counts from 1023)
#
# After going full CCW (−90°), three consecutive CW 90° turns fit:
#   204 → 358 → 512 → 666  (all within 0-1023)
# ---------------------------------------------------------------------------
POS_HOME         = 358          # robot home / neutral
POS_QUARTER_CW   = 154          # +90°  empirical
POS_QUARTER_CCW  = -154         # −90°
POS_HALF         = 307          # +180° empirical (2 × 154 ≈ 307)
MOVE_SPEED       = 1500         # default speed for position moves (units/s)
MOVE_SETTLE_MS   = 300          # extra settle time after move (ms)

STEPS_PER_DEGREE = 154.0 / 90.0  # ≈ 1.71 (empirically measured)
 
# ---------------------------------------------------------------------------
# Face → servo ID mapping
#
# Physical rule:  servo 1 = bottom,  servo 6 = top,
#                 servos 2-3-4-5 go clockwise when viewed from below.
# ---------------------------------------------------------------------------
FACE_SERVO = {
    "U": 6,   # top
    "D": 1,   # bottom
    "F": 2,   # front
    "R": 3,   # right
    "B": 4,   # back
    "L": 5,   # left
}

# Reverse lookup: servo ID → face letter
SERVO_FACE = {v: k for k, v in FACE_SERVO.items()}

# ---------------------------------------------------------------------------
# Cube insertion rule
# ---------------------------------------------------------------------------
# The cube must always be inserted with the SAME two center references:
#   • the same colour on U (servo 6 / top)
#   • the same adjacent colour on F (servo 2 / front)
# This fully fixes orientation for all 6 faces.

# ---------------------------------------------------------------------------
# Vision / cameras
# ---------------------------------------------------------------------------
CAMERA_INDICES = "auto"         # "auto" = detect USB cameras; or e.g. [0, 2]
CAMERA_WIDTH   = 640
CAMERA_HEIGHT  = 480

# ROI grid per camera: list of (face_label, cam_row, cam_col, x, y, w, h)
# These are placeholder rectangles – calibrate for your rig.
ROI_CAM0 = []   # will be auto-generated if empty  (see vision/roi.py)
ROI_CAM1 = []

# Faces visible to each camera (for auto-ROI generation)
# Cam0 (top camera): U top-centre, L bottom-left, F bottom-right
# Cam1 (bottom camera): R top-left, B top-right, D bottom-centre
CAM0_FACES = ["U", "L", "F"]
CAM1_FACES = ["R", "B", "D"]

ROI_SIZE = 30  # pixel size of each ROI square

# ---------------------------------------------------------------------------
# Per-face orientation transform  (camera grid → Kociemba 3×3 order)
#
# Each camera sees faces at a certain rotation relative to the standard
# Kociemba reading order (top-left → top-right, row by row).
# The value is the clockwise rotation IN DEGREES to apply to the camera's
# 3×3 grid so that it aligns with Kociemba facelet order.
#
# Allowed values: 0, 90, 180, 270  (mirror only if absolutely necessary).
# Calibrate these once and leave them fixed.
# ---------------------------------------------------------------------------
FACE_ORIENTATION = {
    "U":   0,
    "R":   0,
    "F":   0,
    "D":   0,
    "L":   0,
    "B":   0,
}

# ---------------------------------------------------------------------------
# HSV colour classification ranges  {colour: (H_lo, S_lo, V_lo, H_hi, S_hi, V_hi)}
# Tuned for standard Rubik's cube under indoor lighting.  Adjust as needed.
# ---------------------------------------------------------------------------
COLOR_RANGES = {
    "W": (0,   0, 160, 180,  60, 255),   # white  (low sat, high val)
    "Y": (20,  80, 120,  40, 255, 255),   # yellow
    "R": (160, 80,  80,  10, 255, 255),   # red  (wraps around 0/180)
    "O": (10,  80, 100,  25, 255, 255),   # orange
    "B": (95,  80,  60, 130, 255, 255),   # blue
    "G": (40,  50,  50,  90, 255, 255),   # green
}

# ---------------------------------------------------------------------------
# Flask server
# ---------------------------------------------------------------------------
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000

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
