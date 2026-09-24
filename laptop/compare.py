"""Compare contralateral (Left vs Right) skin scans for asymmetric thermal patterns.

Core logic for patent-pending "Thermal and Visible-Light Skin Imaging System
for Dermatomal Inflammatory Pattern Assessment":
  1. Loads Left and Right scans (JSON + JPEG).
  2. Symmetrically mirrors the contralateral Right scan horizontally.
  3. Computes cell-by-cell temperature differential: ΔT = T_left - T_right_mirrored.
  4. Identifies asymmetric warm cells (|ΔT| >= threshold) and contiguous dermatomal clusters.
  5. Displays ANSI colored differential grid in terminal.
  6. Generates a standalone, interactive HTML report with side-by-side photos,
     heatmaps, differential map, and photo overlay.

Usage:
    python3 laptop/compare.py                          # compares the most recent left & right scans
    python3 laptop/compare.py left.json right.json      # compare specific scans
    python3 laptop/compare.py --threshold 1.2          # customize ΔT threshold (default: 1.0 °C)
    python3 laptop/compare.py --report                 # generate and auto-open HTML report
    python3 laptop/compare.py --selftest               # verify math & mirroring logic

Standard library only — zero pip dependencies required.
"""
import argparse
import base64
import json
import math
import os
import subprocess
import sys
import time
from pathlib import Path

SCANS_DIR = Path(__file__).resolve().parent.parent / 'scans'

# Terminal ANSI 256-color codes for ΔT (Cool Blue -> Neutral Gray -> Warm Orange/Red)
COLOR_COLD_EXTREME = 27    # << -2.0 °C (Deep Blue)
COLOR_COLD = 39            # -2.0 to -1.0 °C (Light Blue)
COLOR_NEUTRAL_COOL = 74    # -1.0 to -0.3 °C (Soft Cyan/Gray)
COLOR_NEUTRAL = 244        # -0.3 to +0.3 °C (Neutral Gray)
COLOR_NEUTRAL_WARM = 180   # +0.3 to +1.0 °C (Soft Tan/Warm)
COLOR_WARM = 208           # +1.0 to +2.0 °C (Bright Orange)
COLOR_WARM_EXTREME = 196   # >> +2.0 °C (Vivid Red)


def mirror_grid_horizontal(grid):
    """Horizontally mirror an 8x8 row-major grid (64 elements).
    Row r, Col c -> Row r, Col (7 - c).
    """
    if len(grid) != 64:
        raise ValueError(f"Expected 64 cells, got {len(grid)}")
    mirrored = [0.0] * 64
    for r in range(8):
        for c in range(8):
            mirrored[r * 8 + c] = grid[r * 8 + (7 - c)]
    return mirrored


def compute_delta(left, right_mirrored):
    """Compute ΔT = left - right_mirrored for each cell."""
    return [round(l - r, 2) for l, r in zip(left, right_mirrored)]


def find_clusters(delta, threshold):
    """Find contiguous 4-connected components of cells with ΔT >= threshold.
    Returns: list of sets of cell indices.
    """
    elevated = {i for i, dt in enumerate(delta) if dt >= threshold}
    visited = set()
    clusters = []

    for idx in elevated:
        if idx in visited:
            continue
        cluster = set()
        queue = [idx]
        visited.add(idx)
        while queue:
            curr = queue.pop(0)
            cluster.add(curr)
            r, c = divmod(curr, 8)
            for dr, dc in [(-1, 0), (1, 0), (0, -1), (0, 1)]:
                nr, nc = r + dr, c + dc
                if 0 <= nr < 8 and 0 <= nc < 8:
                    nidx = nr * 8 + nc
                    if nidx in elevated and nidx not in visited:
                        visited.add(nidx)
                        queue.append(nidx)
        clusters.append(cluster)
    return sorted(clusters, key=len, reverse=True)


def format_delta_cell(val, threshold):
    """Format cell value with terminal ANSI color and hotspot marker."""
    if val >= threshold:
        color = COLOR_WARM_EXTREME if val >= (threshold + 1.0) else COLOR_WARM
        marker = '*'
    elif val <= -threshold:
        color = COLOR_COLD_EXTREME if val <= -(threshold + 1.0) else COLOR_COLD
        marker = ' '
    elif val > 0.3:
        color = COLOR_NEUTRAL_WARM
        marker = ' '
    elif val < -0.3:
        color = COLOR_NEUTRAL_COOL
        marker = ' '
    else:
        color = COLOR_NEUTRAL
        marker = ' '

    sign = '+' if val > 0 else ''
    text = f"{sign}{val:4.1f}{marker}"
    # ANSI escape: \033[48;5;<color>m background, black text
    return f"\033[48;5;{color}m\033[30m{text}\033[0m"


def print_comparison_terminal(left_data, right_data, delta, threshold, clusters):
    """Render comprehensive comparison report to terminal."""
    l_thermal = left_data.get('thermal', [])
    r_thermal = right_data.get('thermal', [])
    r_mirrored = mirror_grid_horizontal(r_thermal)

    print("\n" + "=" * 65)
    print("  CONTRALATERAL ASYMMETRY REPORT (Left vs Mirrored Right)")
    print("=" * 65)

    print(f"ΔT Threshold: \033[1m{threshold:.1f} °C\033[0m   (Cells with ΔT >= +{threshold:.1f} °C marked with \033[31m*\033[0m)\n")

    # Display side-by-side Left | Mirrored Right | ΔT Difference
    header_left = "Left (Raw °C)".center(28)
    header_right = "Right (Mirrored °C)".center(28)
    header_diff = "ΔT (Left - Right)".center(28)
    print(f" {header_left}   {header_right}   {header_diff}")
    print(" " + "-" * 28 + "   " + "-" * 28 + "   " + "-" * 28)

    for r in range(8):
        l_cells = "".join(f"{l_thermal[r*8+c]:4.1f} " for c in range(8))
        r_cells = "".join(f"{r_mirrored[r*8+c]:4.1f} " for c in range(8))
        d_cells = "".join(format_delta_cell(delta[r*8+c], threshold) + " " for c in range(8))
        print(f" {l_cells} | {r_cells} | {d_cells}")

    # Metrics Summary
    elevated_count = sum(1 for dt in delta if dt >= threshold)
    depressed_count = sum(1 for dt in delta if dt <= -threshold)
    mean_dt = sum(delta) / len(delta)
    max_dt = max(delta)
    min_dt = min(delta)

    l_probe = left_data.get('probe_c')
    r_probe = right_data.get('probe_c')
    probe_diff = (l_probe - r_probe) if (l_probe is not None and r_probe is not None) else None

    print("-" * 65)
    print(f"Thermal Grid Peak ΔT:     \033[1m{max_dt:+.2f} °C\033[0m (Min ΔT: {min_dt:+.2f} °C, Mean ΔT: {mean_dt:+.2f} °C)")
    print(f"Asymmetric Warm Cells:   \033[1m{elevated_count}/64\033[0m cells elevated by >= +{threshold:.1f} °C")
    if depressed_count > 0:
        print(f"Asymmetric Cool Cells:   {depressed_count}/64 cells cooler by >= -{threshold:.1f} °C")

    if probe_diff is not None:
        print(f"Contact Probe Diff:      \033[1m{probe_diff:+.2f} °C\033[0m (Left: {l_probe:.2f} °C, Right: {r_probe:.2f} °C)")

    # Dermatomal Clustering Analysis
    if clusters:
        largest_cluster = len(clusters[0])
        print(f"Max Contiguous Cluster:  \033[1m{largest_cluster} cells\033[0m (Dermatomal pattern: {'HIGH RISK' if largest_cluster >= 3 else 'SUSPECTED'})")
    else:
        print("Dermatomal Clustering:   No contiguous asymmetric cluster detected.")

    print("=" * 65 + "\n")


def generate_html_report(left_path, right_path, left_data, right_data, delta, threshold, clusters):
    """Generate a self-contained HTML comparison report."""
    stem = time.strftime('%Y%m%d-%H%M%S')
    report_file = SCANS_DIR / f"comparison_{stem}.html"

    # Load images as base64 data URIs
    def load_b64(path):
        jpg_path = path.with_suffix('.jpg')
        if jpg_path.exists():
            return "data:image/jpeg;base64," + base64.b64encode(jpg_path.read_bytes()).decode('utf-8')
        return ""

    left_b64 = load_b64(left_path)
    right_b64 = load_b64(right_path)

    l_thermal = left_data.get('thermal', [0] * 64)
    r_thermal = right_data.get('thermal', [0] * 64)
    r_mirrored = mirror_grid_horizontal(r_thermal)

    l_probe = left_data.get('probe_c', 'N/A')
    r_probe = right_data.get('probe_c', 'N/A')
    probe_diff = f"{(left_data['probe_c'] - right_data['probe_c']):+.2f} °C" if (isinstance(l_probe, (int, float)) and isinstance(r_probe, (int, float))) else "N/A"

    max_dt = max(delta)
    mean_dt = sum(delta) / len(delta)
    elevated_count = sum(1 for dt in delta if dt >= threshold)
    largest_cluster = len(clusters[0]) if clusters else 0

    html = f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <title>Skin Scanner — Dermatomal Asymmetry Analysis</title>
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <style>
    :root {{
      --bg: #0f172a;
      --card: #1e293b;
      --border: #334155;
      --text: #f8fafc;
      --text-dim: #94a3b8;
      --accent: #38bdf8;
      --hot: #ef4444;
      --warm: #f97316;
      --cold: #3b82f6;
    }}
    body {{
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
      margin: 0; padding: 24px;
      background: var(--bg); color: var(--text);
    }}
    .container {{ max-width: 1200px; margin: 0 auto; }}
    header {{
      display: flex; justify-content: space-between; align-items: center;
      border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px;
    }}
    h1 {{ margin: 0; font-size: 1.5rem; }}
    .badge {{
      background: #334155; padding: 4px 12px; border-radius: 9999px;
      font-size: 0.85rem; font-weight: 500;
    }}
    .badge.alert {{ background: rgba(239, 68, 68, 0.2); color: #fca5a5; border: 1px solid #ef4444; }}
    .metrics-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
      gap: 16px; margin-bottom: 24px;
    }}
    .card {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 12px; padding: 16px;
    }}
    .card-label {{ font-size: 0.8rem; color: var(--text-dim); text-transform: uppercase; margin-bottom: 6px; }}
    .card-value {{ font-size: 1.8rem; font-weight: bold; }}
    .card-sub {{ font-size: 0.8rem; color: var(--text-dim); margin-top: 4px; }}
    .views-grid {{
      display: grid; grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
      gap: 20px; margin-bottom: 24px;
    }}
    .panel-title {{ font-size: 1rem; font-weight: 600; margin-bottom: 12px; display: flex; justify-content: space-between; }}
    .media-box {{
      position: relative; width: 100%; aspect-ratio: 4/3; background: #000;
      border-radius: 8px; overflow: hidden; border: 1px solid var(--border);
    }}
    .media-box img, .media-box canvas {{
      width: 100%; height: 100%; object-fit: contain; position: absolute; top:0; left:0;
    }}
    .slider-container {{
      background: var(--card); border: 1px solid var(--border);
      border-radius: 12px; padding: 16px; margin-bottom: 24px;
      display: flex; align-items: center; gap: 16px;
    }}
    input[type=range] {{ flex: 1; accent-color: var(--accent); }}
    .grid-table {{
      width: 100%; border-collapse: collapse; font-family: monospace; font-size: 0.85rem; text-align: center;
    }}
    .grid-table td {{ padding: 8px 4px; border: 1px solid var(--border); }}
  </style>
</head>
<body>
<div class="container">
  <header>
    <div>
      <h1>Dermatomal Contralateral Comparison</h1>
      <div style="color:var(--text-dim); font-size: 0.85rem; margin-top: 4px;">
        Left: {left_path.name} &nbsp;|&nbsp; Right: {right_path.name}
      </div>
    </div>
    <div class="badge {'alert' if largest_cluster >= 3 or max_dt >= 1.5 else ''}">
      {'ASYMMETRIC INFLAMMATION' if largest_cluster >= 3 or max_dt >= 1.5 else 'SYMMETRIC / NORMAL'}
    </div>
  </header>

  <div class="metrics-grid">
    <div class="card">
      <div class="card-label">Peak Asymmetry (Max ΔT)</div>
      <div class="card-value" style="color: {'#ef4444' if max_dt >= 1.0 else '#38bdf8'}">{max_dt:+.2f} °C</div>
      <div class="card-sub">Mean ΔT: {mean_dt:+.2f} °C</div>
    </div>
    <div class="card">
      <div class="card-label">Elevated Cells (ΔT ≥ {threshold:.1f}°C)</div>
      <div class="card-value">{elevated_count} <span style="font-size:1rem; color:var(--text-dim)">/ 64</span></div>
      <div class="card-sub">{elevated_count/64*100:.1f}% of inspected area</div>
    </div>
    <div class="card">
      <div class="card-label">Largest Contiguous Cluster</div>
      <div class="card-value" style="color: {'#ef4444' if largest_cluster >= 3 else '#f8fafc'}">{largest_cluster} cells</div>
      <div class="card-sub">{'Pattern indicates dermatomal alignment' if largest_cluster >= 3 else 'Diffuse / Non-clustered'}</div>
    </div>
    <div class="card">
      <div class="card-label">Contact Probe Difference</div>
      <div class="card-value">{probe_diff}</div>
      <div class="card-sub">Left: {l_probe} °C &nbsp;|&nbsp; Right: {r_probe} °C</div>
    </div>
  </div>

  <div class="slider-container card">
    <label for="thSlider" style="font-weight: 500;">Interactive ΔT Threshold:</label>
    <input type="range" id="thSlider" min="0.2" max="3.0" step="0.1" value="{threshold}">
    <span id="thVal" style="font-weight:bold; min-width: 60px;">{threshold:.1f} °C</span>
    <span style="color:var(--text-dim); font-size:0.85rem;">(Adjust to highlight significant inflammatory anomalies)</span>
  </div>

  <div class="views-grid">
    <div class="card">
      <div class="panel-title"><span>Left Skin Site (Target)</span></div>
      <div class="media-box">
        <img id="imgLeft" src="{left_b64}" alt="Left Photo">
        <canvas id="heatLeftCanvas"></canvas>
      </div>
    </div>

    <div class="card">
      <div class="panel-title"><span>Right Skin Site (Mirrored Contralateral)</span></div>
      <div class="media-box">
        <img id="imgRight" src="{right_b64}" alt="Right Photo">
        <canvas id="heatRightCanvas"></canvas>
      </div>
    </div>

    <div class="card">
      <div class="panel-title"><span>Contralateral Difference (ΔT Map)</span></div>
      <div class="media-box">
        <canvas id="deltaCanvas"></canvas>
      </div>
    </div>

    <div class="card">
      <div class="panel-title"><span>Dermatomal Anomaly Overlay</span></div>
      <div class="media-box">
        <img src="{left_b64}" alt="Left Photo Overlay">
        <canvas id="overlayCanvas"></canvas>
      </div>
    </div>
  </div>
</div>

<script>
const leftThermal = {json.dumps(l_thermal)};
const rightMirrored = {json.dumps(r_mirrored)};
const delta = {json.dumps(delta)};

function drawThermalCanvas(canvasId, grid, minT, maxT) {{
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  canvas.width = 320; canvas.height = 240;
  const ctx = canvas.getContext('2d');
  const cellW = canvas.width / 8;
  const cellH = canvas.height / 8;

  grid.forEach((v, i) => {{
    const r = Math.floor(i / 8);
    const c = i % 8;
    const k = maxT > minT ? (v - minT) / (maxT - minT) : 0.5;
    ctx.fillStyle = `hsl(${{240 - 240 * Math.max(0, Math.min(1, k))}}, 100%, 50%)`;
    ctx.fillRect(c * cellW, r * cellH, cellW, cellH);
    ctx.fillStyle = '#000';
    ctx.font = '10px monospace';
    ctx.fillText(v.toFixed(1), c * cellW + 4, r * cellH + cellH / 2 + 3);
  }});
}}

function renderDelta(currentTh) {{
  const canvas = document.getElementById('deltaCanvas');
  const overlay = document.getElementById('overlayCanvas');
  if (!canvas || !overlay) return;
  canvas.width = 320; canvas.height = 240;
  overlay.width = 320; overlay.height = 240;

  const ctx = canvas.getContext('2d');
  const octx = overlay.getContext('2d');
  octx.clearRect(0, 0, 320, 240);

  const cellW = 320 / 8;
  const cellH = 240 / 8;

  delta.forEach((dt, i) => {{
    const r = Math.floor(i / 8);
    const c = i % 8;
    const x = c * cellW;
    const y = r * cellH;

    // Delta Canvas
    let fill = '#334155';
    if (dt >= currentTh) {{
      const intensity = Math.min(1, (dt - currentTh) / 1.5);
      fill = `rgba(239, 68, 68, ${{0.6 + 0.4 * intensity}})`;
    }} else if (dt <= -currentTh) {{
      fill = 'rgba(59, 130, 246, 0.7)';
    }} else {{
      fill = 'rgba(100, 116, 139, 0.4)';
    }}
    ctx.fillStyle = fill;
    ctx.fillRect(x, y, cellW, cellH);
    ctx.strokeStyle = '#1e293b';
    ctx.strokeRect(x, y, cellW, cellH);

    ctx.fillStyle = '#ffffff';
    ctx.font = 'bold 11px monospace';
    const sign = dt > 0 ? '+' : '';
    ctx.fillText(sign + dt.toFixed(1), x + 4, y + cellH / 2 + 4);

    // Overlay Canvas (only elevated hot spots)
    if (dt >= currentTh) {{
      octx.fillStyle = 'rgba(239, 68, 68, 0.65)';
      octx.fillRect(x, y, cellW, cellH);
      octx.strokeStyle = '#ffffff';
      octx.lineWidth = 2;
      octx.strokeRect(x, y, cellW, cellH);
      octx.fillStyle = '#ffffff';
      octx.font = 'bold 12px sans-serif';
      octx.fillText('+' + dt.toFixed(1) + '°', x + 4, y + cellH / 2 + 4);
    }}
  }});
}}

const allT = [...leftThermal, ...rightMirrored];
const minT = Math.min(...allT);
const maxT = Math.max(...allT);

drawThermalCanvas('heatLeftCanvas', leftThermal, minT, maxT);
drawThermalCanvas('heatRightCanvas', rightMirrored, minT, maxT);

const slider = document.getElementById('thSlider');
const thVal = document.getElementById('thVal');
slider.addEventListener('input', (e) => {{
  const val = parseFloat(e.target.value);
  thVal.textContent = val.toFixed(1) + ' °C';
  renderDelta(val);
}});

renderDelta(parseFloat(slider.value));
</script>
</body>
</html>
"""
    report_file.write_text(html, encoding='utf-8')
    print(f"Generated standalone HTML report: {report_file}")
    return report_file


def find_latest_scans():
    """Find the most recent 'left' and 'right' scans in the scans directory."""
    if not SCANS_DIR.exists():
        return None, None
    json_files = sorted(SCANS_DIR.glob('*.json'), key=os.path.getmtime, reverse=True)
    left_scan = next((f for f in json_files if '-left' in f.stem.lower()), None)
    right_scan = next((f for f in json_files if '-right' in f.stem.lower()), None)
    return left_scan, right_scan


def selftest():
    """Verify mirroring, delta calculation, and cluster detection with synthetic data."""
    print("Running compare.py selftest...")
    # Synthetic grid: flat 30.0 with a 2x2 hot patch at Top-Left (Row 0..1, Col 0..1)
    grid_left = [30.0] * 64
    grid_left[0] = 33.0  # R0, C0
    grid_left[1] = 33.0  # R0, C1
    grid_left[8] = 33.0  # R1, C0
    grid_left[9] = 33.0  # R1, C1

    # Symmetric counterpart: same 2x2 hot patch on Right body side (which physically appears at Top-Right: R0..1, C6..7)
    grid_right = [30.0] * 64
    grid_right[6] = 33.0  # R0, C6
    grid_right[7] = 33.0  # R0, C7
    grid_right[14] = 33.0 # R1, C6
    grid_right[15] = 33.0 # R1, C7

    # When horizontally mirrored, grid_right's hot patch moves from C6..7 to C0..1!
    mirrored_r = mirror_grid_horizontal(grid_right)
    assert mirrored_r[0] == 33.0 and mirrored_r[1] == 33.0
    assert mirrored_r[8] == 33.0 and mirrored_r[9] == 33.0

    # Therefore, ΔT should be exactly 0.0 everywhere (bilateral symmetry)!
    delta_symm = compute_delta(grid_left, mirrored_r)
    assert max(delta_symm) == 0.0 and min(delta_symm) == 0.0
    assert len(find_clusters(delta_symm, 1.0)) == 0

    # Now simulate unilateral inflammation on Left (raise to 34.5 °C):
    grid_left[0] = 34.5
    grid_left[1] = 34.5
    grid_left[8] = 34.5
    delta_asymm = compute_delta(grid_left, mirrored_r)
    clusters = find_clusters(delta_asymm, 1.0)
    assert len(clusters) == 1
    assert len(clusters[0]) == 3  # 3 contiguous hot cells (R0C0, R0C1, R1C0)
    assert max(delta_asymm) == 1.5

    print("Selftest PASSED! Mirroring, bilateral subtraction, and cluster detection verified.")


def main():
    parser = argparse.ArgumentParser(description="Skin Scanner Contralateral Comparison Tool")
    parser.add_argument('left', nargs='?', help="Path to Left scan .json")
    parser.add_argument('right', nargs='?', help="Path to Right scan .json")
    parser.add_argument('--threshold', '-t', type=float, default=1.0, help="ΔT threshold in °C (default: 1.0)")
    parser.add_argument('--report', '-r', action='store_true', help="Generate and auto-open HTML report in browser")
    parser.add_argument('--selftest', action='store_true', help="Run internal mathematical self-test")

    args = parser.parse_args()

    if args.selftest:
        selftest()
        return

    if args.left and args.right:
        left_path = Path(args.left)
        right_path = Path(args.right)
    else:
        left_path, right_path = find_latest_scans()
        if not left_path or not right_path:
            sys.exit("Error: Could not locate a pair of '-left' and '-right' scans in scans/.\n"
                     "Usage: python3 laptop/compare.py <left.json> <right.json>\n"
                     "   or: run 'python3 laptop/scan.py --pair' to capture a new bilateral set.")

    if not left_path.exists():
        sys.exit(f"Error: Left scan file not found: {left_path}")
    if not right_path.exists():
        sys.exit(f"Error: Right scan file not found: {right_path}")

    left_data = json.loads(left_path.read_text())
    right_data = json.loads(right_path.read_text())

    l_thermal = left_data.get('thermal')
    r_thermal = right_data.get('thermal')

    if not l_thermal or not r_thermal:
        sys.exit("Error: One or both scans missing 8x8 'thermal' array.")

    r_mirrored = mirror_grid_horizontal(r_thermal)
    delta = compute_delta(l_thermal, r_mirrored)
    clusters = find_clusters(delta, args.threshold)

    print_comparison_terminal(left_data, right_data, delta, args.threshold, clusters)

    report_path = generate_html_report(left_path, right_path, left_data, right_data, delta, args.threshold, clusters)

    if args.report:
        subprocess.run(['open', str(report_path)])


if __name__ == '__main__':
    main()
