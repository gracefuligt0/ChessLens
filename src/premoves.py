"""Conservative, non-automatic premove suggestions for the player's side only."""
import time
import chess,chess.engine
from core import explain

def exact_root_info(engine,board,move,seconds,cancelled):
    # analyse() aggregates UCI fields; a bound from an earlier iteration can linger.
    # Keep complete, unbounded score/PV messages from the current search instead.
    exact=None
    with engine.analysis(board,chess.engine.Limit(time=seconds),root_moves=[move]) as search:
        for info in search:
            if cancelled(): search.stop(); return None
            if info.get('pv') and 'score' in info and not info.get('upperbound') and not info.get('lowerbound'):
                exact=info.copy()
    return exact

def universal_quiet_moves(board,player):
    """Moves of the player's existing pieces, legal after EVERY current opponent reply."""
    if board.turn==player or board.is_game_over(): return [],[]
    branches=[]; common=None
    for reply in board.legal_moves:
        after=board.copy(); after.push(reply)
        if after.is_game_over(): return [],[]
        legal={m for m in after.legal_moves if board.piece_at(m.from_square)
               and board.piece_at(m.from_square).color==player and not board.piece_at(m.to_square)
               and not after.is_capture(m) and not after.is_castling(m) and not m.promotion}
        common=legal if common is None else common & legal
        branches.append(after)
        if not common: return [],[]
    return list(common or []),branches

def checked_premove(engine,board,player,cancelled=lambda:False,check_time=.055,max_replies=40):
    started=time.perf_counter()
    result={'moves':[],'fen':board.fen(),'terminal':'','phase':'premove','mode':'premove','player_color':player}
    if board.turn==player or board.is_game_over() or cancelled(): return result
    choices,branches=universal_quiet_moves(board,player)
    if not choices or len(branches)>max_replies: return result
    infos=engine.analyse(board,chess.engine.Limit(time=.14),multipv=3)
    if cancelled(): return result
    initial=infos[0]['score'].pov(player)
    if initial.mate() is not None and initial.mate()<0: return result
    floor=initial.score(mate_score=100000)-75
    # The reply from the most likely line is only a candidate: all legal branches are still checked.
    preferred=[]
    for info in infos:
        pv=info.get('pv',[])
        if len(pv)>1 and pv[1] in choices and pv[1] not in preferred: preferred.append(pv[1])
    def priority(move):
        piece=board.piece_at(move.from_square)
        center={chess.D4,chess.E4,chess.D5,chess.E5}
        central=len(set(chess.SquareSet(chess.BB_KNIGHT_ATTACKS[move.to_square]))&center) if piece.piece_type==chess.KNIGHT else int(move.to_square in center)
        return (piece.piece_type==chess.KNIGHT,piece.piece_type==chess.BISHOP,central,move.uci())
    for move in sorted(choices,key=priority,reverse=True):
        if move not in preferred: preferred.append(move)
    # Checking evasions and captures first rejects unsafe candidates sooner.
    branches.sort(key=lambda b:b.is_check(),reverse=True)
    for move in preferred[:3]:
        checked=[]
        for branch in branches:
            if cancelled(): return result
            info=exact_root_info(engine,branch,move,check_time,cancelled)
            if info is None: checked=[]; break
            score=info['score'].pov(player)
            if info.get('depth',0)<9 or info.get('upperbound') or score.score(mate_score=100000)<floor or (score.mate() is not None and score.mate()<0):
                checked=[]; break
            checked.append(info)
        if checked and not cancelled():
            worst=min(checked,key=lambda i:i['score'].pov(player).score(mate_score=100000))
            branch=branches[checked.index(worst)]
            item=explain(branch,worst,0)
            assert item['uci']==move.uci()
            item.update(premove=True,brilliant=False,checked_replies=len(branches),line='',
                text=(f'Premove candidate for {"White" if player else "Black"}: {chess.square_name(move.from_square)} to {chess.square_name(move.to_square)}. '
                    f'This quiet move remains legal after all {len(branches)} legal opponent replies in the detected position. Short engine checks found no drop greater than 0.75 pawns from the current evaluation. '
                    'It is a checked suggestion, not a guarantee; you must queue it yourself.'),
                verdict='Shown evaluation is the lowest from those checked reply branches.')
            result['moves']=[item]; break
    result['elapsed_ms']=round((time.perf_counter()-started)*1000)
    return result
