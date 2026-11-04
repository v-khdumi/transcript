"""Scoped test doubles at the external Speech SDK boundary."""

from contextlib import ExitStack, contextmanager
from types import SimpleNamespace
from unittest.mock import Mock, patch

# Import the real modules, but do not read a developer's local .env file.
# Configuration loading itself is tested separately with a controlled dotenv file.
with patch('dotenv.load_dotenv'):
    from transcript_app import transcriber
    from transcript_app.config import Settings


class Signal:
    def __init__(self):
        self.callbacks = []

    def connect(self, callback):
        self.callbacks.append(callback)

    def emit(self, event):
        for callback in list(self.callbacks):
            callback(event)


def result_event(speaker_id, text, reason=None):
    if reason is None:
        reason = transcriber.speechsdk.ResultReason.RecognizedSpeech
    return SimpleNamespace(
        result=SimpleNamespace(speaker_id=speaker_id, text=text, reason=reason)
    )


@contextmanager
def sdk_harness(settings=None):
    if settings is None:
        settings = Settings('test-key', 'westeurope', None, 'ro-RO')
    configuration = SimpleNamespace()
    audio = object()
    start_future = Mock(name='start_future')
    stop_future = Mock(name='stop_future')
    engine = SimpleNamespace(
        transcribing=Signal(),
        transcribed=Signal(),
        session_started=Signal(),
        session_stopped=Signal(),
        canceled=Signal(),
        start_transcribing_async=Mock(return_value=start_future),
        stop_transcribing_async=Mock(return_value=stop_future),
    )
    with ExitStack() as stack:
        config_factory = stack.enter_context(
            patch.object(transcriber.speechsdk, 'SpeechConfig', return_value=configuration)
        )
        audio_factory = stack.enter_context(
            patch.object(transcriber.speechsdk.audio, 'AudioConfig', return_value=audio)
        )
        engine_factory = stack.enter_context(
            patch.object(
                transcriber.speechsdk.transcription,
                'ConversationTranscriber',
                return_value=engine,
            )
        )
        service = transcriber.ConversationTranscriberService(settings)
        yield SimpleNamespace(
            service=service,
            engine=engine,
            configuration=configuration,
            audio=audio,
            config_factory=config_factory,
            audio_factory=audio_factory,
            engine_factory=engine_factory,
            start_future=start_future,
            stop_future=stop_future,
        )
