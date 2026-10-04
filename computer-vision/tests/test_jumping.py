"""Exercise jump tracking without a webcam or a downloaded model."""

import unittest
from types import SimpleNamespace

from pose_detector import PoseDetector


def make_pose(body_lift=0.0, foot_lift=0.0):
    pose = [SimpleNamespace(x=0.0, y=0.0, visibility=0.0) for _ in range(33)]
    for indices, y in (
        ((11, 12), 0.3 - body_lift),
        ((23, 24), 0.6 - body_lift),
        ((29, 30, 31, 32), 0.95 - foot_lift),
    ):
        for index in indices:
            pose[index] = SimpleNamespace(x=0.5, y=y, visibility=0.95)
    return pose


def make_crouch(body_lift=0.0, foot_lift=0.0):
    pose = make_pose(body_lift=-0.1 + body_lift, foot_lift=foot_lift)
    for index in (25, 26):
        pose[index] = SimpleNamespace(x=0.7, y=0.68 - body_lift, visibility=0.95)
    for index in (27, 28):
        pose[index] = SimpleNamespace(x=0.6, y=0.9 - foot_lift, visibility=0.95)
    return pose


class JumpDetectionTests(unittest.TestCase):
    def setUp(self):
        # These methods only need tracking state, not the MediaPipe landmarker.
        self.detector = PoseDetector.__new__(PoseDetector)
        self.detector.reset_jump_detection()
        for timestamp in (0, 100, 200, 300):
            self.assertFalse(self.detector.detect_jumping(make_pose(), timestamp))

    def test_takeoff_airborne_landing_and_second_jump(self):
        airborne = make_pose(body_lift=0.06, foot_lift=0.06)
        self.assertFalse(self.detector.detect_jumping(airborne, 340))
        self.assertTrue(self.detector.detect_jumping(airborne, 400))
        self.assertTrue(self.detector.detect_jumping(airborne, 500))
        self.assertFalse(self.detector.detect_jumping(make_pose(), 600))
        self.assertFalse(self.detector.detect_jumping(airborne, 700))
        self.assertTrue(self.detector.detect_jumping(airborne, 760))

    def test_grounded_crouch_then_stand_is_not_jumping(self):
        for timestamp, lift in ((400, -0.1), (500, -0.15), (600, 0.0), (700, 0.06)):
            self.assertFalse(self.detector.detect_jumping(make_pose(body_lift=lift), timestamp))

    def test_one_raised_foot_and_tiptoeing_are_not_jumping(self):
        for indices in ((29, 31), (29, 30)):
            pose = make_pose(body_lift=0.06)
            for index in indices:
                pose[index].y -= 0.06
            self.assertFalse(self.detector.detect_jumping(pose, 400))
            self.assertFalse(self.detector.detect_jumping(pose, 460))

    def test_tucking_feet_without_raising_torso_is_not_jumping(self):
        pose = make_pose(foot_lift=0.1)
        self.assertFalse(self.detector.detect_jumping(pose, 400))
        self.assertFalse(self.detector.detect_jumping(pose, 500))

    def test_single_frame_noise_does_not_trigger(self):
        self.assertFalse(self.detector.detect_jumping(make_pose(0.06, 0.06), 340))
        self.assertFalse(self.detector.detect_jumping(make_pose(), 370))
        self.assertFalse(self.detector.detect_jumping(make_pose(0.06, 0.06), 400))

    def test_hidden_far_side_is_supported(self):
        pose = make_pose(0.06, 0.06)
        for index in (12, 24, 30, 32):
            pose[index].visibility = 0.1
        self.assertFalse(self.detector.detect_jumping(pose, 400))
        self.assertTrue(self.detector.detect_jumping(pose, 460))

    def test_brief_lost_feet_or_missing_pose_preserves_reference(self):
        for pose in (make_pose(), None):
            self.setUp()
            if pose is not None:
                for index in (29, 30, 31, 32):
                    pose[index].visibility = 0.1
            self.assertFalse(self.detector.detect_jumping(pose, 400))
            self.assertIsNotNone(self.detector._jump_state)
            self.assertFalse(self.detector.detect_jumping(make_pose(0.06, 0.06), 460))
            self.assertTrue(self.detector.detect_jumping(make_pose(0.06, 0.06), 490))

    def test_long_tracking_loss_resets_reference(self):
        self.assertFalse(self.detector.detect_jumping(None, 900))
        self.assertIsNone(self.detector._jump_state)

    def test_small_short_hop_is_detected(self):
        pose = make_pose(body_lift=0.022, foot_lift=0.015)
        self.assertFalse(self.detector.detect_jumping(pose, 340))
        self.assertTrue(self.detector.detect_jumping(pose, 370))
        self.assertFalse(self.detector.detect_jumping(make_pose(), 400))

    def test_gradual_takeoff_does_not_move_ground_reference_upward(self):
        results = []
        for timestamp, lift in ((320, 0.003), (340, 0.005), (360, 0.009), (380, 0.013), (400, 0.017)):
            results.append(self.detector.detect_jumping(make_pose(0.025, lift), timestamp))
        self.assertTrue(results[-1])

    def test_body_rising_before_feet_is_remembered(self):
        self.assertFalse(self.detector.detect_jumping(make_pose(0.05, 0.0), 320))
        self.assertFalse(self.detector.detect_jumping(make_pose(0.055, 0.015), 340))
        self.assertTrue(self.detector.detect_jumping(make_pose(0.056, 0.015), 370))

    def test_uncertain_far_foot_does_not_veto_near_foot(self):
        pose = make_pose(0.04, 0.025)
        for index in (30, 32):
            pose[index].visibility = 0.6
            pose[index].y = 0.95
        self.assertFalse(self.detector.detect_jumping(pose, 340))
        self.assertTrue(self.detector.detect_jumping(pose, 370))

    def test_small_grounded_noise_is_not_a_jump(self):
        for timestamp, lift in ((340, 0.002), (370, 0.004), (400, -0.003), (430, 0.005)):
            self.assertFalse(self.detector.detect_jumping(make_pose(lift, lift), timestamp))

    def test_standing_from_crouch_with_foot_jitter_is_not_jumping(self):
        for timestamp, body_lift, foot_lift in (
            (340, -0.15, 0.0), (380, -0.15, 0.0),
            (420, 0.0, 0.015), (450, 0.0, 0.016), (480, 0.0, 0.014),
        ):
            self.assertFalse(self.detector.detect_jumping(make_pose(body_lift, foot_lift), timestamp))

    def test_jump_from_crouch_still_detected(self):
        self.assertFalse(self.detector.detect_jumping(make_pose(-0.15, 0.0), 340))
        self.assertFalse(self.detector.detect_jumping(make_pose(-0.15, 0.0), 380))
        self.assertFalse(self.detector.detect_jumping(make_pose(0.06, 0.08), 420))
        self.assertTrue(self.detector.detect_jumping(make_pose(0.07, 0.09), 450))

    def test_low_foot_outlier_during_crouch_does_not_shift_floor(self):
        self.assertFalse(self.detector.detect_jumping(make_pose(-0.15, -0.004), 340))
        self.assertFalse(self.detector.detect_jumping(make_pose(-0.15, 0.0), 380))
        self.assertFalse(self.detector.detect_jumping(make_pose(0.0, 0.01), 420))
        self.assertFalse(self.detector.detect_jumping(make_pose(0.0, 0.01), 450))

    def test_recognized_crouch_to_partial_stand_with_foot_error_is_not_jump(self):
        crouch = make_crouch()
        self.assertTrue(self.detector.detect_crouching(crouch))
        self.assertFalse(self.detector.detect_jumping(crouch, 340))
        self.assertFalse(self.detector.detect_jumping(crouch, 380))
        # Body rise plus a plausible foot estimate shift used to pass the
        # generic thresholds, despite being a transition out of a crouch.
        rising = make_crouch(body_lift=0.07, foot_lift=0.027)
        self.assertFalse(self.detector.detect_jumping(rising, 420))
        self.assertFalse(self.detector.detect_jumping(rising, 450))

    def test_recognized_crouch_can_still_jump_with_clear_foot_lift(self):
        self.assertFalse(self.detector.detect_jumping(make_crouch(), 340))
        self.assertFalse(self.detector.detect_jumping(make_crouch(), 380))
        airborne = make_crouch(body_lift=0.13, foot_lift=0.09)
        self.assertFalse(self.detector.detect_jumping(airborne, 420))
        self.assertTrue(self.detector.detect_jumping(airborne, 450))

    def test_switching_visible_foot_cannot_trigger_jump(self):
        self.detector.reset_jump_detection()
        grounded = make_pose()
        for index in (30, 32):
            grounded[index].y = 0.98
        for timestamp in (0, 100, 200, 300):
            self.assertFalse(self.detector.detect_jumping(grounded, timestamp))
        rising = make_pose(body_lift=0.08)
        for index in (30, 32):
            rising[index].visibility = 0.1
        self.assertFalse(self.detector.detect_jumping(rising, 340))
        self.assertFalse(self.detector.detect_jumping(rising, 380))

    def test_tracking_gap_and_airborne_timeout_reset(self):
        self.assertFalse(self.detector.detect_jumping(make_pose(0.06, 0.06), 1000))
        self.setUp()
        pose = make_pose(0.06, 0.06)
        self.detector.detect_jumping(pose, 400)
        self.assertTrue(self.detector.detect_jumping(pose, 460))
        for timestamp in (800, 1200, 1600):
            self.assertTrue(self.detector.detect_jumping(pose, timestamp))
        self.assertFalse(self.detector.detect_jumping(pose, 2000))
        self.assertIsNone(self.detector._jump_state)

    def test_jumping_is_consistent_across_frame_rates_and_body_sizes(self):
        for frame_ms in (16, 33, 67):
            for scale in (0.5, 1.0, 1.5):
                self.detector.reset_jump_detection()
                results = []
                for timestamp in range(0, 1000, frame_ms):
                    lift = 0.0 if timestamp < 450 else 0.06
                    pose = make_pose(lift, lift)
                    for point in pose:
                        point.y = 0.5 + (point.y - 0.5) * scale
                    results.append(self.detector.detect_jumping(pose, timestamp))
                self.assertFalse(any(results[:450 // frame_ms]))
                self.assertTrue(results[-1], (frame_ms, scale))


if __name__ == "__main__":
    unittest.main()
