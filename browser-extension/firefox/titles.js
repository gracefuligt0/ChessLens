(() => {
  const allowed=new Set(['GM','IM','FM','CM','WGM','WIM','WFM','WCM']);
  const nameSelector='.username,.user-username-component,.cc-user-username-component,.user-tagline-username,.player-username,.player-name,[data-cy="player-username"],[data-test-element="user-tagline-username"],[class*="username"]';
  const nativeTitleSelector='.user-tagline-title,.user-tagline-component-title,.user-title-component,.cc-user-title-component,[data-cy="player-title"],[data-test-element="user-title"]';
  const badges=new Map(),hidden=new Map();
  function restore(){for(const [node,display] of hidden){node.style.display=display;}hidden.clear();}
  function clear(){for(const badge of badges.values())badge.remove();badges.clear();restore();}
  function username(state,bottom){
    const board=state.rect,anchor=bottom?board.y+board.height:board.y;
    const candidates=[],seen=new Set();
    for(const node of document.querySelectorAll(nameSelector)){
      if(node.closest('[data-chesslens-title]'))continue;
      const walker=document.createTreeWalker(node,NodeFilter.SHOW_TEXT);
      while(walker.nextNode()){
        const text=walker.currentNode,element=text.parentElement;
        if(element.closest('[data-chesslens-title],'+nativeTitleSelector+',.rating,.flag,.material,[aria-hidden="true"]'))continue;
        const value=text.textContent.trim().replace(/\s*\(\d+\).*$/,'');
        if(!/[\p{L}]/u.test(value)||! /^[\p{L}\p{N}_ -]{1,40}$/u.test(value))continue;
        if(!seen.has(text)){
          const range=document.createRange();range.selectNodeContents(text);
          candidates.push({text,element,r:range.getBoundingClientRect()});seen.add(text);
        }
        break;
      }
    }
    return candidates
      .filter(({r})=>r.width>0&&r.height>0&&r.left>=board.x-60&&r.left<board.x+board.width*.7&&
        (bottom?r.top>=anchor-25&&r.top<anchor+180:r.bottom<=anchor+25&&r.bottom>anchor-180))
      .sort((a,b)=>Math.abs((a.r.top+a.r.bottom)/2-anchor)-Math.abs((b.r.top+b.r.bottom)/2-anchor))[0];
  }
  function decorate(key,anchor,title){
    let badge=badges.get(key);
    if(!anchor||!allowed.has(title)){if(badge)badge.remove();badges.delete(key);return;}
    const {text,element:node}=anchor;
    if(!badge){badge=document.createElement('span');badge.dataset.chesslensTitle=key;badges.set(key,badge);}
    badge.textContent=title;badge.title='Custom visual title · ChessLens · visible only to you';
    badge.setAttribute('aria-label','Custom visual title '+title+' (ChessLens)');
    const font=Math.max(9,Math.min(12,Math.round((parseFloat(getComputedStyle(node).fontSize)||14)*.78)));
    badge.style.cssText=`display:inline-flex;align-items:center;vertical-align:middle;margin:0 4px 0 0;padding:1px 3px;border-radius:2px;background:#b33430;color:#fff;font:700 ${font}px/1.05 Arial,sans-serif;white-space:nowrap;pointer-events:none;flex:none;`;
    // Anchor to the name's actual text, never to a wrapper containing the avatar or material row.
    if(badge.parentNode!==text.parentNode||badge.nextSibling!==text)text.parentNode.insertBefore(badge,text);
    const container=node.closest('.user-tagline-component,.player-component,.player-row,.player-tagline')||node.parentNode;
    for(const original of container.querySelectorAll(nativeTitleSelector)){
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
