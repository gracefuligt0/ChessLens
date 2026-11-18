import os
os.environ.setdefault('QT_QPA_PLATFORM','offscreen')
import unittest
from pathlib import Path
import numpy as np
import chess
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QImage
from PySide6.QtCore import Qt,QEventLoop,QTimer
from core import image_array,Recognizer,match_transition
from overlay import ScreenReader,ArrowOverlay,orient_board

APP=QApplication.instance() or QApplication([])
FIXTURE=Path(__file__).parent/'tests/fixtures/chesscom-start.png'

class ActualScreenTests(unittest.TestCase):
    def setUp(self): self.worker=ScreenReader(Recognizer())
    def screen(self,rgb): return {'name':'fixture','rgb':rgb,'geometry':(0,0,rgb.shape[1],rgb.shape[0])}
    def test_real_start_and_automatic_calibration(self):
        rgb=image_array(QImage(str(FIXTURE)))[:,:,:3]
        frame=self.worker.inspect(self.screen(rgb),(0,0,1176,1176))
        self.assertIsNotNone(frame)
        self.assertEqual(frame['board'].fen(),chess.STARTING_FEN)
        self.assertEqual(len(self.worker.reader.custom),32)
    def test_small_live_browser_board(self):
        rgb=image_array(QImage(str(FIXTURE.with_name('chesscom-small-start.png'))))[:,:,:3]
        frame=self.worker.inspect(self.screen(rgb),(0,0,616,616))
        self.assertIsNotNone(frame)
        self.assertEqual(frame['board'].fen(),chess.STARTING_FEN)
    def test_reacquires_grid_shifted_by_one_rank(self):
        from unittest.mock import patch
        board=image_array(QImage(str(FIXTURE.with_name('chesscom-small-start.png'))))[:,:,:3]
        rgb=np.full((700,616,3),30,np.uint8); rgb[:616]=board
        loop=QEventLoop(); frames=[]
        def receive(frame): frames.append(frame); loop.quit()
        self.worker.frame.connect(receive)
        with patch('overlay.detect_boards',return_value=[(0,77,616,616)]):
            self.worker.start()
            try:
                self.worker.submit([self.screen(rgb)],{'orientation':'Automatic','theme':'Automatic'})
                QTimer.singleShot(12000,loop.quit); loop.exec()
            finally: self.worker.stop()
        self.assertTrue(frames)
        self.assertIsNotNone(frames[0])
        self.assertEqual(frames[0]['rect'],(0,0,616,616))
        self.assertEqual(frames[0]['board'].fen(),chess.STARTING_FEN)
    def test_actual_piece_images_follow_e4_e5(self):
        rgb=image_array(QImage(str(FIXTURE)))[:,:,:3]
        initial=self.worker.inspect(self.screen(rgb),(0,0,1176,1176))
        state=chess.Board()
        for source_row,dest_row,col,move in [(6,4,4,'e2e4'),(1,3,4,'e7e5')]:
            cell=147; patch=rgb[source_row*cell:(source_row+1)*cell,col*cell:(col+1)*cell].copy()
            bg=patch[20,125].copy()
            rgb[dest_row*cell:(dest_row+1)*cell,col*cell:(col+1)*cell]=patch
            rgb[source_row*cell:(source_row+1)*cell,col*cell:(col+1)*cell]=bg
            frame=self.worker.inspect(self.screen(rgb),(0,0,1176,1176))
            self.assertIsNotNone(frame)
            tracked,_=match_transition(state,frame['board'],frame['costs'])
            self.assertIsNotNone(tracked)
            state.push_uci(move)
            self.assertEqual(tracked.fen(),state.fen())
    def test_flipped_screen_orientation(self):
        rgb=image_array(QImage(str(FIXTURE)))[:,:,:3]
        # Rotate square placement while keeping the pieces upright, like a browser's flipped board.
        flipped=np.empty_like(rgb)
        for row in range(8):
            for col in range(8):
                flipped[(7-row)*147:(8-row)*147,(7-col)*147:(8-col)*147]=rgb[row*147:(row+1)*147,col*147:(col+1)*147]
        frame=self.worker.inspect(self.screen(flipped),(0,0,1176,1176))
        self.assertIsNotNone(frame)
        self.assertFalse(frame['white_bottom'])
        self.assertEqual(frame['board'].fen(),chess.STARTING_FEN)
    def test_click_through_arrow_coordinates(self):
        overlay=ArrowOverlay(); overlay.setGeometry(100,200,800,800)
        self.assertTrue(overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents))
        self.assertEqual((overlay.center(chess.E4).x(),overlay.center(chess.E4).y()),(450,450))
        overlay.white_bottom=False
        self.assertEqual((overlay.center(chess.E4).x(),overlay.center(chess.E4).y()),(350,350))
        overlay.close()

if __name__=='__main__': unittest.main(verbosity=2)
