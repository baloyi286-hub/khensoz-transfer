@echo off
cd /d "%~dp0"
py -3 -m pip install pyinstaller "qrcode[pil]" "open-gopro"
py -3 -m PyInstaller --noconfirm --onefile --windowed --name KhensozTransfer --add-data "sender-pwa;sender-pwa" --hidden-import gopro_tab --collect-all open_gopro desktop\receiver.py
pause
