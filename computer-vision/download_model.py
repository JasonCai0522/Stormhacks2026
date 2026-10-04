"""Download a MediaPipe Pose Landmarker model bundle (lite, full, or heavy)."""

import argparse
from pathlib import Path
from urllib.request import urlretrieve


MODELS_DIR = Path(__file__).parent / "models"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--model", choices=("lite", "full", "heavy"), default="lite",
        help="Model variant to download (default: lite)",
    )
    args = parser.parse_args()

    model_name = f"pose_landmarker_{args.model}"
    model_url = (
        "https://storage.googleapis.com/mediapipe-models/pose_landmarker/"
        f"{model_name}/float16/latest/{model_name}.task"
    )
    model_path = MODELS_DIR / f"{model_name}.task"
    model_path.parent.mkdir(parents=True, exist_ok=True)
    if model_path.exists():
        print(f"Model already exists: {model_path}")
        return

    print(f"Downloading Pose Landmarker {args.model.title()} model...")
    urlretrieve(model_url, model_path)
    print(f"Saved model to {model_path}")


if __name__ == "__main__":
    main()
