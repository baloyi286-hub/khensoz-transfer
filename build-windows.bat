@echo off
cd /d "%~dp0"
py -3 -m pip install pyinstaller "qrcode[pil]" "open-gopro"
py -3 -m PyInstaller --noconfirm --onefile --windowed --name KhensozTransfer --add-data "sender-pwa;sender-pwa" --hidden-import gopro_tab --exclude-module open_gopro.demos --exclude-module cv2 --exclude-module PySide6 --exclude-module PyQt5 desktop\receiver.py
pause
