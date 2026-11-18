(() => {
  if (document.getElementById('chesslens-tab-markers')) return;
  const root=document.createElement('div'); root.id='chesslens-tab-markers';
  root.style.cssText='position:fixed;pointer-events:none!important;z-index:2147483646;overflow:hidden;display:none;';
  document.documentElement.appendChild(root);
  const shadow=root.attachShadow({mode:'closed'});
  const layer=document.createElement('div');layer.style.cssText='position:absolute;inset:0;pointer-events:none;';shadow.appendChild(layer);
  let latest=null,busy=false,lastReply=0;
  function clear(){root.style.display='none';root.dataset.moveCount='0';layer.replaceChildren();}
  function clearAll(){clear();globalThis.ChessLensTitles?.clear();}
  function sendState(message){
    if(globalThis.browser)return browser.runtime.sendMessage(message);
    return new Promise((resolve,reject)=>chrome.runtime.sendMessage(message,reply=>{
      if(chrome.runtime.lastError)reject(new Error('Extension unavailable'));else resolve(reply);
    }));
  }
  function draw(state,analysis,fenKey){
    if (!state || !analysis || analysis.fen!==fenKey || !state.visible) { clear();return; }
    const r=state.rect;Object.assign(root.style,{left:r.x+'px',top:r.y+'px',width:r.width+'px',height:r.height+'px',display:'block'});
    layer.replaceChildren();root.dataset.moveCount=String(analysis.moves.length);const counters=new Map();
    for (const [i,move] of analysis.moves.slice(0,5).entries()) {
      const color=move.natural?'#b675ff':move.creative?'#4285ff':(move.color||['#ff4136','#51d72b','#16d6df'][Math.min(i,2)]);
      for (const destination of [false,true]) {
        const square=move.uci.slice(destination?2:0,destination?4:2);let f=square.charCodeAt(0)-97,rank=+square[1]-1;
        let col=state.whiteBottom?f:7-f,row=state.whiteBottom?7-rank:rank;
        const key=square+':'+destination,stack=counters.get(key)||0;counters.set(key,stack+1);
        const mark=document.createElement('span');mark.dataset.rank=String(i+1);mark.dataset.square=square;mark.dataset.kind=move.natural?'natural':move.creative?'idea':'engine';
        const unit=r.width/8,font=Math.max(10,Math.min(15,unit*.17)),dot=Math.max(5,Math.min(10,unit*.1));
        mark.style.cssText=`position:absolute;left:calc(${col*12.5}% + 2px);top:calc(${row*12.5}% + ${2+stack*(destination?font+4:dot+2)}px);background:${color};color:#061510;font:bold ${font}px/1.15 Arial,sans-serif;pointer-events:none;box-sizing:border-box;`;
        if (destination) { mark.textContent=(move.natural?'NAT ':move.creative?'IDEA ':move.premove?'P ':move.brilliant?'!! ':'')+move.score;mark.style.padding='1px 3px';if(move.creative)mark.style.color='#fff';if(move.premove)mark.style.border='1px dashed #142e34'; }
        else {mark.style.width=dot+'px';mark.style.height=dot+'px';}
        layer.appendChild(mark);
      }
    }
  }
  window.addEventListener('message',event => {
    if(event.source!==window || event.origin!==location.origin || event.data?.channel!=='chesslens-position-v1')return;
    latest=event.data.state;
    if(!latest||!latest.visible){clearAll();return;}
    if(busy)return;busy=true;
    sendState({type:'chesslens-state',state:latest}).then(reply=>{
      busy=false;
      root.dataset.connection=reply?.ok?'connected':(reply?.message||'app unavailable');
      if(!reply?.ok||reply.inputFen!==latest?.fen){clearAll();return;}
      lastReply=performance.now();globalThis.ChessLensTitles?.update(latest,reply.appearance,reply.analysis?.player);
      if(!reply.render){clear();return;}draw(latest,reply.analysis,reply.fenKey);
    }).catch(()=>{busy=false;clearAll();});
  });
  setInterval(()=>{if(performance.now()-lastReply>1200)clearAll();},300);
  addEventListener('scroll',clear,true);addEventListener('resize',clear);
})();
