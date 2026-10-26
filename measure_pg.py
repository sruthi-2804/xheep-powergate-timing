#!/usr/bin/env python3
"""
Measure CPU power-gating episodes from an X-HEEP Verilator FST waveform.

Reports, for each power-down episode:
  off_cycles   - how long the power switch was open (CPU truly off)
  wake_cycles  - switch-on -> isolation-release (full recovery latency)

Usage:
  python3 measure_pg.py <waveform.fst> [--clk-mhz 100]
"""
import argparse, re, subprocess, sys, tempfile, os

SIGNALS = {
    "switch": "cpu_subsystem_powergate_switch_no",
    "reset":  "cpu_subsystem_rst_no",
    "iso":    "cpu_subsystem_powergate_iso_n",
}


def fst_to_vcd(fst_path):
    # A complete X-HEEP waveform is megabytes. A few hundred bytes means the
    # simulation died before Verilator finalised the trace - report that
    # directly instead of letting fst2vcd fail with a confusing message.
    size = os.path.getsize(fst_path)
    if size < 100_000:
        raise RuntimeError(
            f"waveform.fst is only {size} bytes - the simulation did not "
            f"complete, so there is nothing to measure.")

    # Keep the VCD next to the FST: it is far larger than the FST and /tmp is
    # a 3.8 GB tmpfs here, which a long trace can exhaust.
    tmp = tempfile.NamedTemporaryFile(suffix=".vcd", delete=False,
                                      dir=os.path.dirname(os.path.abspath(fst_path)))
    tmp.close()
    r = subprocess.run(["fst2vcd", "-f", fst_path, "-o", tmp.name],
                       capture_output=True, text=True)
    if r.returncode != 0:
        os.unlink(tmp.name)
        raise RuntimeError(f"fst2vcd failed ({r.returncode}): "
                           f"{(r.stderr or r.stdout).strip()}")
    return tmp.name


def parse_vcd(vcd_path):
    """Return {role: [(time, value), ...]} for the signals we care about."""
    ids = {}        # vcd short-id -> role
    timescale_ps = None
    series = {r: [] for r in SIGNALS}
    now = 0
    in_defs = True

    with open(vcd_path, "r", errors="ignore") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue

            if in_defs:
                if line.startswith("$timescale"):
                    m = re.search(r"(\d+)\s*(fs|ps|ns|us)", line)
                    if m:
                        unit = {"fs": 0.001, "ps": 1, "ns": 1000, "us": 1e6}[m.group(2)]
                        timescale_ps = int(m.group(1)) * unit
                elif line.startswith("$var"):
                    parts = line.split()
                    # $var wire 1 <id> <name> $end
                    if len(parts) >= 5:
                        vid, vname = parts[3], parts[4]
                        for role, sig in SIGNALS.items():
                            if vname.split("[")[0] == sig:
                                ids[vid] = role
                elif line.startswith("$enddefinitions"):
                    in_defs = False
                continue

            if line.startswith("#"):
                now = int(line[1:])
            elif line and line[0] in "01xzXZ":
                vid = line[1:]
                if vid in ids:
                    series[ids[vid]].append((now, line[0]))

    return series, timescale_ps


def episodes(switch_series):
    """Find (t_off, t_on) pairs: switch_no goes 0 (off) then back to 1 (on)."""
    eps, t_off = [], None
    for t, v in switch_series:
        if v == "0" and t_off is None:
            t_off = t
        elif v == "1" and t_off is not None:
            eps.append((t_off, t))
            t_off = None
    return eps


def first_after(series, t, value):
    for ts, v in series:
        if ts >= t and v == value:
            return ts
    return None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("fst")
    ap.add_argument("--clk-mhz", type=float, default=100.0,
                    help="simulation clock in MHz (X-HEEP tb default: 100)")
    args = ap.parse_args()

    vcd = fst_to_vcd(args.fst)
    try:
        series, ts_ps = parse_vcd(vcd)
    finally:
        os.unlink(vcd)

    if not series["switch"]:
        sys.exit("ERROR: switch signal not found. Was the FST built with tracing on?")

    period_ps = 1e6 / args.clk_mhz          # ps per clock cycle
    scale = (ts_ps or 1)
    def cycles(dt_ticks):
        return dt_ticks * scale / period_ps

    eps = episodes(series["switch"])
    print(f"timescale: {ts_ps} ps/tick   clock: {args.clk_mhz} MHz "
          f"({period_ps/1000:.1f} ns/cycle)")
    print(f"episodes found: {len(eps)}\n")
    print(f"{'#':>2}  {'off_cycles':>11}  {'wake_cycles':>12}")
    print("-" * 30)

    offs, wakes = [], []
    for i, (t_off, t_on) in enumerate(eps, 1):
        off_c = cycles(t_on - t_off)
        t_iso = first_after(series["iso"], t_on, "1")
        wake_c = cycles(t_iso - t_on) if t_iso is not None else float("nan")
        offs.append(off_c); wakes.append(wake_c)
        print(f"{i:>2}  {off_c:>11.1f}  {wake_c:>12.1f}")

    if offs:
        print("-" * 30)
        print(f"{'avg':>2}  {sum(offs)/len(offs):>11.1f}  {sum(wakes)/len(wakes):>12.1f}")


if __name__ == "__main__":
    main()
