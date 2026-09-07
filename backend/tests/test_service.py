import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from queue import Queue
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from backend.service import SessionService, SessionConflict, SessionUnavailable


class Source:
    def __init__(self):
        self.events = Queue()
        self.started = 0
        self.stopped = 0

    def start(self):
        self.started += 1

    def stop(self):
        self.stopped += 1
        self.events.put(('final', 'Guest-1', 'Final at stop'))


class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.source = Source()
        self.service = SessionService(lambda: self.source, self.directory.name,
                                      clock=lambda: datetime(2026, 1, 2, 3, 4, 5))

    def test_start_is_explicit_and_duplicate_start_conflicts(self):
        self.assertFalse(self.service.snapshot().running)
        self.assertEqual(self.source.started, 0)
        self.assertTrue(self.service.start(['Ana']).running)
        self.assertEqual(self.source.started, 1)
        with self.assertRaises(SessionConflict):
            self.service.start(['Other'])

    def test_partial_final_rename_stop_and_export_contract(self):
        self.service.start(['Ana'])
        self.source.events.put(('partial', 'Guest-1', 'Preview'))
        self.assertEqual(self.service.snapshot().partial.text, 'Preview')
        self.source.events.put(('final', 'Guest-1', 'Confirmed'))
        current = self.service.snapshot()
        self.assertIsNone(current.partial)
        self.assertEqual(current.entries[0].speaker, 'Ana')
        self.assertEqual(self.service.rename('Guest-1', ' Renamed ').entries[0].speaker, 'Renamed')
        stopped = self.service.stop()
        self.assertFalse(stopped.running)
        self.assertEqual([entry.text for entry in stopped.entries], ['Confirmed', 'Final at stop'])
        saved = json.loads(Path(stopped.saved.json_path).read_text(encoding='utf-8'))
        self.assertEqual(saved['speakers'], {'Guest-1': 'Renamed'})
        self.assertEqual(saved['entries'][0]['time'], '03:04:05')
        self.assertEqual(self.service.stop().saved, stopped.saved)
        self.assertEqual(self.source.stopped, 1)

    def test_failed_save_retains_entries_for_retry(self):
        store = Mock()
        store.save.side_effect = [OSError('private path'), ('saved.json', 'saved.txt')]
        service = SessionService(lambda: self.source, store_factory=lambda _: store)
        service.start([])
        with self.assertRaises(SessionUnavailable) as caught:
            service.stop()
        self.assertNotIn('private path', str(caught.exception))
        self.assertEqual(len(service.snapshot().entries), 1)
        with self.assertRaises(SessionConflict):
            service.start([])
        self.assertEqual(service.stop().saved.json_path, 'saved.json')

    def test_sdk_errors_do_not_expose_sensitive_details(self):
        self.service.start([])
        self.source.events.put(('error', 'secret-token resource-uri'))
        self.assertNotIn('secret-token', self.service.snapshot().status)

    def test_separate_sessions_use_separate_directories(self):
        self.service.start([])
        first = self.service.stop()
        self.service.start([])
        second = self.service.stop()
        self.assertNotEqual(first.session_id, second.session_id)
        self.assertNotEqual(first.saved.json_path, second.saved.json_path)
        self.assertTrue(Path(first.saved.json_path).exists())