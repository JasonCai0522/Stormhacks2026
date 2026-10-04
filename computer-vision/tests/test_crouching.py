"""Regressions for separating side-view crouching from forward leaning."""

import unittest
from types import SimpleNamespace

from pose_detector import PoseDetector


def make_pose(hip=(0.4, 0.6), knee=(0.5, 0.75), ankle=(0.5, 0.92)):
    pose = [SimpleNamespace(x=0.0, y=0.0, visibility=0.0) for _ in range(33)]
    for indices, point in (
        ((0,), (0.65, 0.23)), ((7, 8), (0.6, 0.23)),
        ((11, 12), (0.55, 0.35)), ((23, 24), hip),
        ((25, 26), knee), ((27, 28), ankle),
    ):
        for index in indices:
            pose[index] = SimpleNamespace(x=point[0], y=point[1], visibility=0.95)
    return pose


class CrouchingTests(unittest.TestCase):
    def test_deep_crouch_with_hips_below_knees_is_not_forward_lean(self):
        for mirrored in (False, True):
            for aspect_ratio in (1.0, 16 / 9):
                pose = make_pose(hip=(0.65, 0.8), knee=(0.3, 0.65), ankle=(0.45, 0.92))
                # Face left, with the torso tilted toward the knees.
                pose[11].x = pose[12].x = 0.5
                pose[0].x, pose[7].x, pose[8].x = 0.42, 0.47, 0.47
                for point in pose:
                    if mirrored:
                        point.x = 1.0 - point.x
                    point.x /= aspect_ratio
                image_size = (480 * aspect_ratio, 480)
                self.assertTrue(PoseDetector.detect_crouching(pose, image_size=image_size))
                self.assertFalse(PoseDetector.detect_leaning_forward(pose, image_size=image_size))

    def test_shallow_crouch_with_forward_torso_is_not_forward_lean(self):
        pose = make_pose()
        self.assertTrue(PoseDetector.detect_crouching(pose))
        self.assertFalse(PoseDetector.detect_leaning_forward(pose))

    def test_uncertain_far_leg_does_not_veto_crouch(self):
        pose = make_pose()
        for index, y in ((24, 0.6), (26, 0.75), (28, 0.92)):
            pose[index] = SimpleNamespace(x=0.4, y=y, visibility=0.6)
        self.assertTrue(PoseDetector.detect_crouching(pose))
        self.assertFalse(PoseDetector.detect_leaning_forward(pose))

    def test_forward_lean_with_soft_knees_is_not_crouching(self):
        pose = make_pose(hip=(0.5, 0.6), knee=(0.53, 0.75), ankle=(0.65, 0.9))
        pose[11].x = pose[12].x = 0.65
        pose[0].x, pose[7].x, pose[8].x = 0.73, 0.66, 0.66
        self.assertFalse(PoseDetector.detect_crouching(pose))
        self.assertTrue(PoseDetector.detect_leaning_forward(pose))

    def test_one_bent_leg_with_reliable_straight_leg_is_not_crouching(self):
        pose = make_pose()
        for index in (24, 26, 28):
            pose[index].x = 0.4
        self.assertFalse(PoseDetector.detect_crouching(pose))

    def test_hidden_far_leg_and_mirrored_person(self):
        pose = make_pose()
        for index in (12, 24, 26, 28):
            pose[index].visibility = 0.1
        for point in pose:
            point.x = 1.0 - point.x
        self.assertTrue(PoseDetector.detect_crouching(pose))
        self.assertFalse(PoseDetector.detect_leaning_forward(pose))


if __name__ == "__main__":
    unittest.main()
