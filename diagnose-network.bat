@echo off
setlocal
echo Khensoz Transfer - Windows network diagnostics
echo.
echo [1] Local receiver
powershell -NoProfile -Command "try { $r=Invoke-WebRequest -Uri 'http://127.0.0.1:8765/' -TimeoutSec 5 -UseBasicParsing; Write-Host ('HTTP '+$r.StatusCode+' - receiver responds') } catch { Write-Host ('FAILED: '+$_.Exception.Message) }"
echo.
echo [2] Listening socket
netstat -ano -p tcp | findstr ":8765"
echo.
echo [3] Active IPv4 addresses
ipconfig | findstr /i "IPv4"
echo.
echo [4] Windows network profile
powershell -NoProfile -Command "Get-NetConnectionProfile | Format-Table InterfaceAlias,NetworkCategory,IPv4Connectivity -AutoSize"
echo.
echo [5] Firewall profile status
powershell -NoProfile -Command "Get-NetFirewallProfile | Format-Table Name,Enabled,DefaultInboundAction -AutoSize"
echo.
echo If the local receiver responds but the iPhone cannot connect, check Windows Firewall and Wi-Fi client isolation.
pause
