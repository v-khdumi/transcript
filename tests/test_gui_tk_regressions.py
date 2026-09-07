from datetime import datetime
import unittest
from unittest.mock import Mock, patch

with patch('dotenv.load_dotenv'):
    from transcript_app import gui
    from transcript_app.config import Settings

from transcript_app.speaker_mapping import SpeakerMapper


class TkTranscriptRegressionTests(unittest.TestCase):
    def setUp(self):
        try:
            self.root = gui.tk.Tk()
        except gui.tk.TclError as exc:
            self.skipTest(f'Tk display unavailable: {exc}')
        self.root.withdraw()
        self.addCleanup(self.destroy_root)
        self.app = gui.TranscriptApp(self.root)
        self.app.mapper = SpeakerMapper(['Ana', 'Ștefan'])
        clock = patch.object(gui, 'datetime')
        self.clock = clock.start()
        self.addCleanup(clock.stop)
        self.clock.now.return_value = datetime(2026, 1, 2, 3, 4, 5)

    def destroy_root(self):
        for callback in self.root.tk.splitlist(self.root.tk.call('after', 'info')):
            self.root.after_cancel(callback)
        self.root.destroy()

    def contents(self):
        return self.app.transcript_text.get('1.0', 'end-1c')

    def test_initial_window_and_widget_states(self):
        self.assertEqual(
            self.root.title(),
            'Transcriere întâlniri în timp real (Azure AI Foundry Speech)',
        )
        self.assertEqual(self.app.status_var.get(), 'Pregătit.')
        self.assertEqual(str(self.app.start_button.cget('state')), gui.tk.NORMAL)
        self.assertEqual(str(self.app.stop_button.cget('state')), gui.tk.DISABLED)
        self.assertEqual(str(self.app.transcript_text.cget('state')), gui.tk.DISABLED)
        self.assertEqual(self.contents(), '')

    def test_repeated_partial_replaces_preview_without_deleting_final_history(self):
        self.app._add_final('Guest-1', 'Prima propoziție.')
        prefix = '[03:04:05] Ana: Prima propoziție.\n'
        self.app._show_partial('Guest-2', 'B')
        mark = self.app.transcript_text.index('partial_start')
        self.assertEqual(self.app.transcript_text.mark_gravity('partial_start'), gui.tk.LEFT)
        self.app._show_partial('Guest-2', 'Bună tuturor')
        self.assertEqual(self.app.transcript_text.index('partial_start'), mark)
        self.assertEqual(self.contents(), prefix + 'Ștefan: Bună tuturor')
        self.assertEqual(len(self.app.entries), 1)
        self.assertTrue(self.app._has_partial)
        self.assertTrue(self.app.transcript_text.tag_ranges('partial'))
        self.assertEqual(self.app.transcript_text.get('end-1c', gui.tk.END), '\n')
        self.assertEqual(str(self.app.transcript_text.cget('state')), gui.tk.DISABLED)

    def test_partial_final_and_next_partial_preserve_line_boundaries(self):
        self.app._show_partial('Guest-1', 'unfinished')
        self.app._add_final('Guest-1', 'Final unu.')
        self.assertEqual(self.contents(), '[03:04:05] Ana: Final unu.\n')
        self.assertFalse(self.app._has_partial)
        self.assertFalse(self.app.transcript_text.tag_ranges('partial'))
        self.app._show_partial('Guest-2', 'a much longer preview')
        self.app._show_partial('Guest-2', 'scurt')
        self.assertEqual(self.contents(), '[03:04:05] Ana: Final unu.\nȘtefan: scurt')
        self.app._add_final('Guest-2', 'Final doi.')
        self.assertEqual(
            self.contents(),
            '[03:04:05] Ana: Final unu.\n[03:04:05] Ștefan: Final doi.\n',
        )
        self.assertEqual(len(self.app.entries), 2)
        self.assertFalse(self.app.transcript_text.tag_ranges('partial'))
        self.assertTrue(self.app.transcript_text.tag_ranges('speaker'))

    def test_rename_redraw_discards_preview_and_allows_new_partial(self):
        self.app._add_final('Guest-1', 'Istoric.')
        self.app._show_partial('Guest-1', 'discarded preview')
        self.app.speaker_id_var.set('Guest-1')
        self.app.new_name_var.set('  Ioana  ')
        self.app._rename_speaker()
        self.assertEqual(self.contents(), '[03:04:05] Ioana: Istoric.\n')
        self.assertEqual(self.app.entries[0]['speaker'], 'Ioana')
        self.assertEqual(self.app.new_name_var.get(), '')
        self.assertFalse(self.app._has_partial)
        self.app._show_partial('Guest-1', 'new preview')
        self.app._show_partial('Guest-1', 'replacement')
        self.assertEqual(self.contents(), '[03:04:05] Ioana: Istoric.\nIoana: replacement')
        menu = self.app.speaker_id_menu['menu']
        self.assertEqual(menu.entrycget(0, 'label'), 'Guest-1 (Ioana)')

    def test_start_and_stop_toggle_real_controls_without_sdk_or_disk_access(self):
        settings = Settings('test-only-key', 'test-region', None, 'ro-RO')
        self.app.session_store = Mock()
        self.app._add_final('old-id', 'Old transcript.')
        self.app.names_var.set('Ana, Ștefan')
        with patch.object(gui, 'load_settings', return_value=settings), \
                patch.object(gui, 'ConversationTranscriberService') as factory, \
                patch.object(gui.messagebox, 'showerror') as dialog:
            self.app.start_session()
            self.assertEqual(self.contents(), '')
            self.assertEqual(self.app.entries, [])
            self.assertEqual(str(self.app.names_entry.cget('state')), gui.tk.DISABLED)
            self.assertEqual(str(self.app.start_button.cget('state')), gui.tk.DISABLED)
            self.assertEqual(str(self.app.stop_button.cget('state')), gui.tk.NORMAL)
            self.app.stop_session()
            factory.return_value.stop.assert_called_once_with()
            dialog.assert_not_called()
        self.assertEqual(str(self.app.names_entry.cget('state')), gui.tk.NORMAL)
        self.assertEqual(str(self.app.start_button.cget('state')), gui.tk.NORMAL)
        self.assertEqual(str(self.app.stop_button.cget('state')), gui.tk.DISABLED)
        self.app.session_store.save.assert_not_called()


if __name__ == '__main__':
    unittest.main()
