"""Small reusable wrapper around MediaPipe Pose Landmarker."""

import math
from pathlib import Path

import cv2
import mediapipe as mp

# This defines how each 
POSE_CONNECTIONS = (
    (11, 12), (11, 13), (13, 15), (15, 17), (15, 19), (15, 21),
    (17, 19), (12, 14), (14, 16), (16, 18), (16, 20), (16, 22),
    (18, 20), (11, 23), (12, 24), (23, 24), (23, 25), (25, 27),
    (27, 29), (29, 31), (27, 31), (24, 26), (26, 28), (28, 30),
    (30, 32), (28, 32),
)


class PoseDetector:
    """Run pose detection on BGR frames and optionally draw the result."""

    def __init__(
        self,
        model_path: str | Path,
        num_poses: int = 1,
        min_detection_confidence: float = 0.5,
        min_presence_confidence: float = 0.5,
        min_tracking_confidence: float = 0.5,
    ) -> None:
        model_path = Path(model_path)
        if not model_path.is_file():
            raise FileNotFoundError(
                f"Pose model not found at {model_path}. "
                "Run `python computer-vision/download_model.py` first."
            )

        options = mp.tasks.vision.PoseLandmarkerOptions(
            base_options=mp.tasks.BaseOptions(model_asset_path=str(model_path)),
            running_mode=mp.tasks.vision.RunningMode.VIDEO,
            num_poses=num_poses,
            min_pose_detection_confidence=min_detection_confidence,
            min_pose_presence_confidence=min_presence_confidence,
            min_tracking_confidence=min_tracking_confidence,
        )
        self._landmarker = mp.tasks.vision.PoseLandmarker.create_from_options(options)
        self._last_timestamp_ms = -1

    def process_frame(self, frame_bgr, timestamp_ms: int):
        """Return MediaPipe results for a BGR image frame."""
        if timestamp_ms <= self._last_timestamp_ms:
            timestamp_ms = self._last_timestamp_ms + 1
        self._last_timestamp_ms = timestamp_ms

        frame_rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        mp_image = mp.Image(image_format=mp.ImageFormat.SRGB, data=frame_rgb)
        return self._landmarker.detect_for_video(mp_image, timestamp_ms)

    @staticmethod
    def _visible_xy(landmarks, index: int, min_visibility: float = 0.5, image_size=None):
        """Return reliable coordinates, correcting for image width/height if given."""
        landmark = landmarks[index]
        if getattr(landmark, "visibility", 1.0) < min_visibility:
            return None
        aspect_ratio = image_size[0] / image_size[1] if image_size else 1.0
        return landmark.x * aspect_ratio, landmark.y

    @staticmethod
    def _angle(a, vertex, c) -> float:
        """Return the angle a-vertex-c in degrees."""
        va = (a[0] - vertex[0], a[1] - vertex[1])
        vc = (c[0] - vertex[0], c[1] - vertex[1])
        dot = va[0] * vc[0] + va[1] * vc[1]
        lengths = math.hypot(*va) * math.hypot(*vc)
        if lengths == 0:
            return 180.0
        cosine = max(-1.0, min(1.0, dot / lengths))
        return math.degrees(math.acos(cosine))

    @classmethod
    def _signed_torso_lean(cls, landmarks, image_size=None):
        """Return forward-positive torso displacement relative to torso height."""
        nose = cls._visible_xy(landmarks, 0, image_size=image_size)
        # A side view often hides the far shoulder/hip. Use the more reliable
        # complete side rather than requiring both sides to be visible.
        sides = []
        for shoulder_i, hip_i in ((11, 23), (12, 24)):
            shoulder = cls._visible_xy(landmarks, shoulder_i, image_size=image_size)
            hip = cls._visible_xy(landmarks, hip_i, image_size=image_size)
            if shoulder is not None and hip is not None:
                confidence = min(landmarks[shoulder_i].visibility, landmarks[hip_i].visibility)
                sides.append((confidence, shoulder, hip))
        if nose is None or not sides:
            return None
        _, shoulder, hip = max(sides, key=lambda side: side[0])
        torso_height = hip[1] - shoulder[1]
        torso_length = math.dist(shoulder, hip)
        if torso_height <= 1e-6:
            return None

        # Nose relative to the ear describes head direction even during a
        # backward lean, when the nose can move behind the shoulder.
        ears = []
        for ear_i in (7, 8):
            ear = cls._visible_xy(landmarks, ear_i, image_size=image_size)
            if ear is not None:
                ears.append((landmarks[ear_i].visibility, ear))
        reference = max(ears, key=lambda ear: ear[0])[1] if ears else shoulder
        facing = nose[0] - reference[0]
        if abs(facing) < torso_length * 0.03:
            return None

        # Positive means shoulders are displaced toward the direction the nose faces.
        return ((shoulder[0] - hip[0]) / torso_height) * (1 if facing > 0 else -1)

    @classmethod
    def detect_leaning_forward(cls, landmarks, min_lean: float = 0.15, image_size=None) -> bool:
        """Detect a forward torso lean from a side-on pose.

        ``landmarks`` is one pose's 33 MediaPipe landmarks. The person is
        assumed to be side-on; the nose indicates their facing direction.
        ``min_lean`` is the horizontal shoulder/hip displacement as a fraction
        of torso height. A detected crouch takes priority over forward lean.
        Pass ``image_size=(width, height)`` for correct geometry on video frames.
        """
        lean = cls._signed_torso_lean(landmarks, image_size=image_size)
        return (
            lean is not None
            and lean > min_lean
            and not cls.detect_crouching(landmarks, image_size=image_size)
        )

    @classmethod
    def detect_leaning_backward(cls, landmarks, min_lean: float = 0.15, image_size=None) -> bool:
        """Detect a backward torso lean from a side-on pose."""
        lean = cls._signed_torso_lean(landmarks, image_size=image_size)
        return (
            lean is not None
            and lean < -min_lean
            and not cls.detect_crouching(landmarks, image_size=image_size)
        )

    @classmethod
    def detect_crouching(
        cls, landmarks, knee_angle_threshold: float = 125.0,
        max_thigh_vertical_ratio: float = 0.75, image_size=None,
    ) -> bool:
        """Require bent knees and lowered hips on every reliably visible leg.

        Lowered hips bring the thighs toward horizontal. This additional check
        distinguishes crouching from leaning with slightly bent knees. A hidden
        leg is ignored; if both legs are visible, both must meet the criteria.
        ``image_size`` is an optional (width, height) tuple.
        """
        crouched_legs = []
        for hip_i, knee_i, ankle_i in ((23, 25, 27), (24, 26, 28)):
            hip = cls._visible_xy(landmarks, hip_i, image_size=image_size)
            knee = cls._visible_xy(landmarks, knee_i, image_size=image_size)
            ankle = cls._visible_xy(landmarks, ankle_i, image_size=image_size)
            if hip is not None and knee is not None and ankle is not None:
                thigh_length = math.dist(hip, knee)
                if thigh_length <= 1e-6 or math.dist(knee, ankle) <= 1e-6:
                    continue
                thigh_vertical_ratio = (knee[1] - hip[1]) / thigh_length
                crouched_legs.append(
                    cls._angle(hip, knee, ankle) < knee_angle_threshold
                    and 0 <= thigh_vertical_ratio < max_thigh_vertical_ratio
                )
        return bool(crouched_legs) and all(crouched_legs)

    @staticmethod
    def draw_landmarks(frame_bgr, result):
        """Draw detected pose landmarks on a copy of the input frame."""
        output = frame_bgr.copy()
        height, width = output.shape[:2]

        for pose in result.pose_landmarks:
            points = [
                (int(landmark.x * width), int(landmark.y * height))
                for landmark in pose
            ]
            visible = [landmark.visibility > 0.35 for landmark in pose]

            for start, end in POSE_CONNECTIONS:
                if visible[start] and visible[end]:
                    cv2.line(output, points[start], points[end], (0, 220, 0), 2)
            for index, point in enumerate(points):
                if visible[index]:
                    cv2.circle(output, point, 4, (0, 80, 255), -1)

        return output

    def close(self) -> None:
        self._landmarker.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc_info):
        self.close()
