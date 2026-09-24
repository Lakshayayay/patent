# Skin Scanner Prototype — Project Log

> Read this first. It is the shared map for every session and every agent. Keep it short; update **Status**, **Open issues**, and **Session log** each session.

## What we're building
A prototype for a patent-pending "Thermal and Visible-Light Skin Imaging System for Dermatomal Inflammatory Pattern Assessment". The device scans a patch of skin (8×8 thermal array plus an RGB photo), then scans the mirror-image patch on the other side of the body. The laptop compares the two sides to find **asymmetric warm regions**, such as early shingles. It compares each side against the person's own opposite side, never against an absolute temperature threshold. GSR and a contact-probe temperature are extra data channels.

**v1 data path:** ESP32-CAM → FTDI USB serial → laptop. A Python script on the laptop builds the heat map and display. The board has no display and no battery. WiFi is initialized for later but not used.

## Hardware
| Part | Interface | ESP32-CAM pin |
|---|---|---|
| AMG8833 8×8 thermal | I2C (0x69, or 0x68 fallback) | SDA GPIO12, SCL GPIO13 |
| ADS1115 16-bit ADC | I2C (0x48), same bus | SDA GPIO12, SCL GPIO13 |
| Grove GSR | analog → ADS1115 A0 | — |
| DS18B20 contact probe | OneWire, 4.7k pull-up to 3.3V | GPIO14 |
| OV2640 camera | onboard | AI-Thinker standard pins |

All sensors run on 3.3V. The board is programmed through the FTDI adapter: GPIO0 to GND while uploading, then disconnect it and reset.

## Firmware — `firmware/skin_scanner/skin_scanner.ino`
- **Board:** "AI Thinker ESP32-CAM" (Espressif esp32 core), with PSRAM enabled.
- **Libraries:** Adafruit AMG88xx, Adafruit ADS1X15, OneWire, DallasTemperature.
- **Serial:** 115200 baud. Send one character as a command:
  - `s`: sensors only
  - `c`: sensors plus a JPEG photo
- **Output:** one JSON object per line, and every line starts with `{`. The laptop should ignore all other lines, because the boot ROM prints its own text at startup.

```
{"type":"boot","camera":true,"amg8833":true,"ads1115":true,"ds18b20":true,"psram":true,"wifi":true}
{"type":"reading","ms":1234,"thermal":[64 floats °C, row-major 8x8],"probe_c":31.25,"gsr_raw":12345,"gsr_v":1.5432}
{"type":"reading", ...same..., "img_w":320,"img_h":240,"image_jpeg_b64":"<base64 JPEG>"}   ← for 'c'
{"type":"error","msg":"camera capture failed"}
```
If a sensor is missing, its field is `null`, so one dead sensor doesn't break the rest. The photo is QVGA (320×240), which takes about 1 s to send at 115200 baud.

## Status
- [x] Firmware v0.1 written: camera, AMG8833, ADS1115/GSR, DS18B20, JSON serial output, WiFi radio initialized
- [ ] Compiles in the user's Arduino IDE
- [ ] Boot line shows all sensors `true`
- [ ] `s` and `c` output verified
- [ ] Python receiver + heat map (laptop side)
- [ ] Left/right mirror-patch comparison logic

## Open issues / risks
1. **GPIO12 is a boot strapping pin, and this is the likely first failure.** If SDA (GPIO12) is pulled HIGH at boot, the ESP32 sets its flash to 1.8V and won't boot. The AMG8833 and ADS1115 breakout boards have I2C pull-up resistors that do exactly that. Symptom: boot loop or `flash read err` in the Serial Monitor. Fixes:
   - (a) Permanently set the flash voltage with `espefuse.py set_flash_voltage 3.3V`. This is an irreversible eFuse burn, but it's the standard fix.
   - (b) Rewire I2C to GPIO14 (SDA) and GPIO15 (SCL), and move the probe to GPIO13. That needs only a 3-line pin change in the sketch.
2. **Brownouts.** WiFi plus the camera draw current spikes. Power the board from the FTDI **5V** pin into the ESP32-CAM 5V pin, not from 3.3V. If it still resets, set `ENABLE_WIFI false`.
3. **Thermal orientation.** How the 8×8 grid maps onto the photo depends on how the AMG8833 is mounted relative to the camera. It needs calibrating on the laptop side.

## Session log
- **2026-09-24 (S1):** Captured the project context. Wrote firmware v0.1 and this log. Not compiled yet, since the Arduino toolchain isn't on the dev machine; the user compiles and flashes. Next: the user uploads it and reports compile errors and the boot JSON line.
