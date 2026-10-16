<h1 align="center">GR4-WebCam</h1>

<p align="center">
  <strong>Control your RICOH GR IV from any web browser over Wi-Fi.<br>
  Photo gallery, download, shutter, and live view — no phone app.</strong>
</p>

GR4-WebCam is an **opt-in** add-on for the GR IV. When it's switched on, the camera makes its
own Wi-Fi network and serves a web page. Join `GR4-WEB` from any phone or laptop, open
`http://192.168.0.1:8080/`, and you get a browser interface — browse and download your
photos, take a shot, and watch live view — with no app required. Switch it off and the
camera behaves exactly as it did before.

This repository contains **no RICOH firmware**. You download the official firmware from RICOH
yourself, and the included tool produces your own personalized copy on your computer.

> ⚠️ Installing a modified firmware is at your own risk. A recovery path always exists:
> re-install the official RICOH **GR IV 1.11** firmware. Keep that file on hand before you start.

---

## What you need

- The official RICOH **GR IV 1.11** firmware file (from RICOH's website).
- `squashfs-tools` (`brew install squashfs`) and Python 3 with `numpy`.

## 1. Build your copy

```
python3 firmware/patch_webfw.py --base /path/to/official-firmware.bin --out my-firmware.bin
```

The tool adds only the GR4-WebCam start-up and leaves everything else in the firmware
untouched; it checks this and refuses to write anything if the check fails. (On macOS/Linux
run it with `sudo` so the tool can preserve special files.)

## 2. Prepare the SD card

Copy the three files from `sd/` to the **top level** of the card:

| file | purpose |
| --- | --- |
| `GR4WEB.SH`  | the add-on |
| `GR4WEB.HTM` | the web page |
| `GR4WEB.ON`  | the **on/off switch** — present = on, delete it = off |

## 3. Install & use

1. Install `my-firmware.bin` the normal RICOH way (firmware update from the card).
2. Power the camera on (leave USB unplugged). After ~10–20 s it broadcasts **`GR4-WEB`**
   (password **`gr4camera`**).
3. Join it from your phone/laptop and open **`http://192.168.0.1:8080/index.html`**.

## Notes

- **Live view works over Wi-Fi only** — not while a USB cable is connected.
- While a browser is connected, the camera shows it's in a remote state; that clears when you
  disconnect (or automatically a couple of minutes after the last device leaves).
- `GR4-WEB` is a private network with a fixed password and no pairing — it's intended for your
  own use on your own camera.
- **Turn it off** anytime by deleting `GR4WEB.ON` from the card.
- **Recovery:** re-install the official RICOH firmware.

## Layout

```
firmware/patch_webfw.py   builds your copy from the official firmware
sd/GR4WEB.SH              the add-on (goes on the card)
sd/GR4WEB.HTM            the web page (goes on the card)
sd/GR4WEB.ON             the on/off switch (goes on the card)
webui/index.html          the web page (source)
```
