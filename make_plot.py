#!/usr/bin/env python3
"""Draw offtime_vs_timer.svg from the measured points.

Writes plain SVG so the figure needs no plotting library, stays diffable in
git, and renders natively on GitHub.
"""

# (timer, measured off-time in core cycles, held_out)
PTS = [
    (3,    111.2,  False),
    (5,    311.2,  False),
    (10,   811.2,  False),
    (64,  6211.5,  False),
    (70,  6812.0,  True),    # unmodified upstream run, not used in the fit
    (256, 25411.5, False),
]
SLOPE, INTERCEPT = 100.0, -188.5

W, H = 760, 450
L, R, T, B = 85, 30, 46, 58           # margins
PW, PH = W - L - R, H - T - B
XMAX, YMAX = 270.0, 26000.0

INK, GRID, FIT, PT, HELD = "#24292f", "#d8dee4", "#0969da", "#1a7f37", "#cf222e"


def px(t):
    return L + t / XMAX * PW


def py(off):
    return T + PH - off / YMAX * PH


def main():
    s = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" '
         f'viewBox="0 0 {W} {H}" font-family="system-ui,sans-serif">',
         f'<rect width="{W}" height="{H}" fill="#ffffff"/>']

    # grid + axis labels
    for off in range(0, 26001, 5000):
        y = py(off)
        s.append(f'<line x1="{L}" y1="{y:.1f}" x2="{L+PW}" y2="{y:.1f}" '
                 f'stroke="{GRID}"/>')
        s.append(f'<text x="{L-10}" y="{y+4:.1f}" font-size="12" fill="{INK}" '
                 f'text-anchor="end">{off:,}</text>')
    for t in range(0, 271, 50):
        x = px(t)
        s.append(f'<line x1="{x:.1f}" y1="{T}" x2="{x:.1f}" y2="{T+PH}" '
                 f'stroke="{GRID}"/>')
        s.append(f'<text x="{x:.1f}" y="{T+PH+20}" font-size="12" fill="{INK}" '
                 f'text-anchor="middle">{t}</text>')

    # fitted line, drawn from where it crosses zero
    t0 = -INTERCEPT / SLOPE
    s.append(f'<line x1="{px(t0):.1f}" y1="{py(0):.1f}" '
             f'x2="{px(XMAX):.1f}" y2="{py(SLOPE*XMAX+INTERCEPT):.1f}" '
             f'stroke="{FIT}" stroke-width="2"/>')

    # measured points
    for t, off, held in PTS:
        x, y = px(t), py(off)
        if held:
            s.append(f'<rect x="{x-5:.1f}" y="{y-5:.1f}" width="10" height="10" '
                     f'fill="#ffffff" stroke="{HELD}" stroke-width="2.5"/>')
        else:
            s.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{PT}"/>')

    # axes
    s.append(f'<line x1="{L}" y1="{T+PH}" x2="{L+PW}" y2="{T+PH}" '
             f'stroke="{INK}" stroke-width="1.5"/>')
    s.append(f'<line x1="{L}" y1="{T}" x2="{L}" y2="{T+PH}" '
             f'stroke="{INK}" stroke-width="1.5"/>')

    # titles
    s.append(f'<text x="{L}" y="26" font-size="15" font-weight="600" '
             f'fill="{INK}">CPU off-time vs. timer value</text>')
    s.append(f'<text x="{W//2}" y="{H-14}" font-size="13" fill="{INK}" '
             f'text-anchor="middle">rv_timer_arm value (ticks)</text>')
    s.append(f'<text transform="translate(20,{T+PH/2}) rotate(-90)" '
             f'font-size="13" fill="{INK}" text-anchor="middle">'
             f'off-time (core clock cycles)</text>')

    # legend
    lx, ly = L + 28, T + 26
    s.append(f'<line x1="{lx}" y1="{ly}" x2="{lx+26}" y2="{ly}" '
             f'stroke="{FIT}" stroke-width="2"/>')
    s.append(f'<text x="{lx+34}" y="{ly+4}" font-size="12" fill="{INK}">'
             f'off = 100·timer − 188.5</text>')
    s.append(f'<circle cx="{lx+13}" cy="{ly+22}" r="5" fill="{PT}"/>')
    s.append(f'<text x="{lx+34}" y="{ly+26}" font-size="12" fill="{INK}">'
             f'measured</text>')
    s.append(f'<rect x="{lx+8}" y="{ly+39}" width="10" height="10" '
             f'fill="#ffffff" stroke="{HELD}" stroke-width="2.5"/>')
    s.append(f'<text x="{lx+34}" y="{ly+48}" font-size="12" fill="{INK}">'
             f'held out of the fit (timer = 70)</text>')

    # The floor: the line crosses zero just below timer = 2. Annotate it away
    # from the timer = 3/5/10 points, which cluster near the origin, with a
    # leader line back to the crossing.
    ax, ay = px(34), py(3700)
    s.append(f'<line x1="{ax-4:.1f}" y1="{ay+4:.1f}" x2="{px(t0)+3:.1f}" '
             f'y2="{py(0)-4:.1f}" stroke="{HELD}" stroke-width="1" '
             f'stroke-dasharray="3,2"/>')
    s.append(f'<text x="{ax:.1f}" y="{ay:.1f}" font-size="11.5" fill="{HELD}">'
             f'crosses zero at timer ≈ 1.9:</text>')
    s.append(f'<text x="{ax:.1f}" y="{ay+15:.1f}" font-size="11.5" '
             f'fill="{HELD}">shorter idles never gate</text>')

    s.append('</svg>')
    open("offtime_vs_timer.svg", "w").write("\n".join(s))

    # report the fit quality we are claiming in the write-up
    worst = max(abs(off - (SLOPE*t + INTERCEPT)) for t, off, _ in PTS)
    print(f"wrote offtime_vs_timer.svg  (max |residual| = {worst:.1f} cycles)")


if __name__ == "__main__":
    main()
