# Characterising CPU power-gating timing in X-HEEP

A small RTL-measurement experiment on [X-HEEP](https://github.com/esl-epfl/x-heep),
run in Verilator on a laptop.

## Motivation

The X-HEEP paper reports the *benefit* of power-gating the idle CPU subsystem:
about **24 µW** saved (310 → 286 µW at 1 MHz, 0.8 V). It does not report the
*cost* of waking the domain back up.

That cost matters, because gating only pays for itself when

```
ΔP · T_off  >  E_wake        ⟺        T_off  >  T_be = E_wake / ΔP
```

The reference application is explicit that the cost is unmodelled. In
`sw/applications/example_power_manager/main.c`:

```c
reset_on = switch_on + 20; // give 20 cycles to emulate the turn on time,
                           // this number depends on technology and here it
                           // is just a random number
```

So the question this experiment answers is the half that *is* measurable from
the RTL: **how long is the CPU actually off, and how long does it take to come
back?** E_wake itself is swept as a parameter — see "Limitations".

## Method

Two knobs in `example_power_manager/main.c` were swept:

| knob | site | meaning |
|---|---|---|
| `reset_on = switch_on + N` | 1 site | emulated turn-on cost ("wake delta") |
| `rv_timer_arm(..., N)` | 4 sites | idle length |

For each point: rebuild the firmware, run the Verilator model, and measure the
power-domain transitions directly from the FST waveform.

`measure_pg.py` matches these signals by name, at whatever hierarchy level they
appear in the trace (the testbench instantiates the DUT as `testharness_i`):

- `off_cycles`  — `cpu_subsystem_powergate_switch_no` low → high (domain truly off)
- `wake_cycles` — switch-on → `cpu_subsystem_powergate_iso_n` release (full recovery)

Each point averages the 4 timer-driven gating episodes in the application.

Scripts: `measure_pg.py` (waveform → cycle counts), `sweep_pg.py` (sweep
driver), `breakeven.py` (analysis).

## Results

`sweep_results_all.csv`:

| wake_delta | timer | off (cyc) | sd | wake (cyc) |
|---:|---:|---:|---:|---:|
| 20 | 3 | 111.2 | 0.8 | 25.0 |
| 20 | 5 | 311.2 | 0.8 | 25.0 |
| 20 | 64 | 6211.5 | 0.9 | 25.0 |
| 20 | 256 | 25411.5 | 0.9 | 25.0 |
| 100 | 64 | 6210.8 | 0.4 | 105.0 |
| 1000 | 64 | 6210.8 | 0.4 | 1005.0 |

The two knobs are **orthogonal**, and both relationships are exact:

```
wake = delta + 5          (independent of idle length)
off  = 100·timer − 188.5  (independent of wake delta)
```

**`wake = delta + 5`** is not a fit — it is `iso_on − switch_on` read straight
off the counter setup (`switch_on = 10; reset_on = switch_on + delta;
iso_on = reset_on + 5`). Measured exactly at delta = 20, 100, 1000.

**`off = 100·timer − 188.5`** was fitted on timer = 64 and 256, then tested:

| timer | model | measured | err | provenance |
|---:|---:|---:|---:|---|
| 3 | 111.5 | 111.2 | −0.3 | measured after fitting |
| 5 | 311.5 | 311.2 | −0.3 | measured after fitting |
| 64 | 6211.5 | 6211.5 | +0.0 | used in fit |
| 70 | 6811.5 | 6812.0 | +0.5 | **held out** — earlier run, not used in fit |
| 256 | 25411.5 | 25411.5 | +0.0 | used in fit |

Max error 0.5 cycles across an 85× range in idle length. Both coefficients are
physically meaningful rather than empirical:

- **slope = 100.0 exactly** — the timer tick divider (100 MHz core clock → 1 MHz tick).
- **intercept = −188.5** — fixed sequencing overhead. The domain is *not* off for
  the whole nominal window: the shutdown sequence (`iso_off = 10`,
  `reset_off = 15`, `switch_off = 20`) and the wake/ISR path consume cycles at
  each end.

### Consequences

**1. Wake-up cost cannot be amortised.** Raising the wake delta 50× (20 → 1000
cycles) left off-time unchanged at ~6211 cycles. The energy-saving window does
not grow to offset a more expensive wake-up, so wake cost is pure overhead.

**2. There is a hard floor on gateable idle.** `off > 0` requires
`timer ≥ 2`. Below roughly two timer ticks the 188.5-cycle sequencing overhead
exceeds the window and the domain never reaches off at all.

### Break-even

Rescaling measured cycle counts to 1 MHz — the operating point ΔP was measured
at — and taking ΔP = 24 µW:

| timer | T_off | break-even E_wake |
|---:|---:|---:|
| 3 | 111 µs | **2.7 nJ** |
| 5 | 311 µs | 7.5 nJ |
| 64 | 6.21 ms | 149 nJ |
| 256 | 25.4 ms | 610 nJ |

At the idle lengths the reference application uses (timer = 64/70), break-even
sits at 149 nJ — far above any plausible wake-up energy for a 0.8 V domain, so
**gating is comfortably worthwhile there**. The decision only becomes
genuinely load-bearing at short idles, where break-even falls into the
single-nanojoule range and therefore depends on the unreported E_wake.

## Limitations

- **E_wake is not measurable here.** Verilator is cycle-accurate, not analog: it
  yields cycles, never joules. E_wake is swept as a parameter, and it is also
  precisely the quantity the paper leaves unreported.
- **Clock-rate mismatch.** The testbench runs at 100 MHz
  (`tb/tb_top.sv:16`, `CLK_FREQUENCY_KHz = 100_000`); ΔP is quoted at 1 MHz,
  0.8 V. Cycle counts are clock-independent so rescaling them is legitimate,
  but pairing these timings with ΔP at 100 MHz would **not** be — the
  leakage/dynamic balance shifts with frequency and voltage.
- **The `timer = 2` floor is extrapolated**, not measured. The measured range
  is timer = 3 … 256.
- **Turn-on time is emulated, not physical.** The 20-cycle delay is upstream's
  placeholder; the measured `wake = delta + 5` characterises the power
  manager's sequencing, not any real technology's settling time.
- ΔP is taken from the paper, not independently reproduced.

## Reproducing

```
commit     b3eb3c8d626d3debe8e5cf99ecff32a5a31549fd
Verilator  5.040 2025-08-30
compiler   riscv32-corev-elf-gcc (corev-openhw-gcc-ubuntu2004-20240530) 14.1.0
```

`sweep_pg.py` and `measure_pg.py` locate the tree relative to their own
location, so they must be run **from the x-heep root**:

```sh
cd /path/to/x-heep
cp /path/to/this-repo/{sweep_pg.py,measure_pg.py,breakeven.py} .
git apply /path/to/this-repo/printf-in-sim.patch

export RISCV_XHEEP=$HOME/tools/riscv   # without this, the Makefile derives
                                       # COMPILER_PREFIX from the host gcc
export PATH=$HOME/tools/verilator/5.040/bin:$RISCV_XHEEP/bin:$PATH
source .venv/bin/activate

make mcu-gen MEMORY_BANKS=4   # MEMORY_BANKS is an mcu-gen parameter
make verilator-build          # builds the C++ model (slow, once)

python3 sweep_pg.py           # ~15 min; sweeps main.c, restores it on exit
python3 breakeven.py
```

`fst2vcd` (from gtkwave) must be on `PATH` — `measure_pg.py` shells out to it.

`sweep_pg.py` keeps a pristine copy of `main.c` and restores it after every
run. The only persistent change to the upstream tree is
`#define PRINTF_IN_SIM 1` in the example, so UART output is visible in
simulation:

```sh
git diff -- sw/applications/example_power_manager/main.c
```
