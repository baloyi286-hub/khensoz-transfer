import hashlib,json,os,secrets,socket,sys,threading,tkinter as tk,traceback,subprocess,ctypes,time
from pathlib import Path
from tkinter import filedialog,ttk
from http.server import ThreadingHTTPServer,BaseHTTPRequestHandler
from urllib.parse import urlsplit,quote

# Windows power APIs: keep the display and system awake while the receiver runs.
ES_CONTINUOUS=0x80000000
ES_SYSTEM_REQUIRED=0x00000001
ES_DISPLAY_REQUIRED=0x00000002
def keep_windows_awake(enabled):
 if sys.platform!="win32":return
 try:
  flags=ES_CONTINUOUS | (ES_SYSTEM_REQUIRED|ES_DISPLAY_REQUIRED if enabled else 0)
  ctypes.windll.kernel32.SetThreadExecutionState(flags)
 except (AttributeError,OSError):pass

def battery_status():
 """Return (percentage, plugged_in), or None on desktops without a battery."""
 if sys.platform!="win32":return None
 class SYSTEM_POWER_STATUS(ctypes.Structure):
  _fields_=[("ACLineStatus",ctypes.c_ubyte),("BatteryFlag",ctypes.c_ubyte),("BatteryLifePercent",ctypes.c_ubyte),("SystemStatusFlag",ctypes.c_ubyte),("BatteryLifeTime",ctypes.c_ulong),("BatteryFullLifeTime",ctypes.c_ulong)]
 status=SYSTEM_POWER_STATUS()
 if not ctypes.windll.kernel32.GetSystemPowerStatus(ctypes.byref(status)):return None
 if status.BatteryLifePercent==255 or status.ACLineStatus==255:return None
 return int(status.BatteryLifePercent),status.ACLineStatus==1

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
 def detect_media_extension(self,path):
  # Detect common photo/video formats from file signatures, not the shortcut filename.
  with path.open("rb") as stream:head=stream.read(4096)
  if head.startswith(b"\\xff\\xd8\\xff"):return ".jpg"
  if head.startswith(b"\\x89PNG\\r\\n\\x1a\\n"):return ".png"
  if head.startswith((b"GIF87a",b"GIF89a")):return ".gif"
  if head.startswith(b"RIFF") and head[8:12]==b"WEBP":return ".webp"
  if head.startswith(b"BM"):return ".bmp"
  if head.startswith((b"II*\\x00",b"MM\\x00*")):return ".tiff"
  if head.startswith(b"\\x00\\x00\\x01\\x00"):return ".ico"
  if head.startswith(b"\\x1a\\x45\\xdf\\xa3"):return ".mkv"
  if head.startswith(b"RIFF") and head[8:12]==b"AVI ":return ".avi"
  if head[4:8]==b"ftyp":
   brands=head[8:32]
   if any(b in brands for b in (b"heic",b"heix",b"hevc",b"hevx",b"mif1",b"msf1")):return ".heic"
   if b"avif" in brands or b"avis" in brands:return ".avif"
   if b"qt  " in brands:return ".mov"
   if b"M4V " in brands:return ".m4v"
   return ".mp4"
  return ""
 def shortcut_upload(self):
  # Apple Shortcuts: POST raw file bytes with X-Filename and X-Transfer-Token.
  # Stream to disk instead of buffering large iPhone videos in RAM.
  from urllib.parse import unquote
  name=Path(unquote(self.headers.get("X-Filename","").replace("\\\\","/"))).name
  try:
   length=int(self.headers.get("Content-Length","-1"))
   if not name or name in (".","..") or len(name)>240 or length<0 or length>10**15:
    return self.send(400,{"error":"Provide X-Filename and a valid Content-Length"})
   state=self.server.state
   with LOCK:
    target=state.destination/name
    n=1
    while target.exists() or any(v["target"]==str(target) for v in state.sessions.values()):
     target=state.destination/(Path(name).stem+f" ({n})"+Path(name).suffix);n+=1
    k=secrets.token_hex(16)
    part_dir=state.destination/".khensoz-partials";part_dir.mkdir(parents=True,exist_ok=True)
    part=part_dir/(k+".part")
    state.sessions[k]=dict(name=name,size=length,fingerprint="shortcut:"+k,offset=0,part=str(part),target=str(target),status="receiving")
    state.save()
   remaining=length
   try:
    with part.open("wb") as out:
     while remaining:
      chunk=self.rfile.read(min(1024*1024,remaining))
      if not chunk:raise ConnectionError("Upload disconnected")
      out.write(chunk)
      remaining-=len(chunk)
      with LOCK:
       state.sessions[k]["offset"]=length-remaining
       state.save()
    # Shortcut's Get Name often strips .HEIC/.JPG/.MOV. Restore it after upload.
    if not Path(name).suffix:
     detected=self.detect_media_extension(part)
     if detected:
      with LOCK:
       original=Path(state.sessions[k]["target"])
       corrected=original.with_name(original.name+detected)
       counter=1
       while corrected.exists() or any(v["target"]==str(corrected) for key,v in state.sessions.items() if key!=k):
        corrected=original.with_name(original.name+f" ({counter})"+detected)
        counter+=1
       state.sessions[k]["target"]=str(corrected)
       state.sessions[k]["name"]=corrected.name
       state.save()
       name=corrected.name
    state.finish(k)
    return self.send(200,{"complete":True,"name":name,"bytes":length})
   except (OSError,ConnectionError,ValueError):
    # Keep incomplete data visible in Windows for diagnosis.
    return self.send(409,{"error":"Shortcut upload interrupted. Please retry the file."})
  except (ValueError,OSError) as e:return self.send(400,{"error":str(e)})
 def do_POST(self):
  if not self.auth():return self.send(403,{"error":"Invalid pairing token"})
  if urlsplit(self.path).path=="/api/shortcut":return self.shortcut_upload()
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
 root=tk.Tk();root.title("Khensoz Transfer");root.geometry("950x740");root.configure(bg="#101b2a")
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
 # Power protection is active only while this window is running.
 keep_windows_awake(True)
 power_row=ttk.Frame(frame,style="Dark.TFrame")
 power_row.pack(fill="x",pady=(0,10))
 awake=tk.BooleanVar(value=True)
 ttk.Checkbutton(power_row,text="Keep laptop and display awake while app is running",variable=awake,command=lambda:keep_windows_awake(awake.get())).pack(anchor="w")
 battery_label=tk.StringVar(value="Battery: checking...")
 ttk.Label(power_row,textvariable=battery_label,style="Dark.TLabel").pack(anchor="w",pady=(5,0))
 last_alarm=[0.0]
 def monitor_battery():
  try:
   status=battery_status()
   if status is None:battery_label.set("Battery status unavailable (or no battery detected)")
   else:
    percent,plugged=status
    battery_label.set(f"Battery: {percent}%  •  "+("Plugged in" if plugged else "On battery"))
    # Audible warning below 20%, repeated at most once every 60 seconds.
    if not plugged and percent<=20 and time.monotonic()-last_alarm[0]>=60:
     last_alarm[0]=time.monotonic()
     def sound_alarm():
      try:
       import winsound
       for frequency in (1100,850,1100):
        winsound.Beep(frequency,300)
      except (ImportError,RuntimeError,OSError):pass
     threading.Thread(target=sound_alarm,daemon=True).start()
  except (OSError,AttributeError,ValueError):battery_label.set("Battery status unavailable")
  root.after(10000,monitor_battery)
 monitor_battery()
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
 # The QR uses a URL fragment so the pairing token is never sent in the HTTP request.
 qr_area=ttk.Frame(frame,style="Dark.TFrame")
 qr_area.pack(fill="x",pady=(8,10))
 qr_label=tk.Label(qr_area,bg="white",padx=8,pady=8)
 qr_label.pack(side="left")
 qr_text=ttk.Frame(qr_area,style="Dark.TFrame")
 qr_text.pack(side="left",fill="x",expand=True,padx=(14,0))
 ttk.Label(qr_text,text="Scan to connect",style="Dark.TLabel",font=("Segoe UI",12,"bold")).pack(anchor="w")
 ttk.Label(qr_text,text="Scan with iPhone Camera. The sender opens with the pairing token filled in and connects automatically.",style="Dark.TLabel",wraplength=520,justify="left").pack(anchor="w",pady=(5,6))
 qr_url=tk.StringVar()
 ttk.Label(qr_text,textvariable=qr_url,style="Dark.TLabel",wraplength=520).pack(anchor="w")
 def refresh_qr():
  try:
   import qrcode
   from PIL import ImageTk
   ips=sorted(addresses,key=lambda ip:(not ip.startswith(("192.168.","10.","172.")),ip))
   if not ips:
    qr_label.configure(text="No LAN IP",image="",fg="#172c3f")
    qr_url.set("Connect the PC and iPhone to the same Wi-Fi.")
    return
   url="http://"+ips[0]+":8765/#token="+quote(state.token,safe="")
   qr=qrcode.QRCode(box_size=5,border=2,error_correction=qrcode.constants.ERROR_CORRECT_M)
   qr.add_data(url);qr.make(fit=True)
   img=ImageTk.PhotoImage(qr.make_image(fill_color="#101b2a",back_color="white").convert("RGB"))
   qr_label.configure(image=img,text="")
   qr_label.image=img
   qr_url.set("http://"+ips[0]+":8765/  •  Same Wi-Fi required")
  except (ImportError,OSError,ValueError) as e:
   qr_label.configure(text="QR unavailable",image="",fg="#172c3f")
   qr_url.set("QR could not be generated: "+str(e))
 refresh_qr()
 ttk.Label(frame,text="Transfers",style="Dark.TLabel").pack(anchor="w",pady=(12,3))
 # Each transfer has its own progress bar and context-sensitive actions.
 transfer_area=ttk.Frame(frame,style="Dark.TFrame")
 transfer_area.pack(fill="both",expand=True)
 canvas=tk.Canvas(transfer_area,bg="#101b2a",highlightthickness=0,borderwidth=0)
 scrollbar=ttk.Scrollbar(transfer_area,orient="vertical",command=canvas.yview)
 canvas.configure(yscrollcommand=scrollbar.set)
 scrollbar.pack(side="right",fill="y")
 canvas.pack(side="left",fill="both",expand=True)
 cards=ttk.Frame(canvas,style="Dark.TFrame")
 window_id=canvas.create_window((0,0),window=cards,anchor="nw")
 cards.bind("<Configure>",lambda e:canvas.configure(scrollregion=canvas.bbox("all")))
 canvas.bind("<Configure>",lambda e:canvas.itemconfigure(window_id,width=e.width))
 widgets={}
 def open_transfer(k,folder=False):
  from tkinter import messagebox
  v=state.snapshot().get(k)
  if not v or v["status"]!="complete":
   messagebox.showinfo("Not completed","You can open a file after its transfer completes.");return
  p=Path(v["target"])
  if not p.exists():
   messagebox.showerror("File missing","The completed file was moved or deleted.");return
  try:
   if folder:subprocess.Popen(["explorer.exe","/select,",str(p)])
   else:os.startfile(str(p))
  except OSError as e:messagebox.showerror("Cannot open",str(e))
 def cancel_transfer(k):
  from tkinter import messagebox
  v=state.snapshot().get(k)
  if not v or v["status"]=="complete":return
  if messagebox.askyesno("Cancel transfer","Cancel this transfer and delete its incomplete data?"):
   try:state.cancel(k)
   except (ValueError,KeyError,OSError) as e:messagebox.showerror("Cannot cancel",str(e))
   root.after_idle(refresh)
 def resume_transfer(k):
  from tkinter import messagebox
  try:
   state.request_resume(k)
   messagebox.showinfo("Resume requested","Keep the iPhone sender page open with the file selected. If Safari was reloaded, reselect the file to resume.")
  except (ValueError,KeyError,OSError) as e:messagebox.showerror("Cannot resume",str(e))
 def remove_transfer(k):
  from tkinter import messagebox
  if messagebox.askyesno("Remove transfer","Remove this item from the list? Completed files are not deleted."):
   try:state.remove(k)
   except (ValueError,KeyError,OSError) as e:messagebox.showerror("Cannot remove",str(e))
   root.after_idle(refresh)
 def icon_button(parent,symbol,tip,command):
  button=ttk.Button(parent,text=symbol,style="Dark.TButton",width=3,command=command)
  button.pack(side="left",padx=(0,6))
  # Native tkinter tooltip: visible only while hovering.
  popup={"window":None}
  def enter(e):
   if popup["window"] is not None:return
   w=tk.Toplevel(root);w.wm_overrideredirect(True)
   w.configure(bg="#eaf4ff")
   tk.Label(w,text=tip,bg="#eaf4ff",fg="#15283a",padx=8,pady=5,font=("Segoe UI",9)).pack()
   w.geometry("+%d+%d"%(e.x_root+10,e.y_root+18));popup["window"]=w
  def leave(e):
   if popup["window"] is not None:
    popup["window"].destroy();popup["window"]=None
  button.bind("<Enter>",enter);button.bind("<Leave>",leave)
  return button
 def make_card(k):
  card=tk.Frame(cards,bg="#203348",padx=14,pady=10)
  card.pack(fill="x",pady=(0,9))
  header=tk.Frame(card,bg="#203348");header.pack(fill="x")
  title=tk.Label(header,bg="#203348",fg="#f1f8ff",font=("Segoe UI",11,"bold"),anchor="w")
  title.pack(side="left",fill="x",expand=True)
  percent=tk.Label(header,bg="#203348",fg="#6ce1aa",font=("Segoe UI",11,"bold"))
  percent.pack(side="right")
  bar=ttk.Progressbar(card,mode="determinate",maximum=100)
  bar.pack(fill="x",pady=(8,5))
  detail=tk.Label(card,bg="#203348",fg="#c0d1e2",font=("Segoe UI",9),anchor="w")
  detail.pack(fill="x")
  actions=tk.Frame(card,bg="#203348");actions.pack(anchor="w",pady=(9,0))
  resume=icon_button(actions,"▶","Resume interrupted transfer",lambda:resume_transfer(k))
  cancel=icon_button(actions,"■","Cancel transfer and delete incomplete data",lambda:cancel_transfer(k))
  remove=icon_button(actions,"✕","Remove from transfer list",lambda:remove_transfer(k))
  open_file=icon_button(actions,"↗","Open completed file",lambda:open_transfer(k))
  open_folder=icon_button(actions,"▣","Show completed file in folder",lambda:open_transfer(k,True))
  return dict(card=card,title=title,percent=percent,bar=bar,detail=detail,resume=resume,cancel=cancel,remove=remove,open_file=open_file,open_folder=open_folder)
 def refresh():
  state.destination=Path(dest.get())
  snapshot={k:v for k,v in state.snapshot().items() if v["status"]!="complete"}
  for k in list(widgets):
   if k not in snapshot:
    widgets.pop(k)["card"].destroy()
  for k,v in snapshot.items():
   if k not in widgets:widgets[k]=make_card(k)
   w=widgets[k]
   size=max(0,int(v.get("size",0)))
   offset=min(size,max(0,int(v.get("offset",0))))
   pct=(offset/size*100) if size else (100 if v["status"]=="complete" else 0)
   complete=v["status"]=="complete"
   w["title"].configure(text=v["name"])
   w["percent"].configure(text=f"{pct:.0f}%")
   w["bar"]["value"]=pct
   w["detail"].configure(text=f'{offset/1048576:,.1f} / {size/1048576:,.1f} MB  •  {v["status"].capitalize()}')
   for name,enabled in [("resume",not complete and v["status"]!="cancelled"),("cancel",not complete and v["status"]!="cancelled"),("open_file",complete),("open_folder",complete)]:
    w[name].configure(state="normal" if enabled else "disabled")
  if not refresh_timer[0]:refresh_timer[0]=True;root.after(500,timed_refresh)
 def timed_refresh():
  refresh_timer[0]=False
  refresh()
 refresh_timer=[False]
 try:server=Server(("0.0.0.0",8765),state)
 except OSError as e:
  from tkinter import messagebox
  messagebox.showerror("Cannot start receiver",str(e));root.destroy();return
 threading.Thread(target=server.serve_forever,daemon=True).start();refresh()
 root.protocol("WM_DELETE_WINDOW",lambda:(keep_windows_awake(False),server.shutdown(),root.destroy()));root.mainloop()
 keep_windows_awake(False)
if __name__=="__main__":main()
