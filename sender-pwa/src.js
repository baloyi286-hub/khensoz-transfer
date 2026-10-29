import {sha256} from './sha256.js';
const $=id=>document.getElementById(id);
const queue=[];
let token="",busy=false;
window.addEventListener("error",e=>{$("error").textContent="App error: "+e.message});
window.addEventListener("unhandledrejection",e=>{$("error").textContent="App error: "+String(e.reason)});
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function count(){const pending=queue.filter(x=>!x.done&&!x.removed&&!x.cancelled).length;$("count").textContent=pending?pending+" file(s) queued":"No files queued"}
async function api(path,method="GET",body,headers={}){
 const r=await fetch(path,{method,headers:{"X-Transfer-Token":token,...headers},body});
 const data=await r.json();
 if(!r.ok)throw Error(data.error||"HTTP "+r.status);
 return data;
}
async function cancelItem(item){
 if(item.done)return;
 if(!confirm("Cancel this transfer and delete its incomplete data?"))return;
 item.cancelled=true;
 item.el.querySelector("small").textContent="Cancelling...";
 if(item.controller)item.controller.abort();
 if(item.id){
  try{await api("/api/cancel/"+item.id,"POST","{}",{"Content-Type":"application/json"})}
  catch(e){$("error").textContent="Could not cancel on Windows: "+e.message;item.el.querySelector("small").textContent="Cancel failed";return}
 }
 item.el.querySelector("small").textContent="Cancelled";
 count();
}
async function removeItem(item){
 if(!confirm("Remove this item from the list? Completed files on Windows will be kept."))return;
 item.removed=true;
 if(item.controller)item.controller.abort();
 if(item.id){
  try{await api("/api/remove/"+item.id,"POST","{}",{"Content-Type":"application/json"})}
  catch(e){$("error").textContent="Could not remove on Windows: "+e.message;item.removed=false;return}
 }
 item.el.remove();
 const index=queue.indexOf(item);if(index>=0)queue.splice(index,1);
 count();
}
function row(item){
 const f=item.file,el=document.createElement("div");el.className="item";
 const top=document.createElement("div");top.className="row";
 const name=document.createElement("strong");name.textContent=f.name;
 const size=document.createElement("span");size.textContent=(f.size/1048576).toFixed(1)+" MB";
 top.append(name,size);
 const progress=document.createElement("progress");progress.max=100;progress.value=0;
 const status=document.createElement("small");status.textContent="Waiting";
 const actions=document.createElement("div");actions.className="actions";
 const resume=document.createElement("button");resume.type="button";resume.className="resume";resume.textContent="▶";resume.title="Resume interrupted transfer";resume.setAttribute("aria-label","Resume interrupted transfer");
 resume.onclick=async()=>{
  if(item.done||item.removed||item.cancelled)return;
  item.retryRequested=true;
  if(item.id){try{await api("/api/resume/"+item.id,"POST","{}",{"Content-Type":"application/json"})}catch(e){$("error").textContent=e.message}}
  if(!busy)runQueue();
 };
 const cancel=document.createElement("button");cancel.type="button";cancel.className="danger";cancel.textContent="■";cancel.title="Cancel transfer and delete partial data";cancel.setAttribute("aria-label","Cancel transfer");
 cancel.onclick=()=>cancelItem(item);
 const remove=document.createElement("button");remove.type="button";remove.className="muted";remove.textContent="✕";remove.title="Remove from transfer list";remove.setAttribute("aria-label","Remove transfer");
 remove.onclick=()=>removeItem(item);
 actions.append(resume,cancel,remove);el.append(top,progress,status,actions);$("queue").append(el);
 item.el=el;item.cancelButton=cancel;item.resumeButton=resume;return el;
}
$("connect").onclick=async()=>{
 token=$("token").value.trim();
 try{await api("/api/status");$("connection").textContent="Connected to Windows receiver";$("error").textContent=""}
 catch(e){$("connection").textContent="Connection failed: "+e.message}
};
function addFiles(selected){
 $("pickerStatus").textContent="Picker returned "+selected.length+" item(s)";
 for(const file of selected){
  const item={file,id:null,done:false,cancelled:false,removed:false,controller:null};
  queue.push(item);row(item);
 }
 count();
 window.dispatchEvent(new Event("khensoz-files-queued"));
 $("error").textContent=selected.length?"":"No files returned by the picker.";
}
window.addEventListener("khensoz-files-picked",event=>{
 try{addFiles(event.detail.files||[])}
 catch(e){$("pickerDebug").textContent="Queue error: "+e.message;throw e}
});
async function digest(buffer){return sha256(new Uint8Array(buffer))}
async function fingerprint(file){
 const head=await file.slice(0,Math.min(file.size,65536)).arrayBuffer();
 const tail=await file.slice(Math.max(0,file.size-65536)).arrayBuffer();
 const bytes=new Uint8Array(head.byteLength+tail.byteLength);
 bytes.set(new Uint8Array(head));bytes.set(new Uint8Array(tail),head.byteLength);
 return digest(bytes.buffer);
}
async function transfer(item){
 const f=item.file,progress=item.el.querySelector("progress"),status=item.el.querySelector("small");
 let attempt=0;
 while(!item.done&&!item.cancelled&&!item.removed){
  try{
   const fp=await fingerprint(f);
   if(item.cancelled||item.removed)return;
   const init=await api("/api/init","POST",JSON.stringify({name:f.name,size:f.size,fingerprint:fp}),{"Content-Type":"application/json"});
   item.id=init.id;item.retryRequested=false;
   if(item.cancelled||item.removed){await api("/api/cancel/"+init.id,"POST","{}",{"Content-Type":"application/json"});return}
   let off=init.offset;
   while(off<f.size&&!item.cancelled&&!item.removed){
    const buf=await f.slice(off,off+4*1024*1024).arrayBuffer();
    if(item.cancelled||item.removed)return;
    const hash=await digest(buf);
    const controller=new AbortController();item.controller=controller;
    const r=await fetch("/api/chunk/"+init.id,{method:"PUT",signal:controller.signal,headers:{"X-Transfer-Token":token,"X-Chunk-Offset":String(off),"X-Chunk-SHA256":hash},body:buf});
    const data=await r.json();item.controller=null;
    if(!r.ok)throw Error(data.error||"Upload failed");
    off=data.offset;progress.value=f.size?off/f.size*100:100;
    status.textContent=(off/1048576).toFixed(1)+" / "+(f.size/1048576).toFixed(1)+" MB";
   }
   if(item.cancelled||item.removed)return;
   if(!init.complete)await api("/api/finish/"+init.id,"POST","{}",{"Content-Type":"application/json"});
   item.done=true;progress.value=100;status.textContent="Completed";item.cancelButton.disabled=true;item.resumeButton.disabled=true;return;
  }catch(e){
   item.controller=null;
   if(item.cancelled||item.removed)return;
   status.textContent="Retrying: "+e.message;
   if(attempt++>=3){status.textContent="Interrupted - tap ▶ to resume";return}
   await wait(Math.min(15000,1000*2**Math.min(attempt,4)));
  }
 }
}
async function runQueue(){
 if(busy)return;
 if(!token)return alert("Connect to Windows first");
 busy=true;$("start").disabled=true;
 try{for(const item of [...queue]){if(!item.done&&!item.cancelled&&!item.removed)await transfer(item)}}
 finally{busy=false;$("start").disabled=false;count()}
}
$("start").onclick=runQueue;
setInterval(async()=>{
 if(!token||busy)return;
 try{
  const data=await api("/api/status");
  for(const item of queue){
   if(item.done||item.cancelled||item.removed||!item.id)continue;
   const remote=data.sessions?.[item.id];
   if(remote?.status==="cancelled"){item.cancelled=true;item.el.querySelector("small").textContent="Cancelled on Windows";count();continue}
   if(!remote&&item.id){item.removed=true;item.el.remove();count();continue}
   if(remote?.resume_requested){await runQueue();break}
  }
 }catch(e){}
},3000);
