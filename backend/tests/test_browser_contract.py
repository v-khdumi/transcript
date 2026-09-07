import sys
import tempfile
import unittest
from pathlib import Path
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from fastapi.testclient import TestClient
from backend.api import create_app
from backend.service import SessionService
from backend.ui_api import BrowserSessions
from test_api import Source


class BrowserContractTests(unittest.TestCase):
    def setUp(self):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        self.service = SessionService(Source, directory.name)
        token = 'fixture-only-not-a-real-secret-0123456789'
        self.client = self.enterContext(TestClient(create_app(self.service, token), base_url='http://localhost'))
        self.headers = {'Authorization': 'Bearer ' + token, 'X-Transcript-Client': 'browser', 'Origin': 'http://127.0.0.1:5173'}
        self.url = '/api/ui/sessions/' + str(uuid4())

    def mutate(self, action, body=None, request_id=None):
        return self.client.post(self.url + '/' + action, json=body or {}, headers={**self.headers, 'X-Request-ID': request_id or str(uuid4())})

    def test_frontend_routes_snapshot_and_monotonic_revisions(self):
        idle = self.client.get(self.url, headers=self.headers).json()
        self.assertEqual(idle['phase'], 'idle')
        self.assertEqual(idle['speakers'], [])
        request_id = str(uuid4())
        start = self.mutate('start', {'participant_names': ['Ana']}, request_id).json()
        self.assertEqual(start['phase'], 'recording')
        self.assertEqual(start['speakers'], [{'id': 'Guest-1', 'name': 'Ana'}])
        self.assertGreater(start['revision'], idle['revision'])
        repeat = self.mutate('start', {'participant_names': ['Ana']}, request_id)
        self.assertEqual(repeat.status_code, 200)
        renamed = self.mutate('rename', {'speaker_id': 'Guest-1', 'new_name': 'Maria'}).json()
        self.assertEqual(renamed['entries'][0]['speaker'], 'Maria')
        stopped = self.mutate('stop').json()
        self.assertEqual(stopped['phase'], 'stopped')
        self.assertGreater(stopped['revision'], renamed['revision'])
        self.assertTrue(Path(stopped['saved']['json_path']).exists())

    def test_close_stops_without_saving_and_denies_other_sessions(self):
        self.mutate('start', {'participant_names': []})
        other = self.client.get('/api/ui/sessions/' + str(uuid4()), headers=self.headers)
        self.assertEqual(other.status_code, 409)
        self.assertEqual(self.client.get('/api/session', headers=self.headers).status_code, 409)
        closed = self.mutate('close').json()
        self.assertEqual(closed['phase'], 'stopped')
        self.assertIsNone(closed['saved'])
        self.assertFalse(self.service.snapshot().running)

    def test_browser_auth_origin_and_payload_are_enforced(self):
        self.assertEqual(self.client.get(self.url).status_code, 401)
        self.assertEqual(self.client.get(self.url, headers={**self.headers, 'Origin': 'http://evil.example'}).status_code, 403)
        self.assertEqual(self.client.get(self.url, headers={'Authorization': self.headers['Authorization']}).status_code, 403)
        self.assertEqual(self.mutate('start', {'extra': True}).status_code, 422)
        self.assertEqual(self.client.post(self.url + '/stop', json={}, headers=self.headers).status_code, 400)

    def test_expired_lease_stops_microphone_without_saving(self):
        current = [0.0]
        sessions = BrowserSessions(self.service, clock=lambda: current[0])
        owner = str(uuid4())
        sessions.dispatch(owner, 'start', {'participant_names': []}, str(uuid4()))
        current[0] = 121
        sessions.expire()
        self.assertFalse(self.service.snapshot().running)
        self.assertIsNone(self.service.snapshot().saved)
        with self.assertRaises(Exception) as caught:
            sessions.dispatch(owner, 'read', {})
        self.assertEqual(caught.exception.status_code, 410)