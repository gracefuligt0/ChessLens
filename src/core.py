"""ChessLens: local Stockfish analysis and screen-board recognition."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sys, os, json, subprocess, hashlib
import numpy as np
import cv2
import chess
import chess.engine
from PySide6.QtCore import Qt, QRectF
from PySide6.QtGui import QImage, QPainter, QColor
from PySide6.QtSvg import QSvgRenderer

BASE = Path(getattr(sys, '_MEIPASS', Path(__file__).resolve().parent))
ASSETS = BASE / 'assets'
DATA = Path(os.environ.get('LOCALAPPDATA', str(Path.home()))) / 'ChessLens'
SYMBOLS = '.PNBRQKpnbrqk'
PIECE_THEMES=[name for name in ['cburnett','merida','alpha','neo'] if (ASSETS/'pieces'/name).is_dir()]
COLORS = ['#9bdc76', '#6ab9f0', '#c19af5']

def image_array(image: QImage) -> np.ndarray:
    image = image.convertToFormat(QImage.Format.Format_RGBA8888)
    return np.frombuffer(image.constBits(), np.uint8).reshape(image.height(), image.bytesPerLine())[:, :image.width()*4].reshape(image.height(), image.width(), 4).copy()

def piece_image(symbol: str, size=96, theme='cburnett') -> QImage:
    prefix = 'w' if symbol.isupper() else 'b'
    directory = ASSETS / 'pieces' / theme
    svg = directory / f'{prefix}{symbol.upper()}.svg'
    if not svg.exists():
        return QImage(str(directory / f'{prefix}{symbol.upper()}.png')).scaled(size, size, Qt.AspectRatioMode.IgnoreAspectRatio, Qt.TransformationMode.SmoothTransformation)
    result = QImage(size, size, QImage.Format.Format_ARGB32)
    result.fill(Qt.GlobalColor.transparent)
    painter = QPainter(result)
    QSvgRenderer(str(svg)).render(painter, QRectF(0, 0, size, size))
    painter.end()
    return result

def engine_path() -> str:
    matches = list((ASSETS / 'engine').rglob('stockfish*.exe'))
    if not matches:
        raise RuntimeError('The bundled Stockfish engine is missing. Restore the full ChessLens folder.')
    return str(matches[0])

def open_engine():
    kwargs = {'creationflags': subprocess.CREATE_NO_WINDOW} if sys.platform == 'win32' else {}
    engine = chess.engine.SimpleEngine.popen_uci(engine_path(), timeout=30, **kwargs)
    engine.configure({'Threads': max(1, min(4, (os.cpu_count() or 2)//2)), 'Hash': 192})
    return engine

def score_text(score):
    mate = score.mate()
    if mate is not None:
        return f'M{mate}' if mate >= 0 else f'−M{abs(mate)}'
    return f'{score.score()/100:+.2f}'

def variation_san(board, moves, limit=8):
    copy = board.copy()
    parts = []
    for move in moves[:limit]:
        if move not in copy.legal_moves:
            break
        prefix = f'{copy.fullmove_number}.' if copy.turn else (f'{copy.fullmove_number}…' if not parts else '')
        parts.append(prefix + copy.san(move))
        copy.push(move)
    return ' '.join(parts)

def explain(board, info, rank):
    """Describe verifiable move features and the actual engine continuation."""
    pv = info['pv']
    move = pv[0]
    piece = board.piece_at(move.from_square)
    after = board.copy()
    san = board.san(move)
    side = 'White' if board.turn else 'Black'
    target = chess.square_name(move.to_square)
    name = chess.piece_name(piece.piece_type)
    reasons = []
    if board.is_castling(move):
        reasons.append('Castles the king and brings the rook into play.')
    elif board.is_capture(move):
        captured = board.piece_at(move.to_square)
        victim = chess.piece_name(captured.piece_type) if captured else 'pawn en passant'
        reasons.append(f'The {name} captures the {victim} on {target}.')
    else:
        reasons.append(f'Moves the {name} from {chess.square_name(move.from_square)} to {target}.')
    if move.promotion:
        reasons.append(f'Promotes the pawn to a {chess.piece_name(move.promotion)}.')
    after.push(move)
    if after.is_checkmate():
        reasons.append('This is checkmate: the king has no legal escape.')
    elif after.is_check():
        reasons.append('Gives check, so the opponent must answer the threat to their king.')
    if piece.piece_type in [chess.KNIGHT, chess.BISHOP] and chess.square_rank(move.from_square) == (0 if board.turn else 7):
        reasons.append('Develops a minor piece from its home rank.')
    center = {chess.D4, chess.E4, chess.D5, chess.E5}
    controlled = len(set(after.attacks(move.to_square)) & center)
    if move.to_square in center:
        reasons.append('Occupies a central square.')
    elif controlled:
        reasons.append(f'The piece attacks {controlled} of the four central squares.')
    attacked = [sq for sq in after.attacks(move.to_square) if (p := after.piece_at(sq)) and p.color != piece.color and p.piece_type != chess.KING]
    if attacked:
        targets = ', '.join(f'{chess.piece_name(after.piece_at(sq).piece_type)} on {chess.square_name(sq)}' for sq in attacked[:3])
        reasons.append(f'Attacks the {targets}.')
    if after.is_attacked_by(not piece.color, move.to_square) and not after.is_checkmate():
        reasons.append('The destination is attacked; use the continuation to check the tactical justification.')
    score = info['score'].pov(board.turn)
    mate = score.mate()
    if mate is not None:
        verdict = f'{side} has a forced mate in {mate}.' if mate > 0 else f'The engine still sees a forced mate against {side} in {abs(mate)}.'
    else:
        cp = score.score()
        if abs(cp) < 35:
            verdict = 'The resulting position is roughly balanced at this search depth.'
        elif cp > 0:
            verdict = f'The engine evaluates the position in {side}’s favour.'
        else:
            verdict = f'{side} remains worse according to the engine.'
    if len(pv) > 1:
        reply = after.san(pv[1]) if pv[1] in after.legal_moves else pv[1].uci()
        reasons.append(f'The engine’s main reply is {reply}.')
    return {'san': san, 'uci': move.uci(), 'score': score_text(score), 'cp': score.score(mate_score=100000),
            'text': ' '.join(reasons), 'verdict': verdict, 'line': variation_san(board, pv), 'depth': info.get('depth', 0), 'rank': rank}

def analyse(engine, board, seconds=2.0):
    if not board.is_valid():
        raise ValueError('This position is not legal. Check the pieces, side to move and castling rights.')
    if board.is_game_over():
        outcome = board.outcome()
        return {'moves': [], 'terminal': outcome.termination.name.replace('_', ' ').title(), 'fen': board.fen()}
    infos = engine.analyse(board, chess.engine.Limit(time=seconds), multipv=3)
    infos.sort(key=lambda info:info['score'].pov(board.turn).score(mate_score=100000), reverse=True)
    return {'moves': [explain(board, info, i) for i, info in enumerate(infos)], 'fen': board.fen(), 'terminal': ''}

def screen_square(row, col, white_bottom=True):
    return chess.square(col, 7-row) if white_bottom else chess.square(7-col, row)

def feature(cell):
    cell = cv2.resize(cell[:, :, :3], (64, 64), interpolation=cv2.INTER_AREA)
    # Ignore coordinates and square edges. Use corners rather than the piece to estimate the background.
    sample = np.concatenate([cell[4:11, 4:11].reshape(-1,3), cell[4:11,53:60].reshape(-1,3), cell[53:60,4:11].reshape(-1,3), cell[53:60,53:60].reshape(-1,3)])
    bg = np.median(sample, axis=0)
    diff = np.max(np.abs(cell.astype(float)-bg), axis=2)
    mask = (diff > 32).astype(np.uint8)
    mask[:3] = 0; mask[-3:] = 0; mask[:,:3] = 0; mask[:,-3:] = 0
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, 8)
    for i in range(1, count):
        if stats[i, cv2.CC_STAT_AREA] < 12:
            mask[labels == i] = 0
    mask = cv2.GaussianBlur(mask.astype(np.float32), (3,3), 0)
    gray = cv2.cvtColor(cell, cv2.COLOR_RGB2GRAY).astype(np.float32)/255
    return np.stack([mask, gray*mask], axis=-1)

class Recognizer:
    def __init__(self):
        self.templates = []
        self.custom = []
        self.theme = 'Automatic'
        self._bank_signature=None
        self._cell_cache={}
        for theme in PIECE_THEMES:
            for symbol in SYMBOLS[1:]:
                rgba = image_array(piece_image(symbol, 96, theme)).astype(float)
                alpha = rgba[:,:,3:]/255
                for bg in [(238,238,210), (118,150,86), (240,217,181), (181,136,99)]:
                    rgb = (rgba[:,:,:3]*alpha+np.array(bg)*(1-alpha)).astype(np.uint8)
                    self.templates.append((symbol, theme, feature(rgb)))
        self.path = DATA / 'calibration.npz'
        if self.path.exists():
            try:
                data = np.load(self.path, allow_pickle=False)
                self.custom = [(str(s), 'Calibrated', f) for s,f in zip(data['symbols'], data['features'])]
            except Exception:
                pass

    def calibrate(self, rgb, board, white_bottom):
        samples = []
        h,w = rgb.shape[:2]
        for r in range(8):
            for c in range(8):
                p = board.piece_at(screen_square(r,c,white_bottom))
                if p:
                    samples.append((p.symbol(), 'Calibrated', feature(rgb[round(r*h/8):round((r+1)*h/8), round(c*w/8):round((c+1)*w/8)])))
        if set(s for s,_,_ in samples) != set(SYMBOLS[1:]):
            raise ValueError('Calibration needs at least one of every white and black piece. Use a starting position, or correct a full board first.')
        self.custom = samples
        DATA.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(self.path, symbols=np.array([s for s,_,_ in samples]), features=np.array([f for _,_,f in samples]))

    def read(self, rgb, white_bottom=True, turn=chess.WHITE):
        h,w = rgb.shape[:2]
        signature=(self.theme,id(self.custom),len(self.custom),id(self.templates),len(self.templates))
        if signature!=self._bank_signature:
            templates = self.custom if self.theme == 'Calibrated' and self.custom else self.templates
            if self.theme not in ['Automatic','Calibrated']:
                templates = [t for t in templates if t[1] == self.theme]
            if self.theme == 'Automatic': templates=templates+self.custom
            self._features=np.array([f for _,_,f in templates],dtype=np.float32)
            self._symbol_indexes={s:np.array([i for i,t in enumerate(templates) if t[0]==s]) for s in SYMBOLS[1:]}
            self._bank_signature=signature; self._cell_cache.clear()
        # Vectorized distances retain silhouette, position, size, and piece colour.
        costs = []
        uncertain = []
        board = chess.Board(None)
        board.turn = turn
        for i in range(64):
            r,c=divmod(i,8)
            pixels=rgb[round(r*h/8):round((r+1)*h/8),round(c*w/8):round((c+1)*w/8)]
            key=(pixels.shape,hashlib.blake2b(pixels.tobytes(),digest_size=12).digest())
            cached=self._cell_cache.get(key)
            if cached is None:
                cell=feature(pixels)
                distances=(np.abs(self._features-cell)*np.array([.7,.3],dtype=np.float32)).mean(axis=(1,2,3))
                row={'.':float(cell[:,:,0].mean())*.5}
                row.update({s:float(distances[indexes].min()) for s,indexes in self._symbol_indexes.items()})
                if len(self._cell_cache)>1024: self._cell_cache.clear()
                self._cell_cache[key]=row
            else: row=cached
            ordered = sorted(row, key=row.get)
            symbol = ordered[0]
            sq = screen_square(i//8,i%8,white_bottom)
            costs.append((sq,row))
            if symbol != '.':
                board.set_piece_at(sq,chess.Piece.from_symbol(symbol))
            if row[ordered[1]]-row[symbol] < .008 or row[symbol] > .065:
                uncertain.append(sq)
        # Screens cannot establish historic castling rights or en passant.
        board.castling_rights = chess.BB_EMPTY
        return board, costs, uncertain

def match_transition(current, observed, costs):
    """Only accept an exact legal successor, including a missed pair of half-moves."""
    if observed.board_fen() == current.board_fen():
        return current.copy(), 'unchanged'
    target = observed.board_fen()
    children = []
    for move in current.legal_moves:
        candidate = current.copy()
        candidate.push(move)
        if candidate.board_fen() == target:
            return candidate, 'move'
        children.append(candidate)
    for child in children:
        for move in child.legal_moves:
            candidate = child.copy()
            candidate.push(move)
            if candidate.board_fen() == target:
                return candidate, 'two moves'
    return None, 'The screen does not match a legal next position. Wait for animations, or use Scan & review.'

def detect_boards(rgb):
    """Find axis-aligned 2D boards from square contours and test 8×8 corner colour alternation."""
    original_h, original_w = rgb.shape[:2]
    scale = min(1.0, 1400/original_w)
    small = cv2.resize(rgb, None, fx=scale, fy=scale)
    h,w = small.shape[:2]
    quant = (small//24)*24
    colors, counts = np.unique(quant.reshape(-1,3), axis=0, return_counts=True)
    candidates = {}
    for color in colors[np.argsort(counts)[-18:]]:
        mask = (np.max(np.abs(small.astype(np.int16)-color.astype(np.int16)),axis=2) < 30).astype(np.uint8)*255
        contours,_ = cv2.findContours(mask, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            x,y,cw,ch = cv2.boundingRect(contour)
            if cw < 20 or abs(cw-ch) > max(4,cw*.12) or cw*8 > min(w,h)*1.05:
                continue
            cell = (cw+ch)/2
            for r in range(8):
                for c in range(8):
                    bx,by = round(x-c*cell),round(y-r*cell)
                    size = round(cell*8)
                    if bx < 0 or by < 0 or bx+size > w or by+size > h:
                        continue
                    key=(round(bx/5),round(by/5),round(size/5))
                    if key in candidates:
                        continue
                    samples=[]
                    for rr in range(8):
                        for cc in range(8):
                            px,py=round(bx+(cc+.16)*cell),round(by+(rr+.16)*cell)
                            samples.append(small[py,px].astype(float))
                    a=np.array(samples)[np.array([(rr+cc)%2==0 for rr in range(8) for cc in range(8)])]
                    b=np.array(samples)[np.array([(rr+cc)%2==1 for rr in range(8) for cc in range(8)])]
                    ma,mb=np.median(a,axis=0),np.median(b,axis=0)
                    contrast=np.linalg.norm(ma-mb)
                    fit=(np.mean(np.linalg.norm(a-ma,axis=1)<45)+np.mean(np.linalg.norm(b-mb,axis=1)<45))/2
                    if contrast>35 and fit>.77:
                        candidates[key]=(fit+min(contrast/500,.3), (round(bx/scale),round(by/scale),round(size/scale),round(size/scale)))
    ranked=sorted(candidates.values(),reverse=True)
    result=[]
    for score,rect in ranked:
        if all(abs(rect[0]-old[0])+abs(rect[1]-old[1])+abs(rect[2]-old[2])>rect[2]*.2 for old in result):
            result.append(rect)
    refined=[]
    for x,y,bw,bh in result[:5]:
        # Corner colours tolerate a few pixels of drift. Snap to the actual repeating grid edges.
        crop=rgb[max(0,y+bh//5):min(original_h,y+4*bh//5)].astype(float)
        vertical=np.zeros(original_w)
        vertical[1:]=np.mean(np.abs(np.diff(crop,axis=1)),axis=(0,2))
        crop=rgb[:,max(0,x+bw//5):min(original_w,x+4*bw//5)].astype(float)
        horizontal=np.zeros(original_h)
        horizontal[1:]=np.mean(np.abs(np.diff(crop,axis=0)),axis=(1,2))
        def snap(projection,start,size):
            cell=size/8
            best=(-1,start,cell)
            for step in np.arange(cell*.93,cell*1.07,.25):
                starts=np.arange(max(0,round(start-cell*.4)),min(len(projection)-round(step*8),round(start+cell*.4))+1)
                if not len(starts): continue
                indexes=np.rint(starts[:,None]+np.arange(9)[None,:]*step).astype(int)
                scores=projection[np.clip(indexes,0,len(projection)-1)].mean(axis=1)
                index=int(np.argmax(scores))
                if scores[index]>best[0]: best=(scores[index],int(starts[index]),step)
            return best[1],round(best[2]*8)
        nx,nw=snap(vertical,x,bw); ny,nh=snap(horizontal,y,bh)
        refined.append((nx,ny,nw,nh))
    return refined
