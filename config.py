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
# ---------------------------------------------------------------------------
POS_HOME         = round((90) * (1024 / 300))  # robot home / neutral (midpoint)
POS_QUARTER_CW   = -round(90 * (1024 / 300))         # one cube-face CW quarter turn
POS_QUARTER_CCW  = round(90 * (1024 / 300))          # one cube-face CCW quarter turn
MOVE_SPEED       = 1000                              # kept for API compat / fallback
MOVE_TIME_MS     = 1000                               # position move duration target
MOVE_SETTLE_MS   = 500                               # extra settle time after move (ms)

STEPS_PER_DEGREE = 1024 / 300
HARD_ANGLE_MIN_BITS = 0
HARD_ANGLE_MAX_BITS = 1023


def _degrees_to_bits(degrees: float) -> int:
    """Convert degrees to the nearest servo bit value."""
    return int(round(degrees * STEPS_PER_DEGREE))


SERVO_LOGICAL_STATES = (0, 90, 180, 270)
SERVO_HOME_STATE = 90


def _default_servo_state_bits(home_bits: int = POS_HOME) -> dict[int, int]:
    """Build the four legal quarter-turn targets for one servo."""
    quarter_bits = _degrees_to_bits(90)
    home_index = SERVO_LOGICAL_STATES.index(SERVO_HOME_STATE)
    return {
        state: home_bits + ((idx - home_index) * quarter_bits)
        for idx, state in enumerate(SERVO_LOGICAL_STATES)
    }


# Per-servo discrete position calibration.
# Keys are logical cube-face orientations in degrees.  Tune these values if a
# servo's "home" or quarter-turn endpoints are mechanically off.  Keep each
# servo's values strictly increasing and within 0..1023.
#
# Current values use the measured 0° and 90° positions from the rig and
# interpolate 180° and 270° by repeating that per-servo 90° delta.
SERVO_STATE_BITS = {
    1: {0: 25, 90: 319, 180: 613, 270: 907},   # D
    2: {0: 33, 90: 303, 180: 573, 270: 843},   # F
    3: {0: 0, 90: 277, 180: 554, 270: 831},    # R
    4: {0: 0, 90: 253, 180: 506, 270: 759},    # B
    5: {0: 67, 90: 331, 180: 595, 270: 859},   # L
    6: {0: 60, 90: 329, 180: 598, 270: 867},   # U
}

SC09_MAX_TORQUE_KGCM = 2.3
SC09_LOCKED_ROTOR_CURRENT_A = 1.0
SC09_LOAD_RAW_FULL_SCALE = 1000
SC09_CURRENT_RAW_TO_A = 0.001

FACE_TELEMETRY_WINDOW_S = 5.0
TOTAL_CURRENT_WINDOW_S = 10.0
 
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

# Per-face turn calibration.
# +1 means a Rubik's "clockwise" token maps directly to +POS_QUARTER_CW bits.
# -1 flips that face because the servo is mounted in the opposite sense.
FACE_TURN_SIGN = {
    "U": 1,
    "D": 1,
    "F": 1,
    "R": 1,
    "B": 1,
    "L": 1,
}

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
ROI_SIZE = 25   # pixel size of each ROI square


# Faces visible to each camera (for auto-ROI generation)
# Cam0 (top camera): U top-centre, L bottom-left, F bottom-right
# Cam1 (bottom camera): R top-left, B top-right, D bottom-centre
CAM0_FACES = ["U", "L", "F"]
CAM1_FACES = ["R", "B", "D"]


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
# HSV colour thresholds.
#
# Each colour can use either:
#   - one range: (H_low, S_low, V_low, H_high, S_high, V_high)
#   - multiple ranges: [(...), (...)]
# This is useful for colours like red that span the HSV hue boundary.
# ---------------------------------------------------------------------------
COLOR_RANGES = {
    "W": [
        (0,   0,   155, 180, 35,  255),    # neutral white
        (90,  36,  150, 130, 95,  255),    # slightly blue white
    ],
    "Y": (43,  40,  125, 67,  255, 255),   # pale greenish-yellow to yellow
    # Red wraps around the HSV hue boundary, so handle it as two ranges
    "R": [
        (0,   60,  120, 7,   255, 255),
        (160, 50,  115, 180, 255, 255),    # pinkish / over-exposed red
    ],
    "O": [
        (8,   90,  60,  25,  255, 255),    # strong orange / red-orange
        (6,   35,  110, 24,  185, 255),    # pale orange
    ],
    "B": (95,  90,  25,  125, 255, 255),   # blue
    "G": (64,  150, 35,  85,  255, 255),   # green
}

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------
FLASK_HOST = "0.0.0.0"
FLASK_PORT = 5000
