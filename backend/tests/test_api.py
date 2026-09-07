import sys
import tempfile
import unittest
from pathlib import Path
from queue import Queue

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.service import SessionService


class Source:
    def __init__(self):
        self.events = Queue()

    def start(self):
        self.events.put(('final', 'Guest-1', 'Hello'))

    def stop(self):
        pass


class ApiTests(unittest.TestCase):
    token = 'fixture-only-not-a-real-secret-0123456789'

    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.service = SessionService(Source, directory.name)
        self.client = self.enterContext(TestClient(create_app(self.service, self.token), base_url='http://localhost'))
        self.headers = {'Authorization': 'Bearer ' + self.token}

    def test_all_session_operations_require_authentication(self):
        for method, route, body in [('GET', '/api/session', None), ('POST', '/api/session/start', {'participant_names': []}), ('PATCH', '/api/session/speaker', {'speaker_id': 'x', 'new_name': 'y'}), ('POST', '/api/session/stop', None)]:
            response = self.client.request(method, route, json=body)
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers['cache-control'], 'no-store')
        self.assertFalse(self.service.snapshot().running)

    def test_http_start_snapshot_rename_stop_matches_contract(self):
        started = self.client.post('/api/session/start', json={'participant_names': ['Ana']}, headers=self.headers)
        self.assertEqual(started.status_code, 200)
        self.assertTrue(started.json()['running'])
        self.assertEqual(started.json()['speakers'], {'Guest-1': 'Ana'})
        conflict = self.client.post('/api/session/start', json={'participant_names': []}, headers=self.headers)
        self.assertEqual(conflict.status_code, 409)
        renamed = self.client.patch('/api/session/speaker', json={'speaker_id': 'Guest-1', 'new_name': 'Maria'}, headers=self.headers)
        self.assertEqual(renamed.json()['entries'][0]['speaker'], 'Maria')
        stopped = self.client.post('/api/session/stop', headers=self.headers)
        self.assertFalse(stopped.json()['running'])
        self.assertTrue(Path(stopped.json()['saved']['json_path']).exists())
        self.assertEqual(self.client.get('/api/session', headers=self.headers).json(), stopped.json())

    def test_invalid_host_and_request_fields_are_rejected(self):
        self.assertEqual(self.client.get('/api/session', headers={**self.headers, 'Host': 'attacker.example'}).status_code, 400)
        self.assertEqual(self.client.post('/api/session/start', json={'participant_names': [], 'token': 'not allowed'}, headers=self.headers).status_code, 422)
        self.assertEqual(self.client.get('/docs', headers=self.headers).status_code, 404)

    def test_short_token_prevents_startup(self):
        with self.assertRaises(RuntimeError):
            with TestClient(create_app(token='short'), base_url='http://localhost'):
                pass