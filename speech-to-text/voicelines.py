import io
import os
from pathlib import Path
from dotenv import load_dotenv
import difflib
import numpy as np
import sounddevice as sd
import soundfile as sf
from elevenlabs.client import ElevenLabs

load_dotenv(Path(__file__).resolve().parents[1] / ".env")
API_KEY = os.getenv("API_KEY")
if not API_KEY:
    raise RuntimeError("Set API_KEY in the repository-root .env file or environment.")
client = ElevenLabs(api_key=API_KEY)

DURATION = 3
SAMPLE_RATE = 16000

print(f"\n[Listening for {DURATION}s...] Say 'Hadouken' into your mic!")
audio = sd.rec(int(DURATION * SAMPLE_RATE), samplerate=SAMPLE_RATE, channels=1, dtype='int16')
sd.wait()
print("Transcribing with ElevenLabs Scribe...")

buf = io.BytesIO()
sf.write(buf, audio, SAMPLE_RATE, format='WAV', subtype='PCM_16')
buf.seek(0)

result = client.speech_to_text.convert(
    file=buf,
    model_id="scribe_v2",
    language_code="eng"
)

transcription = result.text.strip()
print(f"\nRaw Transcription: \"{transcription}\"")

# Classifier
words = transcription.lower().split()
has_hadouken = (
    "hadouken" in transcription.lower() 
    or "hadoken" in transcription.lower() 
    or bool(difflib.get_close_matches("hadouken", words, cutoff=0.7))
)

if has_hadouken:
    print(">>> CLASSIFICATION: SUCCESS (HADOUKEN DETECTED!) <<<")
else:
    print(">>> CLASSIFICATION: UNKNOWN COMMAND <<<")