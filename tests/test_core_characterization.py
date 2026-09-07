import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime
from unittest.mock import patch

with patch('dotenv.load_dotenv'):
    from transcript_app.config import load_settings

from transcript_app import session_store
from transcript_app.speaker_mapping import SpeakerMapper


class SettingsTests(unittest.TestCase):
    def load(self, values):
        with patch.dict(os.environ, values, clear=True):
            return load_settings()

    def test_import_requests_dotenv_loading_without_arguments(self):
        script = (
            'from unittest.mock import patch\n'
            'with patch("dotenv.load_dotenv") as load:\n'
            '    import transcript_app.config\n'
            '    load.assert_called_once_with()\n'
        )
        result = subprocess.run(
            [sys.executable, '-B', '-c', script],
            cwd=Path(__file__).resolve().parents[1],
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_missing_or_empty_key_has_priority_over_location_validation(self):
        for values in ({}, {'AZURE_SPEECH_KEY': ''}):
            with self.subTest(values=values):
                with self.assertRaises(RuntimeError) as caught:
                    self.load(values)
                self.assertEqual(
                    str(caught.exception),
                    'AZURE_SPEECH_KEY lipsește. Configurează cheia resursei Azure AI Foundry '
                    'Speech în fișierul .env (vezi .env.example).',
                )

    def test_key_requires_region_or_endpoint(self):
        for extra in ({}, {'AZURE_SPEECH_REGION': '', 'AZURE_SPEECH_ENDPOINT': ''}):
            with self.subTest(extra=extra):
                with self.assertRaises(RuntimeError) as caught:
                    self.load({'AZURE_SPEECH_KEY': 'test-only-key', **extra})
                self.assertEqual(
                    str(caught.exception),
                    'Trebuie setat AZURE_SPEECH_REGION sau AZURE_SPEECH_ENDPOINT în .env.',
                )

    def test_region_configuration_defaults_to_romanian(self):
        settings = self.load({
            'AZURE_SPEECH_KEY': 'test-only-key',
            'AZURE_SPEECH_REGION': 'test-region',
        })
        self.assertEqual(settings.speech_key, 'test-only-key')
        self.assertEqual(settings.speech_region, 'test-region')
        self.assertIsNone(settings.speech_endpoint)
        self.assertEqual(settings.language, 'ro-RO')

    def test_endpoint_only_and_coexisting_locations_are_preserved(self):
        for extra in ({}, {'AZURE_SPEECH_REGION': 'test-region'}):
            with self.subTest(extra=extra):
                settings = self.load({
                    'AZURE_SPEECH_KEY': 'test-only-key',
                    'AZURE_SPEECH_ENDPOINT': 'https://speech.example.invalid',
                    'AZURE_SPEECH_LANGUAGE': 'en-GB',
                    **extra,
                })
                self.assertEqual(settings.speech_endpoint, 'https://speech.example.invalid')
                self.assertEqual(settings.speech_region, extra.get('AZURE_SPEECH_REGION'))
                self.assertEqual(settings.language, 'en-GB')

    def test_explicit_empty_language_is_not_replaced_by_default(self):
        settings = self.load({
            'AZURE_SPEECH_KEY': 'test-only-key',
            'AZURE_SPEECH_REGION': 'test-region',
            'AZURE_SPEECH_LANGUAGE': '',
        })
        self.assertEqual(settings.language, '')


class SpeakerMapperTests(unittest.TestCase):
    def test_names_are_trimmed_and_assigned_in_first_seen_order(self):
        mapper = SpeakerMapper(['  Ana ', '', '  ', 'Ștefan'])
        self.assertEqual(mapper.resolve('Guest-9'), 'Ana')
        self.assertEqual(mapper.resolve('Guest-9'), 'Ana')
        self.assertEqual(mapper.resolve('Guest-2'), 'Ștefan')
        self.assertEqual(mapper.resolve('Guest-1'), 'Guest-1')
        self.assertEqual(mapper.known_speaker_ids(), ['Guest-9', 'Guest-2', 'Guest-1'])

    def test_no_names_and_empty_identifier_fall_back_to_identifier(self):
        for names in (None, []):
            with self.subTest(names=names):
                mapper = SpeakerMapper(names)
                self.assertEqual(mapper.resolve('Guest-1'), 'Guest-1')
                self.assertEqual(mapper.resolve(''), '')

    def test_duplicate_participant_names_are_not_deduplicated(self):
        mapper = SpeakerMapper(['Ana', 'Ana'])
        self.assertEqual(mapper.resolve('A'), 'Ana')
        self.assertEqual(mapper.resolve('B'), 'Ana')
        self.assertEqual(mapper.resolve('C'), 'C')

    def test_rename_is_trimmed_and_blank_rename_is_ignored(self):
        mapper = SpeakerMapper(['Ana'])
        mapper.resolve('A')
        mapper.resolve('B')
        mapper.rename('A', '  Ioana  ')
        mapper.rename('A', '  ')
        self.assertEqual(mapper.resolve('A'), 'Ioana')
        self.assertEqual(mapper.known_speaker_ids(), ['A', 'B'])

    def test_renaming_unknown_id_does_not_consume_a_participant_name(self):
        mapper = SpeakerMapper(['Ana'])
        mapper.rename('X', 'Moderator')
        mapper.rename('ignored', ' ')
        self.assertEqual(mapper.resolve('X'), 'Moderator')
        self.assertEqual(mapper.resolve('Y'), 'Ana')
        self.assertEqual(mapper.known_speaker_ids(), ['X', 'Y'])

    def test_returned_collections_are_defensive_snapshots(self):
        mapper = SpeakerMapper(['Ana'])
        mapper.resolve('A')
        mapping = mapper.mapping()
        ids = mapper.known_speaker_ids()
        mapping['A'] = 'Changed externally'
        ids.append('B')
        self.assertEqual(mapper.mapping(), {'A': 'Ana'})
        self.assertEqual(mapper.known_speaker_ids(), ['A'])


class SessionStoreTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name) / 'nested' / 'transcripts'
        self.store = session_store.SessionStore(str(self.directory))
        clock = patch.object(session_store, 'datetime')
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5)
        self.entries = [
            {'time': '03:04:01', 'speaker_id': 'Guest-1', 'speaker': 'Ștefan',
             'text': 'Bună, țară!'},
            {'time': '03:04:02', 'speaker_id': 'Guest-2', 'speaker': 'Ana',
             'text': 'Linia 1\nLinia 2'},
        ]
        self.mapping = {'Guest-1': 'Ștefan', 'Guest-2': 'Ana'}

    def test_default_output_directory_remains_transcripts(self):
        self.assertEqual(session_store.SessionStore().output_dir, 'transcripts')

    def test_save_exports_complete_unicode_json_and_ordered_plain_text(self):
        original = copy.deepcopy((self.entries, self.mapping))
        json_path, txt_path = self.store.save(self.entries, self.mapping)
        self.assertEqual(json_path, str(self.directory / 'transcript_20260102_030405.json'))
        self.assertEqual(txt_path, str(self.directory / 'transcript_20260102_030405.txt'))
        expected = {'speakers': self.mapping, 'entries': self.entries}
        raw = Path(json_path).read_text(encoding='utf-8')
        self.assertEqual(json.loads(raw), expected)
        self.assertEqual(raw, json.dumps(expected, ensure_ascii=False, indent=2))
        self.assertIn('Ștefan', raw)
        self.assertEqual(
            Path(txt_path).read_text(encoding='utf-8'),
            '[03:04:01] Ștefan: Bună, țară!\n[03:04:02] Ana: Linia 1\nLinia 2\n',
        )
        self.assertEqual((self.entries, self.mapping), original)

    def test_store_itself_accepts_empty_sessions(self):
        json_path, txt_path = self.store.save([], {})
        self.assertEqual(
            json.loads(Path(json_path).read_text(encoding='utf-8')),
            {'speakers': {}, 'entries': []},
        )
        self.assertEqual(Path(txt_path).read_text(encoding='utf-8'), '')

    def test_same_second_save_follows_explicitly_approved_collision_policy(self):
        first_paths = self.store.save(self.entries, self.mapping)
        first_contents = [Path(value).read_bytes() for value in first_paths]
        second_paths = self.store.save([], {'Guest-1': 'Renamed'})
        if os.environ.get('MODERNIZE_VERIFICATION_VARIANT') == 'baseline':
            self.assertEqual(second_paths, first_paths)
        else:
            self.assertNotEqual(second_paths, first_paths)
            self.assertEqual(Path(second_paths[0]).stem, Path(first_paths[0]).stem + '_1')
            self.assertEqual(Path(second_paths[1]).stem, Path(first_paths[1]).stem + '_1')
            self.assertEqual([Path(value).read_bytes() for value in first_paths], first_contents)
            third_paths = self.store.save(self.entries, self.mapping)
            self.assertEqual(Path(third_paths[0]).stem, Path(first_paths[0]).stem + '_2')
            self.assertEqual(Path(third_paths[1]).stem, Path(first_paths[1]).stem + '_2')
            self.assertEqual([Path(value).read_bytes() for value in first_paths], first_contents)
        self.assertEqual(
            json.loads(Path(second_paths[0]).read_text(encoding='utf-8')),
            {'speakers': {'Guest-1': 'Renamed'}, 'entries': []},
        )
        self.assertEqual(Path(second_paths[1]).read_text(encoding='utf-8'), '')

    def test_directory_and_write_failures_are_not_swallowed(self):
        with patch.object(session_store.os, 'makedirs', side_effect=PermissionError('directory denied')):
            with self.assertRaisesRegex(PermissionError, 'directory denied'):
                self.store.save(self.entries, self.mapping)
        with patch('builtins.open', side_effect=OSError('write denied')):
            with self.assertRaisesRegex(OSError, 'write denied'):
                self.store.save(self.entries, self.mapping)


if __name__ == '__main__':
    unittest.main()
