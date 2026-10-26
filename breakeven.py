#!/usr/bin/env python3
"""Break-even analysis for X-HEEP CPU power gating.

Gating pays for itself when the energy saved while the domain is off exceeds
the energy spent waking it up:

    dP * T_off  >  E_wake        <=>        T_off > T_be = E_wake / dP

dP  : ~24 uW, from the X-HEEP paper (310 -> 286 uW at 1 MHz, 0.8 V).
T_off: measured here from the RTL waveform (see sweep_results.csv).

E_wake is deliberately swept, not measured. Verilator is cycle-accurate, not
analog: it yields cycles and can never yield joules. E_wake is also the one
quantity the paper does not report, which is the gap this experiment targets.

Timings are rescaled to 1 MHz because that is the operating point dP was
measured at. Cycle counts are clock-independent, so this is legitimate;
pairing these cycle counts with dP at a different clock would NOT be, since
the leakage/dynamic balance changes with frequency and voltage.
"""
DP_UW = 24.0        # uW saved while the CPU domain is gated (paper)
CLK_MHZ = 1.0       # report at the paper's operating point

# (timer_arm value, measured off-time in core clock cycles) from
# sweep_results_all.csv. Short idles first: that is where break-even falls into
# the range where E_wake decides the answer.
MEASURED = [(3, 111.2), (5, 311.2), (64, 6211.5), (256, 25411.5)]

for timer, off_cyc in MEASURED:
    off_us = off_cyc / CLK_MHZ                      # cycles / MHz = us
    e_crit_nj = DP_UW * off_us * 1e-12 / 1e-9       # dP[W] * t[s] -> nJ
    print(f"=== timer={timer}: T_off = {off_cyc:.1f} cyc "
          f"= {off_us/1000:.2f} ms at {CLK_MHZ:g} MHz ===")
    print(f"    breaks even at E_wake = {e_crit_nj:.1f} nJ\n")
    print(f"    {'E_wake':>9}  {'T_be':>10}  {'gating wins?':>13}")
    for e_nj in (0.1, 1.0, 10.0, 100.0, 1000.0):
        t_be_us = (e_nj * 1e-9) / (DP_UW * 1e-6) * 1e6
        print(f"    {e_nj:>7.1f}nJ  {t_be_us:>8.1f}us  "
              f"{'YES' if off_us > t_be_us else 'NO':>13}")
    print()
