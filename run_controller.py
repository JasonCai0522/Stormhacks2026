"""Combine webcam movement and ESP32 attacks using game-controller/controller.py."""

import argparse
import importlib.util
import json
import math
import sys
import threading
import time
from contextlib import ExitStack
from pathlib import Path


ROOT = Path(__file__).resolve().parent
VISION_DIR = ROOT / "computer-vision"
ATTACKS = frozenset(("light", "medium", "heavy", "special"))


class AttackInput:
    """Hold the latest Bluetooth attack until its messages stop arriving."""

    def __init__(self, timeout=0.25):
        self.timeout = timeout
        self._attack = None
        self._received_at = 0.0

    def receive(self, message, now):
        command = message.strip().lower()
        if command in ATTACKS:
            self._attack = command
            self._received_at = now

    def held(self, now):
        if self._attack and now - self._received_at < self.timeout:
            return {self._attack}
        return set()


class MicrocontrollerAttacks:
    """Consume messages from microcontroller/bluetooth.py off the webcam thread."""

    def __init__(self, connection, timeout):
        self.connection = connection
        self.state = AttackInput(timeout)
        self.lock = threading.Lock()
        self.stop = threading.Event()
        self.error = None
        self.thread = threading.Thread(target=self._read, daemon=True)

    def _read(self):
        try:
            while not self.stop.is_set():
                message = self.connection.read_message()
                if message:
                    with self.lock:
                        self.state.receive(message, time.monotonic())
        except Exception as exc:
            with self.lock:
                self.error = exc

    def held(self):
        with self.lock:
            if self.error is not None:
                raise RuntimeError(f"Microcontroller connection failed: {self.error}") from self.error
            return self.state.held(time.monotonic())

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def movement_input(detector, pose, timestamp_ms, image_size):
    """Preserve the webcam's jump > crouch > forward > back priority."""
    jumping = detector.detect_jumping(pose, timestamp_ms, image_size=image_size)
    if pose is None:
        return set()
    if jumping:
        return {"up"}
    if detector.detect_crouching(pose, image_size=image_size):
        return {"down"}
    if detector.detect_leaning_forward(pose, image_size=image_size):
        return {"forward"}
    if detector.detect_leaning_backward(pose, image_size=image_size):
        return {"back"}
    return set()


def update_controller(controller, held, last):
    # Resolve every frame, including while a lean stays held during a side swap.
    resolved = controller.resolve(held)
    if resolved != last:
        controller.apply(resolved)
    return resolved


# Key MediaPipe landmark indices exported for the mini stick-figure.
# Covers: nose, shoulders, elbows, wrists, hips, knees, ankles.
_LANDMARK_INDICES = (0, 11, 12, 13, 14, 15, 16, 23, 24, 25, 26, 27, 28)


def write_cv_state(path, movement, attacks, pose=None):
    """Write current input state (and optional pose landmarks) for the Lua overlay.

    ``path`` is a pathlib.Path or str. ``pose`` is a single MediaPipe pose
    landmarks list (or None when no person is detected). Key joints are written
    as {"index": [x, y]} with normalised 0-1 coordinates. Errors are silently
    ignored so a missing path never crashes the main loop.
    """
    try:
        state = {
            "movement": next(iter(movement)) if movement else "neutral",
            "attack": next(iter(attacks)) if attacks else "none",
        }
        if pose is not None:
            lm_data = {}
            for i in _LANDMARK_INDICES:
                lm = pose[i]
                if getattr(lm, "visibility", 0.0) >= 0.35:
                    lm_data[str(i)] = [round(lm.x, 4), round(lm.y, 4)]
            state["landmarks"] = lm_data
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(state, fh)
    except Exception:
        pass


def load_controller(path):
    return load_module("sf6_controller", path)


def load_module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# Default CV state output path mirrors p1_character.json in the same REFramework data folder.
_DEFAULT_CV_STATE = (
    r"C:\Program Files (x86)\Steam\steamapps\common"
    r"\Street Fighter 6\reframework\data\cv_state.json"
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--camera", type=int, default=0)
    parser.add_argument("--model", choices=("lite", "full", "heavy"), default="lite")
    parser.add_argument("--no-bluetooth", action="store_true",
                        help="Run webcam movement and gamepad control without microcontroller attacks")
    parser.add_argument("--transport", choices=("ble", "serial"),
                        help="Attack transport (default: BLE; --port/--baud imply serial)")
    parser.add_argument("--attack-pulse", type=float, default=0.10,
                        help="Seconds to press each detected BLE punch (default: 0.10)")
    parser.add_argument("--port", help="Override the port configured in microcontroller/bluetooth.py")
    parser.add_argument("--baud", type=int,
                        help="Override the baud rate configured in microcontroller/bluetooth.py")
    parser.add_argument("--attack-timeout", type=float, default=0.25,
                        help="Seconds without a repeated attack before releasing it (default: 0.25)")
    parser.add_argument("--controller", type=Path, default=ROOT / "game-controller" / "controller.py")
    parser.add_argument("--game-state", type=Path,
                        help="Override controller.py's facing-state JSON path")
    parser.add_argument("--cv-state-out", type=Path, default=_DEFAULT_CV_STATE,
                        help="Path to write cv_state.json for the REFramework overlay (default: SF6 reframework/data folder)")
    args = parser.parse_args()
    if not math.isfinite(args.attack_timeout) or args.attack_timeout <= 0:
        parser.error("--attack-timeout must be a finite positive number")
    if not math.isfinite(args.attack_pulse) or args.attack_pulse <= 0:
        parser.error("--attack-pulse must be a finite positive number")
    transport = args.transport or ("serial" if args.port is not None or args.baud is not None else "ble")
    if transport == "ble" and (args.port is not None or args.baud is not None):
        parser.error("--port and --baud apply to --transport serial")
    model_path = VISION_DIR / "models" / f"pose_landmarker_{args.model}.task"
    if not model_path.is_file():
        parser.error(f"Model not found: {model_path}. Run python computer-vision/download_model.py --model {args.model}")
    if not args.controller.is_file():
        parser.error(f"Controller not found: {args.controller}")

    import cv2
    sys.path.insert(0, str(VISION_DIR))
    from pose_detector import PoseDetector

    controller = load_controller(args.controller)
    camera = None
    try:
        if args.game_state:
            controller.GAME_STATE_PATH = str(args.game_state)
        controller.apply(set())
        with ExitStack() as resources:
            reader = None
            if not args.no_bluetooth and transport == "ble":
                sys.path.insert(0, str(ROOT / "microcontroller"))
                try:
                    ble = load_module("esp32_ble_attacks", ROOT / "microcontroller" / "ble_attacks.py")
                except ModuleNotFoundError as exc:
                    if exc.name == "bleak":
                        raise RuntimeError("BLE requires bleak; run python -m pip install -r requirements.txt") from exc
                    raise
                reader = resources.enter_context(ble.BLEAttacks(args.attack_pulse))
                mode = "ESP32-IMU over BLE"
            elif not args.no_bluetooth:
                bluetooth = load_module("esp32_bluetooth", ROOT / "microcontroller" / "bluetooth.py")
                port = args.port if args.port is not None else bluetooth.PORT
                baud = args.baud if args.baud is not None else bluetooth.BAUD
                connection = resources.enter_context(bluetooth.BluetoothReceiver(port, baud))
                reader = resources.enter_context(MicrocontrollerAttacks(connection, args.attack_timeout))
                mode = f"ESP32 on {port}"
            else:
                mode = "Bluetooth disabled; movement only"
            camera = cv2.VideoCapture(args.camera)
            if not camera.isOpened():
                raise RuntimeError(f"Could not open camera {args.camera}")
            with PoseDetector(model_path) as detector:
                start = time.monotonic()
                last = set()
                print(f"Controller running; {mode}. Press q, Escape, or Ctrl+C to stop.")
                while True:
                    success, frame = camera.read()
                    if not success:
                        raise RuntimeError("Could not read a webcam frame")
                    timestamp_ms = int((time.monotonic() - start) * 1000)
                    result = detector.process_frame(frame, timestamp_ms)
                    pose = result.pose_landmarks[0] if result.pose_landmarks else None
                    movement = movement_input(detector, pose, timestamp_ms,
                                              (frame.shape[1], frame.shape[0]))
                    attacks = reader.held() if reader is not None else set()
                    held = movement | attacks
                    last = update_controller(controller, held, last)
                    write_cv_state(args.cv_state_out, movement, attacks, pose)
                    display = detector.draw_landmarks(frame, result)
                    label = " + ".join(sorted(held)) or "neutral"
                    cv2.putText(display, label, (10, 30), cv2.FONT_HERSHEY_SIMPLEX,
                                0.7, (0, 255, 0), 2)
                    cv2.imshow("SF6 Controller (q or Esc to quit)", display)
                    if cv2.waitKey(1) & 0xFF in (ord("q"), 27):
                        break
    except KeyboardInterrupt:
        pass
    finally:
        try:
            controller.apply(set())
        finally:
            if camera is not None:
                camera.release()
            cv2.destroyAllWindows()
        print("Released all inputs.")


if __name__ == "__main__":
    main()
