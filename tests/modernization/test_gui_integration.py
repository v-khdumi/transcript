"""Real-Tk integration across the desktop application's module boundaries.

A display is required (for example, an existing X server or Xvfb on Linux).
An unavailable display is an explicit test error, never skipped acceptance.
No microphone, Azure credentials or Azure network access are used.
"""

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import json
from pathlib import Path
import tempfile
import tkinter as tk
import unittest
from unittest.mock import Mock, patch

from tests.modernization.support import result_event, sdk_harness
from transcript_app import gui, session_store
from transcript_app.session_store import SessionStore


FIXED_TIME = datetime(2025, 1, 2, 3, 4, 5)


class DesktopIntegrationCharacterizationTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = tk.Tk()
        except tk.TclError as exc:
            raise RuntimeError(
                'BLOCKED: real-Tk characterization requires Tk and a working display; '
                'provide display access or run under Xvfb. No coverage was skipped.'
            ) from exc
        self.addCleanup(self.destroy_root)
        self.root.withdraw()
        scheduling = patch.object(self.root, 'after')
        self.after = scheduling.start()
        self.addCleanup(scheduling.stop)
        self.app = gui.TranscriptApp(self.root)
        self.after.assert_called_once_with(100, self.app._poll_events)
        self.after.reset_mock()
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.output = Path(temporary.name) / 'exports'
        self.app.session_store = SessionStore(str(self.output))
        for module in (gui, session_store):
            clock = patch.object(module, 'datetime')
            frozen = clock.start()
            self.addCleanup(clock.stop)
            frozen.now.return_value = FIXED_TIME

    def destroy_root(self):
        try:
            self.root.destroy()
        except tk.TclError:
            # on_close may already have destroyed this test's root.
            pass

    def text(self):
        return self.app.transcript_text.get('1.0', 'end-1c')

    def poll(self):
        self.after.reset_mock()
        self.app._poll_events()
        self.after.assert_called_once_with(100, self.app._poll_events)

    def assert_controls(self, recording):
        self.assertEqual(str(self.app.names_entry['state']), 'disabled' if recording else 'normal')
        self.assertEqual(str(self.app.start_button['state']), 'disabled' if recording else 'normal')
        self.assertEqual(str(self.app.stop_button['state']), 'normal' if recording else 'disabled')
        self.assertEqual(str(self.app.transcript_text['state']), 'disabled')

    def test_sdk_queue_to_widgets_rename_and_external_session_files(self):
        self.assert_controls(False)
        self.app.names_var.set(' Ana, , Bogdan ')
        with sdk_harness() as harness:
            with patch.object(gui, 'load_settings', return_value=harness.service._settings):
                with patch.object(gui, 'ConversationTranscriberService', return_value=harness.service):
                    self.app.start_session()
            self.assert_controls(True)
            self.assertEqual(self.app.status_var.get(), 'Se înregistrează... vorbește în microfon.')
            # SDK callbacks execute away from Tk's thread. Only polling may render.
            with ThreadPoolExecutor(max_workers=1) as executor:
                executor.submit(
                    harness.engine.transcribing.emit, result_event('Guest-2', 'Bun')
                ).result(timeout=10)
            self.assertEqual(self.text(), '')
            self.assertEqual(self.app.entries, [])
            self.poll()
            self.assertEqual(self.text(), 'Ana: Bun')
            self.assertEqual(self.app.transcript_text.mark_gravity('partial_start'), 'left')
            self.assertEqual(self.app.mapper.mapping(), {'Guest-2': 'Ana'})
            harness.engine.transcribing.emit(result_event('Guest-2', 'Bună'))
            self.poll()
            self.assertEqual(self.text(), 'Ana: Bună')
            self.assertEqual(self.app.entries, [])
            harness.engine.transcribed.emit(result_event('Guest-2', 'Bună ziua!'))
            self.poll()
            confirmed = '[03:04:05] Ana: Bună ziua!\n'
            self.assertEqual(self.text(), confirmed)
            self.assertFalse(self.app._has_partial)
            self.assertEqual(self.app.entries, [{
                'time': '03:04:05', 'speaker_id': 'Guest-2', 'speaker': 'Ana', 'text': 'Bună ziua!',
            }])
            harness.engine.transcribing.emit(result_event('Guest-1', 'Sa'))
            self.poll()
            harness.engine.transcribing.emit(result_event('Guest-1', 'Salut'))
            self.poll()
            self.assertEqual(self.text(), confirmed + 'Bogdan: Salut')
            self.assertEqual(len(self.app.entries), 1)
            self.app.speaker_id_var.set('Guest-2')
            self.app.new_name_var.set(' Ștefana ')
            self.app._rename_speaker()
            self.assertEqual(self.text(), '[03:04:05] Ștefana: Bună ziua!\n')
            self.assertFalse(self.app._has_partial)
            self.assertEqual(self.app.entries[0]['speaker'], 'Ștefana')
            self.assertEqual(self.app.new_name_var.get(), '')
            self.assertEqual(self.app.mapper.mapping(), {'Guest-2': 'Ștefana', 'Guest-1': 'Bogdan'})
            menu = self.app.speaker_id_menu['menu']
            self.assertEqual(menu.entrycget(0, 'label'), 'Guest-2 (Ștefana)')
            self.assertEqual(menu.entrycget(1, 'label'), 'Guest-1 (Bogdan)')
            harness.engine.transcribed.emit(result_event('Guest-1', 'Salut!'))
            self.poll()
            expected_entries = [
                {'time': '03:04:05', 'speaker_id': 'Guest-2', 'speaker': 'Ștefana', 'text': 'Bună ziua!'},
                {'time': '03:04:05', 'speaker_id': 'Guest-1', 'speaker': 'Bogdan', 'text': 'Salut!'},
            ]
            self.assertEqual(self.app.entries, expected_entries)
            self.assertEqual(self.text(), '[03:04:05] Ștefana: Bună ziua!\n[03:04:05] Bogdan: Salut!\n')
            # Preserve the existing no-drain stop contract, even with queued finals.
            harness.engine.transcribed.emit(result_event('Guest-3', 'queued but not polled'))
            real_save = self.app.session_store.save

            def save_after_stop(entries, mapping):
                harness.stop_future.get.assert_called_once_with()
                self.assertIsNone(self.app.service)
                self.assertEqual(entries, expected_entries)
                self.assertEqual(mapping, {'Guest-2': 'Ștefana', 'Guest-1': 'Bogdan'})
                return real_save(entries, mapping)

            with patch.object(self.app.session_store, 'save', side_effect=save_after_stop) as save:
                self.app.stop_session()
                save.assert_called_once_with(expected_entries, {'Guest-2': 'Ștefana', 'Guest-1': 'Bogdan'})
            self.assert_controls(False)
            self.assertIsNone(self.app.service)
            self.poll()
            self.assertEqual(harness.service.events.get_nowait(), ('final', 'Guest-3', 'queued but not polled'))
            self.assertTrue(harness.service.events.empty())
            json_path = self.output / 'transcript_20250102_030405.json'
            txt_path = self.output / 'transcript_20250102_030405.txt'
            # Read the files as external consumers; do not mock the persistence handoff.
            self.assertEqual(json.loads(json_path.read_text(encoding='utf-8')), {
                'speakers': {'Guest-2': 'Ștefana', 'Guest-1': 'Bogdan'},
                'entries': expected_entries,
            })
            self.assertEqual(txt_path.read_text(encoding='utf-8'),
                             '[03:04:05] Ștefana: Bună ziua!\n[03:04:05] Bogdan: Salut!\n')
            self.assertEqual(self.app.status_var.get(), f'Salvat: {txt_path}')

    def test_empty_stop_does_not_save_and_status_error_events_are_consumed(self):
        with sdk_harness() as harness:
            with patch.object(gui, 'load_settings', return_value=harness.service._settings):
                with patch.object(gui, 'ConversationTranscriberService', return_value=harness.service):
                    self.app.start_session()
            harness.engine.session_started.emit(object())
            self.poll()
            self.assertEqual(self.app.status_var.get(), 'Sesiune pornită')
            harness.service.events.put(('error', 'synthetic error'))
            self.poll()
            self.assertEqual(self.app.status_var.get(), 'Eroare: synthetic error')
            harness.engine.session_stopped.emit(object())
            self.poll()
            self.assertEqual(self.app.status_var.get(), 'Sesiune oprită')
            with patch.object(self.app.session_store, 'save') as save:
                self.app.stop_session()
                self.app.stop_session()
                save.assert_not_called()
            harness.stop_future.get.assert_called_once_with()
            self.assertIsNone(self.app.service)
            self.assertEqual(self.app.status_var.get(), 'Sesiune oprită (nimic de salvat).')
            self.assert_controls(False)
            self.assertFalse(self.output.exists())

    def test_close_stops_before_destroy_without_saving_or_draining(self):
        with sdk_harness() as harness:
            harness.service.start()
            self.app.service = harness.service
            self.app._handle_event(('final', 'Guest-1', 'Unsaved confirmed text'))
            harness.engine.transcribed.emit(result_event('Guest-1', 'pending'))
            real_destroy = self.root.destroy

            def destroy_after_stop():
                harness.stop_future.get.assert_called_once_with()
                real_destroy()

            with patch.object(self.app.session_store, 'save') as save:
                with patch.object(self.root, 'destroy', side_effect=destroy_after_stop) as destroy:
                    self.app.on_close()
                    destroy.assert_called_once_with()
                save.assert_not_called()
            self.assertEqual(harness.service.events.get_nowait(), ('final', 'Guest-1', 'pending'))
            self.assertEqual(len(self.app.entries), 1)
            self.assertFalse(self.output.exists())

    def test_start_configuration_and_service_failures_keep_idle_controls(self):
        self.app.entries = [{'text': 'existing entry'}]
        with patch.object(gui, 'load_settings', side_effect=RuntimeError('synthetic missing config')):
            with patch.object(gui.messagebox, 'showerror') as dialog:
                self.app.start_session()
                dialog.assert_called_once_with('Configurare lipsă', 'synthetic missing config')
        self.assertEqual(self.app.entries, [{'text': 'existing entry'}])
        self.assertIsNone(self.app.service)
        self.assert_controls(False)
        with sdk_harness() as harness:
            harness.engine.start_transcribing_async.side_effect = RuntimeError('synthetic start failure')
            with patch.object(gui, 'load_settings', return_value=harness.service._settings):
                with patch.object(gui, 'ConversationTranscriberService', return_value=harness.service):
                    with patch.object(gui.messagebox, 'showerror') as dialog:
                        self.app.start_session()
                        dialog.assert_called_once_with('Eroare la pornire', 'synthetic start failure')
            self.assertIsNone(self.app.service)
            self.assertEqual(self.app.entries, [])
            self.assert_controls(False)

    def test_blank_rename_is_inert_and_new_session_resets_confirmed_state(self):
        self.app._handle_event(('final', 'Guest-1', 'old text'))
        previous = self.text()
        self.app.speaker_id_var.set('Guest-1')
        self.app.new_name_var.set('  ')
        self.app._rename_speaker()
        self.assertEqual(self.text(), previous)
        self.assertEqual(self.app.mapper.mapping(), {'Guest-1': 'Guest-1'})
        self.app._handle_event(('partial', 'Guest-1', 'old preview'))
        self.app.names_var.set('Nou')
        with sdk_harness() as harness:
            with patch.object(gui, 'load_settings', return_value=harness.service._settings):
                with patch.object(gui, 'ConversationTranscriberService', return_value=harness.service):
                    self.app.start_session()
            self.assertEqual(self.text(), '')
            self.assertEqual(self.app.entries, [])
            self.assertEqual(self.app.mapper.mapping(), {})
            self.assertFalse(self.app._has_partial)
            harness.engine.transcribing.emit(result_event('Guest-9', 'preview'))
            self.poll()
            self.assertEqual(self.text(), 'Nou: preview')
            self.assertEqual(self.app.entries, [])
            with patch.object(self.app.session_store, 'save') as save:
                self.app.stop_session()
                save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
