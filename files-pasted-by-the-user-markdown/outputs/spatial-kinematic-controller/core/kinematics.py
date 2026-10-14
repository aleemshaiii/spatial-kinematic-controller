"""Anatomical normalization and palm orientation (monocular estimates)."""
from dataclasses import dataclass
import math
import numpy as np


@dataclass(frozen=True)
class Pose:
    roll_deg: float
    pitch_deg: float
    yaw_deg: float
    pinch_ratio: float
    fist_ratio: float


def deadzone(value, threshold):
    value = float(np.clip(value, -1, 1))
    if abs(value) <= threshold:
        return 0.0
    return math.copysign((abs(value) - threshold) / (1 - threshold), value)


def geometry(normalized, width, height, world=None, handedness="Right"):
    points = np.asarray(normalized, dtype=np.float64)
    if points.shape != (21, 3) or not np.isfinite(points).all():
        raise ValueError("landmarks must be finite 21x3 matrices")
    # MediaPipe normalized z uses the same approximate scale as x.
    image_points = points * np.array([width, height, width])
    spatial = image_points if world is None else np.asarray(world, dtype=np.float64)
    if spatial.shape != (21, 3) or not np.isfinite(spatial).all():
        raise ValueError("invalid world landmarks")
    palm_width = np.linalg.norm(spatial[5] - spatial[17])
    forward = spatial[9] - spatial[0]
    side = spatial[5] - spatial[17]
    normal = np.cross(side, forward)
    norm = np.linalg.norm(normal)
    image_forward = image_points[9] - image_points[0]
    if palm_width < 1e-8 or norm < 1e-10 or np.linalg.norm(image_forward[:2]) < 1e-8:
        raise ValueError("degenerate palm geometry")
    normal /= norm
    # Stable normal sign for either handedness. Handedness must be consistent
    # across frames; the pipeline resets filters on a change of selected hand.
    if handedness == "Left":
        normal *= -1
    roll = math.degrees(math.atan2(image_forward[1], image_forward[0]))
    pitch = math.degrees(math.acos(float(np.clip(normal[2], -1, 1))))
    yaw = math.degrees(math.atan2(normal[0], normal[2]))
    pinch = np.linalg.norm(spatial[4] - spatial[8]) / palm_width
    # Average fingertip distance to wrist, relative to MCP distance to wrist.
    tip_distance = np.mean([np.linalg.norm(spatial[i] - spatial[0]) for i in (8, 12, 16, 20)])
    mcp_distance = np.mean([np.linalg.norm(spatial[i] - spatial[0]) for i in (5, 9, 13, 17)])
    if mcp_distance < 1e-8:
        raise ValueError("degenerate MCP distance")
    return Pose(roll, pitch, yaw, float(pinch), float(tip_distance / mcp_distance))


class Kinematics:
    def __init__(self, neutral_roll_deg=-90, roll_range_deg=60, steering_sign=1,
                 deadzone=0.06, pinch_closed=0.15, pinch_open=1.1,
                 fist_enter_ratio=0.9, fist_exit_ratio=1.1):
        if roll_range_deg <= 0 or not 0 <= deadzone < 1 or pinch_open <= pinch_closed:
            raise ValueError("invalid roll/deadzone/pinch calibration")
        if fist_exit_ratio <= fist_enter_ratio or steering_sign not in (-1, 1):
            raise ValueError("invalid fist hysteresis/steering sign")
        self.neutral = neutral_roll_deg
        self.roll_range = roll_range_deg
        self.sign = steering_sign
        self.deadzone = deadzone
        self.closed, self.open = pinch_closed, pinch_open
        self.enter, self.exit = fist_enter_ratio, fist_exit_ratio
        self.fist = False

    def reset(self):
        self.fist = False

    def map(self, roll, pinch, fist_ratio):
        delta = (roll - self.neutral + 180) % 360 - 180
        steer = deadzone(self.sign * delta / self.roll_range, self.deadzone)
        throttle = float(np.clip((self.open - pinch) / (self.open - self.closed), 0, 1))
        self.fist = fist_ratio < (self.exit if self.fist else self.enter)
        # Handbrake takes priority over throttle.
        return steer, 0.0 if self.fist else throttle, int(self.fist)
