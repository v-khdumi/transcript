"""Contracts shared by the original implementation and the refactored candidate.

Direct discovery defaults to candidate dependency expectations. For baseline
runs, use verify_variant.py baseline or set MODERNIZE_VERIFICATION_VARIANT=baseline.
TRANSCRIPT_ACCEPTANCE_VARIANT remains a compatibility fallback.
"""

import dataclasses
import json
import os
from pathlib import Path
import queue
import runpy
import subprocess
import sys
import tempfile
import types
import unittest
from datetime import datetime
from unittest.mock import Mock, patch

import dotenv

from tests.modernization.support import Settings, result_event, sdk_harness, transcriber
from transcript_app import session_store
from transcript_app.session_store import SessionStore
from transcript_app.speaker_mapping import SpeakerMapper


ROOT = Path(__file__).resolve().parents[2]
FIXED_TIME = datetime(2025, 1, 2, 3, 4, 5)


class ConfigurationCharacterizationTests(unittest.TestCase):
    def load(self, environment, dotenv_text=''):
        real_load = dotenv.load_dotenv
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / '.env'
            path.write_text(dotenv_text, encoding='utf-8')
            with patch.dict(os.environ, environment, clear=True):
                with patch(
                    'dotenv.load_dotenv',
                    side_effect=lambda: real_load(dotenv_path=path),
                ) as loader:
                    namespace = runpy.run_path(str(ROOT / 'transcript_app/config.py'))
                    loader.assert_called_once_with()
                    return dataclasses.asdict(namespace['load_settings']())

    def test_dotenv_defaults_and_environment_precedence(self):
        actual = self.load(
            {'AZURE_SPEECH_KEY': 'process-test-key'},
            'AZURE_SPEECH_KEY=file-test-key\nAZURE_SPEECH_REGION=westeurope\n',
        )
        self.assertEqual(actual, {
            'speech_key': 'process-test-key',
            'speech_region': 'westeurope',
            'speech_endpoint': None,
            'language': 'ro-RO',
        })

    def test_values_are_not_trimmed_and_empty_language_is_preserved(self):
        self.assertEqual(self.load({
            'AZURE_SPEECH_KEY': ' test-key ',
            'AZURE_SPEECH_REGION': '',
            'AZURE_SPEECH_ENDPOINT': 'https://example.invalid/speech',
            'AZURE_SPEECH_LANGUAGE': '',
        }), {
            'speech_key': ' test-key ',
            'speech_region': '',
            'speech_endpoint': 'https://example.invalid/speech',
            'language': '',
        })
        self.assertEqual(self.load({
            'AZURE_SPEECH_KEY': 'test-key',
            'AZURE_SPEECH_REGION': ' ',
            'AZURE_SPEECH_LANGUAGE': 'en-US',
        })['speech_region'], ' ')

    def test_missing_and_empty_key_errors_are_exact(self):
        expected = (
            'AZURE_SPEECH_KEY lipsește. Configurează cheia resursei Azure AI Foundry '
            'Speech în fișierul .env (vezi .env.example).'
        )
        for environment in ({}, {'AZURE_SPEECH_KEY': ''}):
            with self.assertRaises(RuntimeError) as raised:
                self.load(environment)
            self.assertEqual(str(raised.exception), expected)

    def test_missing_and_empty_location_errors_are_exact(self):
        for environment in (
            {'AZURE_SPEECH_KEY': 'test-key'},
            {'AZURE_SPEECH_KEY': 'test-key', 'AZURE_SPEECH_REGION': '', 'AZURE_SPEECH_ENDPOINT': ''},
        ):
            with self.assertRaises(RuntimeError) as raised:
                self.load(environment)
            self.assertEqual(
                str(raised.exception),
                'Trebuie setat AZURE_SPEECH_REGION sau AZURE_SPEECH_ENDPOINT în .env.',
            )


class SpeechBoundaryCharacterizationTests(unittest.TestCase):
    def assert_connected(self, engine):
        for name in ('transcribing', 'transcribed', 'session_started', 'session_stopped', 'canceled'):
            callbacks = getattr(engine, name).callbacks
            self.assertEqual(len(callbacks), 1, name)
            self.assertTrue(callable(callbacks[0]), name)

    def test_endpoint_precedes_region_and_start_does_not_wait(self):
        settings = Settings('test-key', 'ignored-region', 'https://example.invalid/speech', 'en-US')
        with sdk_harness(settings) as harness:
            harness.engine.start_transcribing_async.side_effect = (
                lambda: (self.assert_connected(harness.engine), harness.start_future)[1]
            )
            harness.service.start()
            harness.config_factory.assert_called_once_with(
                endpoint='https://example.invalid/speech', subscription='test-key'
            )
            self.assertEqual(harness.configuration.speech_recognition_language, 'en-US')
            harness.audio_factory.assert_called_once_with(use_default_microphone=True)
            harness.engine_factory.assert_called_once_with(
                speech_config=harness.configuration, audio_config=harness.audio
            )
            harness.engine.start_transcribing_async.assert_called_once_with()
            self.assertEqual(harness.start_future.mock_calls, [])
            self.assertIsInstance(harness.service.events, queue.Queue)
            self.assertTrue(harness.service.events.empty())

    def test_empty_endpoint_uses_region_and_empty_language_survives(self):
        with sdk_harness(Settings('test-key', 'westeurope', '', '')) as harness:
            harness.service.start()
            harness.config_factory.assert_called_once_with(subscription='test-key', region='westeurope')
            self.assertEqual(harness.configuration.speech_recognition_language, '')

    def test_registered_callbacks_filter_results_and_preserve_exact_tuples(self):
        with sdk_harness() as harness:
            harness.service.start()
            self.assert_connected(harness.engine)
            harness.engine.session_started.emit(object())
            harness.engine.transcribing.emit(result_event('Guest-2', ''))
            harness.engine.transcribing.emit(result_event('Guest-2', ' Bună '))
            harness.engine.transcribed.emit(result_event('Guest-2', ''))
            harness.engine.transcribed.emit(result_event(
                'Guest-2', 'not recognized', transcriber.speechsdk.ResultReason.NoMatch
            ))
            harness.engine.transcribed.emit(result_event('Guest-2', 'Bună ziua!'))
            harness.engine.canceled.emit(types.SimpleNamespace(
                cancellation_details=types.SimpleNamespace(reason='Error', error_details='synthetic detail')
            ))
            harness.engine.session_stopped.emit(object())
            expected = [
                ('status', 'Sesiune pornită'),
                ('partial', 'Guest-2', ' Bună '),
                ('final', 'Guest-2', 'Bună ziua!'),
                ('error', 'Error: synthetic detail'),
                ('status', 'Sesiune oprită'),
            ]
            self.assertEqual([harness.service.events.get_nowait() for _ in expected], expected)
            with self.assertRaises(queue.Empty):
                harness.service.events.get_nowait()

    def test_stop_before_start_is_inert_and_successful_stop_waits_once(self):
        with sdk_harness() as harness:
            harness.service.stop()
            harness.engine.stop_transcribing_async.assert_not_called()
            harness.service.start()
            harness.stop_future.get.side_effect = lambda: self.assertIs(
                harness.service._transcriber, harness.engine
            )
            harness.service.stop()
            harness.engine.stop_transcribing_async.assert_called_once_with()
            harness.stop_future.get.assert_called_once_with()
            self.assertIsNone(harness.service._transcriber)
            harness.service.stop()
            harness.engine.stop_transcribing_async.assert_called_once_with()
            harness.stop_future.get.assert_called_once_with()

    def test_failed_stop_propagates_and_retains_reference_for_retry(self):
        with sdk_harness() as harness:
            harness.service.start()
            error = RuntimeError('synthetic stop failure')
            harness.stop_future.get.side_effect = error
            with self.assertRaises(RuntimeError) as raised:
                harness.service.stop()
            self.assertIs(raised.exception, error)
            self.assertIs(harness.service._transcriber, harness.engine)
            harness.stop_future.get.side_effect = None
            harness.service.stop()
            self.assertIsNone(harness.service._transcriber)
            self.assertEqual(harness.stop_future.get.call_count, 2)

    def test_start_failures_propagate_without_waiting(self):
        with sdk_harness() as harness:
            error = RuntimeError('synthetic configuration failure')
            harness.config_factory.side_effect = error
            with self.assertRaises(RuntimeError) as raised:
                harness.service.start()
            self.assertIs(raised.exception, error)
            harness.audio_factory.assert_not_called()
            harness.engine_factory.assert_not_called()
            self.assertIsNone(harness.service._transcriber)
        with sdk_harness() as harness:
            error = RuntimeError('synthetic start failure')
            harness.engine.start_transcribing_async.side_effect = error
            with self.assertRaises(RuntimeError) as raised:
                harness.service.start()
            self.assertIs(raised.exception, error)
            self.assertIs(harness.service._transcriber, harness.engine)
            self.assert_connected(harness.engine)
            self.assertEqual(harness.start_future.mock_calls, [])


class SpeakerCharacterizationTests(unittest.TestCase):
    def test_assignment_is_ordered_stable_and_uses_fallback_ids(self):
        mapper = SpeakerMapper([' Ana ', '', '  ', 'Bogdan'])
        self.assertEqual(mapper.resolve('Guest-2'), 'Ana')
        self.assertEqual(mapper.resolve('Guest-2'), 'Ana')
        self.assertEqual(mapper.resolve('Guest-1'), 'Bogdan')
        self.assertEqual(mapper.resolve('Guest-3'), 'Guest-3')
        self.assertEqual(mapper.known_speaker_ids(), ['Guest-2', 'Guest-1', 'Guest-3'])
        snapshot = mapper.mapping()
        snapshot['Guest-2'] = 'outside mutation'
        self.assertEqual(mapper.resolve('Guest-2'), 'Ana')
        ids = mapper.known_speaker_ids()
        ids.clear()
        self.assertEqual(len(mapper.known_speaker_ids()), 3)

    def test_rename_trims_ignores_blanks_and_does_not_consume_participant_names(self):
        mapper = SpeakerMapper(['Ana'])
        mapper.rename('unknown', '  Ștefan  ')
        mapper.rename('unknown', '  ')
        mapper.rename('ignored', '')
        self.assertEqual(mapper.resolve('unknown'), 'Ștefan')
        self.assertEqual(mapper.resolve('Guest-1'), 'Ana')
        self.assertEqual(mapper.mapping(), {'unknown': 'Ștefan', 'Guest-1': 'Ana'})
        self.assertEqual(SpeakerMapper().resolve('Guest-9'), 'Guest-9')


class SessionFileCharacterizationTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.output = Path(self.directory.name) / 'nested' / 'exports'
        self.store = SessionStore(str(self.output))
        clock = patch.object(session_store, 'datetime')
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.now.return_value = FIXED_TIME

    def test_exact_paths_unicode_bytes_order_and_extra_fields(self):
        entries = [
            {'time': '03:04:05', 'speaker_id': 'Guest-2', 'speaker': 'Ștefana', 'text': 'Bună ziua!', 'confidence': 0.75},
            {'time': '03:04:06', 'speaker_id': 'Guest-1', 'speaker': 'Bogdan', 'text': 'Da.'},
        ]
        speakers = {'Guest-2': 'Ștefana', 'Guest-1': 'Bogdan'}
        original_entries = json.loads(json.dumps(entries))
        json_path, txt_path = self.store.save(entries, speakers)
        self.assertIsInstance(json_path, str)
        self.assertIsInstance(txt_path, str)
        self.assertEqual(json_path, str(self.output / 'transcript_20250102_030405.json'))
        self.assertEqual(txt_path, str(self.output / 'transcript_20250102_030405.txt'))
        expected_json = '''{
  "speakers": {
    "Guest-2": "Ștefana",
    "Guest-1": "Bogdan"
  },
  "entries": [
    {
      "time": "03:04:05",
      "speaker_id": "Guest-2",
      "speaker": "Ștefana",
      "text": "Bună ziua!",
      "confidence": 0.75
    },
    {
      "time": "03:04:06",
      "speaker_id": "Guest-1",
      "speaker": "Bogdan",
      "text": "Da."
    }
  ]
}'''
        expected_txt = '[03:04:05] Ștefana: Bună ziua!\n[03:04:06] Bogdan: Da.\n'
        # Existing text-mode writes use the host platform's newline convention.
        self.assertEqual(Path(json_path).read_bytes(), expected_json.replace('\n', os.linesep).encode('utf-8'))
        self.assertEqual(Path(txt_path).read_bytes(), expected_txt.replace('\n', os.linesep).encode('utf-8'))
        self.assertEqual(json.loads(Path(json_path).read_text(encoding='utf-8')), {
            'speakers': speakers, 'entries': entries,
        })
        self.assertEqual(entries, original_entries)
        self.assertEqual(speakers, {'Guest-2': 'Ștefana', 'Guest-1': 'Bogdan'})
        self.assertEqual(SessionStore().output_dir, 'transcripts')

    def test_same_second_overwrites_and_direct_empty_save_is_supported(self):
        first = self.store.save([
            {'time': '03:04:05', 'speaker_id': 'Guest-1', 'speaker': 'Ana', 'text': 'Old content'}
        ], {'Guest-1': 'Ana'})
        second = self.store.save([], {})
        self.assertEqual(first, second)
        self.assertEqual(sorted(path.name for path in self.output.iterdir()), [
            'transcript_20250102_030405.json', 'transcript_20250102_030405.txt',
        ])
        self.assertEqual(Path(second[0]).read_bytes(), '{\n  "speakers": {},\n  "entries": []\n}'.replace('\n', os.linesep).encode('utf-8'))
        self.assertEqual(Path(second[1]).read_bytes(), b'')

    def test_filesystem_and_serialization_errors_propagate(self):
        error = PermissionError('synthetic write denial')
        with patch('builtins.open', side_effect=error):
            with self.assertRaises(PermissionError) as raised:
                self.store.save([], {})
        self.assertIs(raised.exception, error)
        blocker = Path(self.directory.name) / 'not-a-directory'
        blocker.write_text('blocker', encoding='utf-8')
        with self.assertRaises(OSError):
            SessionStore(str(blocker / 'child')).save([], {})
        with self.assertRaises(TypeError):
            self.store.save([{'not_serializable': object()}], {})


class RuntimeAndSecurityCharacterizationTests(unittest.TestCase):
    def test_entry_point_invokes_gui_run_once(self):
        fake_gui = types.ModuleType('transcript_app.gui')
        fake_gui.run = Mock()
        with patch.dict(sys.modules, {'transcript_app.gui': fake_gui}):
            runpy.run_path(str(ROOT / 'main.py'), run_name='__main__')
        fake_gui.run.assert_called_once_with()

    def test_dependency_pins_ignore_rules_and_privacy_guidance_are_preserved(self):
        # The security handoff authorizes only this candidate dotenv pin change.
        # Select expectations explicitly, never by inspecting actual dependencies.
        expected_requirements = {
            'baseline': 'azure-cognitiveservices-speech==1.42.0\npython-dotenv==1.0.1',
            'candidate': 'azure-cognitiveservices-speech==1.42.0\npython-dotenv==1.2.2',
        }
        variant = os.environ.get(
            'MODERNIZE_VERIFICATION_VARIANT',
            os.environ.get('TRANSCRIPT_ACCEPTANCE_VARIANT', 'candidate'),
        )
        self.assertIn(variant, expected_requirements, 'Unknown acceptance variant')
        self.assertEqual((ROOT / 'requirements.txt').read_text(encoding='utf-8'),
                         expected_requirements[variant])
        rules = (ROOT / '.gitignore').read_text(encoding='utf-8').splitlines()
        self.assertIn('.env', rules)
        self.assertIn('transcripts/', rules)
        self.assertNotIn('!.env', rules)
        self.assertNotIn('!transcripts/', rules)
        readme = (ROOT / 'README.md').read_text(encoding='utf-8')
        self.assertIn('Python 3.11+', readme)
        self.assertIn('pip install -r requirements.txt', readme)
        self.assertIn('Verifică politica organizației / consimțământul participanților', readme)
        self.assertIn('Audio-ul este trimis către serviciul Azure AI Speech', readme)

    def test_license_is_unchanged(self):
        expected = '''MIT License

Copyright (c) 2025 ariqbasyar

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.'''
        self.assertEqual((ROOT / 'LICENSE').read_bytes(), expected.encode('utf-8'))

    def test_installed_dependency_consistency(self):
        result = subprocess.run(
            [sys.executable, '-m', 'pip', 'check'],
            cwd=ROOT, capture_output=True, text=True, timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_native_sdk_and_tk_imports_in_a_fresh_process(self):
        result = subprocess.run(
            [sys.executable, '-c',
             'import tkinter; import azure.cognitiveservices.speech as sdk; '
             'assert callable(sdk.transcription.ConversationTranscriber); '
             'assert callable(tkinter.Tk)'],
            cwd=ROOT, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
