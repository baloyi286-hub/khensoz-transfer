"""Append-only live camera capture sessions for the iPhone PWA."""
import os
import secrets
import threading
from pathlib import Path

class LiveCaptures:
    def __init__(self, state):
        self.state = state
        self.lock = threading.RLock()
        self.active = {}

    def start(self, extension):
        if extension not in ("mp4", "webm"):
            raise ValueError("Unsupported recording format")
        with self.lock:
            token = secrets.token_hex(20)
            folder = Path(self.state.destination)
            folder.mkdir(parents=True, exist_ok=True)
            from datetime import datetime
            stem = "Khensoz-Live-" + datetime.now().strftime("%Y%m%d-%H%M%S")
            target = folder / (stem + "." + extension)
            i = 1
            while target.exists() or any(s["target"] == target for s in self.active.values()):
                target = folder / (stem + "-" + str(i) + "." + extension)
                i += 1
            partials = folder / ".khensoz-partials"
            partials.mkdir(parents=True, exist_ok=True)
            part = partials / (token + ".live.part")
            part.touch(exist_ok=False)
            self.active[token] = {"part": part, "target": target, "sequence": 0, "bytes": 0}
            return {"id": token, "name": target.name}

    def append(self, token, sequence, payload):
        if not payload or len(payload) > 8 * 1024 * 1024:
            raise ValueError("Invalid video chunk")
        with self.lock:
            session = self.active.get(token)
            if session is None:
                raise ValueError("Recording session not found")
            if sequence == session["sequence"] - 1:
                return {"bytes": session["bytes"], "sequence": session["sequence"]}
            if sequence != session["sequence"]:
                raise ValueError("Out-of-order video chunk")
            with session["part"].open("ab") as file:
                file.write(payload)
                file.flush()
                os.fsync(file.fileno())
            session["bytes"] += len(payload)
            session["sequence"] += 1
            return {"bytes": session["bytes"], "sequence": session["sequence"]}

    def finish(self, token, sequence):
        with self.lock:
            session = self.active.get(token)
            if session is None:
                raise ValueError("Recording session not found")
            if sequence != session["sequence"] or session["bytes"] == 0:
                raise ValueError("Recording has missing or empty chunks")
            session["part"].replace(session["target"])
            del self.active[token]
            return {"name": session["target"].name, "bytes": session["bytes"], "complete": True}
