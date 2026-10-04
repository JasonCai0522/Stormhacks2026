"""Optional background voice attacks for run_controller.py."""

import difflib
import io
import os
from pathlib import Path
from queue import Empty, Queue
import re
import threading
import time

DURATION = 3
SAMPLE_RATE = 16000
# Controller input names, interpreted by controller.py's resolve()/apply().
# Ryu/Ken Modern Hadouken is neutral + Special (default Xbox Y).
VOICE_COMMAND_CONTROLS = {
    "hadouken": frozenset({"special"}),
}
VOICE_COMMAND_ALIASES = {"hadoken": "hadouken"}


def get_api_key():
    from dotenv import load_dotenv

    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    return (os.getenv("ELEVENLABS_API_KEY") or "").strip() or (os.getenv("API_KEY") or "").strip()


def classify_command(transcription):
    """Return a mapped voice command; ignore other attack names."""
    command = None
    for word in re.findall(r"[a-z]+", transcription.lower()):
        name = VOICE_COMMAND_ALIASES.get(word, word)
        if name in VOICE_COMMAND_CONTROLS:
            command = name
        elif difflib.get_close_matches(name, ["hadouken"], n=1, cutoff=0.75):
            command = "hadouken"
    return command


class VoiceCommands:
    """Record/transcribe off the game loop and expose expiring attack presses."""

    def __init__(self, api_key, timeout=0.25):
        self.api_key = api_key
        self.timeout = timeout
        self.stop = threading.Event()
        self.pending = Queue(maxsize=1)
        self._attack = None
        self._expires_at = 0.0
        self.thread = threading.Thread(target=self._listen, daemon=True, name="voice-input")

    def _record(self, sd, np):
        # Small reads allow shutdown during recording. Close the microphone
        # before the HTTP request so audio cannot pile up while transcribing.
        blocks = []
        with sd.InputStream(samplerate=SAMPLE_RATE, channels=1, dtype="int16") as stream:
            for _ in range(DURATION * 10):
                if self.stop.is_set():
                    return None
                block, overflowed = stream.read(SAMPLE_RATE // 10)
                if overflowed:
                    return None
                blocks.append(block.copy())
        return np.concatenate(blocks)

    def _listen(self):
        try:
            import httpx
            import numpy as np
            import sounddevice as sd
            import soundfile as sf
            from elevenlabs.client import ElevenLabs

            with httpx.Client(timeout=10.0) as transport:
                client = ElevenLabs(api_key=self.api_key, timeout=10.0, httpx_client=transport)
                while not self.stop.is_set():
                    audio = self._record(sd, np)
                    if audio is None or self.stop.is_set():
                        continue
                    # Avoid sending silent recordings to the API.
                    if np.max(np.abs(audio.astype(np.int32))) < 300:
                        continue
                    with io.BytesIO() as buf:
                        sf.write(buf, audio, SAMPLE_RATE, format="WAV", subtype="PCM_16")
                        buf.seek(0)
                        result = client.speech_to_text.convert(
                            file=buf, model_id="scribe_v2", language_code="eng",
                            request_options={"max_retries": 0},
                        )
                    command = classify_command(result.text)
                    if command and not self.stop.is_set():
                        # Keep only the latest command, never replay a backlog.
                        try:
                            self.pending.get_nowait()
                        except Empty:
                            pass
                        self.pending.put_nowait(command)
                        print(f"[Voice] {command}")
        except Exception as exc:
            if not self.stop.is_set():
                print(f"Voice disabled: microphone/transcription failed ({type(exc).__name__}).")
            self.stop.set()

    def held(self):
        if self.stop.is_set():
            return set()
        now = time.monotonic()
        try:
            self._attack = self.pending.get_nowait()
            self._expires_at = now + self.timeout
        except Empty:
            pass
        if self._attack and now < self._expires_at:
            return set(VOICE_COMMAND_CONTROLS[self._attack])
        return set()

    def close(self):
        self.stop.set()
        self.thread.join(timeout=1)

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def main():
    api_key = get_api_key()
    if not api_key:
        print("Voice disabled: no ELEVENLABS_API_KEY or API_KEY in .env/environment.")
        return
    print("Listening for Hadouken. Ctrl+C to stop.")
    try:
        with VoiceCommands(api_key) as voice:
            while not voice.stop.wait(0.05):
                voice.held()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
