import queue
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

with patch('dotenv.load_dotenv'):
    from transcript_app.config import Settings
    from transcript_app import transcriber


class TranscriberContractTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings('test-only-key', 'test-region', None, 'ro-RO')
        self.service = transcriber.ConversationTranscriberService(self.settings)
        self.config = Mock()
        self.audio = Mock()
        self.sdk_transcriber = Mock(spec=[
            'transcribing', 'transcribed', 'session_started', 'session_stopped',
            'canceled', 'start_transcribing_async', 'stop_transcribing_async',
        ])
        self.config_factory = self.patch(
            transcriber.speechsdk, 'SpeechConfig', return_value=self.config,
        )
        self.audio_factory = self.patch(
            transcriber.speechsdk.audio, 'AudioConfig', return_value=self.audio,
        )
        self.transcriber_factory = self.patch(
            transcriber.speechsdk.transcription, 'ConversationTranscriber',
            return_value=self.sdk_transcriber,
        )

    def patch(self, target, attribute, **kwargs):
        patcher = patch.object(target, attribute, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def event(self, text='Bună', speaker_id='Guest-1', reason=None):
        if reason is None:
            reason = transcriber.speechsdk.ResultReason.RecognizedSpeech
        return SimpleNamespace(result=SimpleNamespace(
            text=text, speaker_id=speaker_id, reason=reason,
        ))

    def drain(self):
        events = []
        while True:
            try:
                events.append(self.service.events.get_nowait())
            except queue.Empty:
                return events

    def emit(self, signal, event):
        connection = getattr(self.sdk_transcriber, signal).connect
        connection.assert_called_once()
        connection.call_args.args[0](event)

    def test_construction_has_no_sdk_side_effects(self):
        self.assertIsNone(self.service._transcriber)
        self.assertIsInstance(self.service.events, queue.Queue)
        self.assertEqual(self.drain(), [])
        self.config_factory.assert_not_called()
        self.audio_factory.assert_not_called()
        self.transcriber_factory.assert_not_called()

    def test_region_configuration_sets_language(self):
        result = self.service._build_speech_config()
        self.assertIs(result, self.config)
        self.config_factory.assert_called_once_with(
            subscription='test-only-key', region='test-region',
        )
        self.assertEqual(self.config.speech_recognition_language, 'ro-RO')

    def test_endpoint_takes_precedence_over_region(self):
        self.service = transcriber.ConversationTranscriberService(Settings(
            'test-only-key', 'test-region', 'https://speech.example.invalid', 'en-GB',
        ))
        self.service._build_speech_config()
        self.config_factory.assert_called_once_with(
            endpoint='https://speech.example.invalid', subscription='test-only-key',
        )
        self.assertEqual(self.config.speech_recognition_language, 'en-GB')

    def test_empty_endpoint_uses_region(self):
        self.service = transcriber.ConversationTranscriberService(Settings(
            'test-only-key', 'test-region', '', 'ro-RO',
        ))
        self.service._build_speech_config()
        self.config_factory.assert_called_once_with(
            subscription='test-only-key', region='test-region',
        )

    def test_start_wires_callbacks_and_does_not_wait_for_start_future(self):
        self.service.start()
        self.audio_factory.assert_called_once_with(use_default_microphone=True)
        self.transcriber_factory.assert_called_once_with(
            speech_config=self.config, audio_config=self.audio,
        )
        self.assertIs(self.service._transcriber, self.sdk_transcriber)
        self.sdk_transcriber.transcribing.connect.assert_called_once_with(self.service._on_transcribing)
        self.sdk_transcriber.transcribed.connect.assert_called_once_with(self.service._on_transcribed)
        self.sdk_transcriber.canceled.connect.assert_called_once_with(self.service._on_canceled)
        self.sdk_transcriber.start_transcribing_async.assert_called_once_with()
        self.sdk_transcriber.start_transcribing_async.return_value.get.assert_not_called()
        self.emit('session_started', object())
        self.emit('transcribing', self.event('Bun'))
        self.emit('transcribed', self.event('Bună'))
        self.emit('session_stopped', object())
        self.emit('canceled', SimpleNamespace(cancellation_details=SimpleNamespace(
            reason='Error', error_details='test cancellation',
        )))
        self.assertEqual(self.drain(), [
            ('status', 'Sesiune pornită'),
            ('partial', 'Guest-1', 'Bun'),
            ('final', 'Guest-1', 'Bună'),
            ('status', 'Sesiune oprită'),
            ('error', 'Error: test cancellation'),
        ])

    def test_partial_filters_empty_text_but_preserves_whitespace_and_identifier(self):
        self.service._on_transcribing(self.event(''))
        self.service._on_transcribing(self.event(' ', speaker_id=''))
        self.assertEqual(self.drain(), [('partial', '', ' ')])

    def test_final_requires_recognized_speech_and_nonempty_text(self):
        self.service._on_transcribed(self.event(''))
        self.service._on_transcribed(self.event(
            'unrecognized', reason=transcriber.speechsdk.ResultReason.NoMatch,
        ))
        self.service._on_transcribed(self.event(' ', speaker_id='Guest-7'))
        self.assertEqual(self.drain(), [('final', 'Guest-7', ' ')])

    def test_callbacks_deliver_ordered_events_from_worker_thread(self):
        def produce():
            for index in range(50):
                self.service._on_transcribed(self.event(str(index)))

        worker = threading.Thread(target=produce, daemon=True)
        worker.start()
        worker.join(timeout=5)
        self.assertFalse(worker.is_alive(), 'Callback worker did not finish')
        self.assertEqual(
            self.drain(),
            [('final', 'Guest-1', str(index)) for index in range(50)],
        )

    def test_stop_before_start_is_noop_and_repeated_stop_waits_only_once(self):
        self.service.stop()
        self.sdk_transcriber.stop_transcribing_async.assert_not_called()
        self.service.start()
        self.service.stop()
        self.service.stop()
        self.sdk_transcriber.stop_transcribing_async.assert_called_once_with()
        self.sdk_transcriber.stop_transcribing_async.return_value.get.assert_called_once_with()
        self.assertIsNone(self.service._transcriber)

    def test_stop_failure_propagates_and_retains_transcriber_reference(self):
        self.service.start()
        self.sdk_transcriber.stop_transcribing_async.return_value.get.side_effect = RuntimeError('stop failed')
        with self.assertRaisesRegex(RuntimeError, 'stop failed'):
            self.service.stop()
        self.assertIs(self.service._transcriber, self.sdk_transcriber)

    def test_configuration_failure_prevents_audio_and_transcriber_creation(self):
        self.config_factory.side_effect = RuntimeError('configuration failed')
        with self.assertRaisesRegex(RuntimeError, 'configuration failed'):
            self.service.start()
        self.audio_factory.assert_not_called()
        self.transcriber_factory.assert_not_called()
        self.assertIsNone(self.service._transcriber)

    def test_immediate_start_failure_propagates_after_handle_assignment(self):
        self.sdk_transcriber.start_transcribing_async.side_effect = RuntimeError('start failed')
        with self.assertRaisesRegex(RuntimeError, 'start failed'):
            self.service.start()
        self.assertIs(self.service._transcriber, self.sdk_transcriber)


if __name__ == '__main__':
    unittest.main()
