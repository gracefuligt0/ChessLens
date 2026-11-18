import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,time
from pathlib import Path
import chess,chess.engine
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QEventLoop,QTimer
from core import open_engine,analyse,explain
from fast_analysis import FastEngineThread,mark_brilliant,sacrifice_groups

APP=QApplication.instance() or QApplication([])
SACRIFICE_FEN='4kb1r/p2n1ppp/4q3/4p1B1/4P3/1Q6/PPP2PPP/2KR4 w k - 0 16'

class BrillianceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine=open_engine()
    @classmethod
    def tearDownClass(cls): cls.engine.quit()
    def test_engine_verified_queen_sacrifice(self):
        board=chess.Board(SACRIFICE_FEN)
        infos=self.engine.analyse(board,chess.engine.Limit(depth=16),multipv=3)
        moves=[explain(board,i,n) for n,i in enumerate(infos)]
        self.assertTrue(mark_brilliant(self.engine,board,moves))
        marked=[m for m in moves if m.get('brilliant')]
        self.assertEqual([m['uci'] for m in marked],['b3b8'])
        self.assertIn('queen',marked[0]['brilliant_reason'])
        self.assertIn('forced mate',marked[0]['brilliant_reason'])
    def test_ordinary_opening_is_not_brilliant(self):
        board=chess.Board(); moves=analyse(self.engine,board,.2)['moves']
        self.assertFalse(mark_brilliant(self.engine,board,moves))
    def test_verified_sacrifice_for_black(self):
        board=chess.Board(SACRIFICE_FEN).mirror()
        infos=self.engine.analyse(board,chess.engine.Limit(depth=16),multipv=3)
        moves=[explain(board,i,n) for n,i in enumerate(infos)]
        self.assertTrue(mark_brilliant(self.engine,board,moves))
        self.assertEqual([m['uci'] for m in moves if m.get('brilliant')],['b6b1'])
    def test_equal_trade_is_not_a_sacrifice(self):
        board=chess.Board('3rq1k1/8/8/8/8/8/8/3R2K1 w - - 0 1')
        move=chess.Move.from_uci('d1d8')
        self.assertIn(move,board.legal_moves)
        self.assertEqual(sacrifice_groups(board,move),[])
    def test_losing_offer_is_rejected_even_with_a_positive_initial_estimate(self):
        board=chess.Board('6k1/8/8/8/8/5p2/8/3Q3K w - - 0 1')
        move=chess.Move.from_uci('d1e2')
        self.assertIn(move,board.legal_moves)
        candidate={'uci':move.uci(),'cp':500,'depth':16}
        self.assertTrue(sacrifice_groups(board,move))
        self.assertFalse(mark_brilliant(self.engine,board,[candidate]))
        self.assertFalse(candidate['brilliant'])
    def test_cancelled_verification_does_not_add_a_label(self):
        board=chess.Board(SACRIFICE_FEN); candidate={'uci':'b3b8','cp':99998,'depth':16}
        self.assertFalse(mark_brilliant(self.engine,board,[candidate],cancelled=lambda:True))
        self.assertFalse(candidate['brilliant'])

class ProgressiveTests(unittest.TestCase):
    def test_partial_final_iteration_does_not_remove_alternatives(self):
        from unittest.mock import patch
        board=chess.Board(); roots=['e2e4','d2d4','g1f3']
        infos=[{'pv':[chess.Move.from_uci(root)],'score':chess.engine.PovScore(chess.engine.Cp(30-i),chess.WHITE),'depth':12,'multipv':i+1} for i,root in enumerate(roots)]
        class Search:
            multipv=[infos[0],infos[0],infos[0]] # incomplete aggregation repeats only the best root
            def __enter__(self): return self
            def __exit__(self,*args): pass
            def __iter__(self): return iter(infos)
            def stop(self): pass
        class Engine:
            id={'name':'test'}
            def analysis(self,*args,**kwargs): return Search()
            def quit(self): pass
        worker=FastEngineThread(); loop=QEventLoop(); received=[]; errors=[]
        worker.result.connect(lambda generation,payload:(received.append(payload),loop.quit()))
        worker.failure.connect(lambda generation,message:(errors.append(message),loop.quit()))
        with patch('fast_analysis.open_engine',return_value=Engine()):
            worker.start(); worker.submit(1,board,.1); QTimer.singleShot(3000,loop.quit)
            try: loop.exec()
            finally: worker.stop()
        self.assertFalse(errors,errors); self.assertTrue(received)
        self.assertEqual([m['uci'] for m in received[-1]['moves']],roots)
    def test_quick_then_refined_unique_legal_moves(self):
        worker=FastEngineThread(); loop=QEventLoop(); received=[]; errors=[]
        board=chess.Board()
        def result(generation,payload):
            received.append(payload)
            if payload['phase']=='refined': loop.quit()
        worker.result.connect(result); worker.failure.connect(lambda gen,msg:(errors.append(msg),loop.quit()))
        worker.start(); worker.submit(1,board,.8); QTimer.singleShot(8000,loop.quit)
        try: loop.exec()
        finally: worker.stop()
        self.assertFalse(errors,errors)
        self.assertIn('quick',[p['phase'] for p in received]); self.assertEqual(received[-1]['phase'],'refined')
        self.assertLess(received[0]['elapsed_ms'],received[-1]['elapsed_ms'])
        for payload in received:
            moves=[chess.Move.from_uci(m['uci']) for m in payload['moves']]
            self.assertEqual(len(moves),3); self.assertEqual(len(set(moves)),3)
            self.assertTrue(all(move in board.legal_moves for move in moves))
            if payload['phase']=='quick': self.assertFalse(any(m.get('brilliant') for m in payload['moves']))
    def test_new_position_supersedes_an_active_search(self):
        worker=FastEngineThread(); loop=QEventLoop(); received=[]; errors=[]; switched=[False]
        board=chess.Board(); next_board=board.copy(); next_board.push_san('e4')
        def result(generation,payload):
            received.append((generation,payload,switched[0]))
            if generation==2 and payload['phase']=='refined': loop.quit()
        def replace(): switched[0]=True; worker.submit(2,next_board,.5)
        worker.result.connect(result); worker.failure.connect(lambda gen,msg:(errors.append(msg),loop.quit()))
        def ready(name): worker.submit(1,board,2); QTimer.singleShot(50,replace)
        worker.ready.connect(ready); worker.start(); QTimer.singleShot(8000,loop.quit)
        try: loop.exec()
        finally: worker.stop()
        self.assertFalse(errors,errors)
        self.assertTrue(any(g==2 for g,_,_ in received))
        self.assertFalse(any(g==1 and after for g,_,after in received))
        for generation,payload,_ in received:
            if generation==2: self.assertEqual(payload['fen'],next_board.fen())

if __name__=='__main__': unittest.main(verbosity=2)
