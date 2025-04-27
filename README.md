# Speech-to-Text & Speaker Diarization with Whisper and pyannote

This project records audio from your microphone, transcribes it using OpenAI's Whisper, and performs speaker diarization using pyannote-audio. It supports multiple languages (e.g., English, Arabic), and prints out who spoke when, along with the transcribed text. The code also measures and prints the time taken for each major step.

---

## Features

- Record audio from your microphone
- Transcribe speech to text using Whisper (offline, free)
- Perform speaker diarization (who spoke when) using pyannote-audio
- Supports multiple languages (set in code)
- Prints diarized, speaker-attributed transcripts
- Measures and prints timing for each processing step

---

## Requirements

- Python 3.11 (tested)
- [ffmpeg](https://ffmpeg.org/) (required by Whisper, install via `brew install ffmpeg` on macOS)
- A HuggingFace account and access token (for pyannote-audio diarization)

---

## Installation

We recommend using a virtual environment.

1. **Clone the repository:**
    ```bash
    git clone https://github.com/ariqbasyar/speech-to-text-whisper.git
    cd speech-to-text-whisper
    ```

2. **Create and activate a virtual environment:**
    ```bash
    python -m venv env
    source env/bin/activate  # On Windows use `env\Scripts\activate`
    ```

3. **Install the required packages:**
    ```bash
    pip install -r requirements.txt
    ```

4. **Install ffmpeg (if not already installed):**
    - On macOS: `brew install ffmpeg`
    - On Ubuntu: `sudo apt install ffmpeg`
    - On Windows: [Download and add to PATH](https://ffmpeg.org/download.html)

5. **Set your HuggingFace token:**
    - Create a `.env` file in the project root with:
      ```
      HUGGINGFACE_TOKEN=your_huggingface_token_here
      ```

---

## Usage

1. **Run the program:**
    ```bash
    python main.py
    ```

2. **Follow the prompts:**
    - The program will record audio from your microphone for a set duration (default: 20 seconds).
    - It will then transcribe and diarize the audio, printing out the results with timing information.

---

## Customization

- **Change recording duration:**  
  Edit the `duration` parameter in `record_audio()` in `main.py`.
- **Change transcription language:**  
  Edit the `language` parameter in the `transcribe_audio()` function in `main.py` (e.g., `"en"` for English, `"ar"` for Arabic).
- **Change Whisper model:**  
  Edit the model name in `whisper.load_model()` (e.g., `"base"`, `"small"`, `"medium"`, `"large"`).

---

## Example Output

```
Recording for 20 seconds...
Recording finished!
record_audio took 20.01 seconds
save_audio_to_wav took 0.01 seconds
Transcribing...
Transcribed!
transcribe_audio took 4.12 seconds
Raw segments:
[0.0s - 2.0s]  Hello, how are you?
[2.0s - 5.0s]  I'm fine, thank you.
...

Diarization:
SPEAKER_00 [0.0s - 2.3s]
SPEAKER_01 [2.7s - 5.4s]

Transcribed segments:
SPEAKER_00 [0.0s - 2.3s]: Hello, how are you?
SPEAKER_01 [2.7s - 5.4s]: I'm fine, thank you.
...
```

---

## Tested Environment

- Python 3.11.6
- MacBook Air M3 (Apple Silicon)
- macOS

---

## Future Improvements

- Speaker identification (assign real names/roles to speakers)
- Web or GUI interface
- Export results to file (txt, csv, etc.)
- Word-level diarization

---

## License

MIT

---

## Acknowledgements

- [OpenAI Whisper](https://github.com/openai/whisper)
- [pyannote-audio](https://github.com/pyannote/pyannote-audio)
