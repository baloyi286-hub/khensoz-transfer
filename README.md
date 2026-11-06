# Khensoz Transfer

Run `start-windows.bat` on Windows with Python 3.11+, or use the EXE from GitHub Actions. Connect the iPhone and Windows PC to the same trusted Wi-Fi, then open the displayed URL or scan the QR code. **No pairing token is required.** The receiver accepts files from any device able to reach its local network port; do not expose ports 8765/8766 to the internet or untrusted Wi-Fi.

The sender transfers originals without transcoding and resumes interrupted files using a first/last-block fingerprint. Keep Safari open during transfer.

## High Quality Camera (experimental)

The PWA now offers **High Quality Camera (beta)**, alongside the original native camera picker. The beta uses `getUserMedia` and `MediaRecorder` to request 1080p/30, 1080p/60, 4K/30, or 4K/60; it displays the **actual** camera resolution and frame rate Safari reports. The recording is transferred without a second encode. Safari may provide a lower resolution, frame rate, or bitrate; selecting 4K does not guarantee 4K.

**iPhone Safari requires a trusted HTTPS connection for browser camera APIs.** The normal HTTP sender at port 8765 continues to work for file transfers and the native camera picker, but cannot run the beta camera.

### Enable local HTTPS

1. Find the Windows PC's LAN IP shown in the app (example: `192.168.1.10`).
2. On the Windows PC, install [mkcert](https://github.com/FiloSottile/mkcert) and generate a locally trusted certificate for **that exact IP**. In a terminal:
   ```powershell
   mkcert -install
   mkcert -cert-file "$env:LOCALAPPDATA\KhensozTransfer\lan-cert.pem" -key-file "$env:LOCALAPPDATA\KhensozTransfer\lan-key.pem" 192.168.1.10
   ```
   Replace `192.168.1.10` with the actual Windows LAN IP. The `KhensozTransfer` folder is created when you first run the receiver.
3. **Trust the mkcert root CA on the iPhone as well.** Find the CA folder on Windows using `mkcert -CAROOT`; transfer only `rootCA.pem` to the iPhone (never `rootCA-key.pem`), install the certificate profile under iOS Settings, then enable full trust under Settings → General → About → Certificate Trust Settings. Only trust a CA that you control, and keep its private key on your PC.
4. Restart Khensoz Transfer. The displayed QR/URL will use `https://<PC-IP>:8766/`. Allow Windows Firewall access to TCP 8766 on your private network if necessary.
5. Open the HTTPS URL in Safari, grant camera/microphone permission, select a preset, and record. Tap **Stop & transfer** to queue the recording to the same Windows transfer folder.

If the IP changes, generate a certificate covering the new IP and restart the receiver. If Safari shows a certificate warning, do **not** bypass it: fix the certificate and iPhone trust setup first.

**Memory note:** Browser recording buffers encoded video in memory until stopped, so avoid very long recordings; the native Camera app + original-file transfer is more reliable for lengthy 4K clips. Safari may not provide all iPhone lenses, stabilization modes, native codecs, or manual camera controls.

Build `KhensozTransfer.exe` using GitHub Actions or `build-windows.bat`.
