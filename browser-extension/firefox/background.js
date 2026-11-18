const endpoint='http://127.0.0.1:37391';
let token=null;
const extension=globalThis.browser||globalThis.chrome;
async function handle(message,sender){
  if (message?.type!=='chesslens-state'||!sender.tab||!/^https:\/\/(www\.)?chess\.com\//.test(sender.url||''))return;
  try {
    const tab=await extension.tabs.get(sender.tab.id);
    const win=await extension.windows.get(tab.windowId);
    const state={...message.state,active:tab.active,focused:win.focused,tabId:tab.id};
    const headers={'Content-Type':'application/json','X-ChessLens-Extension':extension.runtime.id};
    if (!token) {
      const response=await fetch(endpoint+'/v1/session',{headers:{'X-ChessLens-Extension':extension.runtime.id}});
      if(!response.ok)throw new Error('Local session unavailable');
      token=(await response.json()).token;
    }
    let response=await fetch(endpoint+'/v1/state',{method:'POST',headers:{...headers,Authorization:'Bearer '+token},body:JSON.stringify(state)});
    if (response.status===401) { token=null; throw new Error('Local app restarted; reconnecting.'); }
    if(!response.ok)throw new Error('Local app unavailable');
    return await response.json();
  }catch(_){return {ok:false,render:false,message:'Open ChessLens to connect.'};}
}
if(globalThis.browser){extension.runtime.onMessage.addListener((message,sender)=>handle(message,sender));}
else{extension.runtime.onMessage.addListener((message,sender,sendResponse)=>{handle(message,sender).then(sendResponse);return true;});}
