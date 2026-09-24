# Skin Scanner Prototype — Project Log

> Read this first. It is the shared map for every session and every agent. Keep it short; update **Status**, **Open issues**, and **Session log** each session.

## What we're building
A prototype for a patent-pending "Thermal and Visible-Light Skin Imaging System for Dermatomal Inflammatory Pattern Assessment". The device scans a patch of skin (8×8 thermal array plus an RGB photo), then scans the mirror-image patch on the other side of the body. The laptop compares the two sides to find **asymmetric warm regions**, such as early shingles. It compares each side against the person's own opposite side, never against an absolute temperature threshold. GSR and a contact-probe temperature are extra data channels.

**v1 data path:** ESP32-CAM → FTDI USB serial → laptop. A Python script on the laptop builds the heat map and display. The board has no display and no battery. WiFi connects to the phone hotspot `lakshay`, but no data goes over it yet; it's there for future streaming.

## Hardware setup (confirmed by the user, 2026-09-24)
**Board:** AI-Thinker ESP32-CAM, powered and programmed through an FTDI USB-to-TTL adapter. All sensors run on 3.3V from the ESP32-CAM.

| Part | Pin on part | Goes to |
|---|---|---|
| AMG8833 (8×8 thermal, I2C 0x69/0x68) | VIN / GND | 3.3V / GND |
| | SDA / SCL | **GPIO13 / GPIO15** |
| | INT, AD0 | not connected |
| ADS1115 (16-bit ADC, I2C 0x48) | VDD / GND | 3.3V / GND |
| | SDA / SCL | **GPIO13 / GPIO15** (same bus as the AMG8833) |
| | ADDR | not connected |
| | A0 | GSR signal |
| Grove GSR | VCC / GND | 3.3V / GND |
| | Signal | ADS1115 A0 (not the ESP32; its ADC2 pins stop working while WiFi is on) |
| DS18B20 probe | red / black | 3.3V / GND |
| | yellow (data) | **GPIO14** |
| 4.7kΩ resistor | on breadboard | between the DS18B20 data line (GPIO14 row) and VCC 3.3V: the OneWire pull-up |
| OV2640 camera | onboard | AI-Thinker standard camera pins |

- **GPIO12 is intentionally unused.** It's a boot strapping pin, and I2C pull-ups on it would stop the board from booting.
- **GPIO15 is also a strapping pin,** but the I2C pull-up keeps it high, which is its normal state, so it's safe.
- **Pins in code:** `I2C_SDA`, `I2C_SCL`, `ONEWIRE_PIN` at the top of the sketch.

## Firmware — `firmware/skin_scanner/skin_scanner.ino`
- **Board:** "AI Thinker ESP32-CAM" (Espressif esp32 core), with PSRAM enabled.
- **Libraries:** Adafruit AMG88xx, Adafruit ADS1X15, OneWire, DallasTemperature.
- **Single file:** the `.ino` is the only source of truth. Pins, WiFi credentials and all settings live at its top. Don't split it into extra files.
- **Serial:** 115200 baud. Send one character as a command:
  - `s`: sensors only
  - `c`: sensors plus a JPEG photo
  - `w`: WiFi status
- **Output:** one JSON object per line, and every line starts with `{`. The laptop should ignore all other lines, because the boot ROM prints its own text at startup.

```
{"type":"boot","camera":true,"amg8833":true,"ads1115":true,"ds18b20":true,"psram":true}
{"type":"wifi","enabled":true,"connected":true,"ssid":"lakshay","ip":"192.168.x.x","rssi":-55}
{"type":"reading","ms":1234,"thermal":[64 floats °C, row-major 8x8],"probe_c":31.25,"gsr_raw":12345,"gsr_v":1.5432}
{"type":"reading", ...same..., "img_w":320,"img_h":240,"image_jpeg_b64":"<base64 JPEG>"}   ← for 'c'
{"type":"error","msg":"camera capture failed"}
```
If a sensor is missing, its field is `null`, so one dead sensor doesn't break the rest. The photo is QVGA (320×240), which takes about 1 s to send at 115200 baud.

## How to upload (FTDI)
1. **Install the ESP32 boards in the Arduino IDE.**
   - Settings → Additional boards manager URLs: `https://espressif.github.io/arduino-esp32/package_esp32_index.json`
   - Boards Manager → install **esp32 by Espressif Systems**.
2. **Install the libraries:** Adafruit AMG88xx, Adafruit ADS1X15, OneWire, DallasTemperature.
3. **Wire the FTDI adapter:**

   | FTDI | ESP32-CAM |
   |---|---|
   | GND | GND |
   | 5V | 5V |
   | TX | U0R |
   | RX | U0T |

   Also add a jumper wire from **GPIO0 to GND** (flash mode).
4. **Select the board:** Tools → Board → **AI Thinker ESP32-CAM**; Port → `/dev/cu.usbserial-…`
5. **Upload:** press the RST button on the board, then click Upload.
6. **Run:** when the IDE says "Hard resetting", pull out the GPIO0–GND wire and press RST.
7. **Check:** open Serial Monitor at 115200 and look for the `boot` and `wifi` lines.

If the board sits on an ESP32-CAM-MB programmer shield, skip steps 3, 5 and 6: plug in USB and click Upload.

## Status
- [x] Firmware v0.1 written: camera, AMG8833, ADS1115/GSR, DS18B20, JSON serial output, WiFi connects to hotspot (10 s timeout; auto-reconnects)
- [ ] Compiles in the user's Arduino IDE
- [ ] Boot line shows all sensors `true`
- [ ] `s` and `c` output verified
- [ ] Python receiver + heat map (laptop side)
- [ ] Left/right mirror-patch comparison logic

## Open issues / risks
1. **Brownouts.** WiFi plus the camera draw current spikes. Power the board from the FTDI **5V** pin into the ESP32-CAM 5V pin, not from 3.3V. If it still resets, set `ENABLE_WIFI false`.
2. **The hotspot must be 2.4 GHz.** The ESP32 can't see 5 GHz networks. On an iPhone, turn on "Maximize Compatibility". The credentials are in the `.ino`.
3. **Thermal orientation.** How the 8×8 grid maps onto the photo depends on how the AMG8833 is mounted relative to the camera. It needs calibrating on the laptop side.

## Session log
- **2026-09-24 (S1):** Captured the project context. Wrote firmware v0.1 and this log. Not compiled yet, since the Arduino toolchain isn't on the dev machine; the user compiles and flashes. Next: the user uploads it and reports compile errors and the boot JSON line.
- **2026-09-24 (S1b):** Added the hotspot WiFi connection, the `w` command and the upload guide.
- **2026-09-24 (S1c):** The user moved the wiring to I2C SDA=GPIO13, SCL=GPIO15, probe GPIO14. This fixes the GPIO12 boot-strapping risk. Sketch pins updated.
- **2026-09-24 (S1d):** Recorded the full confirmed setup, including the 4.7kΩ pull-up on GPIO14. Moved the WiFi credentials into the git-ignored `secrets.h` (the repo is public). Committed and pushed.
- **2026-09-24 (S1e):** Per the user, removed `secrets.h`. The WiFi credentials are back in the `.ino`, the single source of truth, with no separate files.
