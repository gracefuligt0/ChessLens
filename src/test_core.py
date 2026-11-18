"""Run: python -m unittest -v test_core (no network or live account required)."""
import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest, random, time
import numpy as np
import chess
from PySide6.QtWidgets import QApplication
from core import (Recognizer,piece_image,image_array,screen_square,match_transition,
                  detect_boards,analyse,open_engine,explain)

APP=QApplication.instance() or QApplication([])

def render_board(board,size=512,theme='cburnett',white_bottom=True,highlight=False):
    rgb=np.zeros((size,size,3),np.uint8)
    colors=[(238,238,210),(118,150,86)] if theme=='neo' else [(240,217,181),(181,136,99)]
    for row in range(8):
        for col in range(8):
            y,y2=round(row*size/8),round((row+1)*size/8)
            x,x2=round(col*size/8),round((col+1)*size/8)
            sq=screen_square(row,col,white_bottom)
            rgb[y:y2,x:x2]=colors[(row+col)%2]
            if highlight and sq in [chess.E2,chess.E4]: rgb[y:y2,x:x2]=(206,210,92)
            piece=board.piece_at(sq)
            if piece:
                rgba=image_array(piece_image(piece.symbol(),x2-x,theme))
                alpha=rgba[:,:,3:]/255
                rgb[y:y2,x:x2]=(rgba[:,:,:3]*alpha+rgb[y:y2,x:x2]*(1-alpha)).astype(np.uint8)
    return rgb

class VisionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.reader=Recognizer()
    def test_four_sets_orientation_resize_highlight(self):
        board=chess.Board()
        for move in ['e4','e5','Nf3','Nc6','Bc4','Nf6']: board.push_san(move)
        for theme in ['cburnett','merida']:
            for size,white_bottom in [(400,True),(600,False)]:
                with self.subTest(theme=theme,size=size,white_bottom=white_bottom):
                    img=render_board(board,size,theme,white_bottom,True)
                    detected,_,_=self.reader.read(img,white_bottom,board.turn)
                    self.assertEqual(board.board_fen(),detected.board_fen())
    def test_calibration(self):
        reader=self.reader
        old=reader.custom
        path=reader.path
        from pathlib import Path
        import tempfile
        with tempfile.TemporaryDirectory() as folder:
            reader.path=Path(folder)/'test.npz'
            reader.calibrate(render_board(chess.Board(),480),chess.Board(),True)
            self.assertEqual(len(reader.custom),32)
            reader.theme='Calibrated'
            board=chess.Board(); board.push_san('d4'); board.push_san('Nf6')
            detected,_,_=reader.read(render_board(board,480),True,board.turn)
            self.assertEqual(detected.board_fen(),board.board_fen())
        reader.custom=old; reader.path=path; reader.theme='Automatic'
    def test_board_detection_with_offset(self):
        screen=np.full((900,1400,3),(35,40,49),np.uint8)
        screen[140:652,210:722]=render_board(chess.Board())
        start=time.monotonic(); found=detect_boards(screen)
        print('Detection seconds:',round(time.monotonic()-start,2),'rectangles:',found)
        self.assertTrue(found)
        self.assertLess(sum(abs(a-b) for a,b in zip(found[0],(210,140,512,512))),15)
    def test_no_board(self): self.assertEqual(detect_boards(np.full((500,900,3),50,np.uint8)),[])

class LegalTrackingTests(unittest.TestCase):
    def check_transition(self,fen,moves):
        initial=chess.Board(fen); target=initial.copy()
        for move in moves: target.push_uci(move)
        # Recognition supplies piece placement, not hidden state.
        observed=chess.Board(None)
        observed.set_board_fen(target.board_fen())
        result,_=match_transition(initial,observed,[])
        self.assertIsNotNone(result)
        self.assertEqual(result.fen(),target.fen())
    def test_two_halfmoves(self): self.check_transition(chess.STARTING_FEN,['e2e4','e7e5'])
    def test_castling(self): self.check_transition('r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1',['e1g1'])
    def test_promotion(self): self.check_transition('7k/P7/8/8/8/8/8/7K w - - 0 1',['a7a8n'])
    def test_en_passant(self): self.check_transition('7k/8/8/3pP3/8/8/8/7K w - d6 0 1',['e5d6'])
    def test_illegal_is_rejected(self):
        current=chess.Board(); observed=current.copy(); observed.remove_piece_at(chess.E1)
        self.assertIsNone(match_transition(current,observed,[])[0])

class EngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.engine=open_engine()
    @classmethod
    def tearDownClass(cls): cls.engine.quit()
    def test_three_real_moves_and_lines(self):
        board=chess.Board(); result=analyse(self.engine,board,.5)
        self.assertEqual(len(result['moves']),3)
        self.assertEqual(len({m['uci'] for m in result['moves']}),3)
        for move in result['moves']:
            self.assertIn(chess.Move.from_uci(move['uci']),board.legal_moves)
            self.assertTrue(move['text']); self.assertTrue(move['line'])
    def test_black_perspective(self):
        board=chess.Board('7k/8/8/8/8/8/q7/7K b - - 0 1')
        result=analyse(self.engine,board,.2)
        self.assertGreater(result['moves'][0]['cp'],0)
    def test_terminal(self):
        board=chess.Board('7k/6Q1/6K1/8/8/8/8/8 b - - 0 1')
        self.assertEqual(analyse(self.engine,board,.1)['terminal'],'Checkmate')
    def test_invalid(self):
        with self.assertRaises(ValueError): analyse(self.engine,chess.Board(None),.1)

if __name__=='__main__': unittest.main(verbosity=2)
