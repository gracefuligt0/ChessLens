import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,time
from unittest.mock import patch
import chess,chess.engine
from PySide6.QtCore import QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from core import open_engine,image_array
from fast_analysis import find_brilliant_idea,idea_sacrifice,exact_search,FastEngineThread
from overlay import ArrowOverlay,Bubble
from tab_bridge import TabBridge,IDEA_COLOR
from test_fast_analysis import SACRIFICE_FEN
from test_player_guidance import move_item

APP=QApplication.instance() or QApplication([])
SETUP_FEN='4kb1q/p1Br1ppp/5n2/1B2pNB1/4P3/1Q6/PPP2PPP/2KR4 w - - 0 15'

def info(board,uci,cp=200,depth=18):
    return {'pv':[chess.Move.from_uci(m) for m in uci.split()],
            'score':chess.engine.PovScore(chess.engine.Cp(cp),board.turn),'depth':depth}

def accept(engine,board,moves,*args,**kwargs):
    for move in moves:move.update(brilliant=True,brilliant_reason='The accepting captures retain compensation.')
    return True

class CreativeSearchTests(unittest.TestCase):
    def setUp(self):self.board=chess.Board(SACRIFICE_FEN)
    def test_search_can_add_an_option_outside_the_top_three(self):
        top=[info(self.board,m) for m in ['b3a3','d1d2','g5h4']]
        sacrifice=info(self.board,'b3b8 d7b8 d1d8')
        with patch('fast_analysis.exact_search',return_value=[sacrifice]),patch('fast_analysis.exact_search_root',return_value=sacrifice),patch('fast_analysis.mark_brilliant',side_effect=accept):
            result=find_brilliant_idea(object(),self.board,top)
        self.assertTrue(result['creative']);self.assertEqual(result['uci'],'b3b8')
        self.assertNotIn(result['uci'],[i['pv'][0].uci() for i in top])
        self.assertEqual(result['idea_kind'],'sacrifice');self.assertFalse(result['brilliant'])
    def test_setup_is_conditional_and_verifies_the_followup_position(self):
        board=self.board.copy();board.remove_piece_at(chess.B3);board.set_piece_at(chess.C3,chess.Piece(chess.QUEEN,chess.WHITE))
        setup=info(board,'c3b3 a7a6 b3b8 d7b8 d1d8')
        branch,pv,is_setup=idea_sacrifice(board,setup)
        self.assertTrue(is_setup);self.assertEqual(pv[0].uci(),'b3b8')
        self.assertEqual(branch.piece_at(chess.A6).symbol(),'p')
        with patch('fast_analysis.exact_search',return_value=[]),patch('fast_analysis.exact_search_root',return_value=setup),patch('fast_analysis.mark_brilliant',side_effect=accept) as verify:
            result=find_brilliant_idea(object(),board,[setup])
        self.assertEqual(verify.call_args.args[1].fen(),branch.fen())
        self.assertEqual(result['idea_kind'],'setup');self.assertIn('if the opponent replies a6',result['idea_reason'])
        self.assertIn('Other replies can change',result['idea_reason'])
    def test_unverified_sacrifice_is_not_promoted_to_an_idea(self):
        candidate=info(self.board,'b3b8 d7b8 d1d8')
        with patch('fast_analysis.exact_search',return_value=[]),patch('fast_analysis.exact_search_root',return_value=candidate),patch('fast_analysis.mark_brilliant',return_value=False):
            self.assertIsNone(find_brilliant_idea(object(),self.board,[candidate]))
    def test_bad_or_shallow_candidate_is_rejected(self):
        candidate=info(self.board,'b3b8 d7b8 d1d8')
        for cp,depth in [(-200,18),(50,11)]:
            checked=info(self.board,'b3b8 d7b8 d1d8',cp,depth)
            with patch('fast_analysis.exact_search',return_value=[]),patch('fast_analysis.exact_search_root',return_value=checked),patch('fast_analysis.mark_brilliant') as verify:
                self.assertIsNone(find_brilliant_idea(object(),self.board,[candidate]));verify.assert_not_called()
    def test_quiet_opening_does_not_get_a_fabricated_marker(self):
        board=chess.Board();opening=info(board,'e2e4 e7e5 g1f3',25)
        with patch('fast_analysis.exact_search',return_value=[opening]),patch('fast_analysis.exact_search_root') as root:
            self.assertIsNone(find_brilliant_idea(object(),board,[opening]));root.assert_not_called()
    def test_cancelled_search_does_not_start_engine_work(self):
        with patch('fast_analysis.exact_search') as search:
            self.assertIsNone(find_brilliant_idea(object(),self.board,[info(self.board,'b3b8')],cancelled=lambda:True))
            search.assert_not_called()
    def test_bounded_or_partial_iterations_are_not_used_as_exact_scores(self):
        board=chess.Board();first=info(board,'e2e4',25,12);first['multipv']=1
        second=info(board,'d2d4',22,12);second['multipv']=2
        bounded=info(board,'g1f3',20,12);bounded.update(multipv=3,lowerbound=True)
        class Search:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def __iter__(self):return iter([first,second,bounded])
        class Engine:
            def analysis(self,*args,**kwargs):return Search()
        self.assertEqual(exact_search(Engine(),board,.1,3,lambda:False),[])

class CreativePresentationTests(unittest.TestCase):
    def test_fourth_marker_is_blue_and_keeps_all_three_regular_options(self):
        moves=[move_item(m) for m in ['e2e4','d2d4','g1f3','b1c3']]
        moves[3].update(creative=True,idea_reason='Sets up a sacrifice if the opponent cooperates.')
        bridge=TabBridge();bridge.publish({'fen':chess.STARTING_FEN,'moves':moves},chess.WHITE)
        self.assertEqual(len(bridge.analysis['moves']),4)
        self.assertEqual(bridge.analysis['moves'][3]['color'],IDEA_COLOR)
        self.assertEqual([m['uci'] for m in bridge.analysis['moves'][:3]],['e2e4','d2d4','g1f3'])
        overlay=ArrowOverlay();overlay.setGeometry(0,0,800,800);overlay.set_moves(moves)
        rgba=image_array(overlay.grab().toImage())
        self.assertEqual(list(rgba[704,104,:3]),[66,133,255]);overlay.close()
        bubble=Bubble();bubble.set_moves(moves)
        self.assertFalse(bubble.buttons[3].isHidden());self.assertIn('BLUE IDEA',bubble.buttons[3].text())
        bubble.explain(3);self.assertIn('Sets up a sacrifice',bubble.explanation.text())
        bubble.set_moves(moves[:3]);self.assertTrue(bubble.buttons[3].isHidden());bubble.close()

class CreativeEngineIntegrationTests(unittest.TestCase):
    def test_real_engine_can_prefer_a_blue_sacrifice_outside_the_top_three(self):
        engine=open_engine();board=chess.Board(SETUP_FEN)
        try:
            infos=engine.analyse(board,chess.engine.Limit(depth=16),multipv=3)
            result=find_brilliant_idea(engine,board,infos)
            self.assertIsNotNone(result)
            self.assertNotIn(result['uci'],[i['pv'][0].uci() for i in infos])
            self.assertTrue(result['creative']);self.assertIn('forced mate',result['idea_reason'])
        finally:engine.quit()
    def test_real_engine_verifies_a_move_setting_up_a_later_sacrifice(self):
        engine=open_engine();board=chess.Board(SETUP_FEN)
        try:
            root=chess.Move.from_uci('b5d7')
            seed=engine.analyse(board,chess.engine.Limit(depth=16),root_moves=[root])
            # Isolate this root to check the setup path; root and accepting captures use Stockfish.
            with patch('fast_analysis.exact_search',return_value=[]):
                result=find_brilliant_idea(engine,board,[seed])
            self.assertIsNotNone(result);self.assertEqual(result['uci'],'b5d7')
            self.assertEqual(result['idea_kind'],'setup');self.assertIn('Qb8+',result['idea_reason'])
        finally:engine.quit()
    def test_real_stockfish_produces_an_idea_for_both_colours_and_none_in_opening(self):
        engine=open_engine()
        try:
            for board,expected in [(chess.Board(SACRIFICE_FEN),'b3b8'),(chess.Board(SACRIFICE_FEN).mirror(),'b6b1')]:
                infos=engine.analyse(board,chess.engine.Limit(depth=16),multipv=3)
                result=find_brilliant_idea(engine,board,infos)
                self.assertIsNotNone(result);self.assertEqual(result['uci'],expected)
                self.assertTrue(result['creative']);self.assertIn('forced mate',result['idea_reason'])
            board=chess.Board();infos=engine.analyse(board,chess.engine.Limit(time=.3),multipv=3)
            self.assertIsNone(find_brilliant_idea(engine,board,infos))
        finally:engine.quit()
    def test_worker_publishes_blue_idea_after_preserving_normal_moves(self):
        worker=FastEngineThread();loop=QEventLoop();received=[];errors=[]
        def result(generation,payload):
            received.append(payload)
            if payload['phase']=='ideas':loop.quit()
        worker.result.connect(result);worker.failure.connect(lambda gen,msg:(errors.append(msg),loop.quit()))
        worker.start();worker.submit(1,chess.Board(SACRIFICE_FEN),.4,player_color=chess.WHITE);QTimer.singleShot(8000,loop.quit)
        try:loop.exec()
        finally:worker.stop()
        self.assertFalse(errors,errors);self.assertTrue(received)
        self.assertEqual(received[-1]['phase'],'ideas');self.assertEqual(len(received[-1]['moves']),4)
        refined=next(p for p in received if p['phase']=='refined')
        self.assertEqual([m['uci'] for m in received[-1]['moves'][:3]],[m['uci'] for m in refined['moves']])
        self.assertTrue(received[-1]['moves'][3]['creative']);self.assertEqual(len(refined['moves']),3)

if __name__=='__main__':unittest.main(verbosity=2)
