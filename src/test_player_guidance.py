import os,sys,uuid
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from unittest.mock import patch
import numpy as np
import chess
from PySide6.QtCore import QObject,Signal,QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from core import open_engine,image_array
from premoves import universal_quiet_moves,checked_premove
from instance_guard import InstanceGuard
from overlay import Controller,ArrowOverlay
from fast_analysis import FastEngineThread

APP=QApplication.instance() or QApplication([])

class FakeEngine(QObject):
    result=Signal(int,object);failure=Signal(int,str)
    def __init__(self): super().__init__(); self.calls=[]
    def start(self): pass
    def stop(self): pass
    def cancel(self): pass
    def submit(self,generation,board,seconds,player_color=None): self.calls.append((generation,board.copy(),player_color))

def frame(board,white_bottom=True):
    return {'screen':'fixture','rect':(0,0,800,800),'dimensions':(800,800),'geometry':(0,0,800,800),
            'board':board,'white_bottom':white_bottom,'initial':board.board_fen()==chess.Board().board_fen(),
            'costs':[],'crop':np.zeros((800,800,3),np.uint8)}

def move_item(uci,premove=False):
    return {'uci':uci,'san':uci,'score':'+0.00','cp':0,'depth':12,'rank':0,'brilliant':False,'premove':premove,
            'text':'Develops your piece. The engine’s main reply is e5.','verdict':'Balanced.','line':'1.e4 e5'}

class PlayerGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.patcher=patch('overlay.FastEngineThread',FakeEngine); self.patcher.start()
        self.controller=Controller(APP,autostart=False); self.controller.player_side='White'
    def tearDown(self): self.controller.quit(); self.patcher.stop()
    def adopt(self,board,white_bottom=True):
        if board.move_stack and self.controller.board is None:self.controller.board=board.root().copy()
        f=frame(board,white_bottom); self.controller.on_frame(f); self.controller.on_frame(f); return f
    def test_enemy_result_never_reaches_overlay(self):
        board=chess.Board(); board.push_san('e4'); self.adopt(board)
        c=self.controller
        self.assertEqual(c.engine.calls[-1][2],chess.WHITE)
        c.on_result(c.generation,{'fen':board.fen(),'moves':[move_item('e7e5')],'phase':'refined','terminal':''})
        self.assertEqual(c.results,[]); self.assertEqual(c.overlay.moves,[])
    def test_own_moves_are_displayed_and_enemy_line_hidden(self):
        board=chess.Board(); self.adopt(board); c=self.controller
        c.on_result(c.generation,{'fen':board.fen(),'moves':[move_item('e2e4')],'phase':'refined','terminal':''})
        self.assertEqual(c.overlay.moves[0]['uci'],'e2e4')
        c.bubble.explain(0)
        self.assertNotIn('e5',c.bubble.explanation.text()); self.assertTrue(c.bubble.line.isHidden())
    def test_checked_premove_is_our_piece_on_opponent_turn(self):
        board=chess.Board(); board.push_san('e4'); self.adopt(board); c=self.controller
        c.on_result(c.generation,{'fen':board.fen(),'moves':[move_item('b1c3',True)],'phase':'premove','mode':'premove','player_color':chess.WHITE,'terminal':''})
        self.assertTrue(c.results[0]['premove']); self.assertEqual(c.overlay.moves[0]['uci'],'b1c3')
        self.assertIn('Premove',c.bubble.status.text())
    def test_empty_premove_check_is_not_repeated_every_frame(self):
        board=chess.Board(); board.push_san('e4'); f=self.adopt(board); c=self.controller
        c.on_result(c.generation,{'fen':board.fen(),'moves':[],'phase':'premove','mode':'premove','player_color':chess.WHITE,'terminal':''})
        calls=len(c.engine.calls)
        for i in range(5): c.on_frame(f)
        self.assertEqual(len(c.engine.calls),calls)
    def test_automatic_player_is_bottom_side(self):
        c=self.controller; c.player_side='Automatic'
        self.adopt(chess.Board(),white_bottom=False)
        self.assertEqual(c.player_color(),chess.BLACK)
        self.assertEqual(c.engine.calls[-1][2],chess.BLACK)

class PremoveTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine=open_engine()
    @classmethod
    def tearDownClass(cls): cls.engine.quit()
    def test_premove_checked_after_every_reply(self):
        board=chess.Board(); board.push_san('e4')
        # Legality/coverage is deterministic; short engine searches may conservatively
        # decline every candidate, depending on depth and hash state.
        class Evaluation:
            def analyse(self,*args,**kwargs):return [{'score':chess.engine.PovScore(chess.engine.Cp(0),chess.WHITE),'pv':[chess.Move.from_uci('e7e5'),chess.Move.from_uci('g1f3')]}]
        def verify(engine,branch,move,*args):return {'score':chess.engine.PovScore(chess.engine.Cp(0),chess.WHITE),'pv':[move],'depth':14}
        with patch('premoves.exact_root_info',side_effect=verify) as checks:
            result=checked_premove(Evaluation(),board,chess.WHITE)
        self.assertEqual(checks.call_count,board.legal_moves.count())
        self.assertTrue(result['moves'])
        item=result['moves'][0]; candidate=chess.Move.from_uci(item['uci'])
        self.assertEqual(board.piece_at(candidate.from_square).color,chess.WHITE)
        self.assertEqual(item['checked_replies'],board.legal_moves.count())
        for reply in board.legal_moves:
            after=board.copy(); after.push(reply); self.assertIn(candidate,after.legal_moves)
    def test_no_automatic_premove_when_checks_prevent_one(self):
        board=chess.Board('k7/3r4/8/8/8/8/8/1N2K3 b - - 0 1')
        self.assertTrue(board.is_valid())
        self.assertEqual(universal_quiet_moves(board,chess.WHITE),([],[]))
        self.assertEqual(checked_premove(self.engine,board,chess.WHITE)['moves'],[])
    def test_cancelled_check_displays_nothing(self):
        board=chess.Board(); board.push_san('e4')
        self.assertEqual(checked_premove(self.engine,board,chess.WHITE,cancelled=lambda:True)['moves'],[])
    def test_worker_does_not_publish_opponent_search_lines(self):
        board=chess.Board(); board.push_san('e4'); worker=FastEngineThread(); loop=QEventLoop(); received=[]; errors=[]
        def result(generation,payload): received.append(payload); loop.quit()
        worker.result.connect(result); worker.failure.connect(lambda gen,msg:(errors.append(msg),loop.quit()))
        worker.start(); worker.submit(1,board,.8,player_color=chess.WHITE); QTimer.singleShot(10000,loop.quit)
        try: loop.exec()
        finally: worker.stop()
        self.assertFalse(errors,errors); self.assertTrue(received)
        self.assertTrue(all(p.get('mode')=='premove' for p in received))
        for p in received:
            self.assertTrue(all(board.piece_at(chess.Move.from_uci(m['uci']).from_square).color==chess.WHITE for m in p['moves']))

class HighlightAndInstanceTests(unittest.TestCase):
    def test_small_corner_markers_leave_the_board_uncovered(self):
        overlay=ArrowOverlay(); overlay.setGeometry(0,0,800,800)
        overlay.set_moves([move_item('e2e4'),move_item('d2d4'),move_item('g1f3')])
        rgba=image_array(overlay.grab().toImage())
        self.assertEqual(rgba[450,450,3],0) # e4 centre stays clear
        self.assertEqual(rgba[650,450,3],0) # e2 piece remains untinted
        self.assertGreater(rgba[604,404,3],0) # tiny source dot
        self.assertEqual(rgba[550,450,3],0) # e3: no connecting arrow
        self.assertGreater(rgba[405,405,3],0) # e4 tag
        self.assertGreater(rgba[405,305,3],0) # d4 tag
        self.assertGreater(rgba[505,505,3],0) # f3 tag
        overlay.selected=1; overlay.update(); rgba=image_array(overlay.grab().toImage())
        self.assertEqual(rgba[450,350,3],0); self.assertGreater(rgba[405,305,3],0)
        overlay.close()
    @unittest.skipUnless(sys.platform=='win32','Windows named instance lock')
    def test_duplicate_instance_is_rejected_and_lock_released(self):
        name='Local\\ChessLens.Test.'+uuid.uuid4().hex
        first,second,third=[InstanceGuard(name) for _ in range(3)]
        try:
            self.assertTrue(first.acquire()); self.assertFalse(second.acquire())
            first.close(); self.assertTrue(third.acquire())
        finally:
            for guard in [first,second,third]: guard.close()

if __name__=='__main__': unittest.main(verbosity=2)
