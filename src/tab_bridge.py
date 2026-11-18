"""Local-only Chess.com extension bridge. No account tokens or game actions."""
from __future__ import annotations
import json,secrets,threading,time,re
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
from urllib.parse import urlparse
import chess

PORT=37391
GUIDE_COLORS=['#ff4136','#51d72b','#16d6df']
IDEA_COLOR='#4285ff'
NATURAL_COLOR='#b675ff'
VISUAL_TITLES=('GM','IM','FM','CM','WGM','WIM','WFM','WCM')
FIREFOX_ID='chesslens@local.invalid'

def extension_origin_allowed(origin,extension_id=''):
    chrome=bool(re.fullmatch(r'chrome-extension://[a-p]{32}',origin))
    firefox=bool(re.fullmatch(r'moz-extension://[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}',origin))
    header=bool(re.fullmatch(r'[a-p]{32}',extension_id)) or extension_id==FIREFOX_ID
    return chrome or firefox or (not origin and header)

def marker_color(move,index):
    return NATURAL_COLOR if move.get('natural') else IDEA_COLOR if move.get('creative') else GUIDE_COLORS[min(index,2)]

def validated_position(data):
    if not isinstance(data,dict):raise ValueError('A position object is required.')
    url=urlparse(str(data.get('url','')))
    if url.scheme!='https' or url.hostname not in ['chess.com','www.chess.com']:
        raise ValueError('The connector only accepts Chess.com boards.')
    fen=data.get('fen')
    if not isinstance(fen,str) or len(fen)>180: raise ValueError('A full position from the tab is required.')
    if len(fen.split())!=6: raise ValueError('Incomplete FEN: turn and move history must be supplied.')
    board=chess.Board(fen)
    if not board.is_valid(): raise ValueError('Chess.com position is not legal; waiting for the board to settle.')
    pieces=data.get('pieces')
    if not isinstance(pieces,list) or not 2<=len(pieces)<=32: raise ValueError('Piece positions are missing.')
    observed=chess.Board(None)
    occupied=set()
    for piece in pieces:
        if not isinstance(piece,dict) or not isinstance(piece.get('square'),str) or not isinstance(piece.get('symbol'),str):raise ValueError('Invalid piece.')
        square=chess.parse_square(piece['square']); symbol=piece['symbol']
        if square in occupied or symbol not in 'PNBRQKpnbrqk': raise ValueError('Duplicate or invalid piece.')
        occupied.add(square); observed.set_piece_at(square,chess.Piece.from_symbol(symbol))
    if observed.board_fen()!=board.board_fen(): raise ValueError('The tab position and drawn pieces differ; waiting for animation.')
    rect=data.get('rect',{})
    if not all(isinstance(rect.get(k),(int,float)) for k in ['x','y','width','height']): raise ValueError('Board bounds are missing.')
    if not 120<=rect['width']<=4000 or not 120<=rect['height']<=4000: raise ValueError('Invalid board size.')
    return board

class TabBridge:
    def __init__(self,port=PORT):
        self.lock=threading.Lock(); self.token=secrets.token_urlsafe(32); self.server=None; self.thread=None
        self.snapshot=None; self.received=0.; self.analysis=None; self.ever_connected=False; self.error=''; self.port=port
        self.appearance={'selfTitle':None,'opponentTitle':None}
    def set_titles(self,self_title=None,opponent_title=None):
        with self.lock:
            self.appearance={'selfTitle':self_title if self_title in VISUAL_TITLES else None,
                             'opponentTitle':opponent_title if opponent_title in VISUAL_TITLES else None}
    def ingest(self,data):
        if not isinstance(data,dict):return {'ok':False,'render':False,'analysis':None,'message':'A position object is required.'}
        board=None; error=''
        try: board=validated_position(data)
        except (ValueError,TypeError,KeyError) as exc: error=str(exc)
        with self.lock:
            if not (data.get('active') and data.get('focused')) and self.snapshot and self.snapshot.get('active') and self.snapshot.get('focused') and time.monotonic()-self.received<1.5:
                return {'ok':bool(board),'render':False,'analysis':None,'inputFen':data.get('fen'),'fenKey':board.fen() if board else None}
            self.ever_connected=True; self.received=time.monotonic(); self.error=error
            self.snapshot=dict(data,board=board) if board else dict(data,board=None)
            current=self.analysis
            visible=bool(data.get('visible') and data.get('active') and data.get('focused'))
            valid=current and board and current.get('fen')==board.fen() and current.get('tabId')==data.get('tabId') and current.get('whiteBottom')==data.get('whiteBottom')
            return {'ok':bool(board),'message':error,'inputFen':data.get('fen'),'fenKey':board.fen() if board else None,
                    'render':bool(visible and valid),'analysis':current if valid else None,
                    'appearance':dict(self.appearance) if visible and board else None}
    def current(self):
        with self.lock:
            if not self.snapshot or time.monotonic()-self.received>1.5: return None
            return dict(self.snapshot)
    def publish(self,payload,player,tab_id=None,white_bottom=True):
        moves=[]
        for i,move in enumerate(payload['moves'][:5]):
            if i>=3 and not (move.get('creative') or move.get('natural')):continue
            moves.append(dict(move,color=marker_color(move,i)))
        with self.lock:
            self.analysis={'fen':payload['fen'],'moves':moves,'player':'white' if player else 'black',
                           'phase':payload.get('phase'),'mode':payload.get('mode','normal'),'tabId':tab_id,'whiteBottom':white_bottom}
    def clear(self):
        with self.lock: self.analysis=None
    def start(self):
        bridge=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args): pass
            def origin_allowed(self):
                origin=self.headers.get('Origin','')
                return extension_origin_allowed(origin,self.headers.get('X-ChessLens-Extension',''))
            def reply(self,status,data):
                body=json.dumps(data).encode(); self.send_response(status)
                origin=self.headers.get('Origin')
                if origin and self.origin_allowed(): self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Content-Type','application/json'); self.send_header('Cache-Control','no-store')
                self.send_header('Content-Length',str(len(body))); self.end_headers(); self.wfile.write(body)
            def do_OPTIONS(self):
                if not self.origin_allowed(): self.reply(403,{'error':'Extension origin required.'}); return
                self.send_response(204); self.send_header('Access-Control-Allow-Origin',self.headers.get('Origin',''))
                self.send_header('Access-Control-Allow-Methods','GET, POST, OPTIONS')
                self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type, X-ChessLens-Extension'); self.end_headers()
            def do_GET(self):
                if self.path!='/v1/session' or not self.origin_allowed(): self.reply(403,{'error':'Extension origin required.'}); return
                self.reply(200,{'token':bridge.token,'version':1})
            def do_POST(self):
                if self.path!='/v1/state' or not self.origin_allowed(): self.reply(403,{'error':'Extension origin required.'}); return
                if self.headers.get('Authorization')!='Bearer '+bridge.token: self.reply(401,{'error':'Refresh local session.'}); return
                try:
                    size=int(self.headers.get('Content-Length','0'))
                    if not 0<size<=65536: raise ValueError('Invalid payload size.')
                    data=json.loads(self.rfile.read(size)); result=bridge.ingest(data)
                    self.reply(200,result)
                except (ValueError,TypeError) as exc: self.reply(400,{'error':str(exc)})
        self.server=ThreadingHTTPServer(('127.0.0.1',self.port),Handler)
        self.port=self.server.server_address[1]
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True); self.thread.start()
    def stop(self):
        if self.server: self.server.shutdown(); self.server.server_close(); self.server=None
