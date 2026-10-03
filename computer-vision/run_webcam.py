"""Run pose detection against the default webcam. Press q or Esc to quit."""

import argparse
import time
from pathlib import Path

import cv2

from pose_detector import PoseDetector


DEFAULT_MODEL = Path(__file__).parent / "models" / "pose_landmarker_lite.task"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0, help="Webcam device index")
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL, help="Pose .task model")
    args = parser.parse_args()

    camera = cv2.VideoCapture(args.camera)
    if not camera.isOpened():
        raise RuntimeError(f"Could not open camera {args.camera}")

    try:
        with PoseDetector(args.model) as detector:
            start_time = time.monotonic()
            while True:
                success, frame = camera.read()
                if not success:
                    print("Could not read a frame from the camera.")
                    break

                timestamp_ms = int((time.monotonic() - start_time) * 1000)
                result = detector.process_frame(frame, timestamp_ms)
                if result.pose_landmarks:
                    pose = result.pose_landmarks[0]
                    image_size = (frame.shape[1], frame.shape[0])
                    if detector.detect_crouching(pose, image_size=image_size):
                        print("Crouching")
                    elif detector.detect_leaning_forward(pose, image_size=image_size):
                        print("Leaning forward")
                    elif detector.detect_leaning_backward(pose, image_size=image_size):
                        print("Leaning backward")
                display = detector.draw_landmarks(frame, result)
                cv2.imshow("MediaPipe Pose (q or Esc to quit)", display)

                key = cv2.waitKey(1) & 0xFF
                if key in (ord("q"), 27):
                    break
    finally:
        camera.release()
        cv2.destroyAllWindows()


if __name__ == "__main__":
    main()
