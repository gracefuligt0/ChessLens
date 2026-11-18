(() => {
  if (window.__chessLensPositionReader) return;
  window.__chessLensPositionReader = true;
  function read() {
    const boards = [...document.querySelectorAll('wc-chess-board, chess-board, .board')].filter(b => {
      const r = b.getBoundingClientRect(); return r.width >= 120 && r.height >= 120 && b.querySelector('.piece');
    }).sort((a,b) => b.getBoundingClientRect().width - a.getBoundingClientRect().width);
    const board = boards[0];
    if (!board) { window.postMessage({channel:'chesslens-position-v1',state:null},location.origin); return; }
    const r = board.getBoundingClientRect();
    const pieces = []; const occupied = new Set(); let error = false;
    let whiteError = 0, blackError = 0;
    for (const element of board.querySelectorAll('.piece')) {
      const classes = [...element.classList];
      const square = classes.map(c => /^square-([1-8])([1-8])$/.exec(c)).find(Boolean);
      const piece = classes.find(c => /^[wb][pnbrqk]$/.test(c));
      if (!square || !piece) continue;
      const name = 'abcdefgh'[+square[1]-1] + square[2];
      if (occupied.has(name)) { error = true; continue; } occupied.add(name);
      pieces.push({square:name,symbol:piece[0]==='w'?piece[1].toUpperCase():piece[1]});
      const pr=element.getBoundingClientRect(); const x=(pr.left+pr.width/2-r.left)/r.width, y=(pr.top+pr.height/2-r.top)/r.height;
      const f=+square[1]-1, rank=+square[2]-1;
      whiteError+=(x-(f+.5)/8)**2+(y-(7-rank+.5)/8)**2;
      blackError+=(x-(7-f+.5)/8)**2+(y-(rank+.5)/8)**2;
    }
    let fen = null,player=null;
    try {
      if (typeof board.game?.getFEN === 'function') fen=board.game.getFEN();
      else if (typeof board.game?.getFen === 'function') fen=board.game.getFen();
      else fen=board.getAttribute('fen') || board.dataset.fen || null;
      if(typeof board.game?.getPlayingAs==='function') {
        const side=String(board.game.getPlayingAs()).toLowerCase();
        if(side==='white'||side==='black')player=side;
      }
    } catch (_) {}
    const visible = !error && document.visibilityState==='visible' && r.bottom>0 && r.right>0 && r.top<innerHeight && r.left<innerWidth;
    window.postMessage({channel:'chesslens-position-v1',state:{url:location.href,fen,player,pieces,
      whiteBottom:whiteError<=blackError,visible,rect:{x:r.x,y:r.y,width:r.width,height:r.height},
      viewport:{width:innerWidth,height:innerHeight,screenX,screenY,outerWidth,outerHeight,devicePixelRatio}}},location.origin);
  }
  setInterval(read,200); read();
})();
