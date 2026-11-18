"""Play a local celebration once a verified move is actually observed on the board."""
from __future__ import annotations
import sys,time,threading,wave,shutil
from collections import deque
import chess
from PySide6.QtCore import QObject,QThread,Signal
from core import ASSETS,DATA,open_engine
from fast_analysis import sacrifice_groups,mark_brilliant,exact_search,exact_search_root

SOUND_NAMES={'chime':'ChessLens celebration','custom':'My custom WAV'}

def import_custom_sound(path):
    from pathlib import Path
    path=Path(path)
    if path.stat().st_size>8*1024*1024:raise ValueError('Choose a WAV smaller than 8 MB.')
    try:
        with wave.open(str(path),'rb') as stream:
            duration=stream.getnframes()/stream.getframerate()
            if stream.getcomptype()!='NONE' or stream.getsampwidth()!=2 or stream.getnchannels() not in [1,2] or not .1<=duration<=20:
                raise ValueError('Use a PCM 16-bit WAV, mono or stereo, lasting 0.1–20 seconds.')
    except (wave.Error,EOFError) as exc:raise ValueError('Choose a valid PCM WAV file.') from exc
    DATA.mkdir(parents=True,exist_ok=True);target=DATA/'custom-brilliant.wav'
    if path.resolve()!=target.resolve():shutil.copy2(path,target)
    return target

def play_clip(clip):
    path=DATA/'custom-brilliant.wav' if clip=='custom' else ASSETS/'sounds/chime.wav'
    if clip=='custom' and not path.is_file():path=ASSETS/'sounds/chime.wav'
    if sys.platform!='win32' or not path.is_file():return False
    import winsound
    try:
        winsound.PlaySound(str(path),winsound.SND_FILENAME|winsound.SND_ASYNC|winsound.SND_NODEFAULT)
        return True
    except RuntimeError:return False

def played_own_move(before,after,player):
    """Match a real one-/two-ply transition using all pieces, turn and FEN counters.

    Includes a move followed by a fast opponent reply, and an opponent reply
    followed by our premove. An unrelated position or a flipped board is not a move.
    """
    plies=after.ply()-before.ply()
    if plies not in (1,2) or before==after:return None
    for first in before.legal_moves:
        branch=before.copy();branch.push(first)
        if plies==1:
            if branch==after and before.turn==player:return before.copy(),first
            continue
        for second in branch.legal_moves:
            end=branch.copy();end.push(second)
            if end==after:
                return (before.copy(),first) if before.turn==player else (branch,second)
    return None

class BrillianceAuditor(QThread):
    """Verify already-played sacrifices without interrupting the main move search."""
    result=Signal(object,bool)
    def __init__(self):
        super().__init__();self.condition=threading.Condition();self.jobs=deque(maxlen=4);self.stopping=False
    def submit(self,event,board,move):
        with self.condition:
            self.jobs.append((event,board.copy(),move));self.condition.notify()
    def run(self):
        engine=None
        try:
            engine=open_engine();engine.configure({'Threads':1,'Hash':64})
            while True:
                with self.condition:
                    while not self.jobs and not self.stopping:self.condition.wait()
                    if self.stopping:break
                    event,board,move=self.jobs.popleft()
                cancelled=lambda:self.stopping
                brilliant=False
                try:
                    best_infos=exact_search(engine,board,.35,1,cancelled)
                    checked=exact_search_root(engine,board,move,.25,cancelled)
                    if best_infos and checked and checked.get('depth',0)>=12:
                        best=max(i['score'].pov(board.turn).score(mate_score=100000) for i in best_infos)
                        cp=checked['score'].pov(board.turn).score(mate_score=100000)
                        if cp>=-30 and best-cp<=35:
                            candidate={'uci':move.uci(),'cp':cp,'depth':checked['depth']}
                            brilliant=mark_brilliant(engine,board,[candidate],cancelled,verification_time=.18)
                except Exception:pass # A failed check must remain silent.
                if not self.stopping:self.result.emit(event,bool(brilliant))
        except Exception:pass
        finally:
            if engine:
                try:engine.quit()
                except Exception:pass
    def stop(self):
        with self.condition:self.stopping=True;self.jobs.clear();self.condition.notify()
        self.wait(10000)

class BrilliantCelebration(QObject):
    celebrated=Signal(object)
    def __init__(self,enabled=True,clip='chime',playback=None,audit_factory=None):
        super().__init__();self.enabled=enabled;self.clip=clip if clip in SOUND_NAMES else 'chime'
        self.playback=playback or play_clip;self.audit_factory=audit_factory or BrillianceAuditor
        self.auditor=None;self.board=None;self.player=None;self.context=None;self.known=set()
        self.heard=set();self.pending={};self.error='';self.played_count=0
        self.invalid_since=None
    def reset(self):
        self.board=None;self.context=None;self.player=None;self.known.clear();self.pending.clear()
        self.invalid_since=None
    def wait_for_valid(self,context):
        """Retain the last verified state across a short piece/capture animation."""
        now=time.monotonic()
        if context!=self.context or (self.invalid_since is not None and now-self.invalid_since>1.5):
            self.reset();return
        if self.invalid_since is None:self.invalid_since=now
    def set_enabled(self,enabled):
        self.enabled=bool(enabled)
        if not self.enabled:self.pending.clear()
    def remember(self,board,moves,player,context):
        # Analysis by itself never plays anything. Only current, verified labels are cached.
        if self.board is None or self.context!=context:
            self.board=board.copy();self.player=player;self.context=context;self.known.clear()
        if self.board!=board or self.player!=player:return
        for move in moves:
            if move.get('brilliant') and not move.get('bound') and not move.get('premove'):
                root=chess.Move.from_uci(move['uci'])
                if board.turn==player and root in board.legal_moves:self.known.add(root.uci())
    def observe(self,board,player,context):
        if self.invalid_since is not None and time.monotonic()-self.invalid_since>1.5:self.reset()
        self.invalid_since=None
        before=self.board
        same=before is not None and context==self.context and player==self.player
        if same and before==board:return
        transition=played_own_move(before,board,player) if same and self.enabled else None
        if transition:
            own_position,move=transition;event=(context,own_position.fen(),move.uci())
            if event not in self.heard and event not in self.pending:
                if own_position==before and move.uci() in self.known:self._play_once(event)
                elif sacrifice_groups(own_position,move):
                    # A quick move may have been played before the brilliant label was ready.
                    # Audit the actual move, instead of losing the event or praising a guess.
                    if self.auditor is None:
                        self.auditor=self.audit_factory();self.auditor.result.connect(self._audited);self.auditor.start()
                    self.pending[event]=time.monotonic();self.auditor.submit(event,own_position,move)
        if not same:self.pending.clear()
        self.board=board.copy();self.player=player;self.context=context;self.known.clear()
    def _audited(self,event,brilliant):
        started=self.pending.pop(event,None)
        if brilliant and started is not None and time.monotonic()-started<8 and event[0]==self.context:
            self._play_once(event)
    def _play_once(self,event):
        if not self.enabled or event in self.heard:return
        self.heard.add(event)
        if len(self.heard)>256:self.heard={event}
        if self.playback(self.clip):
            self.played_count+=1;self.celebrated.emit(event)
        else:self.error='Could not play the brilliant sound.'
    def test(self):return self.playback(self.clip)
    def stop(self):
        self.pending.clear()
        if self.auditor:self.auditor.stop()
