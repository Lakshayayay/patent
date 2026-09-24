"""Grab skin scans from the prototype over WiFi or USB, with auto-discovery and guided bilateral sessions.

Usage:
    python3 laptop/scan.py left                  # capture single scan labelled 'left'
    python3 laptop/scan.py right                 # capture single scan labelled 'right'
    python3 laptop/scan.py left 10.53.144.64     # explicit IP address
    python3 laptop/scan.py --pair                # guided 2-step Left + Right scan session & auto-compare
    python3 laptop/scan.py --alignment           # alignment check (warm-hand test)
    python3 laptop/scan.py --selftest            # verify thermal grid display logic

Saves scans/<timestamp>-<label>.json and .jpg.
Standard library only — zero pip dependencies required.
"""
import argparse
import concurrent.futures
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

DEFAULT_IP = '10.53.144.64'
SCANS_DIR = Path(__file__).resolve().parent.parent / 'scans'
COLOURS = (21, 27, 33, 39, 45, 226, 220, 208, 202, 196)  # 256-color palette (cool blue -> warm red)


def fetch_url(ip, path, timeout=8):
    """Fetch HTTP content from ESP32."""
    url = f'http://{ip}{path}'
    req = urllib.request.Request(url, headers={'User-Agent': 'SkinScannerLaptop/1.0'})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return response.read()


def discover_board_ip():
    """Try to discover the ESP32 board IP automatically on the local subnet."""
    print("Auto-discovering skin scanner on the local network...")

    candidates = set()
    # 1. Check ARP cache for recently seen devices
    try:
        arp_out = subprocess.check_output(['arp', '-a'], text=True, stderr=subprocess.DEVNULL)
        for line in arp_out.splitlines():
            # Match IP address
            m_ip = re.search(r'\((10\.53\.\d+\.\d+|192\.168\.\d+\.\d+)\)', line)
            if m_ip:
                ip = m_ip.group(1)
                # Prioritize Espressif MAC addresses (e.g. b4:bf:e9, 24:0a:c4, 30:ae:a4, etc.)
                if any(oui in line.lower() for oui in ['b4:bf:e9', '24:0a:c4', '30:ae:a4', '84:cc:a8', 'dc:4f:22']):
                    candidates.add((0, ip))  # highest priority
                elif 'incomplete' not in line:
                    candidates.add((1, ip))
    except Exception:
        pass

    # Sort candidates (priority first)
    sorted_ips = [ip for _, ip in sorted(candidates)]

    # Test candidate IPs
    for ip in sorted_ips:
        try:
            fetch_url(ip, '/data', timeout=1.2)
            print(f"Discovered board at {ip} via ARP cache!")
            return ip
        except Exception:
            pass

    # 2. Fast parallel scan of local 10.53.144.x subnet if on hotspot
    def probe(i):
        ip = f"10.53.144.{i}"
        try:
            fetch_url(ip, '/data', timeout=1.0)
            return ip
        except Exception:
            return None

    with concurrent.futures.ThreadPoolExecutor(max_workers=40) as executor:
        futures = [executor.submit(probe, i) for i in range(1, 255)]
        for f in concurrent.futures.as_completed(futures):
            res = f.result()
            if res:
                print(f"Discovered board at {res} via subnet scan!")
                return res

    return None


def grid_text(thermal):
    """Render 8x8 grid as colored terminal text relative to scan min..max."""
    lo, hi = min(thermal), max(thermal)
    rows = []
    for r in range(8):
        cells = ''
        for v in thermal[r * 8:(r + 1) * 8]:
            k = (v - lo) / (hi - lo) if hi > lo else 0
            color_idx = min(int(k * 10), 9)
            cells += f'\033[48;5;{COLOURS[color_idx]}m\033[30m{v:5.1f} \033[0m'
        rows.append(cells)
    return '\n'.join(rows)


def capture_scan(label, ip):
    """Retrieve reading and photo from board, save to scans/, and display."""
    target_ip = ip
    try:
        photo = fetch_url(target_ip, '/capture.jpg')
        reading = json.loads(fetch_url(target_ip, '/data').decode('utf-8'))
    except Exception as e:
        print(f"Notice: Could not connect to {target_ip} ({e}).")
        discovered = discover_board_ip()
        if discovered:
            target_ip = discovered
            photo = fetch_url(target_ip, '/capture.jpg')
            reading = json.loads(fetch_url(target_ip, '/data').decode('utf-8'))
        else:
            sys.exit(f"\nError: Could not reach the scanner at {ip} or find it on the network.\n"
                     "- Make sure your Mac is connected to the 'Lakshay' hotspot.\n"
                     "- Check the board's serial monitor for its current IP address.")

    SCANS_DIR.mkdir(exist_ok=True)
    timestamp = time.strftime('%Y%m%d-%H%M%S')
    stem = SCANS_DIR / f"{timestamp}-{label}"

    json_path = stem.with_suffix('.json')
    jpg_path = stem.with_suffix('.jpg')

    json_path.write_text(json.dumps(reading, indent=2))
    jpg_path.write_bytes(photo)

    print(f"\n--- Scan Captured: {label.upper()} ({timestamp}) ---")
    if reading.get('thermal'):
        print(grid_text(reading['thermal']))
    probe_c = reading.get('probe_c')
    gsr_v = reading.get('gsr_v')
    print(f"Contact Probe: {probe_c if probe_c is not None else 'null'} °C  |  GSR: {gsr_v if gsr_v is not None else 'null'} V")
    print(f"Saved: {json_path.name} & {jpg_path.name}")

    return json_path, jpg_path


def run_pair_session(ip):
    """Guided bilateral 2-step scan session (Left -> Right -> Auto-Compare)."""
    print("\n" + "=" * 60)
    print("   SKIN SCANNER: BILATERAL DERMATOMAL ASSESSMENT SESSION")
    print("=" * 60)
    print("This guided session captures contralateral skin sites to assess")
    print("thermal symmetry (patent-pending bilateral comparison algorithm).\n")

    input("Step 1: Position scanner over LEFT (target/affected) skin site.\nPress [Enter] when ready to scan...")
    left_json, left_jpg = capture_scan('left', ip)

    print("\n" + "-" * 60)
    input("Step 2: Position scanner over symmetrical RIGHT (contralateral) skin site.\nPress [Enter] when ready to scan...")
    right_json, right_jpg = capture_scan('right', ip)

    print("\n" + "=" * 60)
    print("Both scans acquired! Running automated contralateral comparison...")
    print("=" * 60)

    # Run compare.py
    compare_script = Path(__file__).resolve().parent / 'compare.py'
    cmd = [sys.executable, str(compare_script), str(left_json), str(right_json), '--report']
    subprocess.run(cmd)


def run_alignment_check(ip):
    """Run warm-hand alignment check to verify thermal vs RGB camera orientation."""
    print("\n" + "=" * 60)
    print("   WARM-HAND ALIGNMENT CHECK")
    print("=" * 60)
    print("Hold a warm hand or hot cup of water in view on ONE side of the lens.")
    input("Press [Enter] to capture an alignment frame...")

    json_path, jpg_path = capture_scan('alignment', ip)

    print("\nAlignment Verification:")
    print("1. Open the captured photo:")
    print(f"   open \"{jpg_path}\"")
    print("2. Check the colored grid above:")
    print("   - Top rows are Row 0-1, Bottom rows are Row 6-7.")
    print("   - Left columns are Col 0-1, Right columns are Col 6-7.")
    print("3. Confirm that the warm spot on the grid lines up with the hand in the photo.")


def selftest():
    """Verify grid rendering."""
    out = grid_text([30 + i / 10 for i in range(64)]).split('\n')
    assert len(out) == 8
    assert '48;5;21m' in out[0] and '48;5;196m' in out[7]
    assert '30.0' in out[0] and '36.3' in out[7]
    assert '48;5;21m' in grid_text([31.0] * 64)
    print('Selftest PASSED! Terminal color grid rendering verified.')


def main():
    parser = argparse.ArgumentParser(description="Skin Scanner Data Capture & Session Tool")
    parser.add_argument('label', nargs='?', default='scan', help="Label for scan (e.g. 'left', 'right', 'test')")
    parser.add_argument('ip', nargs='?', default=DEFAULT_IP, help=f"Board IP address (default: {DEFAULT_IP})")
    parser.add_argument('--pair', action='store_true', help="Run guided bilateral Left + Right session and auto-compare")
    parser.add_argument('--alignment', action='store_true', help="Run warm-hand alignment test")
    parser.add_argument('--selftest', action='store_true', help="Run rendering self-test")

    args = parser.parse_args()

    if args.selftest:
        selftest()
    elif args.alignment:
        run_alignment_check(args.ip)
    elif args.pair:
        run_pair_session(args.ip)
    else:
        capture_scan(args.label, args.ip)


if __name__ == '__main__':
    main()
