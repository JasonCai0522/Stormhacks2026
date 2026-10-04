# MediaPipe Pose Starter

This folder contains a small webcam-based pose detection example built with
MediaPipe Pose Landmarker and OpenCV. The reusable `PoseDetector` class accepts
BGR image frames and returns MediaPipe's 33 pose landmarks.

## Setup

The repository selects the `stormhacks` pyenv environment through `.python-version`.
From the repository root:

```bash
pyenv activate stormhacks
python -m pip install -r computer-vision/requirements.txt
python computer-vision/download_model.py
```

The downloader defaults to `lite`. Select another variant with `--model`:

```bash
python computer-vision/download_model.py --model full
python computer-vision/download_model.py --model heavy
```

Each variant is saved separately in `computer-vision/models/`. Existing downloads
are skipped. To use a downloaded variant in the webcam example:

```bash
python computer-vision/run_webcam.py --model full
```

If `pyenv activate` is unavailable in your shell, install the `pyenv-virtualenv`
plugin or open a new shell after pyenv initialization. Running commands from the
repository root automatically selects `stormhacks` when pyenv is initialized.

## Run

```bash
python computer-vision/run_webcam.py
```

Choose a different camera with `--camera` or a model variant (`lite`, `full`,
or `heavy`) with `--model`. The default model is `lite`. Press
`q` or Escape in the preview window to exit.

## Use in code

```python
from pose_detector import PoseDetector

with PoseDetector("models/pose_landmarker_lite.task") as detector:
    result = detector.process_frame(frame_bgr, timestamp_ms=0)
    annotated = detector.draw_landmarks(frame_bgr, result)
```

Run the snippet from the `computer-vision` directory, adjusting the model path
if needed. When processing video, pass timestamps in milliseconds. The detector
advances repeated or decreasing timestamps automatically. Landmarks are
normalized to the image dimensions; world landmarks are also available in
`result`.

The webcam example prints jumping, crouching, or leaning when detected. Jumping
takes priority and uses movement across frames: keep the camera fixed, keep the
feet in view, and start with the feet grounded for at least 200 ms. In your own
loop, call `detector.detect_jumping(pose, timestamp_ms, image_size=(width, height))`
every frame, passing `None` as the pose when no person is detected. Brief tracking
loss is tolerated for up to 500 ms; use `detector.reset_jump_detection()` explicitly
when changing people or cameras.
Jump detection tracks one person and estimates airborne movement from visible
feet and torso movement; it does not directly measure floor contact.
