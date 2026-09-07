import json
import os
from pathlib import Path
import queue
import runpy
import tempfile
from datetime import datetime
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, call, patch

with patch('dotenv.load_dotenv'):
    from transcript_app import gui, transcriber
    from transcript_app.config import Settings

from transcript_app.session_store import SessionStore
from transcript_app.speaker_mapping import SpeakerMapper


class Value:
    def __init__(self, value=''):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value


def make_controller():
    app = gui.TranscriptApp.__new__(gui.TranscriptApp)
    app.root = Mock()
    app.service = None
    app.mapper = SpeakerMapper()
    app.entries = []
    app.session_store = Mock()
    app._has_partial = False
    app.names_var = Value()
    app.status_var = Value('Pregătit.')
    app.speaker_id_var = Value()
    app.new_name_var = Value()
    app.names_entry = Mock()
    app.start_button = Mock()
    app.stop_button = Mock()
    app.transcript_text = Mock()
    app.speaker_id_menu = {'menu': Mock()}
    return app


class GuiControllerTests(unittest.TestCase):
    def setUp(self):
        self.app = make_controller()
        self.settings = Settings('test-only-key', 'test-region', None, 'ro-RO')
        self.load = self.patch(gui, 'load_settings', return_value=self.settings)
        self.factory = self.patch(gui, 'ConversationTranscriberService')
        self.dialog = self.patch(gui.messagebox, 'showerror')
        self.clock = self.patch(gui, 'datetime')
        self.clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5)

    def patch(self, target, attribute, **kwargs):
        patcher = patch.object(target, attribute, **kwargs)
        result = patcher.start()
        self.addCleanup(patcher.stop)
        return result

    def test_configuration_error_leaves_existing_transcript_untouched(self):
        self.app.entries = [{'text': 'existing'}]
        self.load.side_effect = RuntimeError('missing settings')
        self.app.start_session()
        self.dialog.assert_called_once_with('Configurare lipsă', 'missing settings')
        self.assertEqual(self.app.entries, [{'text': 'existing'}])
        self.factory.assert_not_called()
        self.app.transcript_text.delete.assert_not_called()
        self.app.start_button.config.assert_not_called()

    def test_start_resets_session_and_sets_recording_controls(self):
        self.app.names_var.set(' Ana, , Ștefan ')
        self.app.entries = [{'text': 'old'}]
        self.app.mapper.resolve('old-id')
        self.app._has_partial = True
        self.app.start_session()
        self.factory.assert_called_once_with(self.settings)
        self.factory.return_value.start.assert_called_once_with()
        self.assertIs(self.app.service, self.factory.return_value)
        self.assertEqual(self.app.entries, [])
        self.assertFalse(self.app._has_partial)
        self.assertEqual(self.app.mapper.mapping(), {})
        self.assertEqual(self.app.mapper.resolve('A'), 'Ana')
        self.assertEqual(self.app.mapper.resolve('B'), 'Ștefan')
        self.app.transcript_text.delete.assert_called_once_with('1.0', gui.tk.END)
        self.app.names_entry.config.assert_called_once_with(state=gui.tk.DISABLED)
        self.app.start_button.config.assert_called_once_with(state=gui.tk.DISABLED)
        self.app.stop_button.config.assert_called_once_with(state=gui.tk.NORMAL)
        self.assertEqual(self.app.status_var.get(), 'Se înregistrează... vorbește în microfon.')

    def test_immediate_start_failure_displays_error_and_clears_service(self):
        self.factory.return_value.start.side_effect = RuntimeError('microphone unavailable')
        self.app.start_session()
        self.dialog.assert_called_once_with('Eroare la pornire', 'microphone unavailable')
        self.assertIsNone(self.app.service)
        self.app.names_entry.config.assert_not_called()
        self.app.start_button.config.assert_not_called()
        self.app.stop_button.config.assert_not_called()

    def test_service_constructor_error_currently_propagates(self):
        self.factory.side_effect = RuntimeError('constructor failed')
        with self.assertRaisesRegex(RuntimeError, 'constructor failed'):
            self.app.start_session()
        self.dialog.assert_not_called()

    def test_stop_saves_final_entries_and_current_mapping(self):
        service = Mock()
        self.app.service = service
        self.app.mapper.resolve('A')
        self.app.entries = [{'time': '03:04:05', 'speaker_id': 'A', 'speaker': 'A', 'text': 'Final'}]
        self.app.session_store.save.return_value = ('session.json', 'session.txt')
        self.app.stop_session()
        service.stop.assert_called_once_with()
        self.assertIsNone(self.app.service)
        self.app.session_store.save.assert_called_once_with(self.app.entries, {'A': 'A'})
        self.app.names_entry.config.assert_called_once_with(state=gui.tk.NORMAL)
        self.app.start_button.config.assert_called_once_with(state=gui.tk.NORMAL)
        self.app.stop_button.config.assert_called_once_with(state=gui.tk.DISABLED)
        self.assertEqual(self.app.status_var.get(), 'Salvat: session.txt')

    def test_stop_without_finals_does_not_save_a_partial_preview(self):
        self.app._show_partial('A', 'unfinished')
        self.app.stop_session()
        self.app.session_store.save.assert_not_called()
        self.assertEqual(self.app.entries, [])
        self.assertEqual(self.app.status_var.get(), 'Sesiune oprită (nimic de salvat).')

    def test_stop_and_save_errors_currently_propagate(self):
        service = Mock()
        self.app.service = service
        service.stop.side_effect = RuntimeError('stop failed')
        with self.assertRaisesRegex(RuntimeError, 'stop failed'):
            self.app.stop_session()
        self.assertIs(self.app.service, service)
        self.app.session_store.save.assert_not_called()
        service.stop.side_effect = None
        self.app.entries = [{'text': 'final'}]
        self.app.session_store.save.side_effect = OSError('disk full')
        with self.assertRaisesRegex(OSError, 'disk full'):
            self.app.stop_session()
        self.assertIsNone(self.app.service)

    def test_stop_does_not_drain_finals_queued_during_stop(self):
        service = Mock()
        service.events = queue.Queue()
        service.stop.side_effect = lambda: service.events.put(('final', 'A', 'late final'))
        self.app.service = service
        self.app.stop_session()
        self.assertIsNone(self.app.service)
        self.assertEqual(self.app.entries, [])
        self.app.session_store.save.assert_not_called()
        self.assertEqual(service.events.get_nowait(), ('final', 'A', 'late final'))

    def test_poll_drains_fifo_queue_and_schedules_next_poll(self):
        self.app.service = Mock()
        self.app.service.events = queue.Queue()
        events = [('status', 'ready'), ('partial', 'A', 'pre'), ('final', 'A', 'final')]
        for event in events:
            self.app.service.events.put(event)
        with patch.object(self.app, '_handle_event') as handle:
            self.app._poll_events()
        self.assertEqual(handle.call_args_list, [call(event) for event in events])
        self.assertTrue(self.app.service.events.empty())
        self.app.root.after.assert_called_once_with(100, self.app._poll_events)

    def test_idle_poll_is_still_scheduled(self):
        self.app._poll_events()
        self.app.root.after.assert_called_once_with(100, self.app._poll_events)

    def test_status_error_and_unknown_event_routing(self):
        self.app._handle_event(('status', 'Sesiune pornită'))
        self.assertEqual(self.app.status_var.get(), 'Sesiune pornită')
        self.app._handle_event(('error', 'cancelled'))
        self.assertEqual(self.app.status_var.get(), 'Eroare: cancelled')
        self.app._handle_event(('unknown', 'ignored'))
        self.assertEqual(self.app.status_var.get(), 'Eroare: cancelled')
        self.assertEqual(self.app.entries, [])

    def test_partial_is_preview_only_and_final_creates_timestamped_entry(self):
        self.app.mapper = SpeakerMapper(['Ana'])
        self.app._handle_event(('partial', 'A', 'Bun'))
        self.assertEqual(self.app.entries, [])
        self.assertTrue(self.app._has_partial)
        self.app.transcript_text.mark_set.assert_called_once_with('partial_start', 'end-1c')
        self.app.transcript_text.mark_gravity.assert_called_once_with('partial_start', gui.tk.LEFT)
        self.app._handle_event(('final', 'A', 'Bună'))
        self.assertEqual(self.app.entries, [
            {'time': '03:04:05', 'speaker_id': 'A', 'speaker': 'Ana', 'text': 'Bună'},
        ])
        self.assertFalse(self.app._has_partial)
        self.app.transcript_text.delete.assert_called_with('partial_start', 'end-1c')
        self.app.transcript_text.config.assert_called_with(state=gui.tk.DISABLED)

    def test_speaker_menu_labels_and_callbacks_keep_distinct_identifiers(self):
        self.app.mapper = SpeakerMapper(['Ana', 'Ștefan'])
        self.app.mapper.resolve('Guest-9')
        self.app.mapper.resolve('Guest-2')
        self.app._refresh_speaker_menu()
        menu = self.app.speaker_id_menu['menu']
        menu.delete.assert_called_once_with(0, gui.tk.END)
        commands = menu.add_command.call_args_list
        self.assertEqual([item.kwargs['label'] for item in commands], [
            'Guest-9 (Ana)', 'Guest-2 (Ștefan)',
        ])
        self.assertEqual(self.app.speaker_id_var.get(), 'Guest-9')
        commands[1].kwargs['command']()
        self.assertEqual(self.app.speaker_id_var.get(), 'Guest-2')
        commands[0].kwargs['command']()
        self.assertEqual(self.app.speaker_id_var.get(), 'Guest-9')

    def test_rename_updates_all_matching_entries_and_clears_partial(self):
        self.app._add_final('A', 'first')
        self.app._add_final('B', 'other')
        self.app._add_final('A', 'second')
        self.app._show_partial('A', 'unfinished')
        self.app.speaker_id_var.set('A')
        self.app.new_name_var.set('  Ioana  ')
        self.app._rename_speaker()
        self.assertEqual([entry['speaker'] for entry in self.app.entries], ['Ioana', 'B', 'Ioana'])
        self.assertEqual(self.app.mapper.mapping(), {'A': 'Ioana', 'B': 'B'})
        self.assertEqual(self.app.new_name_var.get(), '')
        self.assertFalse(self.app._has_partial)
        self.app.transcript_text.delete.assert_called_with('1.0', gui.tk.END)

    def test_blank_rename_inputs_are_noops(self):
        for identifier, name in (('', 'Ana'), ('A', '  ')):
            with self.subTest(identifier=identifier, name=name):
                self.app.speaker_id_var.set(identifier)
                self.app.new_name_var.set(name)
                with patch.object(self.app, '_redraw_transcript') as redraw:
                    self.app._rename_speaker()
                redraw.assert_not_called()
                self.assertEqual(self.app.mapper.mapping(), {})

    def test_close_stops_service_and_destroys_window_without_saving(self):
        service = Mock()
        self.app.service = service
        self.app.entries = [{'text': 'unsaved final'}]
        order = Mock()
        order.attach_mock(service.stop, 'stop')
        order.attach_mock(self.app.root.destroy, 'destroy')
        self.app.on_close()
        self.assertEqual(order.mock_calls, [call.stop(), call.destroy()])
        self.app.session_store.save.assert_not_called()

    def test_idle_close_destroys_window(self):
        self.app.on_close()
        self.app.root.destroy.assert_called_once_with()
        self.app.session_store.save.assert_not_called()


class CallbackToExportIntegrationTests(unittest.TestCase):
    def test_sdk_callbacks_flow_through_controller_mapping_and_exports(self):
        app = make_controller()
        app.names_var.set(' Ana, Ștefan ')
        sdk = Mock()
        environment = {
            'AZURE_SPEECH_KEY': 'test-only-key',
            'AZURE_SPEECH_REGION': 'test-region',
        }
        with tempfile.TemporaryDirectory() as directory:
            app.session_store = SessionStore(directory)
            with patch.dict(os.environ, environment, clear=True), \
                    patch.object(transcriber.speechsdk, 'SpeechConfig') as config_factory, \
                    patch.object(transcriber.speechsdk.audio, 'AudioConfig') as audio_factory, \
                    patch.object(transcriber.speechsdk.transcription, 'ConversationTranscriber', return_value=sdk), \
                    patch.object(gui, 'datetime') as clock, \
                    patch.object(gui.messagebox, 'showerror') as dialog:
                clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5)
                app.start_session()
                service = app.service
                self.assertIsInstance(service, transcriber.ConversationTranscriberService)
                config_factory.assert_called_once_with(subscription='test-only-key', region='test-region')
                audio_factory.assert_called_once_with(use_default_microphone=True)

                def emit(signal, speaker_id, text):
                    callback = getattr(sdk, signal).connect.call_args.args[0]
                    callback(SimpleNamespace(result=SimpleNamespace(
                        speaker_id=speaker_id,
                        text=text,
                        reason=transcriber.speechsdk.ResultReason.RecognizedSpeech,
                    )))

                sdk.session_started.connect.call_args.args[0](object())
                emit('transcribing', 'Guest-9', 'preview only')
                emit('transcribed', 'Guest-9', 'Bună ziua!')
                emit('transcribed', 'Guest-2', 'Mulțumesc.')
                app._poll_events()
                self.assertTrue(service.events.empty())
                self.assertEqual(app.status_var.get(), 'Sesiune pornită')
                self.assertEqual([entry['speaker'] for entry in app.entries], ['Ana', 'Ștefan'])
                app.speaker_id_var.set('Guest-9')
                app.new_name_var.set('  Ioana  ')
                app._rename_speaker()
                app.stop_session()
                sdk.stop_transcribing_async.return_value.get.assert_called_once_with()
                self.assertIsNone(service._transcriber)
                self.assertIsNone(app.service)
                dialog.assert_not_called()

            json_files = list(Path(directory).glob('*.json'))
            txt_files = list(Path(directory).glob('*.txt'))
            self.assertEqual(len(json_files), 1)
            self.assertEqual(len(txt_files), 1)
            self.assertEqual(json.loads(json_files[0].read_text(encoding='utf-8')), {
                'speakers': {'Guest-9': 'Ioana', 'Guest-2': 'Ștefan'},
                'entries': [
                    {'time': '03:04:05', 'speaker_id': 'Guest-9', 'speaker': 'Ioana', 'text': 'Bună ziua!'},
                    {'time': '03:04:05', 'speaker_id': 'Guest-2', 'speaker': 'Ștefan', 'text': 'Mulțumesc.'},
                ],
            })
            self.assertEqual(
                txt_files[0].read_text(encoding='utf-8'),
                '[03:04:05] Ioana: Bună ziua!\n[03:04:05] Ștefan: Mulțumesc.\n',
            )
            self.assertEqual(app.status_var.get(), f'Salvat: {txt_files[0]}')


class EntryPointTests(unittest.TestCase):
    def test_gui_run_registers_close_handler_and_enters_mainloop(self):
        with patch.object(gui.tk, 'Tk') as root_factory, \
                patch.object(gui, 'TranscriptApp') as app_factory:
            gui.run()
        root_factory.assert_called_once_with()
        app_factory.assert_called_once_with(root_factory.return_value)
        root_factory.return_value.protocol.assert_called_once_with(
            'WM_DELETE_WINDOW', app_factory.return_value.on_close,
        )
        root_factory.return_value.mainloop.assert_called_once_with()

    def test_main_launches_only_when_executed_as_entry_point(self):
        main_path = Path(__file__).resolve().parents[1] / 'main.py'
        with patch.object(gui, 'run') as run:
            runpy.run_path(str(main_path), run_name='imported_main')
            run.assert_not_called()
            runpy.run_path(str(main_path), run_name='__main__')
            run.assert_called_once_with()


if __name__ == '__main__':
    unittest.main()
