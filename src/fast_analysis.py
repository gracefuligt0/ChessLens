"""Progressive Stockfish analysis and conservative, engine-checked sacrifice labels."""
from __future__ import annotations
import threading,time,copy
import chess,chess.engine
from PySide6.QtCore import QThread,Signal
from core import open_engine,explain
from premoves import checked_premove

VALUES={chess.PAWN:100,chess.KNIGHT:320,chess.BISHOP:330,chess.ROOK:500,chess.QUEEN:900,chess.KING:0}

def material(board,color):
    return sum(VALUES[p.piece_type]*(1 if p.color==color else -1) for p in board.piece_map().values())

def sacrifice_groups(board,move):
    """Find newly offered non-pawns that lose >=2 pawns even after an immediate recapture.

    Ordinary equal trades, pawn pushes, and already hanging unrelated pieces do not qualify.
    This is an eligibility filter; Stockfish must still verify every accepting capture.
    """
    side=board.turn; baseline=material(board,side); after=board.copy(); after.push(move)
    groups={}
    for capture in after.generate_legal_captures():
        victim=after.piece_at(capture.to_square)
        if not victim or victim.color!=side or victim.piece_type in [chess.PAWN,chess.KING]: continue
        target=capture.to_square
        if target!=move.to_square and not (set(after.attackers(not side,target))-set(board.attackers(not side,target))): continue
        accepted=after.copy(); accepted.push(capture)
        best_material=material(accepted,side)
        for reply in accepted.generate_legal_captures():
            if reply.to_square==target:
                recaptured=accepted.copy(); recaptured.push(reply)
                best_material=max(best_material,material(recaptured,side))
        loss=baseline-best_material
        groups.setdefault(target,{'piece':victim.piece_type,'captures':[]})['captures'].append((capture,loss))
    return [(target,group) for target,group in groups.items()
            if len(group['captures'])<=4 and all(loss>=200 for _,loss in group['captures'])]

def mark_brilliant(engine,board,moves,cancelled=lambda:False,verification_time=.18,minimum_cp=-30):
    """A local label, not Chess.com's grading: near-best, sound, verified material sacrifice."""
    if not moves: return False
    changed=False; best=moves[0]['cp']; side=board.turn
    for candidate in moves:
        candidate['brilliant']=False
        if cancelled(): return changed
        if candidate['cp'] < minimum_cp or best-candidate['cp']>35 or candidate.get('depth',0)<12 or candidate.get('bound',False): continue
        move=chess.Move.from_uci(candidate['uci'])
        for target,group in sacrifice_groups(board,move):
            verified=[]; safe=True
            for capture,loss in group['captures']:
                if cancelled(): return changed
                accepted=board.copy(); accepted.push(move); accepted.push(capture)
                if accepted.is_checkmate(): safe=False; break
                if accepted.is_game_over(): safe=False; break
                info=engine.analyse(accepted,chess.engine.Limit(time=verification_time))
                score=info['score'].pov(side)
                if info.get('depth',0)<12 or score.score(mate_score=100000)<minimum_cp:
                    safe=False; break
                verified.append(score.mate() is not None and score.mate()>0)
            if safe and verified and not cancelled():
                name=chess.piece_name(group['piece']); loss=min(loss for _,loss in group['captures'])/100
                compensation='still lead to a forced mate' if all(verified) else 'retain compensation according to Stockfish'
                candidate['brilliant']=True
                candidate['brilliant_reason']=(f'Offers the {name} on {chess.square_name(target)}, sacrificing at least {loss:g} points in the immediate exchange. '
                    f'The checked capture continuations {compensation}.')
                changed=True; break
    return changed

def payload(board,infos,phase,started):
    infos=[i for i in infos if i.get('pv') and i.get('score') is not None and i['pv'][0] in board.legal_moves]
    infos.sort(key=lambda i:i['score'].pov(board.turn).score(mate_score=100000),reverse=True)
    unique=[]; seen=set()
    for info in infos:
        if info['pv'][0] not in seen: seen.add(info['pv'][0]); unique.append(info)
    moves=[explain(board,i,rank) for rank,i in enumerate(unique)]
    for move,info in zip(moves,unique):
        move['brilliant']=False; move['bound']=bool(info.get('lowerbound',False) or info.get('upperbound',False))
    return {'moves':moves,'fen':board.fen(),'terminal':'','phase':phase,'elapsed_ms':round((time.perf_counter()-started)*1000)}

def exact_search(engine,board,seconds,multipv,cancelled):
    """Keep a complete, unbounded iteration; never mix scores from different depths."""
    iterations={}; complete=[]; expected=min(multipv,board.legal_moves.count())
    with engine.analysis(board,chess.engine.Limit(time=seconds),multipv=multipv) as search:
        for info in search:
            if cancelled(): search.stop(); return []
            if not info.get('pv') or 'score' not in info or info.get('upperbound') or info.get('lowerbound'):continue
            cycle=iterations.setdefault(info.get('depth',0),{})
            cycle[info.get('multipv',1)]=info.copy()
            if len(cycle)==expected and len({i['pv'][0] for i in cycle.values()})==expected:
                complete=list(cycle.values())
    return complete if not cancelled() else []

def idea_sacrifice(board,info):
    """Return the immediate sacrifice, or one after the engine's main reply."""
    pv=info.get('pv',[])
    if not pv or pv[0] not in board.legal_moves:return None
    if sacrifice_groups(board,pv[0]):return board.copy(),pv,False
    if len(pv)<3:return None
    branch=board.copy()
    for move in pv[:2]:
        if move not in branch.legal_moves:return None
        branch.push(move)
    if pv[2] in branch.legal_moves and sacrifice_groups(branch,pv[2]):return branch,pv[2:],True
    return None

def find_brilliant_idea(engine,board,normal_infos,cancelled=lambda:False,seconds=2.2,broad_infos=None):
    """An optional creative idea, not a prediction of Chess.com's brilliant grade.

    Search beyond the usual three, then recheck a near-best root and every capture
    accepting its offered piece. A setup is conditional on the engine's main reply.
    Never invent an idea in a quiet position just to fill the fourth slot.
    """
    if cancelled() or not normal_infos or board.is_game_over():return None
    deadline=time.perf_counter()+seconds
    stop=lambda:cancelled() or time.perf_counter()>=deadline
    side=board.turn
    normal_roots={i['pv'][0] for i in normal_infos}
    best=max(i['score'].pov(side).score(mate_score=100000) for i in normal_infos)
    # This broader pass runs only after the fast top-three results have appeared.
    broad=broad_infos if broad_infos is not None else exact_search(engine,board,min(.8,seconds*.4),min(12,board.legal_moves.count()),stop)
    pool={i['pv'][0]:i for i in broad}
    # Retain deeper original lines for the top three rather than shallow broad-search lines.
    pool.update({i['pv'][0]:i for i in normal_infos})
    candidates=[]
    for root,info in pool.items():
        cp=info['score'].pov(side).score(mate_score=100000)
        if cp<max(-75,best-100):continue
        sacrifice=idea_sacrifice(board,info)
        if sacrifice:candidates.append((root in normal_roots,-cp,root,info))
    # Prefer an extra option outside the top three when a sound one exists.
    for _,_,root,info in sorted(candidates,key=lambda item:item[:2]):
        if stop():return None
        # Recheck this precise move at greater depth, instead of trusting a broad scan.
        checked=exact_search_root(engine,board,root,min(.3,max(.01,deadline-time.perf_counter())),stop)
        if not checked or checked.get('depth',0)<14:continue
        cp=checked['score'].pov(side).score(mate_score=100000)
        if cp<max(-75,best-100):continue
        sacrifice=idea_sacrifice(board,checked)
        if not sacrifice:continue
        branch,pv,setup=sacrifice
        # Every accepting capture is checked, not just the cooperative PV reply.
        probe={'uci':pv[0].uci(),'cp':cp,'depth':checked['depth']-(2 if setup else 0)}
        if not mark_brilliant(engine,branch,[probe],stop,verification_time=.14,minimum_cp=-75) or stop():continue
        item=explain(board,checked,3)
        if setup:
            after=board.copy();after.push(checked['pv'][0]);reply=after.san(checked['pv'][1])
            followup=branch.san(pv[0])
            reason=(f'Sets up the sacrifice {followup} if the opponent replies {reply}. '
                    'Other replies can change the plan. ')
        else:reason='Offers a material sacrifice immediately. '
        reason+=probe['brilliant_reason']+' This is an engine-checked creative idea, not a guaranteed brilliant grade.'
        item.update(creative=True,brilliant=False,idea_kind='setup' if setup else 'sacrifice',
                    idea_reason=reason,brilliant_reason='',bound=False)
        return item
    return None

def exact_search_root(engine,board,root,seconds,cancelled):
    """Unbounded score and PV for a single legal root, with cancellation."""
    complete=None
    with engine.analysis(board,chess.engine.Limit(time=seconds),root_moves=[root]) as search:
        for info in search:
            if cancelled():search.stop();return None
            if info.get('pv') and info['pv'][0]==root and 'score' in info and not info.get('upperbound') and not info.get('lowerbound'):
                complete=info.copy()
    return complete if not cancelled() else None

def natural_features(board,move):
    """Transparent simplicity heuristics, not a model of a human or a detector."""
    piece=board.piece_at(move.from_square);side=board.turn
    after=board.copy();after.push(move)
    values=VALUES;value=values[piece.piece_type]
    # Decline offered sacrifices and moves that put a valuable piece under a cheaper attack.
    if sacrifice_groups(board,move):return None
    attackers=after.attackers(not side,move.to_square)
    if piece.piece_type!=chess.KING and attackers:
        cheapest=min(values[after.piece_at(s).piece_type] for s in attackers)
        if cheapest<value or not after.is_attacked_by(side,move.to_square):return None
    score=0.;reasons=[]
    home=0 if side else 7
    if board.is_castling(move):score+=7;reasons.append('Castles to improve king safety and connect the rooks.')
    if piece.piece_type in [chess.KNIGHT,chess.BISHOP] and chess.square_rank(move.from_square)==home:
        score+=5;reasons.append('Develops a minor piece from its starting rank.')
    center={chess.D4,chess.E4,chess.D5,chess.E5}
    if move.to_square in center:
        score+=3;reasons.append('Takes space in the centre.')
    controlled=len(set(after.attacks(move.to_square))&center)
    if controlled:score+=min(2,controlled)*.7
    if piece.piece_type==chess.PAWN and chess.square_file(move.to_square) in [2,3,4,5] and board.fullmove_number<=12:
        score+=1.5;reasons.append('Supports a straightforward central development plan.')
    if board.is_capture(move):
        victim=board.piece_at(move.to_square)
        captured=100 if board.is_en_passant(move) else values[victim.piece_type]
        if captured>=value or not board.is_attacked_by(not side,move.to_square):
            score+=3;reasons.append('Makes a simple capture or exchange without offering a sacrifice.')
    threatened=board.attackers(not side,move.from_square)
    if threatened and piece.piece_type!=chess.KING:
        cheapest=min(values[board.piece_at(s).piece_type] for s in threatened)
        if (cheapest<value or not board.is_attacked_by(side,move.from_square)) and not attackers:
            score+=4;reasons.append('Moves an attacked piece to a safer square.')
    if piece.piece_type==chess.QUEEN and board.fullmove_number<=10 and not board.is_capture(move):score-=4
    if piece.piece_type==chess.KING and not board.is_castling(move) and board.fullmove_number<=15:score-=3
    if move.promotion:score+=3;reasons.append('Promotes the pawn.')
    if after.is_checkmate():score+=10;reasons.append('Delivers checkmate.')
    if not reasons:reasons=['Chooses a simple move without an immediate material sacrifice.']
    return score,' '.join(reasons[:2])

def find_natural_move(engine,board,normal_infos,broad_infos,cancelled=lambda:False):
    """Pick an understandable, engine-checked move, at most 0.70 below the best.

    The first three retain their engine ranking. This optional category never
    randomises moves, plays them automatically, or claims to bypass detection.
    """
    if cancelled() or not normal_infos or board.is_game_over():return None
    side=board.turn;best=max(i['score'].pov(side).score(mate_score=100000) for i in normal_infos)
    roots={i['pv'][0] for i in normal_infos};pool={i['pv'][0]:i for i in broad_infos}
    pool.update({i['pv'][0]:i for i in normal_infos});ranked=[]
    for root,info in pool.items():
        if root not in board.legal_moves or info.get('upperbound') or info.get('lowerbound'):continue
        cp=info['score'].pov(side).score(mate_score=100000)
        if cp<best-70:continue
        features=natural_features(board,root)
        if features is not None:
            simplicity,reason=features
            ranked.append((simplicity+(.6 if root not in roots else 0),cp,root,reason))
    for _,_,root,reason in sorted(ranked,key=lambda item:item[:2],reverse=True)[:2]:
        if cancelled():return None
        checked=exact_search_root(engine,board,root,.20,cancelled)
        if not checked or checked.get('depth',0)<12:continue
        cp=checked['score'].pov(side).score(mate_score=100000)
        if cp<best-70:continue
        item=explain(board,checked,4)
        item.update(natural=True,brilliant=False,bound=False,natural_reason=reason+' Stockfish rechecked this straightforward option.')
        return item
    return None

class FastEngineThread(QThread):
    result=Signal(int,object)
    failure=Signal(int,str)
    ready=Signal(str)
    def __init__(self):
        super().__init__(); self.condition=threading.Condition(); self.pending=None; self.stopping=False; self.serial=0
    def submit(self,generation,board,seconds=2.5,player_color=None):
        with self.condition:
            self.serial+=1; self.pending=(generation,board.copy(),seconds,self.serial,player_color); self.condition.notify()
    def cancel(self):
        with self.condition:
            self.serial+=1; self.pending=None; self.condition.notify()
    def run(self):
        engine=None
        try:
            engine=open_engine(); self.ready.emit(engine.id.get('name','Stockfish'))
            while True:
                with self.condition:
                    while self.pending is None and not self.stopping: self.condition.wait()
                    if self.stopping: break
                    generation,board,seconds,serial,player=self.pending; self.pending=None
                cancelled=lambda:self.stopping or serial!=self.serial
                try:
                    if not board.is_valid(): raise ValueError('The recognised position is not legal.')
                    started=time.perf_counter()
                    if board.is_game_over():
                        self.result.emit(generation,{'moves':[],'fen':board.fen(),'terminal':board.outcome().termination.name.replace('_',' ').title(),'phase':'refined','elapsed_ms':0})
                        continue
                    if player is not None and board.turn!=player:
                        premove=checked_premove(engine,board,player,cancelled)
                        if not cancelled(): self.result.emit(generation,premove)
                        continue
                    published=False; complete=None; iterations={}; last_update=0.
                    expected=min(3,board.legal_moves.count())
                    with engine.analysis(board,chess.engine.Limit(time=seconds),multipv=3) as search:
                        for info in search:
                            if cancelled(): search.stop(); break
                            if info.get('pv') and 'score' in info:
                                if not info.get('upperbound') and not info.get('lowerbound'):
                                    cycle=iterations.setdefault(info.get('depth',0),{})
                                    cycle[info.get('multipv',1)]=info.copy()
                                    if len(cycle)>=expected and len({i['pv'][0] for i in cycle.values()})==expected:
                                        complete=list(cycle.values())
                            if not published and complete and time.perf_counter()-started>=.16 and min(i.get('depth',0) for i in complete)>=12:
                                quick=payload(board,complete,'quick',started)
                                if len(quick['moves'])==expected:
                                    self.result.emit(generation,quick); published=True;last_update=time.perf_counter()
                            elif published and complete and time.perf_counter()-last_update>=.8:
                                update=payload(board,complete,'refining',started);self.result.emit(generation,update);last_update=time.perf_counter()
                        if not cancelled(): final_infos=[i.copy() for i in search.multipv]
                    if cancelled(): continue
                    # A stopped search can aggregate a partial iteration with repeated PV roots.
                    # Keep the latest complete set so options two and three never disappear.
                    refined=payload(board,complete or final_infos,'refined',started)
                    self.result.emit(generation,refined)
                    # Extra sacrifice checks run after arrows are already visible.
                    checked=copy.deepcopy(refined)
                    if mark_brilliant(engine,board,checked['moves'],cancelled) and not cancelled():
                        checked['phase']='verified'; checked['elapsed_ms']=round((time.perf_counter()-started)*1000)
                        self.result.emit(generation,checked)
                    if cancelled():continue
                    normal_infos=complete or final_infos
                    broad=exact_search(engine,board,.8,min(12,board.legal_moves.count()),cancelled)
                    if cancelled():continue
                    natural=find_natural_move(engine,board,normal_infos,broad,cancelled)
                    extras=copy.deepcopy(checked)
                    if natural and not cancelled():
                        extras['moves'].append(natural);extras['phase']='natural';extras['elapsed_ms']=round((time.perf_counter()-started)*1000)
                        self.result.emit(generation,copy.deepcopy(extras))
                    idea=find_brilliant_idea(engine,board,normal_infos,cancelled,broad_infos=broad)
                    if idea and not cancelled():
                        creative=copy.deepcopy(checked);creative['moves'].append(idea)
                        if natural:creative['moves'].append(natural)
                        creative['phase']='ideas';creative['elapsed_ms']=round((time.perf_counter()-started)*1000)
                        self.result.emit(generation,creative)
                except Exception as exc:
                    if not cancelled(): self.failure.emit(generation,str(exc))
                    if isinstance(exc,chess.engine.EngineTerminatedError):
                        engine=open_engine()
        except Exception as exc: self.failure.emit(-1,str(exc))
        finally:
            if engine:
                try: engine.quit()
                except Exception: pass
    def stop(self):
        with self.condition: self.stopping=True; self.serial+=1; self.condition.notify()
        self.wait(12000)
