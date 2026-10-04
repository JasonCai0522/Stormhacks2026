"""Small reusable wrapper around MediaPipe Pose Landmarker."""

import math
from collections import deque
from dataclasses import dataclass, field
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


@dataclass
class _JumpState:
    foot_y: float
    hip_y: float
    shoulder_y: float
    torso_length: float
    last_timestamp_ms: int
    stable_since_ms: int
    ready: bool = False
    candidate_since_ms: int | None = None
    airborne_since_ms: int | None = None
    body_history: deque = field(default_factory=deque)
    foot_ground_y: dict = field(default_factory=dict)
    last_grounded_crouch_ms: int | None = None


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
        self.reset_jump_detection()

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
        cls, landmarks, knee_angle_threshold: float = 150.0,
        max_thigh_vertical_ratio: float = 0.85, image_size=None,
    ) -> bool:
        """Require bent knees and lowered hips on every reliably visible leg.

        Lowered hips bring the thighs toward horizontal, or below knee height
        in a deep crouch. This additional check
        distinguishes crouching from leaning with slightly bent knees. A hidden
        leg is ignored, as is a far leg with substantially lower confidence.
        If both legs are similarly reliable, both must meet the criteria.
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
                confidence = min(
                    landmarks[hip_i].visibility, landmarks[knee_i].visibility,
                    landmarks[ankle_i].visibility,
                )
                crouched_legs.append((
                    confidence,
                    cls._angle(hip, knee, ankle) < knee_angle_threshold
                    and thigh_vertical_ratio < max_thigh_vertical_ratio,
                ))
        if not crouched_legs:
            return False
        best_confidence = max(confidence for confidence, _ in crouched_legs)
        return all(
            crouched for confidence, crouched in crouched_legs
            if confidence >= best_confidence * 0.8
        )

    def reset_jump_detection(self) -> None:
        """Forget the ground reference when the tracked person disappears."""
        self._jump_state = None

    def detect_jumping(
        self, landmarks, timestamp_ms: int, min_foot_lift: float = 0.04,
        min_body_lift: float = 0.06, image_size=None,
        min_foot_body_ratio: float = 0.20,
        min_crouch_foot_lift: float = 0.12,
    ) -> bool:
        """Detect an airborne jump across frames for one person and a fixed camera.

        Call once per frame, including while crouching or leaning. First keep
        the feet on the ground for 200 ms to learn a reference. Visible feet,
        hips, and shoulders must rise together for at least 20 ms. Thresholds
        are fractions of torso length; the result stays True until landing.
        Foot lift must also be at least ``min_foot_body_ratio`` of body lift,
        rejecting a large rise from crouching accompanied by small foot jitter.
        For 800 ms after a grounded crouch, require clearer foot clearance
        (``min_crouch_foot_lift``) to distinguish standing up from takeoff.
        Briefly hidden feet/body return False but retain the reference for up
        to 500 ms. Longer gaps or a 1.5-second airborne timeout reset tracking.
        This is a movement heuristic, not a physical measurement of floor contact.
        """
        if landmarks is None:
            return self._jump_tracking_missing(timestamp_ms)

        foot_indices = (29, 30, 31, 32)
        best_visibility = max(landmarks[index].visibility for index in foot_indices)
        # Ignore an uncertain far foot instead of letting its stale location
        # veto the reliable near foot in a side view.
        feet = {
            index: point for index in foot_indices
            if (point := self._visible_xy(
                landmarks, index, min_visibility=max(0.35, best_visibility * 0.8),
                image_size=image_size,
            ))
            is not None
        }
        sides = []
        for shoulder_i, hip_i in ((11, 23), (12, 24)):
            shoulder = self._visible_xy(landmarks, shoulder_i, image_size=image_size)
            hip = self._visible_xy(landmarks, hip_i, image_size=image_size)
            if shoulder is not None and hip is not None:
                confidence = min(landmarks[shoulder_i].visibility, landmarks[hip_i].visibility)
                sides.append((confidence, shoulder, hip))
        if not feet or not sides:
            return self._jump_tracking_missing(timestamp_ms)

        _, shoulder, hip = max(sides, key=lambda side: side[0])
        torso_length = math.dist(shoulder, hip)
        if torso_length <= 1e-6:
            return self._jump_tracking_missing(timestamp_ms)
        # The lowest visible heel/toe must rise too, avoiding ordinary tiptoeing
        # and raising just one foot when both feet are visible.
        foot_y = max(point[1] for point in feet.values())
        state = self._jump_state
        if state is None or timestamp_ms - state.last_timestamp_ms > 500:
            self._jump_state = _JumpState(
                foot_y, hip[1], shoulder[1], torso_length,
                timestamp_ms, timestamp_ms,
                foot_ground_y={index: point[1] for index, point in feet.items()},
            )
            return False
        if timestamp_ms <= state.last_timestamp_ms:
            return state.airborne_since_ms is not None
        state.last_timestamp_ms = timestamp_ms
        state.body_history.append((timestamp_ms, hip[1], shoulder[1]))
        while state.body_history and timestamp_ms - state.body_history[0][0] > 300:
            state.body_history.popleft()

        if not state.ready:
            if abs(foot_y - state.foot_y) > state.torso_length * 0.05:
                state.stable_since_ms = timestamp_ms
            state.foot_y = foot_y
            state.hip_y = hip[1]
            state.shoulder_y = shoulder[1]
            state.torso_length = torso_length
            state.foot_ground_y.update({index: point[1] for index, point in feet.items()})
            if self.detect_crouching(landmarks, image_size=image_size):
                state.last_grounded_crouch_ms = timestamp_ms
            state.ready = timestamp_ms - state.stable_since_ms >= 200
            return False

        # Compare each heel/toe with its own reference. Switching from a lower
        # far foot to a higher near foot must not look like leaving the floor.
        matched_feet = [index for index in feet if index in state.foot_ground_y]
        if not matched_feet:
            self.reset_jump_detection()
            return False
        foot_lift = min(
            state.foot_ground_y[index] - feet[index][1] for index in matched_feet
        ) / state.torso_length
        if state.airborne_since_ms is not None:
            if timestamp_ms - state.airborne_since_ms > 1500:
                self.reset_jump_detection()
                return False
            if foot_lift > min_foot_lift / 2:
                return True
            state.airborne_since_ms = None

        # Keep recent body positions so the initial upward motion is not lost
        # while the toes are still near the floor during takeoff.
        reference_hip = max(state.hip_y, *(sample[1] for sample in state.body_history))
        reference_shoulder = max(state.shoulder_y, *(sample[2] for sample in state.body_history))
        body_lift = min(reference_hip - hip[1], reference_shoulder - shoulder[1])
        if (
            state.airborne_since_ms is None
            and foot_lift < min_foot_lift / 2
            and self.detect_crouching(landmarks, image_size=image_size)
        ):
            state.last_grounded_crouch_ms = timestamp_ms
        rising_from_crouch = (
            state.last_grounded_crouch_ms is not None
            and timestamp_ms - state.last_grounded_crouch_ms <= 800
        )
        required_foot_lift = max(min_foot_lift, min_crouch_foot_lift) if rising_from_crouch else min_foot_lift
        required_ratio = max(min_foot_body_ratio, 0.4) if rising_from_crouch else min_foot_body_ratio
        lifted = (
            foot_lift >= required_foot_lift
            and body_lift >= min_body_lift * state.torso_length
            and foot_lift * state.torso_length >= required_ratio * body_lift
        )
        if lifted:
            if state.candidate_since_ms is None:
                state.candidate_since_ms = timestamp_ms
            if timestamp_ms - state.candidate_since_ms >= 20:
                state.airborne_since_ms = timestamp_ms
                return True
        else:
            state.candidate_since_ms = None
            if abs(foot_lift) < min_foot_lift / 2:
                # Follow grounded crouching/leaning without confusing the
                # subsequent upward torso movement with a jump.
                # Never follow feet upward: doing so erases a gradual hop.
                # Allow the reference to follow feet settling lower instead.
                # A single low foot estimate should not permanently shift the
                # floor enough to turn standing from a crouch into a jump.
                state.foot_y += 0.15 * max(0.0, foot_y - state.foot_y)
                for index, point in feet.items():
                    if index not in state.foot_ground_y:
                        state.foot_ground_y[index] = point[1]
                    else:
                        state.foot_ground_y[index] += 0.15 * max(
                            0.0, point[1] - state.foot_ground_y[index],
                        )
                state.hip_y = hip[1]
                state.shoulder_y = shoulder[1]
                state.torso_length = torso_length
        return False

    def _jump_tracking_missing(self, timestamp_ms: int) -> bool:
        """Preserve the ground reference through short landmark dropouts."""
        state = self._jump_state
        if state is not None:
            state.candidate_since_ms = None
            if timestamp_ms - state.last_timestamp_ms > 500:
                self.reset_jump_detection()
        return False

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
