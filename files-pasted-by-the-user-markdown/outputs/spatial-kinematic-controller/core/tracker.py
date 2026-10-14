"""Legacy MediaPipe Hands wrapper; normalized and world coordinates."""
from dataclasses import dataclass
import cv2
import numpy as np


@dataclass(frozen=True)
class Hand:
    normalized: np.ndarray
    world: np.ndarray | None
    handedness: str
    confidence: float


class HandTracker:
    def __init__(self, max_hands=1, model_complexity=0,
                 min_detection_confidence=0.6, min_tracking_confidence=0.6):
        import mediapipe as mp
        if not hasattr(mp, "solutions"):
            raise RuntimeError("Legacy Hands API missing: use Python 3.12 and mediapipe==0.10.21")
        self.pipeline = mp.solutions.hands.Hands(
            static_image_mode=False, max_num_hands=max_hands,
            model_complexity=model_complexity,
            min_detection_confidence=min_detection_confidence,
            min_tracking_confidence=min_tracking_confidence)

    def process(self, bgr):
        rgb = cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        result = self.pipeline.process(rgb)
        hands = []
        for i, points in enumerate(result.multi_hand_landmarks or []):
            normalized = np.array([(p.x, p.y, p.z) for p in points.landmark], dtype=np.float64)
            world = None
            if result.multi_hand_world_landmarks:
                world = np.array([(p.x, p.y, p.z) for p in result.multi_hand_world_landmarks[i].landmark])
            label = result.multi_handedness[i].classification[0]
            hands.append(Hand(normalized, world, label.label, label.score))
        return hands

    def close(self):
        self.pipeline.close()
