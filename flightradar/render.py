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

from .data import Snapshot, bearing_deg, distance_km, low_enough

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


SOON_S = 120   # show "overhead in ..." for planes arriving within this


def _soon(ac):
    return ac.overhead_in is not None and ac.overhead_in <= SOON_S


def _fmt_eta(secs):
    if secs < 8:
        return "now"
    if secs < 90:
        return f"~{int(round(secs / 5) * 5)} s"
    return f"~{round(secs / 60)} min"


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
        self.f_tiny = _font(10, bold=True)
        self.featured = None
        # "nearest" mode: the last low plane we saw, kept on screen for a while
        self.held = None          # Aircraft
        self.held_at = 0.0        # when it was last seen low enough to hear
        self.card = None          # what the nearest card shows this frame
        self.card_live = False    # True: currently low and nearby; False: "last heard"
        self.f_big_call = _font(38, bold=True)
        self.f_big_code = _font(34, bold=True)
        self.f_label = _font(13)
        self.f_value = _font(20, bold=True)

    def observe(self, snap: Snapshot) -> None:
        """Call on every data fetch (not just every redraw) so the
        "last heard" timer in nearest mode is accurate."""
        if self.mode != "nearest" or snap.error:
            return
        low = [a for a in snap.aircraft if low_enough(a, self.cfg)]
        soon = sorted((a for a in low if _soon(a)), key=lambda a: a.overhead_in)
        pick = soon[0] if soon else (low[0] if low else None)
        if pick is not None:
            self.held, self.held_at = pick, snap.fetched_at

    def holding(self, now: float | None = None) -> bool:
        """True while the last low plane is still being shown."""
        if self.held is None:
            return False
        now = time.time() if now is None else now
        return now - self.held_at <= self.cfg["display"]["nearest_hold_seconds"]

    def render(self, snap: Snapshot, width: int, height: int) -> Image.Image:
        if self.mode == "nearest":
            self.observe(snap)
            self.card, self.card_live = None, False
            if self.held is not None and self.holding(snap.fetched_at):
                # use the plane's latest data if it's still on the radar
                current = next((a for a in snap.aircraft if a.hex == self.held.hex), None)
                self.card = current or self.held
                self.card_live = self.held_at == snap.fetched_at
            self.featured = self.card if self.card in snap.aircraft else None
        else:
            # The featured plane: the next to pass overhead, else the nearest.
            soon = sorted((a for a in snap.aircraft if _soon(a)), key=lambda a: a.overhead_in)
            self.featured = soon[0] if soon else (snap.aircraft[0] if snap.aircraft else None)
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
        # map: runways under everything else
        loc = self.cfg["location"]

        def to_px(lat, lon):
            dist = distance_km(loc["latitude"], loc["longitude"], lat, lon)
            b = math.radians(bearing_deg(loc["latitude"], loc["longitude"], lat, lon))
            rr = dist / radius_km * r_px
            return cx + rr * math.sin(b), cy - rr * math.cos(b), dist

        for rw in self.cfg.get("map", {}).get("runways", []):
            self._runway(d, rw, to_px, radius_km, r_px)

        # featured plane's trail: dotted line through its recent positions
        f = self.featured
        if f is not None and self.cfg.get("map", {}).get("trail", True) and f.trail:
            pts = [to_px(f.lat, f.lon)] + [to_px(lat, lon) for lat, lon in reversed(f.trail)]
            path = []
            for x, y, dist in pts:
                if dist > radius_km:
                    break
                path.append((x, y))
            self._dotted(d, path)

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
            numbered = (ac is self.featured) if self.mode == "nearest" else idx < max_list
            size = 11 if numbered else 7
            poly = _plane_polygon(px, py, size, ac.track)
            if ac.on_ground:
                d.polygon(poly, outline=BLACK, fill=WHITE)
            else:
                d.polygon(poly, fill=BLACK)
            if _soon(ac):   # about to pass overhead: ring + line to home
                rr = size + 6
                d.ellipse([px - rr, py - rr, px + rr, py + rr], outline=BLACK, width=2)
                self._dashed(d, px, py, cx, cy)
            if numbered:
                self._badge(d, px + size + 9, py - size - 2, 1 if self.mode == "nearest" else idx + 1)

    def _runway(self, d, rw, to_px, radius_km, r_px):
        (lat1, lon1), (lat2, lon2) = rw["ends"]
        x1, y1, d1 = to_px(lat1, lon1)
        x2, y2, d2 = to_px(lat2, lon2)
        if min(d1, d2) > radius_km:
            return
        length = math.hypot(x2 - x1, y2 - y1) or 1
        ux, uy = (x2 - x1) / length, (y2 - y1) / length     # along the runway
        half = max(2.5, rw.get("width_m", 60) / 1000 / radius_km * r_px / 2)
        px, py = -uy * half, ux * half                       # across the runway
        d.polygon([(x1 + px, y1 + py), (x2 + px, y2 + py), (x2 - px, y2 - py), (x1 - px, y1 - py)],
                  fill=WHITE, outline=BLACK)
        labels = rw.get("labels") or []
        for (x, y, sgn), lab in zip(((x1, y1, -1), (x2, y2, 1)), labels):
            d.text((x + ux * sgn * 10, y + uy * sgn * 10), lab, font=self.f_tiny, fill=BLACK, anchor="mm")
        if rw.get("name"):
            mx, my = (x1 + x2) / 2, (y1 + y2) / 2
            nx, ny = (px, py) if py > 0 else (-px, -py)      # put the name below the runway
            norm = math.hypot(nx, ny) or 1
            d.text((mx + nx / norm * 11, my + ny / norm * 11), rw["name"], font=self.f_tiny,
                   fill=BLACK, anchor="mm")

    @staticmethod
    def _dotted(d, path, spacing=6, r=1.4):
        """Small dots every `spacing` pixels along a polyline."""
        carry = 0.0
        for (x0, y0), (x1, y1) in zip(path, path[1:]):
            seg = math.hypot(x1 - x0, y1 - y0)
            pos = carry
            while pos < seg:
                t = pos / seg
                x, y = x0 + (x1 - x0) * t, y0 + (y1 - y0) * t
                d.ellipse([x - r, y - r, x + r, y + r], fill=BLACK)
                pos += spacing
            carry = pos - seg

    @staticmethod
    def _dashed(d, x0, y0, x1, y1, dash=5, gap=4):
        length = math.hypot(x1 - x0, y1 - y0)
        if length < 1:
            return
        ux, uy = (x1 - x0) / length, (y1 - y0) / length
        pos = 0.0
        while pos < length:
            end = min(pos + dash, length)
            d.line([x0 + ux * pos, y0 + uy * pos, x0 + ux * end, y0 + uy * end], fill=BLACK, width=1)
            pos = end + gap

    def _pill(self, d, x_right, y_mid, text, font):
        tw = d.textlength(text, font=font)
        d.rounded_rectangle([x_right - tw - 10, y_mid - 10, x_right, y_mid + 10], radius=9, fill=BLACK)
        d.text((x_right - 5, y_mid), text, font=font, fill=WHITE, anchor="rm")

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
            details = [p for p in (ac.type_code, _fmt_alt(ac, units) + _trend(ac),
                                   _fmt_speed(ac, units)) if p]
            if _soon(ac):
                right_text = f"overhead {_fmt_eta(ac.overhead_in)}"
                right_w = d.textlength(right_text, font=self.f_badge) + 18
            else:
                right_w = d.textlength(f"{ac.distance_km:.1f} km", font=self.f_detail) + 10
            # drop trailing details (speed first) if they'd run into the right-hand text
            while len(details) > 1 and d.textlength("  ·  ".join(details), font=self.f_detail) > right_x - tx - right_w:
                details.pop()
            d.text((tx, l3), "  ·  ".join(details), font=self.f_detail, fill=BLACK, anchor="lm")
            if _soon(ac):
                self._pill(d, right_x, l3, f"overhead {_fmt_eta(ac.overhead_in)}", self.f_badge)
            else:
                d.text((right_x, l3), f"{ac.distance_km:.1f} km", font=self.f_detail,
                       fill=BLACK, anchor="rm")
            if i < n - 1:
                ly = top + row_h - 1
                for xx in range(int(x0 + pad), int(right_x), 6):  # dotted divider
                    d.line([xx, ly, xx + 2, ly], fill=BLACK)

    # ----------------------------------------------------------------- nearest
    def _nearest(self, d, snap, x0, y0, w, h):
        d.line([x0, y0, x0, y0 + h], fill=BLACK, width=2)
        if snap.error and self.card is None:
            return self._empty(d, snap, x0, y0, w, h)
        if self.card is None:
            return self._scanning(d, snap, x0, y0, w, h)
        ac = self.card
        units = self.cfg["display"]["units"]
        pad = 18
        lx, rx = x0 + pad, x0 + w - pad
        inner_w = rx - lx
        y = y0 + 14

        if not self.card_live:
            ago = max(0, snap.fetched_at - self.held_at)
            when = "just now" if ago < 20 else (f"{int(round(ago / 10) * 10)} s ago" if ago < 90
                                                else f"{round(ago / 60)} min ago")
            label = f"LAST HEARD · {when.upper()}"
            tw = d.textlength(label, font=self.f_badge)
            d.rounded_rectangle([lx - 4, y - 4, lx + tw + 6, y + 15], radius=8, outline=BLACK, width=2)
            d.text((lx + 1, y + 6), label, font=self.f_badge, fill=BLACK, anchor="lm")
        elif _soon(ac):
            label = f"OVERHEAD {_fmt_eta(ac.overhead_in).upper()}" if ac.overhead_in >= 8 else "OVERHEAD NOW"
            tw = d.textlength(label, font=self.f_badge)
            d.rounded_rectangle([lx - 4, y - 4, lx + tw + 6, y + 15], radius=8, fill=BLACK)
            d.text((lx + 1, y + 6), label, font=self.f_badge, fill=WHITE, anchor="lm")
        else:
            d.text((lx, y), "OVERHEAD NEARBY", font=self.f_label, fill=BLACK, anchor="lt")
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

    def _scanning(self, d, snap, x0, y0, w, h):
        cx, cy = x0 + w // 2, y0 + h // 2
        # little radar-sweep icon
        r = 34
        top = cy - 70
        d.ellipse([cx - r, top - r, cx + r, top + r], outline=BLACK, width=2)
        d.ellipse([cx - r / 2, top - r / 2, cx + r / 2, top + r / 2], outline=BLACK, width=1)
        d.pieslice([cx - r, top - r, cx + r, top + r], -90, -45, fill=BLACK)
        d.text((cx, cy + 4), "Scanning…", font=self.f_big_call, fill=BLACK, anchor="mm")
        limit = f"{self.cfg['display']['nearest_max_altitude_ft']:,} ft"
        d.text((cx, cy + 46), f"Listening for planes below {limit}", font=self.f_detail,
               fill=BLACK, anchor="mm")

    # ------------------------------------------------------------------ footer
    def _footer(self, d, snap, width, height, h):
        y = height - h
        d.line([0, y, width, y], fill=BLACK, width=2)
        if snap.error:
            left = "⚠ offline – showing nothing until data returns"
        else:
            left = f"Data: {snap.source}"
        right = f"Radius {self.cfg['filter']['radius_km']} km"
        shown = (1 if self.featured is not None else 0) if self.mode == "nearest" else self.numbered
        extra = len(snap.aircraft) - shown
        if extra > 0:
            d.text((width // 2, y + h // 2 + 1), f"+{extra} more on radar", font=self.f_small,
                   fill=BLACK, anchor="mm")
        d.text((10, y + h // 2 + 1), left, font=self.f_small, fill=BLACK, anchor="lm")
        d.text((width - 10, y + h // 2 + 1), right, font=self.f_small, fill=BLACK, anchor="rm")
