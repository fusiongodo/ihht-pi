# IHHT-Gasmischer – Pi-Teil

Prototyp eines Gasmischers für IHHT. **Kein Einsatz am Menschen.**
Der Pi übernimmt Bildverarbeitung und Regelung, der Arduino Uno erzeugt die Schrittpulse für den NEMA 17 (USB-Seriell).

## Zugriff auf den Pi
- Host: `ihht-pi.local` (Fallback-IP: `192.168.178.48` per LAN; die IP kann sich ändern → FRITZ!Box)
- User: `alice`, Login per SSH-Key, `sudo` ohne Passwort
- Raspberry Pi 3B+, 1 GB RAM, Raspberry Pi OS Lite 64-bit (Bookworm), NetworkManager
- Befehle **nicht interaktiv** ausführen: `ssh alice@ihht-pi.local '<cmd>'`
  - Keine Passwortprompts, kein `--ask`, kein `top`/`nano`
- Code wird **hier lokal** gepflegt und per `rsync -av --delete ./src/ alice@ihht-pi.local:~/ihht/` übertragen
- Vor riskanten Änderungen am Pi (Netzwerk, Boot-Config, `apt full-upgrade`) erst nachfragen. Ein Fehler beim WLAN/SSH sperrt den headless Zugriff aus.

## Installation
Auf dem Pi reicht apt. Kamera-Server und Clipsuche benutzen dieses System-Python:

```
sudo apt install python3-picamera2 python3-opencv python3-numpy python3-pil
```

OpenCV kommt von apt. Die HOG-Suche braucht dieses Paket.

Auf einem anderen Rechner, nur für die Suche:

```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

picamera2 gibt es dort nicht. Der Kamera-Server bleibt auf dem Pi. `opencv-python-headless` bleibt unter Version 5, weil Version 5 kein HOG mehr hat.

## Konventionen
- Kamera: OV5647 über CSI → `picamera2`, **nicht** OpenCV `VideoCapture`
- OpenCV über `apt install python3-opencv`, nicht über pip
- Belichtung, Gain und Weißabgleich fest einstellen
- Native Auflösung nur croppen, nicht skalieren
- Messrate 1 fps, keine Echtzeitanforderung
- Client-Zugriff per WLAN (geplant: FastAPI + Browser-Polling). Bluetooth bleibt reserviert fürs Pulsoximeter (BLE).

## Roadmap
| # | Ziel | Status |
|---|---|---|
| 0 | Pi headless, SSH über WLAN | SSH per LAN läuft; WLAN prüfen (`nmcli dev status`) |
| 1 | Kamera liefert Bild, Fokus fix auf ~20 cm | offen |
| 2 | Pi steuert Arduino seriell | blockiert: USB-A↔USB-B-Kabel fehlt |
| 3 | Bild → Position der Schwebekörper in Pixeln | offen |
| 4 | Regelkreis mit 1 Hz | offen |

## Offen
- Pixelposition → Durchfluss: Kalibrierung pro Röhre nötig (Parallaxe), noch nicht besprochen
