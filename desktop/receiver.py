import hashlib,json,os,secrets,socket,sys,threading,tkinter as tk,traceback,subprocess
from pathlib import Path
from tkinter import filedialog,ttk
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit

ROOT=Path(getattr(sys,"_MEIPASS",Path(__file__).resolve().parents[1]))
WEB=ROOT/"sender-pwa"
LOCK=threading.RLock()
class State:
 def __init__(self,destination,port):
  self.destination=Path(destination);self.destination.mkdir(parents=True,exist_ok=True)
  self.port=port;self.token=secrets.token_urlsafe(18)
  self.home=Path(os.environ.get("LOCALAPPDATA",Path.home()))/"KhensozTransfer";self.home.mkdir(parents=True,exist_ok=True)
  try:self.sessions=json.loads((self.home/"transfers.json").read_text())
  except (OSError,ValueError):self.sessions={}
 def save(self):
  p=self.home/"transfers.json";tmp=p.with_suffix(".tmp");tmp.write_text(json.dumps(self.sessions));tmp.replace(p)
 def create_or_resume(self,name,size,fingerprint):
  name=Path(str(name).replace("\\","/")).name
  if not name or name in (".","..") or len(name)>240 or not isinstance(size,int) or size<0 or size>10**15:raise ValueError("Invalid file")
  with LOCK:
   for k,v in self.sessions.items():
    if v["status"]=="cancelled":continue
    if (v["name"],v["size"],v["fingerprint"])==(name,size,fingerprint):
     if v["status"]=="complete":return {"id":k,"offset":size,"complete":True}
     p=Path(v["part"])
     if p.exists():
      v["offset"]=min(p.stat().st_size,size);v["resume_requested"]=False;self.save()
      return {"id":k,"offset":v["offset"],"complete":False}
   k=secrets.token_hex(16);part_dir=self.destination/".khensoz-partials";part_dir.mkdir(parents=True,exist_ok=True);p=part_dir/(k+".part");p.touch()
   target=self.destination/name;n=1
   while target.exists() or any(v["target"]==str(target) for v in self.sessions.values()):
    target=self.destination/(Path(name).stem+f" ({n})"+Path(name).suffix);n+=1
   self.sessions[k]=dict(name=name,size=size,fingerprint=fingerprint,offset=0,part=str(p),target=str(target),status="receiving")
   self.save();return {"id":k,"offset":0,"complete":False}
 def append(self,k,offset,data):
  with LOCK:
   v=self.sessions[k]
   if v["status"]!="receiving":raise ValueError("Transfer is no longer active")
   p=Path(v["part"])
   actual=p.stat().st_size
   if offset!=actual:raise ValueError(f"Offset mismatch: {actual}")
   if actual+len(data)>v["size"]:raise ValueError("Exceeds file size")
   with p.open("ab") as f:f.write(data);f.flush();os.fsync(f.fileno())
   v["offset"]=actual+len(data);self.save();return v["offset"]
 def finish(self,k):
  with LOCK:
   v=self.sessions[k]
   if v["status"]!="receiving":raise ValueError("Transfer is no longer active")
   p=Path(v["part"])
   if p.stat().st_size!=v["size"]:raise ValueError("Incomplete")
   target=Path(v["target"])
   target.parent.mkdir(parents=True,exist_ok=True)
   if p.resolve().anchor.lower()==target.resolve().anchor.lower():
    p.replace(target)
   else:
    # Legacy sessions may still have partials on C:. Copy safely across drives.
    import shutil
    staging=target.parent/(".khensoz-"+str(k)+".part")
    with p.open("rb") as src,staging.open("wb") as dst:
     shutil.copyfileobj(src,dst,1024*1024)
     dst.flush();os.fsync(dst.fileno())
    staging.replace(target)
    p.unlink()
   v["status"]="complete";v["offset"]=v["size"];self.save()
 def cancel(self,k):
  with LOCK:
   v=self.sessions[k]
   if v["status"]=="complete":raise ValueError("Completed transfers cannot be cancelled")
   if v["status"]!="cancelled":
    v["status"]="cancelled"
    p=Path(v["part"])
    if p.exists():p.unlink()
    self.save()
 def remove(self,k):
  with LOCK:
   v=self.sessions[k]
   if v["status"]=="receiving":self.cancel(k)
   del self.sessions[k]
   self.save()
 def request_resume(self,k):
  with LOCK:
   v=self.sessions[k]
   if v["status"]!="receiving":raise ValueError("Only incomplete transfers can resume; cancelled transfers have no partial data")
   v["resume_requested"]=True
   self.save()
 def snapshot(self):
  with LOCK:
   return {k:dict(v) for k,v in self.sessions.items()}
class Handler(BaseHTTPRequestHandler):
 def log_message(self,format,*args):
  try:
   with (self.server.state.home/'receiver.log').open('a',encoding='utf-8') as log:log.write('%s - %s\n'%(self.address_string(),format%args))
  except OSError:pass
 def send(self,code,data):
  b=json.dumps(data).encode();self.send_response(code);self.send_header("Content-Type","application/json");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
 def auth(self):return secrets.compare_digest(self.headers.get("X-Transfer-Token",""),self.server.state.token)
 def do_GET(self):
  path=urlsplit(self.path).path
  if path.startswith("/api/"):
   if not self.auth():return self.send(403,{"error":"Invalid pairing token"})
   if path=="/api/status":return self.send(200,{"sessions":self.server.state.snapshot()})
   return self.send(404,{"error":"Not found"})
  file=WEB/(path.lstrip("/") or "index.html")
  if not file.is_file() or not file.resolve().is_relative_to(WEB.resolve()):return self.send(404,{"error":"Not found"})
  b=file.read_bytes();mime={".html":"text/html",".js":"text/javascript",".css":"text/css",".svg":"image/svg+xml",".webmanifest":"application/manifest+json"}.get(file.suffix,"application/octet-stream")
  self.send_response(200);self.send_header("Content-Type",mime+"; charset=utf-8" if mime.startswith(("text/","application/manifest")) else mime);self.send_header("Cache-Control","no-store");self.send_header("Content-Length",str(len(b)));self.end_headers();self.wfile.write(b)
 def do_POST(self):
  if not self.auth():return self.send(403,{"error":"Invalid pairing token"})
  try:
   length=int(self.headers.get("Content-Length","0"))
   if length>4096:raise ValueError("Request too large")
   data=json.loads(self.rfile.read(length))
   if self.path=="/api/init":return self.send(200,self.server.state.create_or_resume(data["name"],data["size"],data["fingerprint"]))
   if self.path.startswith("/api/resume/"):
    self.server.state.request_resume(self.path.split("/")[-1]);return self.send(200,{"requested":True})
   if self.path.startswith("/api/cancel/"):
    self.server.state.cancel(self.path.split("/")[-1]);return self.send(200,{"cancelled":True})
   if self.path.startswith("/api/remove/"):
    self.server.state.remove(self.path.split("/")[-1]);return self.send(200,{"removed":True})
   if self.path.startswith("/api/finish/"):
    self.server.state.finish(self.path.split("/")[-1]);return self.send(200,{"complete":True})
   return self.send(404,{"error":"Not found"})
  except (ValueError,KeyError,OSError) as e:return self.send(400,{"error":str(e)})
 def do_PUT(self):
  if not self.auth():return self.send(403,{"error":"Invalid pairing token"})
  try:
   if not self.path.startswith("/api/chunk/"):return self.send(404,{"error":"Not found"})
   n=int(self.headers.get("Content-Length","0"))
   if n<0 or n>8*1024*1024:raise ValueError("Invalid chunk length")
   data=self.rfile.read(n)
   if len(data)!=n or hashlib.sha256(data).hexdigest()!=self.headers.get("X-Chunk-SHA256"):raise ValueError("Chunk checksum mismatch")
   offset=self.server.state.append(self.path.split("/")[-1],int(self.headers["X-Chunk-Offset"]),data)
   return self.send(200,{"offset":offset})
  except (ValueError,KeyError,OSError) as e:return self.send(409,{"error":str(e)})
class Server(ThreadingHTTPServer):
 daemon_threads=True
 def __init__(self,address,state):super().__init__(address,Handler);self.state=state
def main():
 root=tk.Tk();root.title("Khensoz Transfer");root.geometry("750x530");root.configure(bg="#101b2a")
 style=ttk.Style();style.theme_use("clam")
 style.configure("Dark.TFrame",background="#101b2a")
 style.configure("Dark.TLabel",background="#101b2a",foreground="#eaf4ff",font=("Segoe UI",11))
 style.configure("Dark.TEntry",fieldbackground="#263a4e",foreground="white",padding=9)
 style.configure("Dark.TButton",background="#17845a",foreground="white",padding=9)
 style.map("Dark.TButton",background=[("active","#20a570")])
 frame=ttk.Frame(root,style="Dark.TFrame",padding=22);frame.pack(fill="both",expand=True)
 ttk.Label(frame,text="Khensoz Transfer",style="Dark.TLabel",font=("Segoe UI",22,"bold")).pack(anchor="w",pady=(0,15))
 dest=tk.StringVar(value=str(Path.home()/"Downloads"/"Khensoz Transfer"))
 ttk.Label(frame,text="Save incoming files to",style="Dark.TLabel").pack(anchor="w")
 ttk.Entry(frame,textvariable=dest,style="Dark.TEntry").pack(fill="x",pady=7)
 ttk.Button(frame,text="Choose folder",style="Dark.TButton",command=lambda:dest.set(filedialog.askdirectory() or dest.get())).pack(anchor="w",pady=(0,16))
 state=State(dest.get(),8765)
 addresses=set()
 try:
  for item in socket.getaddrinfo(socket.gethostname(),None,socket.AF_INET):
   ip=item[4][0]
   if not ip.startswith(("127.","169.254.")):addresses.add(ip)
 except OSError:pass
 try:
  s=socket.socket(socket.AF_INET,socket.SOCK_DGRAM);s.connect(("1.1.1.1",80));addresses.add(s.getsockname()[0]);s.close()
 except OSError:pass
 ttk.Label(frame,text="Open one of these URLs on iPhone Safari (same Wi-Fi)",style="Dark.TLabel").pack(anchor="w")
 info=tk.Label(frame,text="\\n".join("http://"+ip+":8765" for ip in sorted(addresses)) or "No LAN IP detected",bg="#253a4e",fg="#6ce1aa",font=("Consolas",12),justify="left",anchor="w",padx=12,pady=12)
 info.pack(fill="x",pady=7)
 ttk.Label(frame,text="Pairing token",style="Dark.TLabel").pack(anchor="w")
 token=tk.Entry(frame,bg="#253a4e",fg="white",relief="flat",font=("Consolas",12))
 token.insert(0,state.token);token.pack(fill="x",ipady=8,pady=7)
 ttk.Label(frame,text="Transfers",style="Dark.TLabel").pack(anchor="w",pady=(12,3))
 listing=tk.Listbox(frame,bg="#253a4e",fg="white",selectbackground="#17845a",borderwidth=0,highlightthickness=0)
 listing.pack(fill="both",expand=True)
 controls=ttk.Frame(frame,style="Dark.TFrame");controls.pack(fill="x",pady=(10,0))
 def selected():
  selection=listing.curselection()
  if not selection:return None
  keys=list(state.snapshot())
  return keys[selection[0]] if selection[0]<len(keys) else None
 def resume_selected():
  from tkinter import messagebox
  k=selected()
  if not k:return
  try:
   state.request_resume(k)
   messagebox.showinfo("Resume requested","Resume requested on iPhone. Keep the sender page open; if it was reloaded, reselect the same file first.")
  except (ValueError,KeyError,OSError) as e:messagebox.showerror("Cannot resume",str(e))
 def cancel_selected():
  from tkinter import messagebox
  k=selected()
  if not k:return
  try:
   if messagebox.askyesno("Cancel transfer","Cancel this transfer and delete its incomplete data?"):
    state.cancel(k);update()
  except (ValueError,KeyError,OSError) as e:messagebox.showerror("Cannot cancel",str(e))
 def remove_selected():
  from tkinter import messagebox
  k=selected()
  if not k:return
  if messagebox.askyesno("Remove transfer","Remove this item from the transfer list? Completed files will be kept."):
   state.remove(k);update()
 def open_selected(folder=False):
  from tkinter import messagebox
  k=selected()
  if not k:return
  v=state.snapshot().get(k)
  if not v or v["status"]!="complete":
   messagebox.showinfo("Not completed","Opening files is available after transfer completes.");return
  p=Path(v["target"])
  if not p.exists():messagebox.showerror("File missing","The completed file was moved or deleted.");return
  if folder:subprocess.Popen(["explorer.exe","/select,",str(p)])
  else:os.startfile(str(p))
 ttk.Button(controls,text="▶",style="Dark.TButton",command=resume_selected).pack(side="left",padx=(0,8))
 ttk.Button(controls,text="■",style="Dark.TButton",command=cancel_selected).pack(side="left",padx=(0,8))
 ttk.Button(controls,text="✕",style="Dark.TButton",command=remove_selected).pack(side="left",padx=(0,8))
 ttk.Button(controls,text="↗",style="Dark.TButton",command=lambda:open_selected(False)).pack(side="left",padx=(0,8))
 ttk.Button(controls,text="▣",style="Dark.TButton",command=lambda:open_selected(True)).pack(side="left")
 tips=tk.StringVar(value="▶ Resume   ■ Cancel   ✕ Remove   ↗ Open file   ▣ Show in folder")
 ttk.Label(frame,textvariable=tips,style="Dark.TLabel",font=("Segoe UI",9)).pack(anchor="w",pady=(5,0))
 for widget,tip in zip(controls.winfo_children(),["Resume interrupted transfer","Cancel and delete incomplete data","Remove item from list","Open completed file","Show completed file in folder"]):
  widget.bind("<Enter>",lambda e,t=tip:tips.set(t))
  widget.bind("<Leave>",lambda e:tips.set("▶ Resume   ■ Cancel   ✕ Remove   ↗ Open file   ▣ Show in folder"))
 try:server=Server(("0.0.0.0",8765),state)
 except OSError as e:
  from tkinter import messagebox
  messagebox.showerror("Cannot start receiver",str(e));root.destroy();return
 def update():
  state.destination=Path(dest.get());state.destination.mkdir(parents=True,exist_ok=True)
  current=listing.curselection()
  listing.delete(0,tk.END)
  for v in state.snapshot().values():listing.insert(tk.END,f'{v["name"]} - {v["offset"]:,} / {v["size"]:,} bytes - {v["status"]}')
  if current and current[0]<listing.size():listing.selection_set(current[0])
  root.after(1000,update)
 threading.Thread(target=server.serve_forever,daemon=True).start();update()
 root.protocol("WM_DELETE_WINDOW",lambda:(server.shutdown(),root.destroy()));root.mainloop()
if __name__=="__main__":main()
