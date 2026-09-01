"""Real-time speech transcription with speaker diarization via Azure AI Foundry Speech.

Uses the Azure Cognitive Services Speech SDK's ConversationTranscriber, which
streams microphone audio and returns partial/final results already attributed
to speakers (e.g. "Guest-1", "Guest-2") without any extra offline model.
"""

import queue

import azure.cognitiveservices.speech as speechsdk

from .config import Settings


class ConversationTranscriberService:
    def __init__(self, settings: Settings):
        self._settings = settings
        self._transcriber: speechsdk.transcription.ConversationTranscriber | None = None
        # Cross-thread queue: Azure SDK callbacks fire on background threads.
        self.events: "queue.Queue[tuple]" = queue.Queue()

    def _build_speech_config(self) -> speechsdk.SpeechConfig:
        if self._settings.speech_endpoint:
            speech_config = speechsdk.SpeechConfig(
                endpoint=self._settings.speech_endpoint,
                subscription=self._settings.speech_key,
            )
        else:
            speech_config = speechsdk.SpeechConfig(
                subscription=self._settings.speech_key,
                region=self._settings.speech_region,
            )
        speech_config.speech_recognition_language = self._settings.language
        return speech_config

    def start(self) -> None:
        speech_config = self._build_speech_config()
        audio_config = speechsdk.audio.AudioConfig(use_default_microphone=True)

        self._transcriber = speechsdk.transcription.ConversationTranscriber(
            speech_config=speech_config, audio_config=audio_config
        )

        self._transcriber.transcribing.connect(self._on_transcribing)
        self._transcriber.transcribed.connect(self._on_transcribed)
        self._transcriber.session_started.connect(lambda evt: self.events.put(("status", "Sesiune pornită")))
        self._transcriber.session_stopped.connect(lambda evt: self.events.put(("status", "Sesiune oprită")))
        self._transcriber.canceled.connect(self._on_canceled)

        self._transcriber.start_transcribing_async()

    def stop(self) -> None:
        if self._transcriber is not None:
            self._transcriber.stop_transcribing_async().get()
            self._transcriber = None

    def _on_transcribing(self, evt) -> None:
        # Interim (not-yet-final) result, useful for a live "typing" preview.
        if evt.result.text:
            self.events.put(("partial", evt.result.speaker_id, evt.result.text))

    def _on_transcribed(self, evt) -> None:
        if evt.result.reason == speechsdk.ResultReason.RecognizedSpeech and evt.result.text:
            self.events.put(("final", evt.result.speaker_id, evt.result.text))

    def _on_canceled(self, evt) -> None:
        details = evt.cancellation_details
        self.events.put(("error", f"{details.reason}: {details.error_details}"))
