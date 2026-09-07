import contextlib
import importlib.util
import io
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

root = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(root))
spec = importlib.util.spec_from_file_location('preflight', root / 'ops/cloud/preflight.py')
preflight = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preflight)


class PreflightTests(unittest.TestCase):
    def check(self, side_effect, expected_code, expected_outcome):
        output = io.StringIO()
        with patch('transcript_app.config.load_settings', side_effect=side_effect), contextlib.redirect_stdout(output):
            self.assertEqual(preflight.main(), expected_code)
        report = json.loads(output.getvalue())
        self.assertEqual(report['outcome'], expected_outcome)
        self.assertEqual(report['scope'], 'configuration_only')
        self.assertEqual(report['event'], 'transcript.configuration_preflight')
        self.assertGreaterEqual(report['duration_ms'], 0)
        self.assertNotIn('sensitive-secret', output.getvalue())

    def test_valid_configuration_is_not_claimed_as_cloud_health(self):
        self.check(None, 0, 'ready')

    def test_invalid_configuration_returns_one_without_secret(self):
        self.check(RuntimeError('sensitive-secret'), 1, 'not_ready')

    def test_unexpected_failure_returns_two_without_secret(self):
        self.check(ValueError('sensitive-secret'), 2, 'error')