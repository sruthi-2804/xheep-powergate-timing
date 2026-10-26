#!/usr/bin/env python3
"""
X-HEEP CPU power-gating sweep.

Varies two knobs in sw/applications/example_power_manager/main.c:
  * wake-up cost : reset_on = switch_on + N      (main.c ~line 117)
  * idle length  : the four rv_timer_arm(...) values

For each combination it rebuilds the firmware, runs the Verilator
simulation, measures the power-domain transitions from the FST waveform,
and appends a row to sweep_results_all.csv.

main.c is backed up on start and restored on exit (including on Ctrl-C).

Run from the x-heep root, inside the venv, with the X-HEEP PATH set:
    source .venv/bin/activate
    python3 sweep_pg.py
"""
import csv, os, re, shutil, statistics, subprocess, sys, signal

ROOT = os.path.abspath(os.path.dirname(__file__))
MAIN_C = os.path.join(ROOT, "sw/applications/example_power_manager/main.c")
# Written once, on the first clean run, and never deleted. A backup that gets
# removed on exit cannot protect a *later* run, and if a crashed run leaves
# main.c patched, the next run's backup would capture the patched file.
PRISTINE = MAIN_C + ".pristine"
FST = os.path.join(
    ROOT, "build/openhwgroup.org_systems_core-v-mini-mcu_1.0.6/sim-verilator/waveform.fst")
UART = os.path.join(
    ROOT, "build/openhwgroup.org_systems_core-v-mini-mcu_1.0.6/sim-verilator/uart0.log")
OUT_CSV = os.path.join(ROOT, "sweep_results_all.csv")

# (wake_delta, timer_value) pairs - every point reported in
# POWERGATE_EXPERIMENT.md.
#
# The two knobs are orthogonal, so a full cross product buys nothing:
#   wake = delta + 5           (= iso_on - switch_on; independent of timer)
#   off  = 100*timer - 188.5   (independent of delta)
# So the delta axis is swept at one timer value, and the timer axis at one
# delta. Simulation cost grows steeply with the timer value, which is why the
# timer axis is sampled sparsely but over a wide range (3 ... 256).
RUNS = [
    (20,   3),     # short idle - where break-even actually bites
    (20,   5),
    (20,   64),    # upstream default
    (20,   256),   # long idle
    (100,  64),    # 5x wake-up cost
    (1000, 64),    # 50x wake-up cost
]
CLK_MHZ = 100.0                    # tb/tb_top.sv: CLK_FREQUENCY_KHz = 100_000

sys.path.insert(0, ROOT)
try:
    from measure_pg import fst_to_vcd, parse_vcd, episodes, first_after
except ImportError:
    sys.exit("ERROR: measure_pg.py must sit next to this script in the x-heep root.")


def patch_main_c(wake_delta, timer_value):
    """Rewrite the two knobs in main.c. Returns (n_wake, n_timer) substitutions."""
    src = open(MAIN_C).read()

    src, n_wake = re.subn(
        r"(reset_on\s*=\s*switch_on\s*\+\s*)\d+",
        lambda m: m.group(1) + str(wake_delta), src)

    src, n_timer = re.subn(
        r"(rv_timer_arm\(\s*&timer_[0-9_]+\s*,\s*\d+\s*,\s*\d+\s*,\s*)\d+",
        lambda m: m.group(1) + str(timer_value), src)

    open(MAIN_C, "w").write(src)
    return n_wake, n_timer


def run_sim():
    """Build firmware + run the Verilator model. Returns True on success."""
    # Remove last run's artefacts. Otherwise a run that dies leaves the previous
    # run's uart0.log and waveform.fst in place, and this point gets "validated"
    # and measured against stale data from a different configuration.
    for stale in (UART, FST):
        if os.path.exists(stale):
            os.unlink(stale)

    r = subprocess.run(
        ["make", "verilator-run-app", "PROJECT=example_power_manager"],
        cwd=ROOT, capture_output=True, text=True)
    if r.returncode != 0:
        print("    BUILD/RUN FAILED:")
        print("    " + "\n    ".join((r.stderr or r.stdout).strip().splitlines()[-8:]))
        return False

    # make can return 0 even when the simulation itself died, because fusesoc
    # does not always propagate the simulator's exit code. Check the artefacts.
    log = open(UART, errors="ignore").read() if os.path.exists(UART) else ""
    if not log.strip():
        print("    SIM PRODUCED NO UART OUTPUT - simulation did not run to completion.")
        print("    last lines of make output:")
        print("    " + "\n    ".join((r.stdout or "").strip().splitlines()[-10:]))
        return False
    if "Success" not in log:
        print("    SIM RAN BUT TESTS DID NOT PASS. Last UART lines:")
        print("    " + "\n    ".join(log.strip().splitlines()[-6:]))
        return False
    return True


def measure():
    """Return (off_cycles list, wake_cycles list) for the 4 timer-driven episodes."""
    vcd = fst_to_vcd(FST)
    try:
        series, ts_ps = parse_vcd(vcd)
    finally:
        os.unlink(vcd)

    period_ps = 1e6 / CLK_MHZ
    scale = ts_ps or 1

    eps = episodes(series["switch"])
    offs, wakes = [], []
    for t_off, t_on in eps:
        off_c = (t_on - t_off) * scale / period_ps
        if off_c < 1.0:                      # drop the t=0 reset artifact
            continue
        t_iso = first_after(series["iso"], t_on, "1")
        wake_c = (t_iso - t_on) * scale / period_ps if t_iso is not None else float("nan")
        offs.append(off_c); wakes.append(wake_c)

    # the four rv_timer_arm sleeps come first; later episodes are the
    # DMA / GPIO wake tests further down main.c
    return offs[:4], wakes[:4]


def restore(*_):
    if os.path.exists(PRISTINE):
        shutil.copy(PRISTINE, MAIN_C)
        print("\nmain.c restored from main.c.pristine.")


def write_csv(rows):
    if not rows:
        return
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


def main():
    if not os.path.exists(MAIN_C):
        sys.exit(f"ERROR: {MAIN_C} not found - run this from the x-heep root.")

    if os.path.exists(PRISTINE):
        # A previous run may have left main.c patched; always start from clean.
        shutil.copy(PRISTINE, MAIN_C)
        print("Starting from main.c.pristine.")
    else:
        shutil.copy(MAIN_C, PRISTINE)
        print(f"Saved pristine copy -> {PRISTINE}")

    signal.signal(signal.SIGINT, lambda *a: (restore(), sys.exit(1)))

    rows = []
    total = len(RUNS)
    n = 0

    try:
        for wake_delta, timer_value in RUNS:
            n += 1
            print(f"[{n}/{total}] wake_delta={wake_delta:<5} timer={timer_value}")

            nw, nt = patch_main_c(wake_delta, timer_value)
            if nw != 1 or nt != 4:
                print(f"    WARNING: patched {nw} wake / {nt} timer sites "
                      f"(expected 1 / 4) - check main.c")

            if not run_sim():
                print("    -> skipping this point, continuing sweep\n")
                continue

            try:
                offs, wakes = measure()
            except Exception as e:
                print(f"    MEASURE FAILED: {e}")
                print("    -> skipping this point, continuing sweep\n")
                continue

            if len(offs) < 4:
                print(f"    WARNING: only {len(offs)} episodes found (expected 4)")
            if not offs:
                continue

            off_mean = statistics.mean(offs)
            wake_mean = statistics.mean(wakes)
            off_sd = statistics.pstdev(offs) if len(offs) > 1 else 0.0

            print(f"    off={off_mean:9.1f} cyc (sd {off_sd:.1f})   "
                  f"wake={wake_mean:6.1f} cyc   episodes={len(offs)}")

            rows.append({
                "wake_delta_cycles": wake_delta,
                "timer_arm_value": timer_value,
                "off_cycles_mean": round(off_mean, 1),
                "off_cycles_sd": round(off_sd, 1),
                "wake_cycles_mean": round(wake_mean, 1),
                "episodes": len(offs),
                "clk_mhz": CLK_MHZ,
            })
            write_csv(rows)   # save after every run, not just at the end
    finally:
        restore()

    if rows:
        print(f"\nWrote {len(rows)} rows to {OUT_CSV}")
    else:
        print("\nNo results collected.")


if __name__ == "__main__":
    main()
