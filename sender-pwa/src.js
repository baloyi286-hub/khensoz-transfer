import {sha256} from './sha256.js';
const $=id=>document.getElementById(id),queue=[];let token="",busy=false;
window.addEventListener("error",e=>{$("error").textContent="App error: "+e.message});
window.addEventListener("unhandledrejection",e=>{$("error").textContent="App error: "+String(e.reason)});
function row(f){let el=document.createElement("div");el.className="item";el.innerHTML='<div class="row"><strong></strong><span></span></div><progress max="100" value="0"></progress><small>Waiting</small>';el.querySelector("strong").textContent=f.name;el.querySelector("span").textContent=(f.size/1048576).toFixed(1)+" MB";$("queue").append(el);return el}
$("connect").onclick=async()=>{token=$("token").value.trim();try{let r=await fetch("/api/status",{headers:{"X-Transfer-Token":token}});if(!r.ok)throw Error("Incorrect token");$("connection").textContent="✓ Connected to Windows receiver"}catch(e){$("connection").textContent="Connection failed: "+e.message}};
function addFiles(input){const selected=Array.from(input.files||[]);for(const f of selected){queue.push({file:f,el:row(f),done:false})}const pending=queue.filter(x=>!x.done).length;$("count").textContent=pending?pending+" file(s) queued":"No files selected";if(!selected.length)$("error").textContent="No files returned by iOS picker. Try Choose files instead.";else $("error").textContent="";input.value=""}
$("choosePhotos").addEventListener("click",()=>{$("error").textContent="";$("photos").click()});
$("chooseFiles").addEventListener("click",()=>{$("error").textContent="";$("files").click()});
$("photos").addEventListener("change",()=>addFiles($("photos")));
$("files").addEventListener("change",()=>addFiles($("files")));
async function api(path,method,body,headers={}){let r=await fetch(path,{method,headers:{"X-Transfer-Token":token,...headers},body});let data=await r.json();if(!r.ok)throw Error(data.error||"HTTP "+r.status);return data}
async function digest(buf){return sha256(new Uint8Array(buf))}
async function fingerprint(f){let head=await f.slice(0,Math.min(f.size,65536)).arrayBuffer();let tail=await f.slice(Math.max(0,f.size-65536)).arrayBuffer();let a=new Uint8Array(head.byteLength+tail.byteLength);a.set(new Uint8Array(head));a.set(new Uint8Array(tail),head.byteLength);return digest(a)}
const wait=ms=>new Promise(r=>setTimeout(r,ms));
async function transfer(item){let f=item.file,el=item.el,progress=el.querySelector("progress"),status=el.querySelector("small");let attempt=0;
while(!item.done){try{
let fp=await fingerprint(f),init=await api("/api/init","POST",JSON.stringify({name:f.name,size:f.size,fingerprint:fp}),{"Content-Type":"application/json"});let off=init.offset;
while(off<f.size){let blob=f.slice(off,off+4*1024*1024),buf=await blob.arrayBuffer();let hash=await digest(buf);let result=await api("/api/chunk/"+init.id,"PUT",buf,{"X-Chunk-Offset":String(off),"X-Chunk-SHA256":hash});off=result.offset;progress.value=f.size?off/f.size*100:100;status.textContent=(off/1048576).toFixed(1)+" / "+(f.size/1048576).toFixed(1)+" MB"}
if(!init.complete)await api("/api/finish/"+init.id,"POST","{}",{"Content-Type":"application/json"});item.done=true;progress.value=100;status.textContent="✓ Completed";return
}catch(e){status.textContent="Disconnected — retrying: "+e.message;await wait(Math.min(15000,1000*2**Math.min(attempt++,4)))}}}
$("start").onclick=async()=>{if(busy||!token)return alert("Connect to Windows first");busy=true;for(const item of queue){if(!item.done)await transfer(item)}busy=false;$("count").textContent="All transfers complete"};
