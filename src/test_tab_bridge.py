import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,json,urllib.request,urllib.error
from unittest.mock import patch
import chess
from PySide6.QtWidgets import QApplication
from tab_bridge import TabBridge,validated_position
from overlay import Controller
from test_player_guidance import FakeEngine,frame

APP=QApplication.instance() or QApplication([])

def state(board=None,tab=7):
    board=board or chess.Board()
    return {'url':'https://www.chess.com/play/coach','fen':board.fen(en_passant='fen'),
            'pieces':[{'square':chess.square_name(s),'symbol':p.symbol()} for s,p in board.piece_map().items()],
            'rect':{'x':20,'y':80,'width':640,'height':640},'viewport':{'width':1200,'height':900},
            'whiteBottom':True,'player':'white','visible':True,'active':True,'focused':True,'tabId':tab}

class PositionTruthTests(unittest.TestCase):
    def test_complete_position_includes_turn_castling_and_en_passant(self):
        board=chess.Board('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1')
        result=validated_position(state(board));self.assertEqual(result.fen(),board.fen())
        self.assertIn(chess.Move.from_uci('e5d6'),result.legal_moves)
    def test_piece_mismatch_or_missing_turn_is_not_accepted(self):
        data=state();data['pieces'].pop()
        with self.assertRaises(ValueError):validated_position(data)
        data=state();data['fen']=chess.Board().board_fen()
        with self.assertRaises(ValueError):validated_position(data)
    def test_non_chesscom_page_is_rejected(self):
        data=state();data['url']='https://example.com/play'
        with self.assertRaises(ValueError):validated_position(data)
    def test_pawn_move_ep_field_is_normalised_without_losing_request_identity(self):
        board=chess.Board();board.push_san('e4');bridge=TabBridge()
        data=state(board);reply=bridge.ingest(data)
        self.assertEqual(reply['inputFen'],board.fen(en_passant='fen'))
        self.assertEqual(reply['fenKey'],board.fen())
    def test_background_tab_does_not_replace_focused_game(self):
        bridge=TabBridge();bridge.ingest(state(tab=7))
        background=state(tab=9);background['focused']=False;bridge.ingest(background)
        self.assertEqual(bridge.current()['tabId'],7)
    def test_old_tab_or_position_never_receives_markers(self):
        bridge=TabBridge();data=state();bridge.ingest(data)
        payload={'fen':chess.Board().fen(),'moves':[{'uci':'e2e4','score':'+0.3'}]}
        bridge.publish(payload,chess.WHITE,7,True)
        self.assertTrue(bridge.ingest(data)['render'])
        self.assertFalse(bridge.ingest(state(tab=8))['render'])
        bridge.received-=2;self.assertIsNone(bridge.current())

class LocalTransportTests(unittest.TestCase):
    def test_only_extension_origin_and_session_can_post(self):
        bridge=TabBridge(port=0);bridge.start();base=f'http://127.0.0.1:{bridge.port}'
        try:
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(base+'/v1/session')
            headers={'Origin':'chrome-extension://'+'a'*32}
            token=json.load(urllib.request.urlopen(urllib.request.Request(base+'/v1/session',headers=headers)))['token']
            body=json.dumps(state()).encode()
            with self.assertRaises(urllib.error.HTTPError):urllib.request.urlopen(urllib.request.Request(base+'/v1/state',data=body,headers=headers))
            headers.update(Authorization='Bearer '+token,**{'Content-Type':'application/json'})
            reply=json.load(urllib.request.urlopen(urllib.request.Request(base+'/v1/state',data=body,headers=headers)))
            self.assertTrue(reply['ok'])
        finally:bridge.stop()

class VerifiedControllerTests(unittest.TestCase):
    def setUp(self):
        self.patch=patch('overlay.FastEngineThread',FakeEngine);self.patch.start()
        self.c=Controller(APP,autostart=False);self.c.player_side='White'
    def tearDown(self):self.c.quit();self.patch.stop()
    def test_unknown_midgame_pixels_do_not_invent_turn_or_history(self):
        board=chess.Board();board.push_san('e4');f=frame(board)
        for i in range(6):self.c.on_frame(f)
        self.assertIsNone(self.c.board);self.assertEqual(self.c.engine.calls,[])
    def test_authoritative_tab_position_overrides_stale_screen_state(self):
        self.c.board=chess.Board()
        board=chess.Board('4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1')
        data=state(board);data['board']=board
        self.c.capture_tab(data)
        self.assertEqual(self.c.board.fen(),board.fen());self.assertTrue(self.c.tab_mode)
        self.assertEqual(self.c.engine.calls[-1][1].fen(),board.fen())
        self.assertEqual(self.c.engine.calls[-1][2],chess.WHITE)

if __name__=='__main__':unittest.main(verbosity=2)
