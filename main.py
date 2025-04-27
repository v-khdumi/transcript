import dotenv
import numpy as np
import os
import sounddevice as sd
import tempfile
import time
import torch
import wave
import whisper
import warnings
warnings.filterwarnings("ignore", message="FP16 is not supported on CPU; using FP32 instead")

from pprint import pprint
from pyannote.audio import Pipeline
from functools import wraps

dotenv.load_dotenv()

HUGGINGFACE_TOKEN = os.getenv("HUGGINGFACE_TOKEN")

def timing_decorator(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        start = time.perf_counter()
        result = func(*args, **kwargs)
        end = time.perf_counter()
        print(f"{func.__name__} took {end - start:.2f} seconds")
        return result
    return wrapper

@timing_decorator
def record_audio(duration=10, sample_rate=16000):
    print(f"Recording for {duration} seconds...")
    audio = sd.rec(int(duration * sample_rate), samplerate=sample_rate, channels=1, dtype='float32')
    sd.wait()
    print("Recording finished!")
    return audio

@timing_decorator
def save_audio_to_wav(audio, sample_rate=16000):
    # Create a temporary WAV file
    temp_file = tempfile.NamedTemporaryFile(suffix='.wav', delete=False)
    temp_filename = temp_file.name

    with wave.open(temp_filename, 'wb') as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 2 bytes per sample
        wf.setframerate(sample_rate)
        wf.writeframes((audio * 32767).astype(np.int16).tobytes())

    return temp_filename

@timing_decorator
def transcribe_audio(audio_file: str) -> list[dict]:
    # base is pretty good for english, at least small for arabic
    model = whisper.load_model("small")  # or "base", "small", "medium", "large"
    print("Transcribing...")
    result = model.transcribe(audio_file, language="ar")
    print("Transcribed!")
    return result["segments"]

def get_overlap_text(seg, turn):
    # Calculate overlap
    seg_start, seg_end = seg['start'], seg['end']
    turn_start, turn_end = turn.start, turn.end
    overlap_start = max(seg_start, turn_start)
    overlap_end = min(seg_end, turn_end)
    overlap = max(0.0, overlap_end - overlap_start)
    seg_duration = seg_end - seg_start
    if overlap <= 0 or seg_duration <= 0:
        return ""
    # Proportion of the segment that overlaps
    proportion = overlap / seg_duration
    # Approximate split of text
    words = seg['text'].split()
    n_words = max(1, int(len(words) * proportion))
    # If the turn starts after the segment, take from the end; else from the start
    if turn_start > seg_start:
        # Take from the end
        return " ".join(words[-n_words:])
    else:
        # Take from the start
        return " ".join(words[:n_words])

@timing_decorator
def get_diarization(audio_file: str):
    pipeline = Pipeline.from_pretrained(
        "pyannote/speaker-diarization-3.1",
        use_auth_token=HUGGINGFACE_TOKEN)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    print(f"Using device: {device}")
    pipeline.to(device)

    return pipeline(audio_file)

@timing_decorator
def main():

    # Record audio from microphone
    audio = record_audio(duration=20)  # Record for 10 seconds

    # Save the recorded audio to a temporary WAV file
    audio_file = save_audio_to_wav(audio)

    segments = transcribe_audio(audio_file)
    print("Raw segments:")
    for seg in segments:
        print(f"[{seg['start']:.1f}s - {seg['end']:.1f}s] {seg['text']}")
    print()

    try:
        # Apply pretrained pipeline
        diarization = get_diarization(audio_file)

        # For each diarization segment, print the text that overlaps
        print("Diarization:")
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            print(f"{speaker} [{turn.start:.1f}s - {turn.end:.1f}s]")
        print()

        print("Transcribed segments:")
        for turn, _, speaker in diarization.itertracks(yield_label=True):
            speaker_text = ""
            for seg in segments:
                if seg['end'] > turn.start and seg['start'] < turn.end:
                    speaker_text += get_overlap_text(seg, turn) + " "
            print(f"{speaker} [{turn.start:.1f}s - {turn.end:.1f}s]: {speaker_text.strip()}")
    finally:
        # Clean up the temporary file
        os.unlink(audio_file)

if __name__ == "__main__":
    main()
