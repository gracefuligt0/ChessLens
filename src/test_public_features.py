import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,tempfile,wave
from pathlib import Path
from unittest.mock import patch
import chess
from PySide6.QtWidgets import QApplication,QDialog,QCheckBox,QComboBox
from tab_bridge import TabBridge,extension_origin_allowed
from test_tab_bridge import state
from celebrations import import_custom_sound
from core import ASSETS
from overlay import Controller
from test_player_guidance import FakeEngine

APP=QApplication.instance() or QApplication([])

class BrowserBridgeTests(unittest.TestCase):
    def test_firefox_origin_and_fixed_extension_id_are_accepted(self):
        self.assertTrue(extension_origin_allowed('moz-extension://12345678-abcd-1234-abcd-1234567890ab'))
        self.assertTrue(extension_origin_allowed('','chesslens@local.invalid'))
        self.assertTrue(extension_origin_allowed('chrome-extension://'+'a'*32))
    def test_web_origins_cannot_impersonate_an_extension_header(self):
        for origin in ['https://chess.com','https://evil.example','moz-extension://not-a-uuid','null']:
            self.assertFalse(extension_origin_allowed(origin,'a'*32))
    def test_visual_titles_are_whitelisted_and_independent_of_analysis(self):
        bridge=TabBridge();bridge.set_titles('GM','WGM');reply=bridge.ingest(state())
        self.assertFalse(reply['render']);self.assertEqual(reply['appearance'],{'selfTitle':'GM','opponentTitle':'WGM'})
        bridge.set_titles('Off','IM');self.assertEqual(bridge.ingest(state())['appearance'],{'selfTitle':None,'opponentTitle':'IM'})
        bridge.set_titles('<script>','invalid');self.assertEqual(bridge.ingest(state())['appearance'],{'selfTitle':None,'opponentTitle':None})
    def test_inactive_or_invalid_position_never_receives_title_badges(self):
        bridge=TabBridge();bridge.set_titles('GM','IM');data=state();data['focused']=False
        self.assertIsNone(bridge.ingest(data)['appearance'])
        self.assertFalse(bridge.ingest(None)['ok'])
        data=state();data['pieces']=[None]*32;self.assertFalse(bridge.ingest(data)['ok'])

class PublicMediaTests(unittest.TestCase):
    def test_personal_media_is_not_bundled(self):
        self.assertFalse((ASSETS/'pieces/neo').exists());self.assertFalse((ASSETS/'pieces/alpha').exists())
        self.assertFalse((ASSETS/'sounds/brilliant.wav').exists());self.assertFalse((ASSETS/'sounds/yes.wav').exists())
    def test_custom_wav_import_validates_before_copying(self):
        with tempfile.TemporaryDirectory() as folder,patch('celebrations.DATA',Path(folder)):
            target=import_custom_sound(ASSETS/'sounds/chime.wav');self.assertTrue(target.is_file())
            invalid=Path(folder)/'invalid.wav';invalid.write_bytes(b'not a wave')
            with self.assertRaises(ValueError):import_custom_sound(invalid)

class TitleOptionsTests(unittest.TestCase):
    def test_title_controls_save_each_player_and_turn_off_independently(self):
        with patch('overlay.FastEngineThread',FakeEngine):
            c=Controller(APP,autostart=False);saved_settings={key:c.settings.value(key) for key in c.settings.allKeys()}
            def accept(dialog):
                checks={x.text():x for x in dialog.findChildren(QCheckBox)}
                checks['Show a custom title for me'].setChecked(True);checks['Show a custom title for my opponent'].setChecked(False)
                choices=[x for x in dialog.findChildren(QComboBox) if x.findText('WGM')>=0]
                self.assertEqual(len(choices),2);choices[0].setCurrentText('FM')
                return QDialog.DialogCode.Accepted
            try:
                with patch.object(QDialog,'exec',accept):c.options()
                self.assertEqual(c.bridge.appearance,{'selfTitle':'FM','opponentTitle':None})
            finally:
                for key in c.settings.allKeys():
                    if key not in saved_settings:c.settings.remove(key)
                for key,value in saved_settings.items():c.settings.setValue(key,value)
                c.settings.sync();c.quit()

if __name__=='__main__':unittest.main(verbosity=2)
