# Skin Scanner Prototype — Project Log

> Read this first. It is the shared map for every session and every agent. Keep it short and high-level. Each session, update **Where we are**, **Next steps** and **History**.

## What we're building
A prototype for a patent-pending "Thermal and Visible-Light Skin Imaging System for Dermatomal Inflammatory Pattern Assessment". The device scans a patch of skin (8×8 thermal grid plus an RGB photo), then scans the mirror-image patch on the other side of the body. The laptop compares the two sides to find **asymmetric warm regions**, such as early shingles. It compares each side against the person's own opposite side, never against an absolute temperature threshold. A contact-probe temperature (and later GSR) are extra data channels.

## Where we are (2026-09-24)
**The entire hardware and software pipeline is built and functional.**
- **Firmware (`firmware/skin_scanner/skin_scanner.ino`):** Boots ESP32-CAM, GC2145 camera, AMG8833 8x8 thermal grid, DS18B20 probe, connects to hotspot, and serves live HTTP (`/data`, `/capture.jpg`) and Serial (115200) data.
- **Data Capture (`laptop/scan.py`):** Automatically discovers the ESP32 on the hotspot (or connects via IP), captures paired skin scans, renders colored terminal grids, and supports guided 2-step sessions (`--pair`) and warm-hand alignment (`--alignment`).
- **Patent Comparison Engine (`laptop/compare.py`):** Mirrors contralateral scans horizontally, calculates differential ΔT = T_left - T_right_mirrored, flags asymmetric warm cells, detects dermatomal contiguous clusters, and generates an interactive, standalone HTML report with side-by-side photos, heatmaps, and overlay.

## Hardware (see photos in `circuit photo/`)
The AI-Thinker ESP32-CAM is powered and programmed through an FTDI USB-serial adapter, which plugs into the Mac as `/dev/cu.usbserial-0001`. Every sensor runs on 3.3V.

| Part | Connection |
|---|---|
| AMG8833 8×8 thermal (I2C) | SDA **GPIO13**, SCL **GPIO15** |
| DS18B20 probe, on a screw-terminal adapter with its own 4.7kΩ pull-up | DAT **GPIO14** |
| Camera | onboard. It's a **GC2145**, which has no hardware JPEG, so the firmware encodes JPEG in software |
| ADS1115 + Grove GSR | **not fitted.** The code is ready and reports `null` until they're added (GSR → ADS1115 A0, ADS1115 on the same I2C bus, ADDR → GND) |

GPIO12 is left unused on purpose, because it's a boot strapping pin.

## Code
- **`firmware/skin_scanner/skin_scanner.ino`:** AI-Thinker ESP32-CAM firmware with camera, sensors, and HTTP endpoints (`/`, `/data`, `/capture.jpg`). Supports optional `secrets.h`.
- **`laptop/scan.py`:** Standard library Python 3. Grabs scans, auto-discovers board IP on hotspot, guides bilateral pair sessions (`--pair`), and saves to `scans/`.
- **`laptop/compare.py`:** Standard library Python 3. Core bilateral mirroring, ΔT subtraction, dermatomal cluster detection, and HTML report generation.
- **Compile check for agents:** `"/Applications/Arduino IDE.app/Contents/Resources/app/lib/backend/resources/arduino-cli" --config-file ~/.arduinoIDE/arduino-cli.yaml compile --fqbn esp32:esp32:esp32cam firmware/skin_scanner`

## How to use
1. **Connect:** Ensure Mac and ESP32 are both on the `Lakshay` phone hotspot.
2. **Alignment test (one-time check):**
   ```bash
   python3 laptop/scan.py --alignment
   ```
   Hold a warm hand in view and confirm the hot spot in the terminal grid matches the saved photo.
3. **Capture & Compare a Patient Skin Region:**
   ```bash
   python3 laptop/scan.py --pair
   ```
   - Step 1: Follow terminal prompt to scan LEFT (affected/target) site.
   - Step 2: Follow prompt to scan symmetrical RIGHT (contralateral) site.
   - The comparison report is immediately generated in terminal and opened as an interactive HTML report!
4. **Compare existing scans manually:**
   ```bash
   python3 laptop/compare.py                          # latest scans
   python3 laptop/compare.py left.json right.json --report
   python3 laptop/compare.py --threshold 1.2
   ```

## Next steps
1. **Live alignment verification:** Run `python3 laptop/scan.py --alignment` with the physical board.
2. **Clinical testing:** Scan symmetric body areas on test subjects and tune the ΔT threshold (default 1.0 °C).
3. **Later:** Wire up ADS1115 and GSR sensor.

## History
- **S1 (2026-09-24):** Wrote firmware v0.1, moved I2C bus to GPIO13/15, and installed toolchain.
- **S2 (2026-09-24):** FTDI upload working, GC2145 software JPEG fallback, on-board web server, initial scan.py.
- **S3 (2026-09-24):** Implemented `laptop/compare.py` (bilateral mirroring, ΔT thresholding, dermatomal contiguous cluster detection, and interactive HTML report). Upgraded `laptop/scan.py` with automatic network IP discovery, guided `--pair` bilateral workflow, and alignment check. Fixed firmware web server auto-start and added `secrets.h` support. All self-tests passing.
