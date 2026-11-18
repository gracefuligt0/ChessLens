from __future__ import annotations
import sys, json, threading, traceback, time, math, ctypes
from pathlib import Path
import numpy as np
import chess
from PySide6.QtCore import Qt, QTimer, Signal, QThread, QPointF, QRectF, QRect, QSettings
from PySide6.QtGui import QPainter, QColor, QPen, QFont, QPolygonF, QPixmap, QImage, QIcon, QKeySequence, QShortcut, QFontDatabase
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QLabel,
    QPushButton, QComboBox, QFrame, QScrollArea, QSplitter, QDialog, QDialogButtonBox,
    QLineEdit, QMessageBox, QCheckBox, QGridLayout, QFileDialog, QSizePolicy, QToolTip, QTabWidget)
from core import (ASSETS, DATA, COLORS, SYMBOLS, Recognizer, image_array, piece_image,
                  screen_square, open_engine, analyse, match_transition, detect_boards)

STYLE = '''
QWidget { background:#12171c; color:#e9eee9; font-family:"Segoe UI"; font-size:13px; }
QMainWindow { background:#12171c; }
QLabel { background:transparent; }
QLabel#eyebrow { color:#91a29b; font-size:11px; font-weight:700; letter-spacing:2px; }
QLabel#title { font-size:27px; font-weight:700; }
QLabel#subtle { color:#92a29b; }
QLabel#status { color:#b4c6b9; padding:10px; background:#1b2524; border-radius:8px; }
QFrame#panel { background:#1a2126; border:1px solid #2c363c; border-radius:13px; }
QPushButton { background:#263139; border:1px solid #38474e; border-radius:7px; padding:9px 14px; font-weight:600; }
QPushButton:hover { background:#34434b; border-color:#7c988c; }
QPushButton:pressed { background:#46584c; }
QPushButton:disabled { color:#66736f; border-color:#2c363c; }
QPushButton#primary { background:#a5df7d; color:#142315; border-color:#a5df7d; }
QPushButton#primary:hover { background:#bcf294; }
QPushButton:checked { background:#384d37; border-color:#a5df7d; }
QComboBox, QLineEdit { background:#202b32; border:1px solid #3c4a51; border-radius:6px; padding:7px; min-height:18px; }
QComboBox QAbstractItemView { background:#263139; selection-background-color:#4b684b; }
QCheckBox { spacing:7px; background:transparent; }
QScrollArea { border:none; background:transparent; }
QScrollBar:vertical { background:#192126; width:9px; }
QScrollBar::handle:vertical { background:#42524b; min-height:30px; border-radius:4px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height:0; }
QToolTip { background:#263139; color:white; border:1px solid #60756c; padding:7px; }
'''

def label(text, name=None, wrap=False):
    item=QLabel(text)
    if name: item.setObjectName(name)
    item.setWordWrap(wrap)
    return item

def button(text, callback, primary=False):
    item=QPushButton(text)
    if primary: item.setObjectName('primary')
    item.clicked.connect(callback)
    return item

class EngineThread(QThread):
    result=Signal(int,object)
    failure=Signal(int,str)
    ready=Signal(str)
    def __init__(self):
        super().__init__()
        self.condition=threading.Condition()
        self.pending=None
        self.stopping=False
    def submit(self, generation, board, seconds):
        with self.condition:
            self.pending=(generation,board.copy(),seconds)
            self.condition.notify()
    def run(self):
        engine=None
        try:
            engine=open_engine()
            self.ready.emit(engine.id.get('name','Stockfish'))
            while True:
                with self.condition:
                    while not self.pending and not self.stopping:
                        self.condition.wait()
                    if self.stopping: break
                    generation,board,seconds=self.pending
                    self.pending=None
                try:
                    self.result.emit(generation,analyse(engine,board,seconds))
                except Exception as exc:
                    self.failure.emit(generation,str(exc))
                    if isinstance(exc,chess.engine.EngineTerminatedError):
                        engine=open_engine()
        except Exception as exc:
            self.failure.emit(-1,str(exc))
        finally:
            if engine:
                try: engine.quit()
                except Exception: pass
    def stop(self):
        with self.condition:
            self.stopping=True
            self.condition.notify()
        self.wait(12000)

class BoardView(QWidget):
    squareClicked=Signal(int)
    def __init__(self, editable=False):
        super().__init__()
        self.board=chess.Board()
        self.white_bottom=True
        self.moves=[]
        self.selected=0
        self.uncertain=[]
        self.editable=editable
        self.images={s:piece_image(s,128) for s in SYMBOLS[1:]}
        self.setMinimumSize(280,280)
        self.setSizePolicy(QSizePolicy.Policy.Expanding,QSizePolicy.Policy.Expanding)
    def board_rect(self):
        size=min(self.width()-36,self.height()-36)
        return QRectF((self.width()-size)/2,(self.height()-size)/2,size,size)
    def center(self,sq):
        r,c=(7-chess.square_rank(sq),chess.square_file(sq)) if self.white_bottom else (chess.square_rank(sq),7-chess.square_file(sq))
        box=self.board_rect(); cell=box.width()/8
        return QPointF(box.x()+(c+.5)*cell,box.y()+(r+.5)*cell)
    def paintEvent(self,event):
        painter=QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        box=self.board_rect(); cell=box.width()/8
        painter.setPen(Qt.PenStyle.NoPen)
        for r in range(8):
            for c in range(8):
                sq=screen_square(r,c,self.white_bottom)
                rect=QRectF(box.x()+c*cell,box.y()+r*cell,cell,cell)
                painter.fillRect(rect,QColor('#dce2cf' if (r+c)%2==0 else '#6f8d71'))
                if sq in self.uncertain:
                    painter.fillRect(rect,QColor(235,163,61,95))
                if self.moves and self.selected<len(self.moves) and sq in [chess.Move.from_uci(self.moves[self.selected]['uci']).from_square,chess.Move.from_uci(self.moves[self.selected]['uci']).to_square]:
                    painter.fillRect(rect,QColor(181,230,85,80))
                piece=self.board.piece_at(sq)
                if piece:
                    painter.drawImage(rect.adjusted(cell*.025,cell*.025,-cell*.025,-cell*.025),self.images[piece.symbol()])
        painter.setFont(QFont('Segoe UI',9))
        painter.setPen(QColor('#92a49a'))
        for i in range(8):
            f='abcdefgh'[i if self.white_bottom else 7-i]
            rank=str(8-i if self.white_bottom else i+1)
            painter.drawText(QRectF(box.x()+i*cell,box.bottom()+3,cell,18),Qt.AlignmentFlag.AlignCenter,f)
            painter.drawText(QRectF(box.x()-20,box.y()+i*cell,16,cell),Qt.AlignmentFlag.AlignCenter,rank)
        # Draw alternatives first so the selected line remains most prominent.
        order=[i for i in range(len(self.moves)) if i!=self.selected]+([self.selected] if self.moves else [])
        for i in order:
            move=chess.Move.from_uci(self.moves[i]['uci'])
            a,b=self.center(move.from_square),self.center(move.to_square)
            color=QColor(COLORS[i]); color.setAlpha(235 if i==self.selected else 140)
            painter.setPen(QPen(color,cell*.11,Qt.PenStyle.SolidLine,Qt.PenCapStyle.RoundCap))
            v=b-a; length=math.hypot(v.x(),v.y())
            if not length: continue
            u=QPointF(v.x()/length,v.y()/length)
            tip=b-u*cell*.14
            end=tip-u*cell*.2
            painter.drawLine(a,end)
            normal=QPointF(-u.y(),u.x())*cell*.14
            painter.setPen(Qt.PenStyle.NoPen); painter.setBrush(color)
            painter.drawPolygon(QPolygonF([tip,end+normal,end-normal]))
            painter.setBrush(QColor(COLORS[i])); painter.drawEllipse(a,cell*.14,cell*.14)
            painter.setPen(QColor('#142019')); painter.setFont(QFont('Segoe UI',max(9,round(cell*.15)),QFont.Weight.Bold))
            painter.drawText(QRectF(a.x()-cell*.16,a.y()-cell*.16,cell*.32,cell*.32),Qt.AlignmentFlag.AlignCenter,str(i+1))
        painter.end()
    def mousePressEvent(self,event):
        box=self.board_rect()
        if box.contains(event.position()):
            c=int((event.position().x()-box.x())/(box.width()/8)); r=int((event.position().y()-box.y())/(box.height()/8))
            self.squareClicked.emit(screen_square(r,c,self.white_bottom))

class ReviewDialog(QDialog):
    def __init__(self, board, white_bottom, uncertain=None, parent=None, reference=None):
        super().__init__(parent)
        self.setWindowTitle('Review detected position — ChessLens')
        self.resize(900,690)
        self.board=board.copy()
        self.symbol='.'
        root=QVBoxLayout(self)
        root.addWidget(label('Check the position', 'title'))
        root.addWidget(label('Choose a piece, then click a square to correct it. Amber squares need a closer look.','subtle',True))
        row=QHBoxLayout(); root.addLayout(row,1)
        self.view=BoardView(True); self.view.board=self.board; self.view.white_bottom=white_bottom; self.view.uncertain=uncertain or []
        self.view.squareClicked.connect(self.place)
        if reference is not None:
            tabs=QTabWidget(); tabs.addTab(self.view,'Detected position')
            ref=QLabel(); ref.setAlignment(Qt.AlignmentFlag.AlignCenter)
            h,w=reference.shape[:2]
            img=QImage(reference.copy().tobytes(),w,h,w*3,QImage.Format.Format_RGB888).copy()
            ref.setPixmap(QPixmap.fromImage(img).scaled(450,450,Qt.AspectRatioMode.KeepAspectRatio,Qt.TransformationMode.SmoothTransformation))
            tabs.addTab(ref,'Original screen capture'); row.addWidget(tabs,1)
        else: row.addWidget(self.view,1)
        controls=QVBoxLayout(); row.addLayout(controls)
        controls.addWidget(label('PIECE PALETTE','eyebrow'))
        grid=QGridLayout()
        self.palette=[]
        for i,s in enumerate(SYMBOLS[1:]):
            btn=QPushButton(); btn.setIcon(QIcon(QPixmap.fromImage(piece_image(s,64)))); btn.setIconSize(QPixmap.fromImage(piece_image(s,40)).size()); btn.setFixedSize(58,54); btn.setCheckable(True)
            btn.setToolTip(('White ' if s.isupper() else 'Black ')+chess.piece_name(chess.Piece.from_symbol(s).piece_type))
            btn.clicked.connect(lambda checked,s=s:self.choose(s))
            grid.addWidget(btn,i//6,i%6); self.palette.append((s,btn))
        controls.addLayout(grid)
        erase=button('Erase square',lambda:self.choose('.')); erase.setCheckable(True); erase.setChecked(True)
        self.palette.append(('.',erase)); controls.addWidget(erase)
        controls.addWidget(label('SIDE TO MOVE','eyebrow'))
        self.turn=QComboBox(); self.turn.addItems(['White','Black']); self.turn.setCurrentIndex(0 if board.turn else 1); controls.addWidget(self.turn)
        controls.addWidget(label('CASTLING RIGHTS','eyebrow'))
        self.rights={}
        for text,key in [('White kingside','K'),('White queenside','Q'),('Black kingside','k'),('Black queenside','q')]:
            check=QCheckBox(text); check.setChecked(key in board.castling_xfen()); self.rights[key]=check; controls.addWidget(check)
        controls.addWidget(label('A screenshot cannot determine earlier king/rook moves or an en passant opportunity. Use FEN to preserve that history.','subtle',True))
        controls.addStretch()
        tools=QHBoxLayout(); tools.addWidget(button('Starting position',self.start)); tools.addWidget(button('Clear board',self.clear)); controls.addLayout(tools)
        self.error=label('','subtle',True); root.addWidget(self.error)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText('Confirm & analyse')
        buttons.accepted.connect(self.confirm); buttons.rejected.connect(self.reject); root.addWidget(buttons)
    def choose(self,symbol):
        self.symbol=symbol
        for s,btn in self.palette: btn.setChecked(s==symbol)
    def place(self,sq):
        self.board.set_piece_at(sq,chess.Piece.from_symbol(self.symbol) if self.symbol!='.' else None)
        if sq in self.view.uncertain: self.view.uncertain.remove(sq)
        self.view.update()
    def start(self):
        self.board=chess.Board(); self.view.board=self.board; self.view.uncertain=[]; self.view.update()
        self.turn.setCurrentIndex(0)
        for check in self.rights.values(): check.setChecked(True)
    def clear(self):
        self.board=chess.Board(None); self.view.board=self.board; self.view.update()
        for check in self.rights.values(): check.setChecked(False)
    def confirm(self):
        self.board.turn=self.turn.currentIndex()==0
        rights=''.join(key for key,check in self.rights.items() if check.isChecked())
        try:
            self.board.set_castling_fen(rights or '-')
            self.board.ep_square=None
            if not self.board.is_valid():
                raise ValueError('Check both kings, pawn placement, checks, and castling rights. This position is not legal.')
            self.accept()
        except ValueError as exc: self.error.setText(str(exc))

class RegionSelector(QDialog):
    def __init__(self, screen, shot):
        super().__init__(None,Qt.WindowType.FramelessWindowHint|Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('Select chessboard — ChessLens')
        self.screen=screen; self.shot=shot; self.a=None; self.b=None; self.region=None
        self.setGeometry(screen.geometry()); self.setCursor(Qt.CursorShape.CrossCursor)
        self.setMouseTracking(True)
    def paintEvent(self,event):
        p=QPainter(self); p.drawPixmap(self.rect(),self.shot)
        p.fillRect(self.rect(),QColor(0,0,0,100))
        if self.a and self.b:
            rect=QRect(self.a,self.b).normalized()
            sx=self.shot.width()/self.width(); sy=self.shot.height()/self.height()
            p.drawPixmap(rect,self.shot,QRect(round(rect.x()*sx),round(rect.y()*sy),round(rect.width()*sx),round(rect.height()*sy)))
            p.setPen(QPen(QColor('#b4ed8a'),3)); p.drawRect(rect)
            p.setPen(QPen(QColor(255,255,255,90),1))
            for i in range(1,8):
                p.drawLine(QPointF(rect.x()+rect.width()*i/8,rect.y()),QPointF(rect.x()+rect.width()*i/8,rect.bottom()))
                p.drawLine(QPointF(rect.x(),rect.y()+rect.height()*i/8),QPointF(rect.right(),rect.y()+rect.height()*i/8))
        p.fillRect(QRect(25,25,min(self.width()-50,760),70),QColor('#14201b'))
        p.setPen(QColor('white')); p.setFont(QFont('Segoe UI',15,QFont.Weight.Bold))
        p.drawText(42,55,'Drag around the 64 squares, from corner to corner')
        p.setFont(QFont('Segoe UI',11)); p.drawText(42,79,'Leave out coordinates and borders. Release to confirm. Esc cancels.')
    def mousePressEvent(self,event): self.a=event.position().toPoint(); self.b=self.a; self.update()
    def mouseMoveEvent(self,event):
        if self.a: self.b=event.position().toPoint(); self.update()
    def mouseReleaseEvent(self,event):
        self.b=event.position().toPoint(); rect=QRect(self.a,self.b).normalized().intersected(self.rect())
        if min(rect.width(),rect.height())<100: self.a=None; self.b=None; self.update(); return
        if abs(rect.width()-rect.height())/max(rect.width(),rect.height())>.08:
            self.a=None; self.b=None; self.update(); return
        sx=self.shot.width()/self.width(); sy=self.shot.height()/self.height()
        self.region=(round(rect.x()*sx),round(rect.y()*sy),round(rect.width()*sx),round(rect.height()*sy))
        self.accept()

class MoveCard(QFrame):
    clicked=Signal(int)
    def __init__(self,index):
        super().__init__(); self.index=index; self.setObjectName('panel'); self.setCursor(Qt.CursorShape.PointingHandCursor)
        root=QVBoxLayout(self); root.setContentsMargins(18,15,18,15); root.setSpacing(8)
        top=QHBoxLayout(); root.addLayout(top)
        self.rank=label(['01  BEST MOVE','02  SECOND CHOICE','03  THIRD CHOICE'][index],'eyebrow')
        self.rank.setStyleSheet(f'color:{COLORS[index]}'); top.addWidget(self.rank); top.addStretch()
        self.score=label('—'); self.score.setStyleSheet('font-size:23px; font-weight:700;'); top.addWidget(self.score)
        move_row=QHBoxLayout(); root.addLayout(move_row)
        self.move=label('Waiting for analysis'); self.move.setStyleSheet('font-size:23px; font-weight:650;'); move_row.addWidget(self.move)
        move_row.addStretch(); self.route=label('','subtle'); move_row.addWidget(self.route)
        self.text=label('The engine’s top moves and a plain-language explanation will appear here.','subtle',True); root.addWidget(self.text)
        self.verdict=label('',None,True); root.addWidget(self.verdict)
        self.line=label('',None,True); self.line.setStyleSheet('background:#131b20; border-radius:5px; padding:9px; color:#afc6b1; font-family:Consolas; font-size:12px;'); root.addWidget(self.line)
        self.line.hide()
    def set_move(self,move,selected=False):
        self.move.setText(move['san']); self.score.setText(move['score']); self.text.setText(move['text']); self.verdict.setText(move['verdict'])
        self.route.setText(move['uci'][:2]+'  →  '+move['uci'][2:4]+(' · promotion' if len(move['uci'])>4 else ''))
        self.line.setText(move['line']); self.line.show(); self.set_selected(selected)
    def set_selected(self,selected):
        self.setStyleSheet(f'QFrame#panel {{ border:1px solid {COLORS[self.index] if selected else "#2c363c"}; }}')
    def mousePressEvent(self,event): self.clicked.emit(self.index)

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle('ChessLens — Screen Chess Analysis')
        self.setMinimumSize(520,720); self.resize(610,min(1180,QApplication.primaryScreen().availableGeometry().height()-70))
        self.board=chess.Board(); self.region=None; self.last_crop=None; self.generation=0; self.results=[]; self.confirmed=False
        self.white_bottom=True
        self.pending_fingerprint=None; self.stable_frames=0; self.capture_busy=False; self.failures=0
        self.recognizer=Recognizer()
        self.settings=QSettings('ChessLens','ChessLens')
        self.worker=EngineThread(); self.worker.result.connect(self.on_result); self.worker.failure.connect(self.on_error); self.worker.ready.connect(self.on_ready)
        rootwidget=QWidget(); self.setCentralWidget(rootwidget); root=QVBoxLayout(rootwidget); root.setContentsMargins(26,22,26,15); root.setSpacing(16)
        header=QHBoxLayout(); root.addLayout(header)
        logo=label('♞'); logo.setStyleSheet('font-size:42px; color:#b1e88a;'); header.addWidget(logo)
        branding=QVBoxLayout(); branding.setSpacing(1); branding.addWidget(label('CHESSLENS','eyebrow')); branding.addWidget(label('Your screen. Your board.','title')); header.addLayout(branding); header.addStretch()
        header.addWidget(button('Help',self.help))
        displayrow=QHBoxLayout(); root.addLayout(displayrow)
        self.displays=QComboBox()
        for i,screen in enumerate(QApplication.screens()): self.displays.addItem(f'Display {i+1} · {screen.geometry().width()}×{screen.geometry().height()}',screen.name())
        displayrow.addWidget(self.displays,1)
        self.pin=QCheckBox('Always on top'); self.pin.toggled.connect(self.set_pin); displayrow.addWidget(self.pin)
        toolbar=QHBoxLayout(); root.addLayout(toolbar)
        toolbar.addWidget(button('Find board',lambda:self.begin_capture('auto'),True))
        toolbar.addWidget(button('Select board',lambda:self.begin_capture('select')))
        toolbar.addWidget(button('Rescan',self.scan))
        self.watch=QPushButton('Watch screen'); self.watch.setCheckable(True); self.watch.clicked.connect(self.toggle_watch); toolbar.addWidget(self.watch)
        self.status=label('Open a chessboard on your screen, then choose Find board. This panel analyses that board.','status',True); root.addWidget(self.status)
        opts=QHBoxLayout(); root.addLayout(opts)
        self.turn=QComboBox(); self.turn.addItems(['White to move','Black to move']); self.turn.currentIndexChanged.connect(self.change_turn); opts.addWidget(self.turn)
        self.orientation=QComboBox(); self.orientation.addItems(['White at bottom','Black at bottom']); self.orientation.currentIndexChanged.connect(self.flip); opts.addWidget(self.orientation)
        opts.addWidget(button('Recognition settings',self.recognition_settings))
        r=root
        titleline=QHBoxLayout(); titleline.addWidget(label('THREE WAYS FORWARD','eyebrow')); titleline.addStretch(); self.depth=QComboBox(); self.depth.addItems(['Quick · 1 s','Balanced · 3 s','Deep · 8 s']); self.depth.setCurrentIndex(1); titleline.addWidget(self.depth); r.addLayout(titleline)
        self.position_label=label('Waiting for a board on your screen','subtle'); r.addWidget(self.position_label)
        scroll=QScrollArea(); scroll.setWidgetResizable(True); scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        cardswidget=QWidget(); cardslayout=QVBoxLayout(cardswidget); cardslayout.setContentsMargins(0,0,4,0); cardslayout.setSpacing(12)
        self.cards=[MoveCard(i) for i in range(3)]
        self.empty=label('1   Open a chessboard in your browser or another app.\n\n2   Click Find board, or drag around it with Select board.\n\n3   Leave this panel beside the board. The top three moves update as the position changes.','subtle',True)
        self.empty.setStyleSheet('padding:24px 12px; font-size:16px; color:#a8bbb0;')
        cardslayout.addWidget(self.empty)
        for card in self.cards: card.clicked.connect(self.select_move); cardslayout.addWidget(card); card.hide()
        cardslayout.addStretch(); scroll.setWidget(cardswidget); r.addWidget(scroll,1)
        actionrow=QHBoxLayout(); self.analyse_button=button('Analyse screen',self.scan,True); actionrow.addWidget(self.analyse_button,1); actionrow.addWidget(button('Save report',self.save_report)); r.addLayout(actionrow)
        r.addWidget(label('Scores favour the side to move. Move explanations and analysis run locally.','subtle',True))
        self.engine_label=label('●  Starting Stockfish…','subtle'); root.addWidget(self.engine_label)
        self.timer=QTimer(self); self.timer.setInterval(1600); self.timer.timeout.connect(self.watch_tick)
        QShortcut(QKeySequence('Ctrl+Return'),self,activated=self.scan)
        QShortcut(QKeySequence('Escape'),self,activated=self.stop_watch)
        self.worker.start()
        available=QApplication.primaryScreen().availableGeometry()
        self.move(available.right()-self.width()-18,available.top()+30)
    def recognition_settings(self):
        dialog=QDialog(self); dialog.setWindowTitle('Screen recognition settings — ChessLens'); layout=QVBoxLayout(dialog)
        layout.addWidget(label('Screen recognition','title'))
        layout.addWidget(label('Choose a piece theme, or teach ChessLens the pieces from a captured starting position.','subtle',True))
        theme=QComboBox(); theme.addItems(['Automatic','neo','cburnett','merida','alpha','Calibrated']); theme.setCurrentText(self.recognizer.theme); theme.currentTextChanged.connect(self.theme_change); layout.addWidget(theme)
        layout.addWidget(button('Learn piece set from last capture',lambda:(dialog.accept(),self.calibrate())))
        layout.addWidget(button('Correct detected position / castling rights',lambda:(dialog.accept(),self.edit())))
        layout.addWidget(label('Exact position (optional FEN)','eyebrow'))
        fen=QLineEdit(self.board.fen() if self.confirmed else ''); fen.setMinimumWidth(430); layout.addWidget(fen)
        def load():
            try:
                board=chess.Board(fen.text().strip())
                if not board.is_valid(): raise ValueError('The position is not legal.')
                self.adopt(board,'Position history supplied by FEN'); dialog.accept()
            except ValueError as exc: QMessageBox.information(dialog,'Check position',str(exc))
        layout.addWidget(button('Use FEN for current screen board',load))
        layout.addWidget(button('Close',dialog.accept)); dialog.exec()
    def on_ready(self,name):
        self.engine_label.setText('●  '+name+' · ready')
    def current_screen(self):
        name=self.displays.currentData()
        return next((s for s in QApplication.screens() if s.name()==name),QApplication.primaryScreen())
    def set_pin(self,checked):
        self.setWindowFlag(Qt.WindowType.WindowStaysOnTopHint,checked); self.show()
    def theme_change(self,text): self.recognizer.theme=text; self.settings.setValue('theme',text)
    def set_status(self,text): self.status.setText(text)
    def clear_results(self):
        self.generation+=1; self.results=[]
        self.analyse_button.setText('Analyse screen')
        self.empty.show()
        for card in self.cards: card.hide()
    def adopt(self,board,title='Confirmed position'):
        self.clear_results(); self.board=board.copy(); self.confirmed=True
        self.turn.blockSignals(True); self.turn.setCurrentIndex(0 if board.turn else 1); self.turn.blockSignals(False)
        self.position_label.setText(title); self.pending_fingerprint=None
        self.request_analysis()
    def change_turn(self,index):
        if not self.confirmed: return
        self.stop_watch(); board=self.board.copy(); board.turn=index==0; board.clear_stack(); board.ep_square=None
        self.adopt(board)
    def flip(self,index):
        self.stop_watch(); self.white_bottom=index==0
        if self.region: self.scan()
    def edit(self):
        self.stop_watch(); dialog=ReviewDialog(self.board,self.white_bottom,parent=self,reference=self.last_crop)
        if dialog.exec(): self.adopt(dialog.board)
    def request_analysis(self,checked=False,example=False):
        if not self.confirmed or not self.region: self.set_status('Choose a chessboard on your screen first.'); return
        if not self.board.is_valid(): self.clear_results(); self.set_status('Correct the board before analysis: the current position is not legal.'); return
        self.generation+=1
        seconds=[1.0,3.0,8.0][self.depth.currentIndex()]
        self.worker.submit(self.generation,self.board,seconds)
        self.analyse_button.setText('Analysing…')
        if not example: self.set_status('Stockfish is comparing up to three moves…')
    def on_result(self,generation,payload):
        if generation!=self.generation: return
        self.analyse_button.setText('Analyse screen'); self.results=payload['moves']
        self.empty.setVisible(not self.results)
        if payload['terminal']: self.empty.setText('Game over · '+payload['terminal'])
        for i,card in enumerate(self.cards):
            card.setVisible(i<len(self.results))
            if i<len(self.results): card.set_move(self.results[i],i==0)
        if payload['terminal']: self.set_status('Game over · '+payload['terminal'])
        elif self.confirmed:
            depth=min(x['depth'] for x in self.results)
            self.set_status(f'{"Watching screen · " if self.watch.isChecked() else "Analysis ready · "}{"White" if self.board.turn else "Black"} to move · depth {depth} · {len(self.results)} candidates')
    def on_error(self,generation,message):
        if generation not in [-1,self.generation]: return
        self.analyse_button.setText('Analyse screen'); self.set_status('Analysis issue: '+message)
    def select_move(self,index):
        if index>=len(self.results): return
        for i,card in enumerate(self.cards): card.set_selected(i==index)
    def begin_capture(self,mode):
        self.stop_watch(); self.hide(); self.capture_busy=True
        QTimer.singleShot(450,lambda:self.capture_dialog(mode))
    def capture_dialog(self,mode):
        screen=self.current_screen(); shot=screen.grabWindow(0)
        if shot.isNull(): self.show(); self.capture_busy=False; self.set_status('This display could not be captured. Choose another display.'); return
        rgb=image_array(shot.toImage())[:,:,:3]
        region=None
        if mode=='auto':
            candidates=detect_boards(rgb)
            if candidates: region=candidates[0]
        if region is None:
            selector=RegionSelector(screen,shot)
            if selector.exec(): region=selector.region
        self.show(); self.capture_busy=False
        if region:
            self.region=(screen.name(),region,shot.width(),shot.height())
            self.park_beside_board()
            x,y,w,h=region; self.review_crop(rgb[y:y+h,x:x+w])
        else: self.set_status('Selection cancelled. Open a 2D chessboard and try again.')
    def park_beside_board(self):
        name,(x,y,w,h),sw,sh=self.region
        screen=next((s for s in QApplication.screens() if s.name()==name),None)
        if not screen: return
        geo=screen.geometry(); area=screen.availableGeometry(); sx=geo.width()/sw
        left=geo.x()+round(x*sx); right=geo.x()+round((x+w)*sx)
        if area.right()-right>self.width()+24:
            self.move(min(area.right()-self.width()-8,right+20),area.top()+20)
        elif left-area.left()>self.width()+24:
            self.move(max(area.left()+8,left-self.width()-20),area.top()+20)
    def crop(self):
        if not self.region: raise ValueError('Choose Find board or Select board first.')
        name,(x,y,w,h),sw,sh=self.region
        screen=next((s for s in QApplication.screens() if s.name()==name),None)
        if not screen: raise ValueError('The selected display is no longer connected. Select the board again.')
        geo=screen.geometry(); sx=geo.width()/sw; sy=geo.height()/sh
        globalrect=QRect(round(geo.x()+x*sx),round(geo.y()+y*sy),round(w*sx),round(h*sy))
        if self.isVisible() and not self.isMinimized() and self.frameGeometry().intersects(globalrect):
            raise ValueError('Move ChessLens beside the chessboard so the captured squares stay visible.')
        shot=screen.grabWindow(0)
        if shot.width()!=sw or shot.height()!=sh: raise ValueError('Display size changed. Select the board again.')
        rgb=image_array(shot.toImage())[:,:,:3]
        return rgb[y:y+h,x:x+w]
    def scan(self):
        self.stop_watch()
        if not self.region: self.begin_capture('select'); return
        self.hide(); QTimer.singleShot(400,self.scan_hidden)
    def scan_hidden(self):
        try: crop=self.crop()
        except Exception as exc: self.show(); self.set_status(str(exc)); return
        self.show(); self.review_crop(crop)
    def review_crop(self,crop):
        self.last_crop=crop.copy()
        board,costs,uncertain=self.recognizer.read(crop,self.white_bottom,self.turn.currentIndex()==0)
        # Exact positions can retain known hidden state when the screen matches.
        if board.board_fen()==self.board.board_fen(): board=self.board.copy()
        if board.is_valid() and len(uncertain)<=3:
            self.adopt(board,'Reading your screen · '+('White' if board.turn else 'Black')+' to move')
            self.watch.setChecked(True); self.toggle_watch(True)
        else:
            self.clear_results(); self.confirmed=False
            self.board=board; self.position_label.setText('Screen recognition needs a correction')
            self.set_status('Some pieces could not be read confidently. Try the correct piece set in Recognition settings, or correct the detected position.')
    def calibrate(self):
        self.stop_watch()
        if self.last_crop is None: self.set_status('Select or scan a board before learning its piece set.'); return
        dialog=ReviewDialog(self.board,self.white_bottom,parent=self,reference=self.last_crop)
        dialog.setWindowTitle('Confirm the captured position for calibration — ChessLens')
        if dialog.exec():
            try:
                self.recognizer.calibrate(self.last_crop,dialog.board,self.white_bottom)
                self.theme_change('Calibrated'); self.adopt(dialog.board)
                self.set_status('Piece set learned from the last capture. Keep the board size and theme unchanged.')
            except ValueError as exc: self.set_status(str(exc))
    def toggle_watch(self,checked):
        if checked:
            if not self.region or not self.confirmed:
                self.watch.setChecked(False); self.set_status('Select a screen board and confirm the position before watching.'); return
            self.watch.setText('Stop watching'); self.timer.start(); self.pending_fingerprint=None; self.failures=0
            self.set_status('Watching for stable, legal board changes. Keep the screen board visible.'); self.watch_tick()
        else: self.stop_watch()
    def stop_watch(self):
        self.timer.stop(); self.watch.setChecked(False); self.watch.setText('Watch screen')
    def watch_tick(self):
        if self.capture_busy: return
        try:
            crop=self.crop(); self.last_crop=crop.copy()
            observed,costs,uncertain=self.recognizer.read(crop,self.white_bottom,self.board.turn)
            fingerprint=observed.board_fen()
            if fingerprint!=self.pending_fingerprint:
                self.pending_fingerprint=fingerprint; self.stable_frames=1; return
            self.stable_frames+=1
            if self.stable_frames<2: return
            candidate,kind=match_transition(self.board,observed,costs)
            if candidate is None:
                self.failures+=1
                if self.failures>=2:
                    self.clear_results(); self.set_status(kind+' Suggestions hidden until the screen matches.'); self.position_label.setText('Screen needs review')
                return
            self.failures=0
            if kind!='unchanged':
                self.adopt(candidate,'Live screen · legal move tracked')
            elif not self.results and self.analyse_button.text()!='Analysing…': self.request_analysis()
        except Exception as exc:
            self.stop_watch(); self.clear_results(); self.set_status(str(exc))
    def save_report(self):
        if not self.results: self.set_status('Analyse a position before saving a report.'); return
        path,_=QFileDialog.getSaveFileName(self,'Save analysis report','ChessLens-analysis.txt','Text files (*.txt)')
        if path:
            parts=['CHESSLENS ANALYSIS',f'FEN: {self.board.fen()}','Scores favour the side to move.','']
            for i,m in enumerate(self.results): parts.extend([f'{i+1}. {m["san"]}  {m["score"]}  (depth {m["depth"]})',m['text'],m['verdict'],m['line'],''])
            Path(path).write_text('\n'.join(parts),encoding='utf-8'); self.set_status('Report saved.')
    def help(self):
        QMessageBox.information(self,'Using ChessLens',
            '1. Open a visible 2D chessboard, then choose Find board or Select board.\n'
            '2. Set whose turn it is and the board orientation using the two controls.\n'
            '3. The three best moves and explanations appear in this side panel. There is no separate game board.\n'
            '4. ChessLens watches the selected screen area automatically. Keep the board visible. Esc stops watching.\n\n'
            'Recognition: Chess.com Neo and Lichess cburnett, merida and alpha are included. For another theme, capture a starting position, correct it, then choose Learn this set. Recalibrate after changing theme or size.\n\n'
            'Screenshots do not reveal move history. Recognition settings lets you correct misread pieces, set castling rights, or supply FEN for exact state including en passant. A recognised starting position retains all castling rights. Other newly scanned positions start with no castling rights until supplied. Watching preserves legal move history.\n\n'
            'All capture and analysis stays on this device. Explanations are factual, locally generated descriptions; Stockfish does not itself provide prose. Scores are pawns from the current player’s perspective; M indicates mate.\n\n'
            'Keyboard: Ctrl+Enter scans the selected screen board. Esc stops watching.\n\n'
            'ChessLens is GPL-3.0-or-later. Source and third-party notices are included in the ChessLens folder.')
    def closeEvent(self,event):
        self.stop_watch(); self.worker.stop(); event.accept()

def initialize_fonts():
    # Also works with Qt's offscreen renderer, which does not enumerate Windows fonts.
    import os
    folder=Path(os.environ.get('WINDIR','C:/Windows'))/'Fonts'
    for name in ['segoeui.ttf','segoeuib.ttf','seguisym.ttf','consola.ttf']:
        if (folder/name).exists(): QFontDatabase.addApplicationFont(str(folder/name))

def main():
    app=QApplication(sys.argv); initialize_fonts(); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    app.setApplicationName('ChessLens'); app.setOrganizationName('ChessLens')
    window=MainWindow()
    # Generated vector icon stays crisp at Windows display scaling.
    icon=QPixmap(64,64); icon.fill(QColor('#18241c')); p=QPainter(icon); p.setPen(QColor('#b1e88a')); p.setFont(QFont('Segoe UI Symbol',42)); p.drawText(icon.rect(),Qt.AlignmentFlag.AlignCenter,'♞'); p.end()
    app.setWindowIcon(QIcon(icon))
    if '--self-test' in sys.argv:
        output=Path(sys.argv[sys.argv.index('--self-test')+1])
        def complete(generation,payload):
            if generation!=window.generation: return
            try:
                assert len(window.results)==3
                assert not window.findChildren(BoardView)
                assert window.board.fen()==chess.STARTING_FEN
                assert window.results[0]['cp']>=window.results[1]['cp']>=window.results[2]['cp']
                window.resize(610,1180); window.grab().save(str(output.with_suffix('.png')))
                output.write_text(json.dumps({'passed':True,'packaged':bool(getattr(sys,'frozen',False)),
                    'engine':window.engine_label.text(),'recognized_screen_fixture':True,'main_board_widgets':0,
                    'moves':window.results},indent=2),encoding='utf-8')
            except Exception:
                output.write_text(traceback.format_exc(),encoding='utf-8')
            finally: window.close(); app.quit()
        window.worker.result.connect(complete)
        # A rendered external-board fixture exercises the packaged vision assets and engine together.
        rgb=np.zeros((512,512,3),np.uint8)
        for r in range(8):
            for c in range(8):
                cell=rgb[r*64:(r+1)*64,c*64:(c+1)*64]; cell[:]=(238,238,210) if (r+c)%2==0 else (118,150,86)
                piece=chess.Board().piece_at(screen_square(r,c,True))
                if piece:
                    rgba=image_array(piece_image(piece.symbol(),64,'neo')); alpha=rgba[:,:,3:]/255
                    cell[:]=(rgba[:,:,:3]*alpha+cell*(1-alpha)).astype(np.uint8)
        window.region=('self-test',(0,0,512,512),1920,1080)
        window.toggle_watch=lambda checked:None
        window.review_crop(rgb)
        def timeout():
            if not output.exists(): output.write_text('Self-test timed out',encoding='utf-8')
            window.close(); app.quit()
        QTimer.singleShot(25000,timeout)
    else: window.show()
    return app.exec()

if __name__=='__main__':
    try: sys.exit(main())
    except Exception:
        DATA.mkdir(parents=True,exist_ok=True); (DATA/'last-error.txt').write_text(traceback.format_exc(),encoding='utf-8')
        raise
