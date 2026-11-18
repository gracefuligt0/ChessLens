"""ChessLens 2: automatically detected screen board, click-through move arrows."""
from __future__ import annotations
import sys, os, json, math, time, threading, traceback, ctypes
from pathlib import Path
import numpy as np
import chess
from PySide6.QtCore import Qt, QThread, Signal, QTimer, QRect, QRectF, QPointF, QSettings
from PySide6.QtGui import (QPainter,QColor,QPen,QFont,QPolygonF,QPixmap,QIcon,QAction,QImage,
                         QGuiApplication,QCursor)
from PySide6.QtWidgets import (QApplication,QWidget,QLabel,QVBoxLayout,QHBoxLayout,QPushButton,
    QFrame,QSystemTrayIcon,QMenu,QDialog,QComboBox,QDialogButtonBox,QCheckBox,QMessageBox)
from core import (Recognizer,screen_square,match_transition,detect_boards,image_array,
                  COLORS,DATA,SYMBOLS)
from app import RegionSelector,ReviewDialog,initialize_fonts
from fast_analysis import FastEngineThread
from instance_guard import InstanceGuard
from tab_bridge import TabBridge,GUIDE_COLORS,IDEA_COLOR,NATURAL_COLOR,marker_color,VISUAL_TITLES
from celebrations import BrilliantCelebration,SOUND_NAMES,play_clip,import_custom_sound
from PySide6.QtWidgets import QFileDialog,QScrollArea

STYLE='''
QWidget { color:#e9f0e9; font-family:"Segoe UI"; font-size:12px; }
QFrame#bubble { background:#151d21; border:1px solid #46564a; border-radius:12px; }
QLabel { background:transparent; }
QPushButton { background:#25322f; border:1px solid #3c5145; border-radius:6px; padding:5px 8px; text-align:left; }
QPushButton:hover { background:#3b5140; }
QPushButton#move { background:#1c2827; padding:7px 9px; }
QComboBox { color:#edf2eb; background:#26332d; padding:7px; border:1px solid #59715d; }
QComboBox QAbstractItemView { background:#26332d; selection-background-color:#4a6b42; }
QDialog { background:#17221d; }
QMenu { background:#17221d; border:1px solid #59715d; padding:6px; }
QMenu::item:selected { background:#3b5140; }
QToolTip { background:#17221d; color:white; border:1px solid #59715d; }
'''

def exclude_capture(widget):
    """Exclude our own UI so the vision reader sees the original board pixels."""
    if sys.platform!='win32': return False
    user=ctypes.WinDLL('user32',use_last_error=True)
    user.SetWindowDisplayAffinity.argtypes=[ctypes.c_void_p,ctypes.c_uint]
    user.SetWindowDisplayAffinity.restype=ctypes.c_bool
    return bool(user.SetWindowDisplayAffinity(ctypes.c_void_p(int(widget.winId())),0x11))

def rotated_board(board):
    result=chess.Board(None)
    for sq,piece in board.piece_map().items(): result.set_piece_at(63-sq,piece)
    result.turn=board.turn
    return result

def orient_board(board,preference='Automatic'):
    if preference=='Black at bottom': return rotated_board(board),False
    if preference=='White at bottom': return board,True
    white=[chess.square_rank(s) for s,p in board.piece_map().items() if p.color]
    black=[chess.square_rank(s) for s,p in board.piece_map().items() if not p.color]
    # Most pieces remain nearer their own side. A saved/manual orientation can override this.
    white_bottom=not(white and black and np.mean(white)>np.mean(black))
    return (board,True) if white_bottom else (rotated_board(board),False)

def guess_turn(rgb,white_bottom):
    """Read a likely last-move highlight; return None when the pixels cannot establish the turn."""
    h,w=rgb.shape[:2]
    samples=[]
    for r in range(8):
        for c in range(8):
            # Avoid the rank/file text inside Chess.com's left and bottom edges.
            y=round((r+.12)*h/8); x=round((c+.88)*w/8)
            samples.append(rgb[y,x].astype(float))
    samples=np.array(samples)
    base=[np.median(samples[[i for i in range(64) if (i//8+i%8)%2==parity]],axis=0) for parity in [0,1]]
    unusual=[i for i in range(64) if np.linalg.norm(samples[i]-base[(i//8+i%8)%2])>55]
    if len(unusual)!=2: return None
    return unusual

class ScreenReader(QThread):
    frame=Signal(object)
    problem=Signal(str)
    def __init__(self,reader):
        super().__init__(); self.reader=reader; self.condition=threading.Condition()
        self.pending=None; self.stopping=False; self.cached=None; self.bad=0; self.last_discovery=0
        self.orientation='Automatic'; self.theme='Automatic'; self.learned_key=None
        self.auto_orientation=None
        self.discovery_details=[]
    def submit(self,screens,options):
        with self.condition:
            self.pending=(screens,options); self.condition.notify()
    def reset(self):
        with self.condition: self.cached=None; self.learned_key=None; self.auto_orientation=None
    def run(self):
        while True:
            with self.condition:
                while self.pending is None and not self.stopping: self.condition.wait()
                if self.stopping: return
                screens,options=self.pending; self.pending=None
            try:
                self.orientation=options['orientation']; self.theme=options['theme']; self.reader.theme=self.theme
                found=None
                cropped=next((s for s in screens if s.get('capture_rect') is not None),None)
                if cropped is not None:
                    height,width=cropped['rgb'].shape[:2]
                    found=self.inspect(cropped,(0,0,width,height))
                    if found is not None:
                        found['rect']=cropped['capture_rect']; found['dimensions']=cropped['dimensions']; self.bad=0
                    else: self.bad+=1
                    self.frame.emit(found); continue
                if self.cached:
                    name,rect,shape=self.cached
                    screen=next((s for s in screens if s['name']==name and s['rgb'].shape[:2]==shape),None)
                    if screen:
                        found=self.inspect(screen,rect)
                        if found is None: self.bad+=1
                        else: self.bad=0
                    else: self.cached=None
                if found is None and (self.cached is None or self.bad>=2):
                    self.cached=None
                    self.discovery_details=[]
                    for screen in screens:
                        rectangles=detect_boards(screen['rgb'])[:3]
                        self.discovery_details.append({'screen':screen['name'],'shape':screen['rgb'].shape[:2],'candidates':rectangles})
                        for rect in rectangles:
                            x,y,w,h=rect
                            # A checker pattern is periodic: edge-only detection can land one rank/file away.
                            # Validate neighbouring phases against the actual pieces before locking the region.
                            for dx,dy in [(0,0),(0,-1),(0,1),(-1,0),(1,0),(-1,-1),(1,-1),(-1,1),(1,1)]:
                                adjusted=(x+round(dx*w/8),y+round(dy*h/8),w,h)
                                found=self.inspect(screen,adjusted)
                                if found is not None:
                                    self.cached=(screen['name'],adjusted,screen['rgb'].shape[:2]); self.bad=0; break
                            if found is not None: break
                        if found is not None: break
                self.frame.emit(found)
            except Exception as exc:
                self.problem.emit(str(exc)); self.frame.emit(None)
    def inspect(self,screen,rect):
        x,y,w,h=rect; rgb=screen['rgb']
        if min(w,h)<128 or x<0 or y<0 or x+w>rgb.shape[1] or y+h>rgb.shape[0]: return None
        crop=rgb[y:y+h,x:x+w]
        raw,costs,uncertain=self.reader.read(crop,True)
        # Resolve ambiguous colours/shapes in a starting arrangement using all 64 squares.
        # Occupancy must match exactly, and every adjusted label must already be a close visual match.
        for seed in [chess.Board(),rotated_board(chess.Board())]:
            occupancy=all(bool(raw.piece_at(sq))==bool(seed.piece_at(sq)) for sq in chess.SQUARES)
            different=sum(raw.piece_at(sq)!=seed.piece_at(sq) for sq in chess.SQUARES)
            close=all(row[(seed.piece_at(sq).symbol() if seed.piece_at(sq) else '.')]-min(row.values())<.018 for sq,row in costs)
            if occupancy and different<=3 and close:
                raw=seed.copy(); break
        preference=self.orientation
        if preference=='Automatic':
            if raw.board_fen()==chess.Board().board_fen(): self.auto_orientation=True
            elif rotated_board(raw).board_fen()==chess.Board().board_fen(): self.auto_orientation=False
            if self.auto_orientation is not None: preference='White at bottom' if self.auto_orientation else 'Black at bottom'
        board,white_bottom=orient_board(raw,preference)
        if not board.is_valid(): board.turn=not board.turn
        if not board.is_valid() or len(uncertain)>10: return None
        total=sum(min(row.values()) for _,row in costs)/64
        if total>.045: return None
        if self.orientation=='Automatic': self.auto_orientation=white_bottom
        # Seeing a fully recognised starting arrangement gives us labelled examples of every piece.
        initial=board.board_fen()==chess.Board().board_fen()
        key=(screen['name'],screen.get('capture_rect',rect),white_bottom)
        if initial and self.learned_key!=key:
            # Keep auto-learning in memory: no existing saved custom set is overwritten.
            oldpath=self.reader.path
            from tempfile import TemporaryDirectory
            with TemporaryDirectory() as folder:
                self.reader.path=Path(folder)/'calibration.npz'
                self.reader.calibrate(crop,board,white_bottom)
            self.reader.path=oldpath; self.learned_key=key
        if initial: board=chess.Board()
        last_highlights=guess_turn(crop,white_bottom)
        inferred_turn=None
        if last_highlights:
            occupied=[board.piece_at(screen_square(i//8,i%8,white_bottom)) for i in last_highlights]
            occupied=[p for p in occupied if p]
            if len(occupied)==1: inferred_turn=not occupied[0].color
        if inferred_turn is not None: board.turn=inferred_turn
        if not board.is_valid(): board.turn=not board.turn
        return {'screen':screen['name'],'rect':rect,'dimensions':(rgb.shape[1],rgb.shape[0]),
                'geometry':screen['geometry'],'board':board,'white_bottom':white_bottom,
                'initial':initial,'inferred_turn':inferred_turn,'uncertain':len(uncertain),'costs':costs,'crop':crop}
    def stop(self):
        with self.condition: self.stopping=True; self.condition.notify()
        self.wait(15000)

class ArrowOverlay(QWidget):
    def __init__(self):
        super().__init__(None,Qt.WindowType.FramelessWindowHint|Qt.WindowType.Tool|
            Qt.WindowType.WindowStaysOnTopHint|Qt.WindowType.WindowTransparentForInput|
            Qt.WindowType.WindowDoesNotAcceptFocus)
        self.setWindowTitle('ChessLens move highlights')
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.moves=[]; self.white_bottom=True; self.selected=0; self.excluded=False
    def position(self,frame):
        x,y,w,h=frame['rect']; sw,sh=frame['dimensions']; gx,gy,gw,gh=frame['geometry']
        self.setGeometry(round(gx+x*gw/sw),round(gy+y*gh/sh),round(w*gw/sw),round(h*gh/sh))
        self.white_bottom=frame['white_bottom']
    def center(self,square):
        r,c=(7-chess.square_rank(square),chess.square_file(square)) if self.white_bottom else (chess.square_rank(square),7-chess.square_file(square))
        return QPointF((c+.5)*self.width()/8,(r+.5)*self.height()/8)
    def set_moves(self,moves):
        if moves is self.moves and self.isVisible(): return
        self.moves=moves
        if moves:
            self.show(); self.excluded=exclude_capture(self); self.update()
        else: self.hide()
    def paintEvent(self,event):
        p=QPainter(self); p.setRenderHint(QPainter.RenderHint.Antialiasing)
        cell=min(self.width(),self.height())/8
        if not self.moves: return
        sources={}; destinations={}
        for index,item in enumerate(self.moves[:5]):
            move=chess.Move.from_uci(item['uci'])
            color=QColor(marker_color(item,index)); dot=max(5,min(10,cell*.1)); font=max(9,min(14,cell*.17))
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(color)
            center=self.center(move.from_square); stack=sources.get(move.from_square,0);sources[move.from_square]=stack+1
            p.drawRect(QRectF(center.x()-cell/2+2,center.y()-cell/2+2+stack*(dot+2),dot,dot))
            center=self.center(move.to_square);stack=destinations.get(move.to_square,0);destinations[move.to_square]=stack+1
            p.setFont(QFont('Arial',round(font),QFont.Weight.Bold))
            text=('NAT ' if item.get('natural') else 'IDEA ' if item.get('creative') else 'P ' if item.get('premove') else '!! ' if item.get('brilliant') else '')+item['score']
            height=font+5;width=min(cell-4,p.fontMetrics().horizontalAdvance(text)+6)
            rect=QRectF(center.x()-cell/2+2,center.y()-cell/2+2+stack*(height+2),width,height)
            p.setPen(Qt.PenStyle.NoPen);p.setBrush(color);p.drawRect(rect)
            if item.get('premove'):p.setPen(QPen(QColor('#172d28'),1,Qt.PenStyle.DashLine));p.setBrush(Qt.BrushStyle.NoBrush);p.drawRect(rect)
            p.setPen(QColor('#ffffff' if item.get('creative') else '#061510'));p.drawText(rect,Qt.AlignmentFlag.AlignCenter,text)

class Bubble(QWidget):
    pauseClicked=Signal()
    settingsClicked=Signal()
    moveClicked=Signal(int)
    quitClicked=Signal()
    sideClicked=Signal()
    connectClicked=Signal()
    def __init__(self):
        super().__init__(None,Qt.WindowType.FramelessWindowHint|Qt.WindowType.Tool|Qt.WindowType.WindowStaysOnTopHint)
        self.setWindowTitle('ChessLens — Auto Overlay'); self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.drag_origin=None; self.user_moved=False; self.expanded=False; self.moves=[]; self.setFixedWidth(310)
        outer=QVBoxLayout(self); outer.setContentsMargins(0,0,0,0)
        frame=QFrame(); frame.setObjectName('bubble'); outer.addWidget(frame)
        root=QVBoxLayout(frame); root.setContentsMargins(12,9,12,10); root.setSpacing(7)
        top=QHBoxLayout(); root.addLayout(top)
        title=QLabel('♞  CHESSLENS'); title.setStyleSheet('color:#ade181; font-weight:700; letter-spacing:1px;'); top.addWidget(title); top.addStretch()
        self.pause=QPushButton('Ⅱ'); self.pause.setToolTip('Pause / resume automatic scanning'); self.pause.clicked.connect(self.pauseClicked); top.addWidget(self.pause)
        settings=QPushButton('⚙'); settings.setToolTip('Options'); settings.clicked.connect(self.settingsClicked); top.addWidget(settings)
        close=QPushButton('×'); close.setToolTip('Quit ChessLens'); close.clicked.connect(self.quitClicked); top.addWidget(close)
        self.status=QLabel('Looking for a chessboard…'); self.status.setWordWrap(True); self.status.setStyleSheet('color:#b7c7ba;'); root.addWidget(self.status)
        self.side=QPushButton('Playing: Auto (bottom side)'); self.side.setStyleSheet('color:#a8b9ad; font-size:11px; padding:3px 6px;'); self.side.clicked.connect(self.sideClicked); root.addWidget(self.side)
        self.connect=QPushButton('Connect browser · one-time setup');self.connect.clicked.connect(self.connectClicked);root.addWidget(self.connect)
        self.brilliant=QLabel('!!  BRILLIANT CANDIDATE'); self.brilliant.setStyleSheet('color:#29e2d0; font-weight:700;'); self.brilliant.hide(); root.addWidget(self.brilliant)
        self.brilliant.setToolTip('A near-best material sacrifice checked with Stockfish. This is a local heuristic, not an official Chess.com grade.')
        self.buttons=[]
        for i in range(5):
            btn=QPushButton(); btn.setObjectName('move'); btn.hide(); btn.clicked.connect(lambda checked=False,i=i:self.moveClicked.emit(i)); root.addWidget(btn); self.buttons.append(btn)
        self.explanation=QLabel(); self.explanation.setWordWrap(True); self.explanation.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse); self.explanation.setStyleSheet('color:#e0e9dc; padding:6px 0;'); self.explanation.hide(); root.addWidget(self.explanation)
        self.line=QLabel(); self.line.setWordWrap(True); self.line.setStyleSheet('color:#a5c4a2; font-family:Consolas; font-size:11px;'); self.line.hide(); root.addWidget(self.line)
        self.set_moves([])
    def set_status(self,text): self.status.setText(text); self.resize_to_contents()
    def set_moves(self,moves):
        expanded_uci=self.moves[self.property('selected')]['uci'] if self.expanded and isinstance(self.property('selected'),int) and self.property('selected')<len(self.moves) else None
        self.moves=moves
        self.brilliant.setVisible(any(m.get('brilliant',False) for m in moves))
        for i,btn in enumerate(self.buttons):
            btn.setVisible(i<len(moves))
            if i<len(moves):
                m=moves[i]; mark='PREMOVE  ' if m.get('premove') else '!!  ' if m.get('brilliant',False) else ''
                rank='NATURAL  ' if m.get('natural') else 'BLUE IDEA  ' if m.get('creative') else '' if m.get('premove') else ['1 BEST  ','2 SECOND  ','3 THIRD  '][min(i,2)]
                btn.setText(f'{rank}{mark}{m["san"]}    {m["uci"][:2]} → {m["uci"][2:4]}     {m["score"]}')
                color=NATURAL_COLOR if m.get('natural') else IDEA_COLOR if m.get('creative') else '#29e2d0' if m.get('brilliant',False) else GUIDE_COLORS[min(i,2)]
                btn.setStyleSheet(f'color:{color};'); btn.setToolTip(m.get('natural_reason',m.get('idea_reason',m.get('brilliant_reason','')))+' '+m['text']+' '+m['verdict'])
        self.explanation.hide(); self.line.hide(); self.expanded=False; self.resize_to_contents()
        if expanded_uci:
            index=next((i for i,m in enumerate(moves) if m['uci']==expanded_uci),None)
            if index is not None: self.explain(index)
    def explain(self,index):
        if index>=len(self.moves): return
        m=self.moves[index]; own_text=m['text'].split('The engine’s main reply is ')[0].strip()
        self.explanation.setText((m.get('natural_reason',m.get('idea_reason',m.get('brilliant_reason','')))+' '+own_text+' '+m['verdict']).strip())
        self.expanded=not(self.expanded and self.property('selected')==index)
        self.setProperty('selected',index); self.explanation.setVisible(self.expanded); self.line.hide(); self.resize_to_contents()
    def resize_to_contents(self):
        self.layout().activate(); self.setFixedHeight(self.layout().sizeHint().height())
    def mousePressEvent(self,event):
        if event.button()==Qt.MouseButton.LeftButton: self.drag_origin=event.globalPosition().toPoint()-self.frameGeometry().topLeft()
    def mouseMoveEvent(self,event):
        if self.drag_origin is not None: self.user_moved=True; self.move(event.globalPosition().toPoint()-self.drag_origin)
    def mouseReleaseEvent(self,event): self.drag_origin=None
    def showEvent(self,event): super().showEvent(event); exclude_capture(self)

class Controller:
    def __init__(self,app,autostart=True):
        self.app=app; self.settings=QSettings('ChessLens','ChessLensOverlay')
        self.orientation=self.settings.value('orientation','Automatic'); self.theme=self.settings.value('theme','Automatic')
        self.player_side=self.settings.value('player_side','Automatic')
        self.board=None; self.frame=None; self.generation=0; self.fingerprint=None; self.stable=0; self.missing=0
        self.last_result_color=None
        self.paused=False; self.scanning=False; self.results=[]; self.last_result_fen=None; self.stopping=False
        self.diagnostic=None; self.observations=0; self.matches_after_arrows=0
        self.request_inflight=False; self.last_phase=None; self.first_arrows_ms=None; self.analysis_started=None
        self.bridge=TabBridge(); self.tab_mode=False; self.tab_key=None
        self.celebration=BrilliantCelebration(enabled=self.settings.value('sound_enabled',True,type=bool),clip=self.settings.value('sound_clip','chime'))
        self.visual_self_title=self.settings.value('visual_self_title','Off');self.visual_opponent_title=self.settings.value('visual_opponent_title','Off')
        self.bridge.set_titles(self.visual_self_title,self.visual_opponent_title)
        self.overlay=ArrowOverlay(); self.bubble=Bubble(); self.bubble.pauseClicked.connect(self.toggle_pause)
        self.bubble.settingsClicked.connect(self.options); self.bubble.moveClicked.connect(self.select_move); self.bubble.quitClicked.connect(self.quit)
        self.bubble.sideClicked.connect(self.choose_side)
        self.bubble.connectClicked.connect(self.connection_guide)
        area=QApplication.primaryScreen().availableGeometry(); self.bubble.move(area.right()-self.bubble.width()-18,area.top()+70)
        self.reader=ScreenReader(Recognizer()); self.reader.frame.connect(self.on_frame); self.reader.problem.connect(self.on_vision_error)
        self.engine=FastEngineThread(); self.engine.result.connect(self.on_result); self.engine.failure.connect(self.on_engine_error)
        try:
            saved=json.loads(self.settings.value('last_region','null'))
            if saved and any(s.name()==saved['screen'] for s in QApplication.screens()):
                self.reader.cached=(saved['screen'],tuple(saved['rect']),(saved['dimensions'][1],saved['dimensions'][0]))
        except (ValueError,TypeError,KeyError): pass
        icon=QPixmap(64,64); icon.fill(QColor('#18241c')); p=QPainter(icon); p.setPen(QColor('#b1e88a')); p.setFont(QFont('Segoe UI Symbol',40)); p.drawText(icon.rect(),Qt.AlignmentFlag.AlignCenter,'♞'); p.end()
        self.app.setWindowIcon(QIcon(icon)); self.tray=QSystemTrayIcon(QIcon(icon),app); self.tray.setToolTip('ChessLens · automatically looking for boards')
        menu=QMenu(); menu.addAction('Show / hide move explanations',self.toggle_bubble); menu.addAction('Pause / resume',self.toggle_pause)
        self.sound_action=menu.addAction('Brilliant sound');self.sound_action.setCheckable(True);self.sound_action.setChecked(self.celebration.enabled);self.sound_action.toggled.connect(self.set_sound_enabled)
        menu.addAction('Rescan screen',self.reset); menu.addAction('Select board manually',self.manual_select); menu.addAction('Options',self.options); menu.addSeparator(); menu.addAction('Quit ChessLens',self.quit)
        menu.insertAction(menu.actions()[-2],menu.addAction('Connect Chess.com in a browser',self.connection_guide))
        self.tray.setContextMenu(menu); self.tray.activated.connect(lambda reason:self.toggle_bubble() if reason==QSystemTrayIcon.ActivationReason.Trigger else None)
        self.timer=QTimer(); self.timer.setInterval(160); self.timer.timeout.connect(self.capture)
        self.reader.start(); self.engine.start()
        self.update_side_label()
        if autostart:
            try: self.bridge.start()
            except OSError: self.bubble.set_status('Chess.com connector unavailable; screen mode is active.')
            self.bubble.show(); self.tray.show(); self.timer.start(); QTimer.singleShot(300,self.capture)
    def capture(self):
        if self.paused or self.stopping:return
        snapshot=self.bridge.current()
        if snapshot is not None or self.bridge.ever_connected:
            self.capture_tab(snapshot);return
        if self.scanning:return
        # Capture is done on the GUI thread; recognition runs independently so the controls stay responsive.
        screens=[]; hidden=False
        if self.overlay.isVisible() and not self.overlay.excluded:
            self.overlay.hide(); QApplication.processEvents(); hidden=True
            if sys.platform=='win32': ctypes.windll.dwmapi.DwmFlush()
        selected=next((s for s in QApplication.screens() if self.frame and s.name()==self.frame['screen']),None)
        fast=selected is not None and self.missing<3 and selected.geometry().getRect()==tuple(self.frame['geometry'])
        for screen in ([selected] if fast else QApplication.screens()):
            if fast:
                x,y,w,h=self.frame['rect']; sw,sh=self.frame['dimensions']; geo=screen.geometry()
                pix=screen.grabWindow(0,round(x*geo.width()/sw),round(y*geo.height()/sh),round(w*geo.width()/sw),round(h*geo.height()/sh))
            else: pix=screen.grabWindow(0)
            if not pix.isNull():
                geo=screen.geometry(); snapshot={'name':screen.name(),'geometry':geo.getRect(),'rgb':image_array(pix.toImage())[:,:,:3]}
                if fast: snapshot.update(capture_rect=self.frame['rect'],dimensions=self.frame['dimensions'])
                screens.append(snapshot)
                if self.diagnostic and not fast:
                    screenshot=self.diagnostic.with_name(self.diagnostic.stem+'-'+screen.name()+'.png')
                    if not screenshot.exists(): pix.save(str(screenshot))
        if hidden and self.results: self.overlay.show()
        self.scanning=True
        self.reader.submit(screens,{'orientation':self.orientation,'theme':self.theme})
    def capture_tab(self,snapshot):
        self.bubble.connect.hide()
        self.overlay.set_moves([])
        if snapshot is None or snapshot.get('board') is None:
            if snapshot is None:self.celebration.reset()
            else:self.celebration.wait_for_valid(('tab',snapshot.get('tabId'),snapshot.get('url','')))
            if self.tab_key is not None:
                self.engine.cancel();self.generation+=1;self.request_inflight=False;self.results=[];self.bubble.set_moves([]);self.bridge.clear()
            self.tab_key=None
            self.bubble.set_status('Waiting for a verified Chess.com browser tab…')
            return
        if not snapshot.get('active'): return
        board=snapshot['board']
        self.tab_mode=True
        r=snapshot['rect'];v=snapshot.get('viewport',{})
        area=QApplication.primaryScreen().availableGeometry()
        self.frame={'source':'chesscom-tab','tab_id':snapshot.get('tabId'),'board':board,'white_bottom':snapshot.get('whiteBottom',True),
                    'url':snapshot.get('url',''),
                    'player':snapshot.get('player'),'rect':(r['x'],r['y'],r['width'],r['height']),
                    'dimensions':(v.get('width',area.width()),v.get('height',area.height())),
                    'geometry':area.getRect(),'screen':QApplication.primaryScreen().name(),'initial':board.board_fen()==chess.Board().board_fen(),'costs':[],'crop':None}
        self.update_side_label()
        key=(snapshot.get('tabId'),board.fen(),self.frame['white_bottom'],self.player_color(),snapshot.get('url',''))
        if key==self.tab_key:
            if self.results:self.bridge.publish({'fen':board.fen(),'moves':self.results,'phase':self.last_phase},self.player_color(),snapshot.get('tabId'),self.frame['white_bottom'])
            elif not self.request_inflight and self.last_result_fen!=board.fen() and not board.is_game_over():self.submit_analysis()
            return
        self.celebration.observe(board,self.player_color(),self.sound_context())
        self.tab_key=key;self.board=board.copy();self.fingerprint=board.board_fen();self.stable=2
        self.engine.cancel();self.request_inflight=False;self.bridge.clear();self.submit_analysis()
    def connection_guide(self):
        from PySide6.QtGui import QDesktopServices
        from PySide6.QtCore import QUrl
        base=Path(sys.executable).parent if getattr(sys,'frozen',False) else Path(__file__).resolve().parents[1]
        guide=base/'Browser-Connector/SETUP.html' if getattr(sys,'frozen',False) else base/'docs/SETUP.html'
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(guide)))
    def on_frame(self,frame):
        self.scanning=False
        if self.tab_mode or self.bridge.ever_connected:return
        if self.paused or self.stopping: return
        self.observations+=1
        if frame is None:
            self.celebration.wait_for_valid(self.sound_context())
            self.missing+=1; self.overlay.set_moves([])
            if self.missing==1:
                self.engine.cancel(); self.request_inflight=False
                self.generation+=1; self.results=[]; self.bubble.set_moves([]); self.bubble.set_status('Looking for a chessboard…')
                self.last_result_fen=None
                self.write_diagnostic()
            return
        self.missing=0
        new_region=self.frame is None or self.frame['screen']!=frame['screen'] or sum(abs(a-b) for a,b in zip(self.frame['rect'],frame['rect']))>20
        previous_color=self.player_color()
        self.frame=frame; self.overlay.position(frame); self.update_side_label()
        if previous_color!=self.player_color():
            self.celebration.reset()
            self.engine.cancel(); self.request_inflight=False; self.generation+=1; self.results=[]; self.last_result_fen=None
            self.overlay.set_moves([]); self.bubble.set_moves([])
        region=json.dumps({key:frame[key] for key in ['screen','rect','dimensions']})
        if any(s.name()==frame['screen'] for s in QApplication.screens()) and region!=self.settings.value('last_region'):
            self.settings.setValue('last_region',region)
        if not self.bubble.user_moved: self.position_bubble(frame)
        observed=frame['board']; fingerprint=observed.board_fen()
        if self.board is not None and fingerprint==self.board.board_fen() and not new_region:
            self.fingerprint=fingerprint; self.stable=2
            if self.results and self.last_result_fen==self.board.fen(): self.overlay.set_moves(self.results)
            if self.results:
                self.matches_after_arrows+=1
                if self.matches_after_arrows%20==0: self.write_diagnostic()
            elif not self.request_inflight and not self.board.is_game_over() and (self.last_result_fen!=self.board.fen() or self.last_result_color!=self.player_color()): self.submit_analysis()
            return
        self.overlay.set_moves([])
        if fingerprint!=self.fingerprint:
            self.engine.cancel(); self.request_inflight=False
            self.generation+=1; self.results=[]; self.bubble.set_moves([])
            self.last_result_fen=None
            self.fingerprint=fingerprint; self.stable=1; self.bubble.set_status('Reading the position…'); return
        self.stable+=1
        if self.stable<2: return
        candidate=None
        if self.board is not None and not new_region: candidate,_=match_transition(self.board,observed,frame['costs'])
        if frame['initial']: candidate=chess.Board()
        if candidate is None:
            self.bubble.set_status('Position is not verified. Connect your browser or correct the position in Options.');return
        self.celebration.observe(candidate,self.player_color(),self.sound_context())
        self.board=candidate; self.submit_analysis()
    def submit_analysis(self):
        self.generation+=1; self.results=[]; self.overlay.set_moves([]); self.bubble.set_moves([])
        self.overlay.selected=0
        self.bridge.clear()
        ours=self.player_color()
        self.bubble.set_status('Finding your moves…' if self.board.turn==ours else 'Opponent’s turn · checking for a premove…')
        self.request_inflight=True; self.analysis_started=time.perf_counter(); self.first_arrows_ms=None
        self.engine.submit(self.generation,self.board,2.5,player_color=ours)
    def on_result(self,generation,payload):
        if self.paused or generation!=self.generation or self.board is None or payload['fen']!=self.board.fen(): return
        ours=self.player_color(); premove=payload.get('mode')=='premove'
        # Never display an opponent's engine move, including results queued before a side change.
        if self.board.turn!=ours and not premove and not payload['terminal']: return
        if premove and payload.get('player_color')!=ours: return
        if any(not self.board.piece_at(chess.Move.from_uci(m['uci']).from_square) or self.board.piece_at(chess.Move.from_uci(m['uci']).from_square).color!=ours for m in payload['moves']): return
        self.results=payload['moves']; self.last_result_fen=self.board.fen()
        self.celebration.remember(self.board,self.results,ours,self.sound_context())
        self.last_result_color=ours
        self.last_phase=payload.get('phase','refined'); self.request_inflight=self.last_phase in ['quick','refining']
        if self.first_arrows_ms is None and self.analysis_started is not None:
            self.first_arrows_ms=round((time.perf_counter()-self.analysis_started)*1000)
        self.bubble.set_moves(self.results)
        if self.bubble.expanded: self.overlay.selected=self.bubble.property('selected')
        detail='initial suggestions · analysing deeper…' if self.last_phase in ['quick','refining'] else 'click a move for why'
        if premove: status='Premove candidate available' if self.results else 'Opponent’s turn · no checked premove'
        elif any(m.get('creative') for m in self.results):status='Your turn · blue sacrifice idea available'
        elif any(m.get('natural') for m in self.results):status='Your turn · purple natural move available'
        else: status=f'Your turn · {detail}'
        self.bubble.set_status(payload['terminal'] or status)
        if self.frame: self.overlay.position(self.frame)
        if self.tab_mode:
            self.overlay.set_moves([])
            self.bridge.publish(payload,ours,self.frame.get('tab_id'),self.frame['white_bottom'])
        else:self.overlay.set_moves(self.results)
        self.tray.setToolTip('ChessLens · '+self.bubble.status.text())
        self.write_diagnostic()
    def sound_context(self):
        if self.frame and self.frame.get('source')=='chesscom-tab':return ('tab',self.frame.get('tab_id'),self.frame.get('url',''))
        return ('screen',self.frame.get('screen') if self.frame else None)
    def set_sound_enabled(self,enabled):
        self.celebration.set_enabled(enabled);self.settings.setValue('sound_enabled',bool(enabled))
        self.sound_action.setChecked(bool(enabled))
    def player_color(self):
        if self.player_side in ['White','Black']: return self.player_side=='White'
        if self.frame and self.frame.get('player') in ['white','black']:return self.frame['player']=='white'
        return self.frame['white_bottom'] if self.frame else chess.WHITE
    def update_side_label(self):
        name='White' if self.player_color() else 'Black'
        self.bubble.side.setText(f'Playing: {name}'+(' (auto)' if self.player_side=='Automatic' else '')+' ▾')
    def choose_side(self):
        menu=QMenu(self.bubble)
        for text,value in [('Auto — side at bottom','Automatic'),('I play White','White'),('I play Black','Black')]:
            action=menu.addAction(text); action.setCheckable(True); action.setChecked(self.player_side==value)
            action.triggered.connect(lambda checked=False,value=value:self.set_player_side(value))
        menu.exec(self.bubble.side.mapToGlobal(self.bubble.side.rect().bottomLeft()))
    def set_player_side(self,value):
        self.celebration.reset()
        self.player_side=value; self.settings.setValue('player_side',value); self.engine.cancel(); self.request_inflight=False
        self.generation+=1; self.results=[]; self.overlay.set_moves([]); self.bubble.set_moves([]); self.update_side_label()
        self.bridge.clear();self.tab_key=None
        if self.board is not None and not self.paused: self.submit_analysis()
    def write_diagnostic(self):
        if self.diagnostic:
            self.diagnostic.write_text(json.dumps({'status':self.bubble.status.text(),'observations':self.observations,
                'platform':QGuiApplication.platformName(),'screens':[(s.name(),s.geometry().getRect()) for s in QApplication.screens()],
                'discovery':self.reader.discovery_details,
                'matches_after_arrows':self.matches_after_arrows,'capture_excluded':self.overlay.excluded,
                'analysis_phase':self.last_phase,'first_arrows_ms':self.first_arrows_ms,'scan_interval_ms':self.timer.interval(),
                'brilliant_sound_count':self.celebration.played_count,'sound_enabled':self.celebration.enabled,'sound_error':self.celebration.error,
                'player_side':self.player_side,'player_color':'White' if self.player_color() else 'Black',
                'rect':self.frame['rect'] if self.frame else None,'fen':self.board.fen() if self.board else None,
                'moves':self.results},indent=2),encoding='utf-8')
            if self.results:
                bubble_image=self.diagnostic.with_name(self.diagnostic.stem+'-bubble.png')
                if not bubble_image.exists(): self.bubble.grab().save(str(bubble_image))
    def on_engine_error(self,generation,message):
        if generation in [-1,self.generation]:
            self.request_inflight=False;self.last_result_fen=None; self.bubble.set_status('Engine issue: '+message); self.overlay.set_moves([])
    def on_vision_error(self,message):
        self.scanning=False; DATA.mkdir(parents=True,exist_ok=True); (DATA/'overlay-vision-error.txt').write_text(message,encoding='utf-8')
    def position_bubble(self,frame):
        area=next((s.availableGeometry() for s in QApplication.screens() if s.name()==frame['screen']),QApplication.primaryScreen().availableGeometry())
        rect=self.overlay.geometry(); width=self.bubble.width()
        if area.right()-rect.right()>width+24: x=rect.right()+18; y=rect.top()+5
        elif rect.left()-area.left()>width+24: x=rect.left()-width-18; y=rect.top()+5
        else: x=area.right()-width-12; y=area.top()+14
        self.bubble.move(x,max(area.top()+5,min(y,area.bottom()-self.bubble.height()-5)))
    def select_move(self,index): self.overlay.selected=index; self.overlay.update(); self.bubble.explain(index)
    def toggle_bubble(self):
        self.bubble.setVisible(not self.bubble.isVisible())
    def toggle_pause(self):
        self.celebration.reset()
        self.paused=not self.paused; self.generation+=1
        self.engine.cancel(); self.request_inflight=False
        self.overlay.set_moves([]); self.bubble.set_moves([]); self.results=[]
        self.bubble.pause.setText('▶' if self.paused else 'Ⅱ')
        self.bubble.set_status('Paused' if self.paused else 'Looking for a chessboard…')
        if not self.paused:
            self.board=None; self.fingerprint=None; self.capture()
    def reset(self):
        self.celebration.reset()
        self.generation+=1; self.board=None; self.fingerprint=None; self.frame=None; self.results=[]
        self.engine.cancel(); self.request_inflight=False
        self.reader.reset(); self.overlay.set_moves([]); self.bubble.set_moves([]); self.bubble.set_status('Looking for a chessboard…')
        self.capture()
    def options(self):
        waspaused=self.paused; self.paused=True
        dialog=QDialog(self.bubble);dialog.setWindowTitle('ChessLens options');outer=QVBoxLayout(dialog)
        scroll=QScrollArea();scroll.setWidgetResizable(True);content=QWidget();scroll.setWidget(content);outer.addWidget(scroll);layout=QVBoxLayout(content)
        dialog.resize(450,min(850,QApplication.primaryScreen().availableGeometry().height()-80))
        layout.addWidget(QLabel('Your side (suggestions are only for your pieces)'))
        player=QComboBox(); player.addItems(['Automatic','White','Black']); player.setCurrentText(self.player_side); layout.addWidget(player)
        layout.addWidget(QLabel('Board orientation'))
        orientation=QComboBox(); orientation.addItems(['Automatic','White at bottom','Black at bottom']); orientation.setCurrentText(self.orientation); layout.addWidget(orientation)
        layout.addWidget(QLabel('Piece set'))
        from core import PIECE_THEMES
        theme=QComboBox(); theme.addItems(['Automatic']+PIECE_THEMES+['Calibrated']); theme.setCurrentText(self.theme); layout.addWidget(theme)
        layout.addWidget(QLabel('Side to move (automatically tracked from a starting position)'))
        turn=QComboBox(); turn.addItems(['Keep automatic tracking','White to move','Black to move']); layout.addWidget(turn)
        sound=QCheckBox('Play a sound when I make a brilliant move');sound.setChecked(self.celebration.enabled);layout.addWidget(sound)
        sound_clip=QComboBox()
        for key,name in SOUND_NAMES.items():sound_clip.addItem(name,key)
        sound_clip.setCurrentIndex(max(0,sound_clip.findData(self.celebration.clip)));layout.addWidget(sound_clip)
        test_sound=QPushButton('Test brilliant sound');test_sound.clicked.connect(lambda:play_clip(sound_clip.currentData()));layout.addWidget(test_sound)
        def choose_sound():
            path,_=QFileDialog.getOpenFileName(dialog,'Choose a celebration sound','','WAV audio (*.wav)')
            if not path:return
            try:import_custom_sound(path);sound_clip.setCurrentIndex(sound_clip.findData('custom'))
            except (ValueError,OSError) as exc:QMessageBox.information(dialog,'Sound file',str(exc))
        choose_audio=QPushButton('Load my WAV sound…');choose_audio.clicked.connect(choose_sound);layout.addWidget(choose_audio)
        layout.addWidget(QLabel('Visual title badges — visible only in your browser'))
        own_title=QCheckBox('Show a custom title for me');own_title.setChecked(self.visual_self_title in VISUAL_TITLES);layout.addWidget(own_title)
        own_choice=QComboBox();own_choice.addItems(VISUAL_TITLES);own_choice.setCurrentText(self.visual_self_title if self.visual_self_title in VISUAL_TITLES else 'GM');layout.addWidget(own_choice)
        enemy_title=QCheckBox('Show a custom title for my opponent');enemy_title.setChecked(self.visual_opponent_title in VISUAL_TITLES);layout.addWidget(enemy_title)
        enemy_choice=QComboBox();enemy_choice.addItems(VISUAL_TITLES);enemy_choice.setCurrentText(self.visual_opponent_title if self.visual_opponent_title in VISUAL_TITLES else 'IM');layout.addWidget(enemy_choice)
        own_choice.setEnabled(own_title.isChecked());enemy_choice.setEnabled(enemy_title.isChecked());own_title.toggled.connect(own_choice.setEnabled);enemy_title.toggled.connect(enemy_choice.setEnabled)
        manual=QPushButton('Select board manually'); manual.clicked.connect(lambda:(dialog.reject(),self.manual_select())); layout.addWidget(manual)
        correct=QPushButton('Correct detected pieces / castling rights'); correct.clicked.connect(lambda:(dialog.reject(),self.correct())); layout.addWidget(correct)
        note=QLabel('Red, green and cyan show your top three moves. Blue IDEA marks a sacrifice plan; purple NAT marks a simpler, engine-checked move. Click a row for its explanation. The sound plays after your actual move is observed and verified, not when a suggestion appears. These are local labels, not official Chess.com grades.'); note.setWordWrap(True); layout.addWidget(note)
        buttons=QDialogButtonBox(QDialogButtonBox.StandardButton.Ok|QDialogButtonBox.StandardButton.Cancel); buttons.accepted.connect(dialog.accept); buttons.rejected.connect(dialog.reject); outer.addWidget(buttons)
        if dialog.exec():
            self.visual_self_title=own_choice.currentText() if own_title.isChecked() else 'Off';self.visual_opponent_title=enemy_choice.currentText() if enemy_title.isChecked() else 'Off'
            self.settings.setValue('visual_self_title',self.visual_self_title);self.settings.setValue('visual_opponent_title',self.visual_opponent_title)
            self.bridge.set_titles(self.visual_self_title,self.visual_opponent_title)
            self.set_sound_enabled(sound.isChecked());self.celebration.clip=sound_clip.currentData();self.settings.setValue('sound_clip',self.celebration.clip)
            if self.player_side!=player.currentText():
                self.celebration.reset()
                self.player_side=player.currentText(); self.settings.setValue('player_side',self.player_side)
                self.engine.cancel(); self.request_inflight=False; self.generation+=1; self.results=[]; self.last_result_fen=None; self.bubble.set_moves([]); self.overlay.set_moves([]); self.update_side_label()
            changed=self.orientation!=orientation.currentText() or self.theme!=theme.currentText()
            self.orientation=orientation.currentText(); self.theme=theme.currentText(); self.settings.setValue('orientation',self.orientation); self.settings.setValue('theme',self.theme)
            if changed: self.reset()
            if turn.currentIndex() and self.board:
                self.celebration.reset()
                self.board.turn=turn.currentIndex()==1; self.board.ep_square=None; self.board.clear_stack()
                if self.board.is_valid(): self.submit_analysis()
        self.paused=waspaused
        if not self.paused: self.capture()
    def manual_select(self):
        self.celebration.reset()
        waspaused=self.paused; self.paused=True
        self.overlay.hide(); self.bubble.hide(); QApplication.processEvents()
        screen=QApplication.screenAt(QCursor.pos())
        if screen is None: screen=QApplication.primaryScreen()
        shot=screen.grabWindow(0); selector=RegionSelector(screen,shot)
        if selector.exec():
            self.reader.cached=(screen.name(),selector.region,(shot.height(),shot.width())); self.board=None; self.fingerprint=None
            self.frame=None; self.missing=0; self.engine.cancel(); self.request_inflight=False
        self.bubble.show(); self.paused=waspaused; self.capture()
    def correct(self):
        self.celebration.reset()
        if not self.frame: self.bubble.set_status('Open a visible board first, or choose Select board manually.'); return
        waspaused=self.paused; self.paused=True; self.overlay.hide()
        dialog=ReviewDialog(self.board or self.frame['board'],self.frame['white_bottom'],parent=self.bubble,reference=self.frame['crop'])
        if dialog.exec(): self.board=dialog.board; self.fingerprint=self.board.board_fen(); self.paused=False; self.submit_analysis()
        self.paused=waspaused
    def quit(self):
        if self.stopping: return
        self.stopping=True; self.timer.stop(); self.overlay.close(); self.bubble.hide(); self.tray.hide()
        self.reader.stop(); self.engine.stop(); self.celebration.stop(); self.bridge.stop();self.app.quit()

def self_test(controller,path,fixture):
    from core import piece_image,ASSETS
    sound_assets={'chime':(ASSETS/'sounds/chime.wav').is_file()}
    assert all(sound_assets.values()),'The celebration sound must be bundled'
    controller.player_side='White'
    rgb=image_array(QImage(str(fixture)))[:,:,:3]
    rects=detect_boards(rgb)
    assert rects,'Must detect the real screenshot board'
    source={'name':'fixture','rgb':rgb,'geometry':(0,0,rgb.shape[1],rgb.shape[0])}
    frame=controller.reader.inspect(source,rects[0]); assert frame is not None,'Must accept the real screen board'
    assert frame['board'].board_fen()==chess.Board().board_fen()
    controller.on_frame(frame); controller.on_frame(frame)
    def completed(generation,payload):
        if generation!=controller.generation: return
        assert len(controller.results)==3
        assert controller.overlay.testAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        # Render the real screenshot with the actual overlay painter for visual alignment QA.
        controller.overlay.setGeometry(frame['rect'][0],frame['rect'][1],frame['rect'][2],frame['rect'][3])
        original=QImage(str(fixture)).convertToFormat(QImage.Format.Format_ARGB32)
        painter=QPainter(original); painter.drawPixmap(frame['rect'][0],frame['rect'][1],controller.overlay.grab()); painter.end()
        original.save(str(path.with_suffix('.png')))
        report={'passed':True,'packaged':bool(getattr(sys,'frozen',False)), 'detected_rect':frame['rect'],
            'recognized_fen':frame['board'].fen(),'arrows':controller.results,'click_through':True,
            'capture_excluded':controller.overlay.excluded,'automatic_start':True,'sound_assets':sound_assets}
        path.write_text(json.dumps(report,indent=2),encoding='utf-8'); controller.quit()
    controller.engine.result.connect(completed)
    QTimer.singleShot(30000,controller.quit)

def main():
    test='--self-test' in sys.argv
    guard=InstanceGuard()
    if not test and not guard.acquire(): return 0
    app=QApplication(sys.argv); app.setApplicationName('ChessLens'); app.setQuitOnLastWindowClosed(False)
    initialize_fonts(); app.setStyle('Fusion'); app.setStyleSheet(STYLE)
    controller=Controller(app,autostart=not test)
    if '--diagnostics' in sys.argv: controller.diagnostic=Path(sys.argv[sys.argv.index('--diagnostics')+1])
    if test:
        i=sys.argv.index('--self-test'); self_test(controller,Path(sys.argv[i+1]),Path(sys.argv[i+2]))
    app.aboutToQuit.connect(controller.quit)
    try: return app.exec()
    finally: guard.close()

if __name__=='__main__':
    try: sys.exit(main())
    except Exception:
        DATA.mkdir(parents=True,exist_ok=True); (DATA/'overlay-last-error.txt').write_text(traceback.format_exc(),encoding='utf-8'); raise
