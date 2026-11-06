import {sha256} from './sha256.js';
const $=id=>document.getElementById(id);
const queue=[];
let connected=false,busy=false,wakeLock=null;
const storageKey="khensoz-transfer-pending";
function savePending(){try{sessionStorage.setItem(storageKey,JSON.stringify(queue.filter(x=>!x.done&&!x.removed&&!x.cancelled).map(x=>({name:x.file.name,size:x.file.size,lastModified:x.file.lastModified,id:x.id||null}))));}catch(e){}}
function restoreNotice(){try{const saved=JSON.parse(sessionStorage.getItem(storageKey)||"[]");if(saved.length)$("pickerStatus").textContent="Interrupted transfer: select the same video again to resume from the saved Windows progress."; }catch(e){}}
async function holdAwake(){try{if("wakeLock" in navigator&&!wakeLock&&document.visibilityState==="visible"){wakeLock=await navigator.wakeLock.request("screen");wakeLock.addEventListener("release",()=>{wakeLock=null});}}catch(e){}}
async function releaseAwake(){if(wakeLock){try{await wakeLock.release()}catch(e){}wakeLock=null}}
document.addEventListener("visibilitychange",()=>{if(document.visibilityState==="visible"&&busy)holdAwake()});
window.addEventListener("error",e=>{$("error").textContent="App error: "+e.message});
window.addEventListener("unhandledrejection",e=>{$("error").textContent="App error: "+String(e.reason)});
const wait=ms=>new Promise(resolve=>setTimeout(resolve,ms));
function count(){const pending=queue.filter(x=>!x.done&&!x.removed&&!x.cancelled).length;$("count").textContent=pending?pending+" file(s) queued":"No files queued"}
async function api(path,method="GET",body,headers={}){
 const r=await fetch(path,{method,headers:{...headers},body});
 const data=await r.json();
 if(!r.ok)throw Error(data.error||"HTTP "+r.status);
 return data;
}
async function cancelItem(item){
 if(item.done)return;
 if(!confirm("Cancel this transfer and delete its incomplete data?"))return;
 item.cancelled=true;
 savePending();
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
 savePending();
 if(item.controller)item.controller.abort();
 if(item.id){
  try{await api("/api/remove/"+item.id,"POST","{}",{"Content-Type":"application/json"})}
  catch(e){$("error").textContent="Could not remove on Windows: "+e.message;item.removed=false;return}
 }
 item.el.remove();
 const index=queue.indexOf(item);if(index>=0)queue.splice(index,1);
 savePending();count();
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
async function connect(){
 try{
  await api("/api/status");
  connected=true;
  $("connection").textContent="Connected to Windows receiver";
  $("error").textContent="";
 }catch(e){
  connected=false;
  $("connection").textContent="Connection failed: "+e.message;
 }
}
connect();
// Retry automatically if the Windows app starts after this page was opened.
setInterval(()=>{if(!connected)connect()},5000);
// Restore the original iPhone picker path: native input inside a label,
// with direct change/input listeners. Transfer actions are independent.
function addFiles(input){
 const selected=Array.from(input.files||[]);
 $("pickerStatus").textContent="Picker returned "+selected.length+" item(s)";
 for(const file of selected){
  // Re-selecting a file replaces its stale browser handle, never creates a second queue row.
  const existing=queue.find(x=>!x.done&&!x.cancelled&&!x.removed&&x.file.name===file.name&&x.file.size===file.size&&x.file.lastModified===file.lastModified);
  if(existing){existing.file=file;continue}
  const item={file,id:null,done:false,cancelled:false,removed:false,controller:null};
  queue.push(item);row(item);
 }
 savePending();count();
 $("error").textContent=selected.length?"":"No files returned by the picker. Try Choose files.";
}
for(const id of ["photos","files","cameraPhoto","cameraVideo"]){
 const input=$(id);
 // iOS Safari may dispatch both input and change for a single selection.
 // Process only change, once per picker selection, to avoid duplicate rows.
 input.addEventListener("change",()=>{addFiles(input);if(id==="cameraPhoto"||id==="cameraVideo")runQueue();});
}
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
   item.id=init.id;item.retryRequested=false;savePending();
   progress.value=f.size?init.offset/f.size*100:100;
   status.textContent=init.offset?"Resuming from "+(init.offset/1048576).toFixed(1)+" MB":"Starting transfer";
   if(item.cancelled||item.removed){await api("/api/cancel/"+init.id,"POST","{}",{"Content-Type":"application/json"});return}
   let off=init.offset;
   while(off<f.size&&!item.cancelled&&!item.removed){
    const buf=await f.slice(off,off+4*1024*1024).arrayBuffer();
    if(item.cancelled||item.removed)return;
    const hash=await digest(buf);
    const controller=new AbortController();item.controller=controller;
    const r=await fetch("/api/chunk/"+init.id,{method:"PUT",signal:controller.signal,headers:{"X-Chunk-Offset":String(off),"X-Chunk-SHA256":hash},body:buf});
    const data=await r.json();item.controller=null;
    if(!r.ok)throw Error(data.error||"Upload failed");
    off=data.offset;progress.value=f.size?off/f.size*100:100;
    status.textContent=(off/1048576).toFixed(1)+" / "+(f.size/1048576).toFixed(1)+" MB";
   }
   if(item.cancelled||item.removed)return;
   if(!init.complete)await api("/api/finish/"+init.id,"POST","{}",{"Content-Type":"application/json"});
   item.done=true;progress.value=100;status.textContent="Completed";
   // Remove only the UI entry; Windows retains the completed file and its record.
   item.el.remove();savePending();count();return;
  }catch(e){
   item.controller=null;
   if(item.cancelled||item.removed)return;
   status.textContent="Retrying: "+e.message;
   if(attempt++>=3){status.textContent="Interrupted - tap ▶ to resume";savePending();return}
   await wait(Math.min(15000,1000*2**Math.min(attempt,4)));
  }
 }
}
async function runQueue(){
 if(busy)return;
 if(!connected){await connect();if(!connected)return alert("Cannot reach Windows receiver. Check Wi-Fi and the URL.");}
 busy=true;$("start").disabled=true;await holdAwake();
 try{for(const item of [...queue]){if(!item.done&&!item.cancelled&&!item.removed)await transfer(item)}}
 finally{busy=false;$("start").disabled=false;await releaseAwake();savePending();count()}
}
$("start").onclick=runQueue;

let hqStream=null,hqRecorder=null,hqChunks=[],hqRecording=false;
const hqStatus=message=>{$("hqStatus").textContent=message};
function hqMime(){
 const candidates=["video/mp4;codecs=avc1.42E01E,mp4a.40.2","video/mp4","video/webm;codecs=vp9,opus","video/webm"];
 return candidates.find(type=>MediaRecorder.isTypeSupported(type))||"";
}
async function closeHQ(){
 if(hqRecording){hqStatus("Stop recording before closing.");return}
 if(hqStream){hqStream.getTracks().forEach(track=>track.stop());hqStream=null}
 $("hqPreview").srcObject=null;
 $("hqCamera").hidden=true;
 $("hqOpen").disabled=false;
}
async function openHQ(){
 $("hqCamera").hidden=false;
 $("hqOpen").disabled=true;
 if(!window.isSecureContext||!navigator.mediaDevices?.getUserMedia){
  hqStatus("High Quality Camera requires trusted HTTPS. Open the receiver's HTTPS URL with a trusted certificate. The native camera button still works over HTTP.");
  $("hqActual").textContent="Camera unavailable in this browser context";
  return;
 }
 if(typeof MediaRecorder==="undefined"){hqStatus("MediaRecorder is not supported by this browser.");return}
 try{
  if(hqStream)hqStream.getTracks().forEach(track=>track.stop());
  const [width,height,frameRate]=$("hqPreset").value.split("x").map(Number);
  hqStream=await navigator.mediaDevices.getUserMedia({
   video:{facingMode:{ideal:"environment"},width:{ideal:width},height:{ideal:height},frameRate:{ideal:frameRate}},
   audio:true
  });
  $("hqPreview").srcObject=hqStream;
  const actual=hqStream.getVideoTracks()[0].getSettings();
  $("hqActual").textContent="Actual camera: "+(actual.width||"?")+" × "+(actual.height||"?")+" @ "+(actual.frameRate||"?")+" FPS (requested "+width+" × "+height+" @ "+frameRate+")";
  hqStatus("Ready. Recordings upload without additional compression.");
 }catch(e){hqStatus("Camera access failed: "+e.message)}
}
$("hqOpen").onclick=openHQ;
$("hqClose").onclick=closeHQ;
$("hqPreset").onchange=()=>{if(!hqRecording)openHQ()};
$("hqStart").onclick=async()=>{
 if(!hqStream){await openHQ();if(!hqStream)return}
 try{
  const mime=hqMime();
  const options={videoBitsPerSecond:25_000_000,audioBitsPerSecond:192_000};
  if(mime)options.mimeType=mime;
  hqChunks=[];
  hqRecorder=new MediaRecorder(hqStream,options);
  hqRecorder.ondataavailable=e=>{if(e.data.size)hqChunks.push(e.data)};
  hqRecorder.onerror=e=>hqStatus("Recording error: "+(e.error?.message||"unknown"));
  hqRecorder.onstop=()=>{
   hqRecording=false;
   $("hqStart").disabled=false;
   $("hqStop").disabled=true;
   const type=hqRecorder.mimeType||mime||"video/mp4";
   const extension=type.includes("webm")?"webm":"mp4";
   const blob=new Blob(hqChunks,{type});hqChunks=[];
   if(!blob.size){hqStatus("Recording was empty; nothing transferred.");return}
   const name="Khensoz-"+new Date().toISOString().replace(/[:.]/g,"-")+"."+extension;
   const file=new File([blob],name,{type,lastModified:Date.now()});
   const item={file,id:null,done:false,cancelled:false,removed:false,controller:null};
   queue.push(item);row(item);savePending();count();
   hqStatus("Recorded "+(blob.size/1048576).toFixed(1)+" MB. Uploading original encoded file to Windows.");
   runQueue();
  };
  hqRecorder.start(1000);
  hqRecording=true;
  $("hqStart").disabled=true;
  $("hqStop").disabled=false;
  hqStatus("Recording… keep this page in the foreground. Actual encoding depends on Safari.");
 }catch(e){hqStatus("Unable to start recording: "+e.message)}
};
$("hqStop").onclick=()=>{
 if(hqRecorder?.state==="recording")hqRecorder.stop();
};


let libraryFolder="";
const libraryURL=(path,download=false)=>"/api/library/file?path="+encodeURIComponent(path)+(download?"&download=1":"");
function libraryViewerClose(){
 $("libraryMedia").replaceChildren();$("libraryViewer").hidden=true;
 document.body.style.overflow="";
}
$("libraryClose").onclick=libraryViewerClose;
$("libraryRefresh").onclick=()=>loadLibrary(libraryFolder);
async function loadLibrary(folder=""){
 $("libraryStatus").textContent="Loading Windows files…";
 $("libraryGrid").replaceChildren();
 try{
  const data=await api("/api/library?path="+encodeURIComponent(folder));
  libraryFolder=data.folder;
  const crumb=$("libraryBreadcrumb");crumb.replaceChildren();
  const home=document.createElement("button");home.textContent="Shared folder";home.onclick=()=>loadLibrary("");crumb.append(home);
  if(libraryFolder){
   const up=document.createElement("button");up.textContent="↑ Up";up.onclick=()=>loadLibrary(libraryFolder.split("/").slice(0,-1).join("/"));crumb.append(up);
   const label=document.createElement("span");label.textContent=" / "+libraryFolder;crumb.append(label);
  }
  for(const item of data.items){
   const card=document.createElement("div");card.className="library-card";
   const preview=document.createElement("button");preview.className="library-preview";
   const url=libraryURL(item.path);
   if(item.folder){preview.textContent="📁";preview.onclick=()=>loadLibrary(item.path)}
   else{
    if(item.type.startsWith("image/")){
     const img=document.createElement("img");img.src=url;img.alt=item.name;img.loading="lazy";preview.append(img);
    }else if(item.type.startsWith("video/")){
     const video=document.createElement("video");video.src=url+"#t=0.1";video.preload="metadata";video.muted=true;video.playsInline=true;preview.append(video);
    }else preview.textContent="📄";
    preview.onclick=()=>openLibraryItem(item);
   }
   const title=document.createElement("div");title.className="library-name";title.textContent=item.name;
   card.append(preview,title);
   if(!item.folder){
    const download=document.createElement("a");download.href=libraryURL(item.path,true);download.download=item.name;download.textContent="Download original";download.className="library-download";card.append(download);
   }
   $("libraryGrid").append(card);
  }
  $("libraryStatus").textContent=data.items.length+" item(s) in Windows folder";
 }catch(e){$("libraryStatus").textContent="Unable to load Windows media: "+e.message}
}
function openLibraryItem(item){
 const url=libraryURL(item.path),area=$("libraryMedia");area.replaceChildren();
 $("libraryTitle").textContent=item.name;
 $("libraryDownload").onclick=()=>{const a=document.createElement("a");a.href=libraryURL(item.path,true);a.download=item.name;document.body.append(a);a.click();a.remove()};
 if(item.type.startsWith("image/")){
  const img=document.createElement("img");img.src=url;img.alt=item.name;area.append(img);
 }else if(item.type.startsWith("video/")){
  const video=document.createElement("video");video.src=url;video.controls=true;video.playsInline=true;video.preload="metadata";area.append(video);
 }else{const p=document.createElement("p");p.textContent="Preview unavailable. Download the original file.";area.append(p)}
 $("libraryViewer").hidden=false;document.body.style.overflow="hidden";
}
loadLibrary();

restoreNotice();
setInterval(async()=>{
 if(!connected||busy)return;
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
