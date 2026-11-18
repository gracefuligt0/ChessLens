(() => {
  const allowed=new Set(['GM','IM','FM','CM','WGM','WIM','WFM','WCM']);
  const badges=new Map(),hidden=new Map();
  function restore(){for(const [node,display] of hidden){node.style.display=display;}hidden.clear();}
  function clear(){for(const badge of badges.values())badge.remove();badges.clear();restore();}
  function username(state,bottom){
    const board=state.rect,anchor=bottom?board.y+board.height:board.y;
    return [...document.querySelectorAll('.username,.user-username-component,.cc-user-username-component,.user-tagline-username,[data-cy="player-username"],[class*="username"]')]
      .filter(node=>!node.closest('[data-chesslens-title]'))
      .map(node=>({node,r:node.getBoundingClientRect()}))
      .filter(({r})=>r.width>0&&r.height>0&&r.left>=board.x-60&&r.left<board.x+board.width*.7&&
        (bottom?r.top>=anchor-25&&r.top<anchor+180:r.bottom<=anchor+25&&r.bottom>anchor-180))
      .sort((a,b)=>Math.abs((a.r.top+a.r.bottom)/2-anchor)-Math.abs((b.r.top+b.r.bottom)/2-anchor))[0]?.node;
  }
  function decorate(key,node,title){
    let badge=badges.get(key);
    if(!node||!allowed.has(title)){if(badge)badge.remove();badges.delete(key);return;}
    if(!badge){badge=document.createElement('span');badge.dataset.chesslensTitle=key;badges.set(key,badge);}
    badge.textContent=title;badge.title='Custom visual title · ChessLens · visible only to you';
    badge.setAttribute('aria-label','Custom visual title '+title+' (ChessLens)');
    badge.style.cssText='display:inline-flex;align-items:center;vertical-align:middle;margin-right:5px;padding:2px 4px;border-radius:3px;background:#b33430;color:#fff;font:bold 11px/1.1 Arial,sans-serif;pointer-events:none;flex:none;';
    if(badge.parentNode!==node.parentNode||badge.nextSibling!==node)node.parentNode.insertBefore(badge,node);
    const container=node.closest('.user-tagline-component,.player-component,.player-row,.player-tagline')||node.parentNode;
    for(const original of container.querySelectorAll('.user-tagline-title,.user-title-component,.cc-user-title-component,[data-cy="player-title"]')){
      if(!hidden.has(original))hidden.set(original,original.style.display);
      original.style.display='none';
    }
  }
  globalThis.ChessLensTitles={clear,update(state,appearance,player){
    if(!state?.visible||!appearance){clear();return;}
    // Restore the native title when either corresponding custom control is turned off.
    restore();
    const side=player||state.player||(state.whiteBottom?'white':'black');
    const ownBottom=(side==='white')===state.whiteBottom;
    decorate('self',username(state,ownBottom),appearance.selfTitle);
    decorate('opponent',username(state,!ownBottom),appearance.opponentTitle);
  }};
})();
