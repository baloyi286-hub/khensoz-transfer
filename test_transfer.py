import hashlib,os,tempfile,unittest
from pathlib import Path
from desktop.receiver import State
class TransferTests(unittest.TestCase):
 def test_resume(self):
  with tempfile.TemporaryDirectory() as temp:
   old=os.environ.get("LOCALAPPDATA");os.environ["LOCALAPPDATA"]=temp
   try:
    state=State(Path(temp)/"received",8765)
    data=b"khensoz"*2000
    fingerprint=hashlib.sha256(data).hexdigest()
    a=state.create_or_resume("video.mov",len(data),fingerprint)
    self.assertEqual(state.append(a["id"],0,data[:1000]),1000)
    restored=State(Path(temp)/"received",8765)
    b=restored.create_or_resume("video.mov",len(data),fingerprint)
    self.assertEqual(b["offset"],1000)
    restored.append(a["id"],1000,data[1000:])
    restored.finish(a["id"])
    self.assertEqual(Path(restored.sessions[a["id"]]["target"]).read_bytes(),data)
   finally:
    if old is None:os.environ.pop("LOCALAPPDATA",None)
    else:os.environ["LOCALAPPDATA"]=old
if __name__=="__main__":unittest.main()
