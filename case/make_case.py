"""Generates a 3D-printable two-part case for the flight radar:

    Waveshare 7.5" e-Paper HAT (V2, 800x480) + Raspberry Pi 3 A+ or Pi Zero

Outputs (in this folder):
    case_front.stl          front frame: holds the panel, print FACE DOWN
    case_back_pi3a.stl      back cover for a Raspberry Pi 3 Model A+
    case_back_pizero.stl    back cover for a Pi Zero / Zero 2 (W/WH)
    case_feet.stl           two slide-on feet to stand it on a desk
    (back covers: Pi mount, panel supports, wall-mount keyholes, vents.
     Print OUTSIDE FACE DOWN. Print only the one for your Pi.)

Run:  python3 make_case.py     (needs only numpy)

All sizes are in millimetres and live in the PARAMETERS block, so you can
tweak them and regenerate. The geometry is built from axis-aligned boxes
(added or cut away in order), which keeps the generator dependency-free
and always produces a closed, printable mesh.
"""
from __future__ import annotations

import math
import struct
from pathlib import Path

import numpy as np

# ----------------------------------------------------------------------------
# PARAMETERS
# ----------------------------------------------------------------------------
PANEL_W, PANEL_H, PANEL_T = 170.2, 111.2, 1.2     # Waveshare 7.5" V2 raw panel
ACTIVE_W, ACTIVE_H = 163.2, 97.92                  # visible pixel area
FIT = 0.4                                          # clearance around the panel

# Window in the front. Centred and slightly taller than the active area, so
# every pixel shows even if the active area sits off-centre vertically (the
# ribbon-cable edge has a wider border). Measure your panel and tighten
# WINDOW_H / WINDOW_Y_OFFSET if you want a snugger border.
WINDOW_W = ACTIVE_W + 1.0
WINDOW_H = PANEL_H - 6.0
WINDOW_Y_OFFSET = 0.0          # + moves the window up

BAND = 9.0          # frame border from panel pocket to outside edge
FRONT_T = 2.0       # thickness of the front face
LOCATOR_D = 3.0     # depth of the ledge that locates the panel
DEPTH = 30.0        # total depth of the front part (front face to back rim)
WALL = 2.4          # outer wall thickness
COVER_T = 2.5       # back cover thickness
COVER_FIT = 0.3     # gap between cover and walls

COLUMN = 6.0        # corner screw columns (M3 self-tapping, 4x ~12 mm)
COLUMN_HOLE = 2.6   # pilot hole for M3 into plastic
COLUMN_HOLE_D = 12.0
COVER_HOLE = 3.4    # clearance hole in the cover for M3

FFC_NOTCH_W = 120.0  # gap in the bottom ledge for the panel's ribbon cable

CABLE_NOTCH_W, CABLE_NOTCH_D = 14.0, 12.0   # micro-USB cable exit (bottom wall)

# Raspberry Pi mount (on the back cover, facing the panel). The Pi sits near
# the bottom edge with its GPIO header - and so the display's driver HAT -
# towards the bottom, close to where the panel's ribbon cable comes out.
# Its ports then face up, with room for the micro-USB plug.
BOARDS = {
    #          board w x h (mm)   mounting holes (centre to centre)
    "pi3a":   {"size": (65.0, 56.5), "holes": (58.0, 49.0)},   # Pi 3 Model A+
    "pizero": {"size": (65.0, 30.0), "holes": (58.0, 23.0)},   # Pi Zero / Zero 2
}
PI_EDGE_GAP = 3.0   # gap between the board's bottom edge and the cover's edge
PI_STANDOFF, PI_STANDOFF_H, PI_HOLE = 5.0, 4.0, 2.0   # M2.5 self-tapping

# Posts on the cover that rest (via a felt/foam pad) on the panel's back
PANEL_POSTS = [(-70, 35), (70, 35), (-70, -35), (70, -35)]
POST = 6.0
POST_GAP = 0.8      # leave room for a thin foam pad between post and panel

# Wall-mount keyholes (screw head <= 8 mm, shank <= 4 mm)
KEYHOLES = [(-45.0, 42.0), (45.0, 42.0)]

# Desk feet: slide onto the bottom edge near each end, tilt the frame back
FOOT_TILT = 15.0       # degrees back from vertical
FOOT_WIDTH = 25.0      # each foot, along the frame's bottom edge
FOOT_GRIP = 14.0       # how far the frame sits down into the foot (back side)
FOOT_LIP = 9.0         # front lip height (stays below the window)
FOOT_SLOT_FIT = 0.5    # extra slot width so it slides on easily
FOOT_FLOOR = 7.0       # lifts the frame, leaving room for the cable underneath
FOOT_WALL = 3.0

# ----------------------------------------------------------------------------
# Derived sizes
# ----------------------------------------------------------------------------
POCKET_W, POCKET_H = PANEL_W + 2 * FIT, PANEL_H + 2 * FIT
OUT_W, OUT_H = POCKET_W + 2 * BAND, POCKET_H + 2 * BAND
HX, HY = OUT_W / 2, OUT_H / 2
IN_X, IN_Y = HX - WALL, HY - WALL                  # inner face of outer wall
COL_CX, COL_CY = IN_X - COLUMN / 2, IN_Y - COLUMN / 2
COVER_Z0 = DEPTH - COVER_T                          # cover sits inside the rim
PANEL_BACK_Z = FRONT_T + PANEL_T


def box(x0, x1, y0, y1, z0, z1):
    return (min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1), min(z0, z1), max(z0, z1))


def cbox(cx, cy, w, h, z0, z1):
    return box(cx - w / 2, cx + w / 2, cy - h / 2, cy + h / 2, z0, z1)


# ----------------------------------------------------------------------------
# Part definitions: ordered list of (+1 add / -1 cut, box), in assembly
# coordinates: x right, y up (seen from the front), z = depth from the front.
# ----------------------------------------------------------------------------
def front_part():
    ops = []
    # outer shell walls, full depth
    ops.append((+1, box(-HX, HX, -HY, HY, 0, DEPTH)))
    ops.append((-1, box(-IN_X, IN_X, -IN_Y, IN_Y, FRONT_T + LOCATOR_D, DEPTH + 1)))
    # front face + locator ledge (solid band around the panel pocket)
    ops.append((-1, cbox(0, 0, POCKET_W, POCKET_H, FRONT_T, DEPTH + 1)))
    # window
    ops.append((-1, cbox(0, WINDOW_Y_OFFSET, WINDOW_W, WINDOW_H, -1, FRONT_T + 1)))
    # notch in the bottom ledge for the panel's ribbon cable
    ops.append((-1, box(-FFC_NOTCH_W / 2, FFC_NOTCH_W / 2, -IN_Y, -POCKET_H / 2 + 0.01,
                        FRONT_T, DEPTH + 1)))
    # corner screw columns (stop where the cover starts)
    for sx in (-1, 1):
        for sy in (-1, 1):
            ops.append((+1, cbox(sx * COL_CX, sy * COL_CY, COLUMN, COLUMN, 0, COVER_Z0)))
            ops.append((-1, cbox(sx * COL_CX, sy * COL_CY, COLUMN_HOLE, COLUMN_HOLE,
                                 COVER_Z0 - COLUMN_HOLE_D, COVER_Z0 + 1)))
    # micro-USB cable notch, open at the back rim, bottom wall centre
    ops.append((-1, box(-CABLE_NOTCH_W / 2, CABLE_NOTCH_W / 2, -HY - 1, -IN_Y + 0.01,
                        DEPTH - CABLE_NOTCH_D, DEPTH + 1)))
    return ops


def back_part(board="pi3a"):
    ops = []
    bw, bh = BOARDS[board]["size"]
    holes_x, holes_y = BOARDS[board]["holes"]
    cw, ch = 2 * IN_X - 2 * COVER_FIT, 2 * IN_Y - 2 * COVER_FIT
    ops.append((+1, cbox(0, 0, cw, ch, COVER_Z0, DEPTH)))
    # screw clearance holes over the corner columns
    for sx in (-1, 1):
        for sy in (-1, 1):
            ops.append((-1, cbox(sx * COL_CX, sy * COL_CY, COVER_HOLE, COVER_HOLE,
                                 COVER_Z0 - 1, DEPTH + 1)))
    # posts resting on the back of the panel
    for (px, py) in PANEL_POSTS:
        ops.append((+1, cbox(px, py, POST, POST, PANEL_BACK_Z + POST_GAP, COVER_Z0 + 0.01)))
    # Pi standoffs with pilot holes
    pcx, pcy = 0.0, -(IN_Y - COVER_FIT) + PI_EDGE_GAP + bh / 2
    for dx in (-holes_x / 2, holes_x / 2):
        for dy in (-holes_y / 2, holes_y / 2):
            ops.append((+1, cbox(pcx + dx, pcy + dy, PI_STANDOFF, PI_STANDOFF,
                                 COVER_Z0 - PI_STANDOFF_H, COVER_Z0 + 0.01)))
            ops.append((-1, cbox(pcx + dx, pcy + dy, PI_HOLE, PI_HOLE,
                                 COVER_Z0 - PI_STANDOFF_H - 1, DEPTH - 1.0)))
    # wall-mount keyholes: wide square entry with a narrow slot above it
    for (kx, ky) in KEYHOLES:
        ops.append((-1, cbox(kx, ky - 5, 9, 9, COVER_Z0 - 1, DEPTH + 1)))
        ops.append((-1, box(kx - 2.2, kx + 2.2, ky - 5, ky + 7, COVER_Z0 - 1, DEPTH + 1)))
    # vents: slots above the Pi and near the bottom corners
    for i in range(7):
        x = -30 + i * 10
        ops.append((-1, box(x - 1.5, x + 1.5, 2, 24, COVER_Z0 - 1, DEPTH + 1)))
    for x0 in (-75, 45):
        for i in range(4):
            x = x0 + i * 8
            ops.append((-1, box(x - 1.5, x + 1.5, -55, -42, COVER_Z0 - 1, DEPTH + 1)))
    return ops


# ----------------------------------------------------------------------------
# Box-CSG -> watertight triangle mesh
# ----------------------------------------------------------------------------
def voxelize(ops):
    xs = sorted({round(v, 4) for _, b in ops for v in (b[0], b[1])})
    ys = sorted({round(v, 4) for _, b in ops for v in (b[2], b[3])})
    zs = sorted({round(v, 4) for _, b in ops for v in (b[4], b[5])})
    xs, ys, zs = np.array(xs), np.array(ys), np.array(zs)
    cx, cy, cz = (xs[:-1] + xs[1:]) / 2, (ys[:-1] + ys[1:]) / 2, (zs[:-1] + zs[1:]) / 2
    filled = np.zeros((len(cx), len(cy), len(cz)), dtype=bool)
    for sign, (x0, x1, y0, y1, z0, z1) in ops:
        mx = (cx > x0) & (cx < x1)
        my = (cy > y0) & (cy < y1)
        mz = (cz > z0) & (cz < z1)
        sel = mx[:, None, None] & my[None, :, None] & mz[None, None, :]
        filled = filled | sel if sign > 0 else filled & ~sel
    return xs, ys, zs, filled


def mesh_from_voxels(xs, ys, zs, filled):
    tris = []
    padded = np.pad(filled, 1)
    for axis in range(3):
        for direction in (-1, 1):
            nb = np.roll(padded, -direction, axis=axis)[1:-1, 1:-1, 1:-1]
            faces = np.argwhere(filled & ~nb)
            for i, j, k in faces:
                x0, x1, y0, y1, z0, z1 = xs[i], xs[i + 1], ys[j], ys[j + 1], zs[k], zs[k + 1]
                if axis == 0:
                    x = x1 if direction > 0 else x0
                    q = [(x, y0, z0), (x, y1, z0), (x, y1, z1), (x, y0, z1)]
                elif axis == 1:
                    y = y1 if direction > 0 else y0
                    q = [(x0, y, z0), (x0, y, z1), (x1, y, z1), (x1, y, z0)]
                else:
                    z = z1 if direction > 0 else z0
                    q = [(x0, y0, z), (x1, y0, z), (x1, y1, z), (x0, y1, z)]
                if direction < 0:
                    q = q[::-1]
                tris.append((q[0], q[1], q[2]))
                tris.append((q[0], q[2], q[3]))
    return np.array(tris, dtype=np.float64)


# ----------------------------------------------------------------------------
# Desk feet: an extruded side profile (not box-based, because it's tilted)
# ----------------------------------------------------------------------------
def _triangulate(poly):
    """Ear clipping for a simple counter-clockwise polygon."""
    def cross(o, a, b):
        return (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0])

    def inside(pt, a, b, c):
        return cross(a, b, pt) >= 0 and cross(b, c, pt) >= 0 and cross(c, a, pt) >= 0

    idx = list(range(len(poly)))
    tris = []
    while len(idx) > 3:
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = poly[i0], poly[i1], poly[i2]
            if cross(a, b, c) <= 1e-9:
                continue
            if any(inside(poly[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            raise ValueError("could not triangulate profile")
    tris.append(tuple(idx))
    return tris


def _prism(poly, z0, z1):
    """Closed mesh: polygon (x, y) extruded from z0 to z1."""
    out = []
    for a, b, c in _triangulate(poly):
        out.append(((*poly[a], z1), (*poly[b], z1), (*poly[c], z1)))       # top
        out.append(((*poly[a], z0), (*poly[c], z0), (*poly[b], z0)))       # bottom
    n = len(poly)
    for i in range(n):
        p, q = poly[i], poly[(i + 1) % n]
        out.append(((*p, z0), (*q, z0), (*q, z1)))
        out.append(((*p, z0), (*q, z1), (*p, z1)))
    return out


def foot_profile():
    """Side view of one foot (u = front-to-back, v = up), counter-clockwise:
    a U-shaped channel for the frame's bottom edge, tilted back, sitting on
    a solid base that runs back along the desk for stability."""
    th = math.radians(FOOT_TILT)
    slot = DEPTH + FOOT_SLOT_FIT
    w, f = FOOT_WALL, FOOT_FLOOR

    def R(s_, t):                    # channel coords -> side view (top leans back)
        return (s_ * math.cos(th) + t * math.sin(th), -s_ * math.sin(th) + t * math.cos(th))

    lowest = R(slot + w, -f)[1]      # leaning back, the back-bottom corner is lowest
    P = lambda s_, t: (R(s_, t)[0], R(s_, t)[1] - lowest)
    base_top = 4.0
    b0, b1 = P(slot + w, -f), P(slot + w, FOOT_GRIP)     # back wall, outside edge
    q = (b0[0] + (b1[0] - b0[0]) * (base_top - b0[1]) / (b1[1] - b0[1]), base_top)
    tail = b1[0] + 30.0
    front = P(-w, -f)
    return [
        (front[0], 0.0), (tail, 0.0), (tail, base_top), q,           # base on the desk
        b1, P(slot, FOOT_GRIP), P(slot, 0), P(0, 0),                 # back wall + floor
        P(0, FOOT_LIP), P(-w, FOOT_LIP), front,                      # front lip
    ]


def feet_part():
    prof = foot_profile()
    us = [u for u, _ in prof]
    span = max(us) - min(us)
    tris = []
    for dx in (0.0, span + 15):                  # two feet side by side
        tris += _prism([(u + dx, v) for u, v in prof], 0.0, FOOT_WIDTH)
    t = np.array(tris, dtype=np.float64)
    t[..., 0] -= t[..., 0].min()
    return t


def write_stl(path, tris, name):
    with open(path, "wb") as f:
        f.write(name.encode()[:80].ljust(80, b"\0"))
        f.write(struct.pack("<I", len(tris)))
        for t in tris:
            n = np.cross(t[1] - t[0], t[2] - t[0])
            n = n / (np.linalg.norm(n) or 1)
            f.write(struct.pack("<12fH", *n, *t[0], *t[1], *t[2], 0))


def build(ops, flip_for_print=False):
    xs, ys, zs, filled = voxelize(ops)
    tris = mesh_from_voxels(xs, ys, zs, filled)
    if flip_for_print:
        # rotate 180 deg about X so the cover's outside face is on the bed
        tris[..., 1] *= -1
        tris[..., 2] = DEPTH - tris[..., 2]
    tris[..., 2] -= tris[..., 2].min()
    return tris


def main():
    here = Path(__file__).parent
    parts = {"front": build(front_part())}
    for board in BOARDS:
        parts[f"back_{board}"] = build(back_part(board), flip_for_print=True)
    parts["feet"] = feet_part()
    for name, t in parts.items():
        write_stl(here / f"case_{name}.stl", t, f"flight radar case {name}")
        size = t.reshape(-1, 3).max(0) - t.reshape(-1, 3).min(0)
        print(f"case_{name}.stl: {len(t)} triangles, "
              f"{size[0]:.1f} x {size[1]:.1f} x {size[2]:.1f} mm")


if __name__ == "__main__":
    main()
