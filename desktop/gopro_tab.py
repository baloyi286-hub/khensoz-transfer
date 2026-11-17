"""GoPro HERO11 control tab for Khensoz Transfer.

The Open GoPro SDK is imported lazily so normal iPhone transfers still work
when the optional GoPro dependencies or a camera are unavailable.
"""
import asyncio
import threading
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk


def mount_gopro_tab(parent, root):
    status = tk.StringVar(value="Not connected")
    connection = tk.StringVar(value="USB")
    seconds = tk.StringVar(value="10")
    output = tk.StringVar(value=str(Path.home() / "Videos" / "GoPro"))
    busy = [False]

    ttk.Label(parent, text="GoPro HERO11 Black", style="Dark.TLabel",
              font=("Segoe UI", 20, "bold")).pack(anchor="w", pady=(0, 12))
    ttk.Label(parent, text="Record on the camera and download the original file to Windows. "
              "The camera must have a microSD card for native recording.",
              style="Dark.TLabel", wraplength=780).pack(anchor="w", pady=(0, 12))
    ttk.Label(parent, textvariable=status, style="Dark.TLabel",
              wraplength=780).pack(anchor="w", pady=(0, 14))
    ttk.Label(parent, text="Connection", style="Dark.TLabel").pack(anchor="w")
    ttk.Combobox(parent, textvariable=connection, values=("USB", "Wi-Fi / Bluetooth"),
                 state="readonly", width=28).pack(anchor="w", pady=(3, 12))
    ttk.Label(parent, text="Record duration (seconds)", style="Dark.TLabel").pack(anchor="w")
    ttk.Entry(parent, textvariable=seconds, width=14).pack(anchor="w", pady=(3, 12))
    ttk.Label(parent, text="Save original media to", style="Dark.TLabel").pack(anchor="w")
    ttk.Entry(parent, textvariable=output, width=72).pack(fill="x", pady=(3, 6))
    ttk.Button(parent, text="Choose folder", style="Dark.TButton",
               command=lambda: output.set(filedialog.askdirectory() or output.get())).pack(anchor="w", pady=(0, 15))

    def report(message):
        try:
            root.after(0, lambda: status.set(message))
        except RuntimeError:
            pass

    def launch(action):
        if busy[0]:
            messagebox.showinfo("GoPro busy", "Wait for the current GoPro operation to finish.")
            return
        try:
            duration = int(seconds.get())
            if duration < 1 or duration > 86400:
                raise ValueError()
        except ValueError:
            messagebox.showerror("Invalid duration", "Choose 1 to 86400 seconds.")
            return
        mode = connection.get()
        folder = Path(output.get()).expanduser()
        busy[0] = True

        async def operate():
            from open_gopro import WiredGoPro, WirelessGoPro
            # Use a fresh connection per operation to avoid sharing an asyncio
            # loop with tkinter. The SDK closes the camera on context exit.
            camera = WiredGoPro() if mode == "USB" else WirelessGoPro()
            async with camera as gopro:
                report("Connected. Camera ready.")
                if action == "check":
                    response = await gopro.http_command.get_camera_info()
                    if not response.ok:
                        raise RuntimeError(str(response))
                    report("Connected: " + str(response.data))
                    return
                folder.mkdir(parents=True, exist_ok=True)
                # Native capture happens on the camera's SD card.
                report("Starting camera recording...")
                from open_gopro import Params
                start = await gopro.http_command.set_shutter(shutter=Params.Toggle.ENABLE)
                if not start.ok:
                    raise RuntimeError(str(start))
                try:
                    report(f"Recording on GoPro for {duration} seconds...")
                    await asyncio.sleep(duration)
                finally:
                    stop = await gopro.http_command.set_shutter(shutter=Params.Toggle.DISABLE)
                    if not stop.ok:
                        raise RuntimeError("Could not confirm recording stopped: " + str(stop))
                report("Recording stopped. Looking up last video...")
                last = await gopro.http_command.get_last_captured_media()
                if not last.ok:
                    raise RuntimeError(str(last))
                # Last-captured media is modelled as a MediaPath; field names
                # can vary between SDK versions, so report it if not recognized.
                media = last.data
                directory = getattr(media, "folder", None)
                filename = getattr(media, "file", None)
                if not directory or not filename:
                    report("Video saved on GoPro SD card. Media: " + str(media))
                    return
                target = folder / filename
                if target.exists():
                    target = folder / (target.stem + "-gopro" + target.suffix)
                report("Downloading original: " + filename)
                result = await gopro.http_command.download_file(
                    camera_file=media.as_path, local_file=target)
                if not result.ok:
                    raise RuntimeError(str(result))
                report("Downloaded: " + str(target))

        def work():
            try:
                asyncio.run(operate())
            except ImportError as exc:
                report("GoPro SDK unavailable: " + str(exc) + ". Install open-gopro.")
            except Exception as exc:
                report("GoPro error: " + str(exc))
            finally:
                busy[0] = False

        threading.Thread(target=work, daemon=True).start()

    row = ttk.Frame(parent, style="Dark.TFrame")
    row.pack(anchor="w", pady=8)
    ttk.Button(row, text="Test connection", style="Dark.TButton",
               command=lambda: launch("check")).pack(side="left", padx=(0, 8))
    ttk.Button(row, text="Record + download", style="Dark.TButton",
               command=lambda: launch("record")).pack(side="left")
    ttk.Label(parent, text="Advanced controls, live preview, continuous PC capture, "
              "and camera media browser will follow after hardware validation. "
              "Wi-Fi/Bluetooth discovery may temporarily change the PC network connection.",
              style="Dark.TLabel", wraplength=780).pack(anchor="w", pady=(14, 0))
