"""Draws the radar screen as a 1-bit (black & white) Pillow image.

Layout (landscape):
  +--------------------------------------------------+
  | OVERHEAD · Luxembourg              11:52 · 7 a/c  |  header
  +------------------------+-------------------------+
  |        radar           |  (1) LGL8008  LUX→BCN    |
  |     (range rings,      |      BCS3 · 1,800 ft ▼  |
  |      plane icons)      |  (2) ...                 |
  +------------------------+-------------------------+
  | source · radius                                   |  footer
  +--------------------------------------------------+
"""
from __future__ import annotations

import math
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

from .data import Snapshot

BLACK, WHITE = 0, 255

FONT_DIRS = [
    "/usr/share/fonts/truetype/dejavu",
    "/usr/share/fonts/dejavu",
    str(Path(__file__).parent / "fonts"),
]


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    name = "DejaVuSans-Bold.ttf" if bold else "DejaVuSans.ttf"
    for d in FONT_DIRS:
        p = Path(d) / name
        if p.exists():
            return ImageFont.truetype(str(p), size)
    return ImageFont.load_default(size)


# A simple airliner silhouette pointing "up" (north), in unit coordinates.
PLANE_SHAPE = [
    (0.0, -1.0), (0.12, -0.75), (0.12, -0.25), (1.0, 0.25), (1.0, 0.4),
    (0.12, 0.15), (0.1, 0.7), (0.4, 0.9), (0.4, 1.0), (0.0, 0.9),
    (-0.4, 1.0), (-0.4, 0.9), (-0.1, 0.7), (-0.12, 0.15), (-1.0, 0.4),
    (-1.0, 0.25), (-0.12, -0.25), (-0.12, -0.75),
]


def _plane_polygon(cx, cy, size, heading):
    a = math.radians(heading or 0)
    ca, sa = math.cos(a), math.sin(a)
    pts = []
    for x, y in PLANE_SHAPE:
        x, y = x * size, y * size
        pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
    return pts


def _fmt_alt(ac, units):
    if ac.on_ground:
        return "GND"
    if ac.altitude_ft is None:
        return "—"
    if units == "metric":
        return f"{round(ac.altitude_ft * 0.3048, -1):,.0f} m"
    return f"{ac.altitude_ft:,} ft"


def _fmt_speed(ac, units):
    if ac.speed_kt is None:
        return ""
    if units == "metric":
        return f"{ac.speed_kt * 1.852:.0f} km/h"
    return f"{ac.speed_kt:.0f} kt"


def _fit(d, text, font, max_w):
    """Shorten text with an ellipsis so it fits in max_w pixels."""
    if d.textlength(text, font=font) <= max_w:
        return text
    while text and d.textlength(text + "…", font=font) > max_w:
        text = text[:-1]
    return text.rstrip() + "…"


COMPASS = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]


def _compass(deg):
    return COMPASS[int((deg + 22.5) // 45) % 8]


def _trend(ac):
    if ac.vertical_rate is None or abs(ac.vertical_rate) < 300:
        return ""
    return " ▲" if ac.vertical_rate > 0 else " ▼"


class Renderer:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.mode = cfg["display"].get("mode", "list")
        self.numbered = 1 if self.mode == "nearest" else cfg["display"]["max_list"]
        self.f_title = _font(22, bold=True)
        self.f_header = _font(18)
        self.f_call = _font(22, bold=True)
        self.f_route = _font(18, bold=True)
        self.f_detail = _font(15)
        self.f_small = _font(13)
        self.f_badge = _font(13, bold=True)
        self.f_city = _font(14)
        # "nearest" mode
        self.f_big_call = _font(38, bold=True)
        self.f_big_code = _font(34, bold=True)
        self.f_label = _font(13)
        self.f_value = _font(20, bold=True)

    def render(self, snap: Snapshot, width: int, height: int) -> Image.Image:
        img = Image.new("1", (width, height), WHITE)
        d = ImageDraw.Draw(img)
        header_h, footer_h = 38, 24
        body_top, body_bottom = header_h, height - footer_h

        self._header(d, snap, width, header_h)
        radar_size = min(body_bottom - body_top, int(width * 0.55))
        self._radar(d, snap, 0, body_top, radar_size, body_bottom - body_top)
        panel = (d, snap, radar_size, body_top, width - radar_size, body_bottom - body_top)
        if self.mode == "nearest":
            self._nearest(*panel)
        else:
            self._list(*panel)
        self._footer(d, snap, width, height, footer_h)
        return img

    # ------------------------------------------------------------------ header
    def _header(self, d, snap, width, h):
        d.rectangle([0, 0, width, h], fill=BLACK)
        title = f"✈ OVERHEAD · {self.cfg['location']['name']}"
        d.text((12, h // 2), title, font=self.f_title, fill=WHITE, anchor="lm")
        n = len(snap.aircraft)
        right = f"{time.strftime('%H:%M', time.localtime(snap.fetched_at))}  ·  {n} aircraft"
        d.text((width - 12, h // 2), right, font=self.f_header, fill=WHITE, anchor="rm")

    # ------------------------------------------------------------------- radar
    def _radar(self, d, snap, x0, y0, w, h):
        cx, cy = x0 + w // 2, y0 + h // 2
        r_px = min(w, h) // 2 - 22
        radius_km = self.cfg["filter"]["radius_km"]

        # range rings at "nice" distances (e.g. 10, 20 km) plus the outer edge
        step = next((s for s in (0.25, 0.5, 1, 2, 5, 10, 20, 25, 50, 100) if radius_km / s <= 3.5), 100)
        rings = [k * step for k in range(1, int(radius_km // step) + 1) if k * step < radius_km - step * 0.3]
        rings.append(radius_km)
        for km in rings:
            rr = r_px * km / radius_km
            outer = km == radius_km
            d.ellipse([cx - rr, cy - rr, cx + rr, cy + rr], outline=BLACK, width=2 if outer else 1)
            d.text((cx + rr * 0.7071 + 3, cy - rr * 0.7071 - 3), f"{km:g} km",
                   font=self.f_small, fill=BLACK, anchor="ls")
        # compass ticks + N
        for ang in range(0, 360, 30):
            a = math.radians(ang)
            inner = r_px - (8 if ang % 90 == 0 else 4)
            d.line([cx + inner * math.sin(a), cy - inner * math.cos(a),
                    cx + r_px * math.sin(a), cy - r_px * math.cos(a)], fill=BLACK, width=2)
        d.text((cx, cy - r_px - 4), "N", font=self.f_badge, fill=BLACK, anchor="mb")
        # home marker
        d.line([cx - 6, cy, cx + 6, cy], fill=BLACK, width=2)
        d.line([cx, cy - 6, cx, cy + 6], fill=BLACK, width=2)

        max_list = self.numbered
        # draw far aircraft first so the nearest ends up on top
        for idx in range(len(snap.aircraft) - 1, -1, -1):
            ac = snap.aircraft[idx]
            dist = min(ac.distance_km / radius_km, 1.0) * r_px
            b = math.radians(ac.bearing)
            px, py = cx + dist * math.sin(b), cy - dist * math.cos(b)
            numbered = idx < max_list
            size = 11 if numbered else 7
            poly = _plane_polygon(px, py, size, ac.track)
            if ac.on_ground:
                d.polygon(poly, outline=BLACK, fill=WHITE)
            else:
                d.polygon(poly, fill=BLACK)
            if numbered:
                self._badge(d, px + size + 9, py - size - 2, idx + 1)

    def _badge(self, d, x, y, n, r=9, inverted=False):
        bg, fg = (WHITE, BLACK) if inverted else (BLACK, WHITE)
        d.ellipse([x - r, y - r, x + r, y + r], fill=bg, outline=BLACK, width=2)
        d.text((x, y), str(n), font=self.f_badge, fill=fg, anchor="mm")

    # -------------------------------------------------------------------- list
    def _empty(self, d, snap, x0, y0, w, h):
        msg = "Can't reach flight data" if snap.error else "Clear skies"
        sub = "Will retry shortly" if snap.error else (
            f"Nothing within {self.cfg['filter']['radius_km']} km right now")
        d.text((x0 + w // 2, y0 + h // 2 - 14), msg, font=self.f_call, fill=BLACK, anchor="mm")
        d.text((x0 + w // 2, y0 + h // 2 + 16), sub, font=self.f_detail, fill=BLACK, anchor="mm")

    def _list(self, d, snap, x0, y0, w, h):
        d.line([x0, y0, x0, y0 + h], fill=BLACK, width=2)
        if not snap.aircraft:
            return self._empty(d, snap, x0, y0, w, h)
        pad = 14
        units = self.cfg["display"]["units"]
        n = self.cfg["display"]["max_list"]
        row_h = h / n
        for i, ac in enumerate(snap.aircraft[:n]):
            top = y0 + i * row_h
            l1, l2, l3 = top + row_h * 0.27, top + row_h * 0.55, top + row_h * 0.80
            tx, right_x = x0 + pad + 26, x0 + w - pad
            self._badge(d, x0 + pad + 9, l1, i + 1)

            # line 1: callsign ............ LUX→BCN (or emergency tag)
            d.text((tx, l1), ac.label, font=self.f_call, fill=BLACK, anchor="lm")
            if ac.emergency:
                tw = d.textlength(ac.emergency, font=self.f_route)
                d.rectangle([right_x - tw - 6, l1 - 12, right_x + 2, l1 + 12], fill=BLACK)
                d.text((right_x - 2, l1), ac.emergency, font=self.f_route, fill=WHITE, anchor="rm")
            elif ac.route:
                d.text((right_x, l1), ac.route.codes, font=self.f_route, fill=BLACK, anchor="rm")

            # line 2: Luxembourg → Barcelona   (or registration if no route)
            if ac.route:
                line2 = ac.route.cities
            else:
                line2 = ac.registration if ac.registration and ac.registration != ac.label else ""
            if line2:
                d.text((tx, l2), _fit(d, line2, self.f_city, right_x - tx), font=self.f_city,
                       fill=BLACK, anchor="lm")

            # line 3: type · altitude · speed ....... distance
            details = [ac.type_code, _fmt_alt(ac, units) + _trend(ac), _fmt_speed(ac, units)]
            d.text((tx, l3), "  ·  ".join(p for p in details if p), font=self.f_detail,
                   fill=BLACK, anchor="lm")
            d.text((right_x, l3), f"{ac.distance_km:.1f} km", font=self.f_detail,
                   fill=BLACK, anchor="rm")
            if i < n - 1:
                ly = top + row_h - 1
                for xx in range(int(x0 + pad), int(right_x), 6):  # dotted divider
                    d.line([xx, ly, xx + 2, ly], fill=BLACK)

    # ----------------------------------------------------------------- nearest
    def _nearest(self, d, snap, x0, y0, w, h):
        d.line([x0, y0, x0, y0 + h], fill=BLACK, width=2)
        if not snap.aircraft:
            return self._empty(d, snap, x0, y0, w, h)
        ac = snap.aircraft[0]
        units = self.cfg["display"]["units"]
        pad = 18
        lx, rx = x0 + pad, x0 + w - pad
        inner_w = rx - lx
        y = y0 + 14

        d.text((lx, y), "NEAREST AIRCRAFT", font=self.f_label, fill=BLACK, anchor="lt")
        if ac.emergency:
            tw = d.textlength(ac.emergency, font=self.f_badge)
            d.rectangle([rx - tw - 8, y - 3, rx, y + 15], fill=BLACK)
            d.text((rx - 4, y + 6), ac.emergency, font=self.f_badge, fill=WHITE, anchor="rm")
        y += 20
        d.text((lx, y), _fit(d, ac.label, self.f_big_call, inner_w), font=self.f_big_call,
               fill=BLACK, anchor="lt")
        y += 46
        reg = ac.registration if ac.registration != ac.label else ""
        airline = ac.route.airline if ac.route else ""
        sub = "  ·  ".join(x for x in (airline, reg) if x)
        if sub:
            d.text((lx, y), _fit(d, sub, self.f_route, inner_w), font=self.f_route,
                   fill=BLACK, anchor="lt")
        y += 34

        # route block:  LUX ──✈── HKG  with city names underneath
        d.line([lx, y, rx, y], fill=BLACK, width=2)
        y += 12
        if ac.route:
            r = ac.route
            d.text((lx, y), r.origin, font=self.f_big_code, fill=BLACK, anchor="lt")
            d.text((rx, y), r.destination, font=self.f_big_code, fill=BLACK, anchor="rt")
            ow = d.textlength(r.origin, font=self.f_big_code)
            dw = d.textlength(r.destination, font=self.f_big_code)
            ly = y + 19
            a, b = lx + ow + 12, rx - dw - 12
            for xx in range(int(a), int(b), 8):
                d.line([xx, ly, xx + 4, ly], fill=BLACK, width=2)
            d.polygon(_plane_polygon((a + b) / 2, ly, 11, 90), fill=BLACK)
            half = inner_w / 2 - 6
            d.text((lx, y + 44), _fit(d, r.origin_city, self.f_detail, half),
                   font=self.f_detail, fill=BLACK, anchor="lt")
            d.text((rx, y + 44), _fit(d, r.destination_city, self.f_detail, half),
                   font=self.f_detail, fill=BLACK, anchor="rt")
        else:
            d.text((lx + inner_w / 2, y + 30), "Route unknown", font=self.f_route,
                   fill=BLACK, anchor="mm")
        y += 72
        d.line([lx, y, rx, y], fill=BLACK, width=2)

        # stats grid, 2 columns x 3 rows
        aircraft = ac.type_code
        heading = f"{ac.track:.0f}° {_compass(ac.track)}" if ac.track is not None else "—"
        stats = [
            ("ALTITUDE", _fmt_alt(ac, units) + _trend(ac)),
            ("SPEED", _fmt_speed(ac, units) or "—"),
            ("DISTANCE", f"{ac.distance_km:.1f} km {_compass(ac.bearing)}"),
            ("HEADING", heading),
            ("AIRCRAFT", aircraft or "—"),
            ("SQUAWK", ac.squawk or "—"),
        ]
        grid_top = y + 10
        cell_h = (y0 + h - grid_top - 6) / 3
        col_w = inner_w / 2
        for k, (label, value) in enumerate(stats):
            cx = lx + (k % 2) * col_w
            cy = grid_top + (k // 2) * cell_h
            d.text((cx, cy + 4), label, font=self.f_label, fill=BLACK, anchor="lt")
            d.text((cx, cy + 20), _fit(d, value, self.f_value, col_w - 8), font=self.f_value,
                   fill=BLACK, anchor="lt")

    # ------------------------------------------------------------------ footer
    def _footer(self, d, snap, width, height, h):
        y = height - h
        d.line([0, y, width, y], fill=BLACK, width=2)
        if snap.error:
            left = "⚠ offline – showing nothing until data returns"
        else:
            left = f"Data: {snap.source}"
        right = f"Radius {self.cfg['filter']['radius_km']} km"
        extra = len(snap.aircraft) - self.numbered
        if extra > 0:
            d.text((width // 2, y + h // 2 + 1), f"+{extra} more on radar", font=self.f_small,
                   fill=BLACK, anchor="mm")
        d.text((10, y + h // 2 + 1), left, font=self.f_small, fill=BLACK, anchor="lm")
        d.text((width - 10, y + h // 2 + 1), right, font=self.f_small, fill=BLACK, anchor="rm")
