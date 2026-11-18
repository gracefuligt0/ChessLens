import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest,wave,array
from unittest.mock import patch
import chess,chess.engine
from PySide6.QtCore import QObject,Signal,QEventLoop,QTimer
from PySide6.QtWidgets import QApplication
from core import ASSETS,open_engine,image_array
from fast_analysis import natural_features,find_natural_move
from celebrations import BrilliantCelebration,played_own_move,BrillianceAuditor
from tab_bridge import TabBridge,NATURAL_COLOR
from overlay import ArrowOverlay,Bubble,Controller
from test_player_guidance import move_item,FakeEngine
from test_tab_bridge import state
from test_fast_analysis import SACRIFICE_FEN

APP=QApplication.instance() or QApplication([])

def info(uci,cp=25,depth=16):
    return {'pv':[chess.Move.from_uci(uci)],'score':chess.engine.PovScore(chess.engine.Cp(cp),chess.WHITE),'depth':depth}

class NaturalMoveTests(unittest.TestCase):
    def test_simple_development_is_preferred_to_an_early_queen_move(self):
        board=chess.Board();queen=chess.Board();queen.push_san('e4');queen.push_san('e5')
        self.assertGreater(natural_features(board,chess.Move.from_uci('g1f3'))[0],natural_features(queen,chess.Move.from_uci('d1h5'))[0])
    def test_a_piece_offered_to_a_cheaper_attacker_is_rejected(self):
        board=chess.Board('6k1/8/8/2p5/8/8/8/3Q2K1 w - - 0 1')
        self.assertIsNone(natural_features(board,chess.Move.from_uci('d1d4')))
    def test_natural_option_can_come_from_outside_the_top_three(self):
        board=chess.Board();top=[info(m) for m in ['e2e4','d2d4','g1f3']];extra=info('b1c3',20)
        with patch('fast_analysis.exact_search_root',return_value=extra):result=find_natural_move(object(),board,top,[extra])
        self.assertEqual(result['uci'],'b1c3');self.assertTrue(result['natural']);self.assertFalse(result['brilliant'])
        self.assertIn('Develops',result['natural_reason'])
    def test_recheck_rejects_a_large_evaluation_drop_or_a_shallow_score(self):
        board=chess.Board();top=[info('g1f3')]
        for checked in [info('g1f3',-100),info('g1f3',25,8)]:
            with patch('fast_analysis.exact_search_root',return_value=checked):self.assertIsNone(find_natural_move(object(),board,top,[]))
    def test_bounds_and_cancelled_jobs_never_produce_a_natural_move(self):
        candidate=info('g1f3');candidate['lowerbound']=True
        self.assertIsNone(find_natural_move(object(),chess.Board(),[candidate],[]))
        self.assertIsNone(find_natural_move(object(),chess.Board(),[info('g1f3')],[],cancelled=lambda:True))
    def test_real_stockfish_natural_option_is_legal_and_not_a_sacrifice(self):
        engine=open_engine();board=chess.Board()
        try:
            top=engine.analyse(board,chess.engine.Limit(time=.4),multipv=3)
            result=find_natural_move(engine,board,top,[])
            self.assertIsNotNone(result);self.assertTrue(result['natural'])
            self.assertIn(chess.Move.from_uci(result['uci']),board.legal_moves)
            best=max(i['score'].pov(board.turn).score(mate_score=100000) for i in top)
            self.assertGreaterEqual(result['cp'],best-70)
        finally:engine.quit()
    def test_purple_fifth_marker_does_not_replace_engine_or_blue_options(self):
        moves=[move_item(m) for m in ['e2e4','d2d4','g1f3','b1c3','c2c4']]
        moves[3]['creative']=True;moves[4].update(natural=True,natural_reason='Supports the centre.')
        bridge=TabBridge();bridge.publish({'fen':chess.STARTING_FEN,'moves':moves},chess.WHITE)
        self.assertEqual(len(bridge.analysis['moves']),5);self.assertEqual(bridge.analysis['moves'][4]['color'],NATURAL_COLOR)
        overlay=ArrowOverlay();overlay.setGeometry(0,0,800,800);overlay.set_moves(moves)
        rgba=image_array(overlay.grab().toImage());self.assertEqual(list(rgba[604,204,:3]),[182,117,255]);overlay.close()
        bubble=Bubble();bubble.set_moves(moves);self.assertIn('NATURAL',bubble.buttons[4].text())
        bubble.explain(4);self.assertIn('Supports the centre',bubble.explanation.text());bubble.close()

class FakeAuditor(QObject):
    result=Signal(object,bool)
    def __init__(self):super().__init__();self.jobs=[]
    def start(self):pass
    def stop(self):pass
    def submit(self,*args):self.jobs.append(args)

class PlayedSoundTests(unittest.TestCase):
    def setUp(self):
        self.plays=[];self.auditor=FakeAuditor()
        self.sound=BrilliantCelebration(playback=lambda clip:(self.plays.append(clip) or True),audit_factory=lambda:self.auditor)
        self.board=chess.Board();self.context=('tab',7,'game')
    def tearDown(self):self.sound.stop()
    def remember(self,board=None,uci='e2e4',player=chess.WHITE):
        board=board or self.board
        self.sound.observe(board,player,self.context)
        item=move_item(uci);item['brilliant']=True
        self.sound.remember(board,[item],player,self.context)
    def test_analysis_and_repeated_scans_are_silent(self):
        self.remember()
        for _ in range(5):self.sound.observe(self.board,chess.WHITE,self.context)
        self.assertEqual(self.plays,[])
    def test_only_actual_play_celebrates_once(self):
        self.remember();after=self.board.copy();after.push_san('e4')
        self.sound.observe(after,chess.WHITE,self.context)
        for _ in range(5):self.sound.observe(after,chess.WHITE,self.context)
        self.assertEqual(self.plays,['chime']);self.assertEqual(self.sound.played_count,1)
    def test_fast_opponent_reply_does_not_lose_the_event(self):
        self.remember();after=self.board.copy();after.push_san('e4');after.push_san('e5')
        self.sound.observe(after,chess.WHITE,self.context);self.assertEqual(self.plays,['chime'])
    def test_black_moves_are_recognised_with_the_correct_player(self):
        board=chess.Board(SACRIFICE_FEN).mirror();self.remember(board,'b6b1',chess.BLACK)
        after=board.copy();after.push_uci('b6b1');self.sound.observe(after,chess.BLACK,self.context)
        self.assertEqual(self.plays,['chime'])
    def test_enemy_move_or_tab_switch_does_not_celebrate(self):
        self.remember();after=self.board.copy();after.push_san('e4')
        self.sound.observe(after,chess.WHITE,('tab',9,'game'));self.assertEqual(self.plays,[])
        board=chess.Board();board.push_san('e4');self.sound.observe(board,chess.WHITE,self.context)
        after=board.copy();after.push_san('e5');self.sound.observe(after,chess.WHITE,self.context);self.assertEqual(self.plays,[])
    def test_muting_or_resetting_suppresses_an_event(self):
        for reset in [False,True]:
            self.remember();after=self.board.copy();after.push_san('e4')
            if reset:self.sound.reset()
            else:self.sound.set_enabled(False)
            self.sound.observe(after,chess.WHITE,self.context)
        self.assertEqual(self.plays,[])
    def test_short_animation_gap_preserves_the_verified_move(self):
        self.remember();self.sound.wait_for_valid(self.context)
        after=self.board.copy();after.push_san('e4');self.sound.observe(after,chess.WHITE,self.context)
        self.assertEqual(self.plays,['chime'])
    def test_long_invalid_board_gap_does_not_celebrate_a_stale_move(self):
        self.remember();self.sound.wait_for_valid(self.context);self.sound.invalid_since-=2
        after=self.board.copy();after.push_san('e4');self.sound.observe(after,chess.WHITE,self.context)
        self.assertEqual(self.plays,[])
    def test_unrelated_placement_or_wrong_history_is_not_a_played_move(self):
        self.remember();after=self.board.copy();after.push_san('e4');after.fullmove_number=20
        self.sound.observe(after,chess.WHITE,self.context);self.assertEqual(self.plays,[])
        self.assertIsNone(played_own_move(chess.Board(),chess.Board(SACRIFICE_FEN),chess.WHITE))
    def test_quick_sacrifice_is_audited_before_any_sound(self):
        board=chess.Board(SACRIFICE_FEN);self.sound.observe(board,chess.WHITE,self.context)
        after=board.copy();after.push_uci('b3b8');self.sound.observe(after,chess.WHITE,self.context)
        self.assertEqual(self.plays,[]);self.assertEqual(len(self.auditor.jobs),1)
        event,original,move=self.auditor.jobs[0]
        self.assertEqual(original.fen(),board.fen());self.assertEqual(move.uci(),'b3b8')
        self.auditor.result.emit(event,True);self.auditor.result.emit(event,True)
        self.assertEqual(self.plays,['chime'])
    def test_failed_or_stale_audit_is_silent(self):
        for switch in [False,True]:
            board=chess.Board(SACRIFICE_FEN);self.sound.observe(board,chess.WHITE,self.context)
            after=board.copy();after.push_uci('b3b8');self.sound.observe(after,chess.WHITE,self.context)
            event=self.auditor.jobs[-1][0]
            if switch:self.sound.observe(after,chess.WHITE,('tab',8,'game'))
            self.auditor.result.emit(event,switch)
        self.assertEqual(self.plays,[])
    def test_controller_observes_a_played_move_not_a_displayed_suggestion(self):
        with patch('overlay.FastEngineThread',FakeEngine):
            c=Controller(APP,autostart=False);c.player_side='White';c.celebration.playback=lambda clip:(self.plays.append(clip) or True);c.celebration.set_enabled(True)
            try:
                first=state();first['board']=chess.Board();c.capture_tab(first)
                item=move_item('e2e4');item['brilliant']=True
                c.on_result(c.generation,{'fen':chess.STARTING_FEN,'moves':[item],'phase':'verified','terminal':''})
                self.assertEqual(self.plays,[])
                next_board=chess.Board();next_board.push_san('e4');second=state(next_board);second['board']=next_board
                c.capture_tab(second);self.assertEqual(self.plays,['chime'])
            finally:c.quit()

class SoundIntegrationTests(unittest.TestCase):
    def test_bundled_audio_is_short_valid_pcm_and_not_clipped(self):
        for clip in ['chime']:
            with wave.open(str(ASSETS/'sounds'/f'{clip}.wav'),'rb') as stream:
                self.assertEqual(stream.getnchannels(),1);self.assertEqual(stream.getsampwidth(),2)
                duration=stream.getnframes()/stream.getframerate();self.assertGreater(duration,.1);self.assertLess(duration,3)
                samples=array.array('h',stream.readframes(stream.getnframes()))
                self.assertGreater(max(abs(x) for x in samples),1000);self.assertLess(max(abs(x) for x in samples),32767)
    def test_real_auditor_confirms_an_already_played_sacrifice(self):
        worker=BrillianceAuditor();loop=QEventLoop();results=[]
        worker.result.connect(lambda event,verified:(results.append(verified),loop.quit()))
        board=chess.Board(SACRIFICE_FEN);worker.start();worker.submit('actual-move',board,chess.Move.from_uci('b3b8'));QTimer.singleShot(7000,loop.quit)
        try:loop.exec()
        finally:worker.stop()
        self.assertEqual(results,[True])

if __name__=='__main__':unittest.main(verbosity=2)
