# Khensoz Transfer

Run `start-windows.bat` on Windows with Python 3.11+. Connect iPhone and laptop to the same trusted Wi-Fi network, open the displayed HTTP address in Safari, and enter the pairing token. Select files and transfer. The receiver persists partial files and resumes by matching file name, size and a first/last-block fingerprint.

Build `KhensozTransfer.exe` via GitHub Actions or `build-windows.bat`. The sender is served locally by the receiver, avoiding mixed-content restrictions on Vercel. Keep Safari open while transferring; iOS background execution is not guaranteed. HTTP is unencrypted: use trusted LAN only; do not port-forward port 8765.
