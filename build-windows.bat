@echo off
cd /d "%~dp0"
py -3 -m pip install pyinstaller
py -3 -m PyInstaller --noconfirm --onefile --windowed --name KhensozTransfer --add-data "sender-pwa;sender-pwa" desktop\receiver.py
pause
