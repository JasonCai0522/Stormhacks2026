"""Voice input tests without microphone access or API requests."""

from contextlib import ExitStack
import os
import unittest
from unittest.mock import MagicMock, Mock, patch

import run_controller

voice = run_controller.load_module(
    "test_voice_commands", run_controller.ROOT / "speech-to-text" / "voicelines.py"
)


class VoiceInputTests(unittest.TestCase):
    def test_commands_and_unknown_speech(self):
        for text in ("Hadouken!", "HADOKEN", "hadoukan"):
            self.assertEqual(voice.classify_command(text), "hadouken")
        for text in ("light", "medium", "heavy", "special", "light then heavy", "Shoryuken"):
            self.assertIsNone(voice.classify_command(text))
        self.assertIsNone(voice.classify_command("hello there"))
        self.assertIsNone(voice.classify_command(""))

    def test_missing_key_skips_worker_and_optional_dependencies(self):
        with patch.dict(os.environ, {}, clear=True), \
                patch("dotenv.load_dotenv"), \
                patch.dict("sys.modules", {"elevenlabs": None, "sounddevice": None}), \
                patch.object(voice, "VoiceCommands") as worker, \
                patch.object(run_controller, "load_module", return_value=voice), \
                ExitStack() as resources:
            self.assertIsNone(run_controller.start_voice_input(resources, 0.25))
            worker.assert_not_called()

    def test_api_key_alias_and_environment_precedence(self):
        with patch("dotenv.load_dotenv"), patch.dict(os.environ, {"API_KEY": " legacy "}, clear=True):
            self.assertEqual(voice.get_api_key(), "legacy")
            os.environ["ELEVENLABS_API_KEY"] = " preferred "
            self.assertEqual(voice.get_api_key(), "preferred")
            os.environ["ELEVENLABS_API_KEY"] = "   "
            self.assertEqual(voice.get_api_key(), "legacy")

    def test_press_starts_when_consumed_and_expires(self):
        reader = voice.VoiceCommands("unused", timeout=0.25)
        reader.pending.put("hadouken")
        with patch.object(voice.time, "monotonic", side_effect=[100.0, 100.2, 100.25]):
            self.assertEqual(reader.held(), {"special"})
            self.assertEqual(reader.held(), {"special"})
            self.assertEqual(reader.held(), set())

    def test_disabled_worker_releases_pending_attack(self):
        reader = voice.VoiceCommands("unused")
        reader.pending.put("hadouken")
        reader.stop.set()
        self.assertEqual(reader.held(), set())

    def test_transcription_queues_command_and_microphone_failure_disables_voice(self):
        import numpy as np

        reader = voice.VoiceCommands("unused")
        client = Mock()
        client.speech_to_text.convert.return_value.text = "Hadouken!"
        with patch.object(reader, "_record", side_effect=[np.full((10, 1), 1000, dtype=np.int16), OSError()]), \
                patch("elevenlabs.client.ElevenLabs", return_value=client), \
                patch("builtins.print"):
            reader._listen()
        self.assertEqual(reader.pending.get_nowait(), "hadouken")
        self.assertTrue(reader.stop.is_set())
        self.assertEqual(reader.held(), set())
        client.speech_to_text.convert.assert_called_once()

    def test_shutdown_during_request_drops_result(self):
        import numpy as np

        reader = voice.VoiceCommands("unused")
        client = Mock()
        def convert(**kwargs):
            reader.stop.set()
            return Mock(text="Hadouken")
        client.speech_to_text.convert.side_effect = convert
        with patch.object(reader, "_record", return_value=np.full((10, 1), 1000, dtype=np.int16)), \
                patch("elevenlabs.client.ElevenLabs", return_value=client):
            reader._listen()
        self.assertTrue(reader.pending.empty())

    def test_silence_does_not_call_api(self):
        import numpy as np

        reader = voice.VoiceCommands("unused")
        client = Mock()
        def next_record(*args):
            if next_record.called:
                reader.stop.set()
            next_record.called = True
            return np.zeros((10, 1), dtype=np.int16)
        next_record.called = False
        with patch.object(reader, "_record", side_effect=next_record), \
                patch("elevenlabs.client.ElevenLabs", return_value=client):
            reader._listen()
        client.speech_to_text.convert.assert_not_called()

    def test_recording_closes_microphone_when_stopped(self):
        import numpy as np

        reader = voice.VoiceCommands("unused")
        sd = Mock()
        stream_context = MagicMock()
        sd.InputStream.return_value = stream_context
        def read(frames):
            reader.stop.set()
            return np.zeros((frames, 1), dtype=np.int16), False
        stream_context.__enter__.return_value.read.side_effect = read
        self.assertIsNone(reader._record(sd, np))
        stream_context.__exit__.assert_called_once()

    def test_controller_context_starts_and_stops_voice_worker(self):
        reader = voice.VoiceCommands("unused")
        with patch.object(reader.thread, "start") as start, \
                patch.object(reader.thread, "join") as join, \
                patch.object(voice, "get_api_key", return_value="unused"), \
                patch.object(voice, "VoiceCommands", return_value=reader), \
                patch.object(run_controller, "load_module", return_value=voice):
            with ExitStack() as resources:
                self.assertIs(run_controller.start_voice_input(resources, 0.25), reader)
                start.assert_called_once()
                self.assertFalse(reader.stop.is_set())
            self.assertTrue(reader.stop.is_set())
            join.assert_called_once()


if __name__ == "__main__":
    unittest.main()
