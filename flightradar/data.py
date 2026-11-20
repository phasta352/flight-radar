"""Fetches live aircraft positions from free ADS-B community APIs.

airplanes.live, adsb.fi and adsb.lol all return the same JSON format
(the "ADSBExchange v2" format), so one parser handles all three.
Each aircraft is a dict with keys like:
    hex       ICAO 24-bit transponder address, e.g. "4ca87c"
    flight    callsign, e.g. "LGL4TV  " (padded with spaces)
    r         registration, e.g. "LX-LGA"
    t         ICAO type code, e.g. "DH8D"
    lat, lon  position
    alt_baro  barometric altitude in feet, or the string "ground"
    gs        ground speed in knots
    track     direction of travel in degrees (0 = north)
    baro_rate climb/descent rate in feet per minute
    squawk    transponder code (7500/7600/7700 = emergency)
"""
from __future__ import annotations

import json
import logging
import math
import time
from dataclasses import dataclass
from pathlib import Path

import requests

log = logging.getLogger(__name__)

KM_PER_NM = 1.852

# {lat} {lon} {nm} are filled in; radius is in nautical miles (max 250).
SOURCES = {
    "airplanes.live": "https://api.airplanes.live/v2/point/{lat}/{lon}/{nm}",
    "adsb.fi": "https://opendata.adsb.fi/api/v2/lat/{lat}/lon/{lon}/dist/{nm}",
    "adsb.lol": "https://api.adsb.lol/v2/lat/{lat}/lon/{lon}/dist/{nm}",
}

ROUTE_URL = "https://api.adsbdb.com/v0/callsign/{callsign}"
USER_AGENT = "pi-eink-flightradar/0.1 (hobby project)"

EMERGENCY_SQUAWKS = {"7500": "HIJACK", "7600": "RADIO FAIL", "7700": "EMERGENCY"}


@dataclass
class Aircraft:
    hex: str
    callsign: str
    registration: str
    type_code: str
    lat: float
    lon: float
    altitude_ft: int | None
    on_ground: bool
    speed_kt: float | None
    track: float | None
    vertical_rate: int | None
    squawk: str
    distance_km: float = 0.0
    bearing: float = 0.0
    route: str | None = None

    @property
    def label(self) -> str:
        """Best available name: callsign, else registration, else hex code."""
        return self.callsign or self.registration or self.hex.upper()

    @property
    def emergency(self) -> str | None:
        return EMERGENCY_SQUAWKS.get(self.squawk)


@dataclass
class Snapshot:
    aircraft: list[Aircraft]
    source: str
    fetched_at: float
    error: str | None = None


# --------------------------------------------------------------------------
# Geometry helpers
# --------------------------------------------------------------------------

def distance_km(lat1, lon1, lat2, lon2) -> float:
    """Great-circle distance (haversine formula)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = p2 - p1
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def bearing_deg(lat1, lon1, lat2, lon2) -> float:
    """Compass direction from point 1 to point 2 (0 = north, 90 = east)."""
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dl = math.radians(lon2 - lon1)
    x = math.sin(dl) * math.cos(p2)
    y = math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)
    return (math.degrees(math.atan2(x, y)) + 360) % 360


# --------------------------------------------------------------------------
# Parsing
# --------------------------------------------------------------------------

def parse_aircraft(raw: dict, home_lat: float, home_lon: float) -> Aircraft | None:
    lat, lon = raw.get("lat"), raw.get("lon")
    if lat is None or lon is None:
        return None  # no position (yet) - nothing to plot
    if raw.get("seen_pos", 0) > 60:
        return None  # position is stale

    alt = raw.get("alt_baro")
    on_ground = alt == "ground"
    if on_ground:
        altitude = 0
    elif isinstance(alt, (int, float)):
        altitude = int(alt)
    elif isinstance(raw.get("alt_geom"), (int, float)):
        altitude = int(raw["alt_geom"])
    else:
        altitude = None

    vr = raw.get("baro_rate", raw.get("geom_rate"))
    ac = Aircraft(
        hex=str(raw.get("hex", "")).strip().lstrip("~"),
        callsign=str(raw.get("flight", "")).strip(),
        registration=str(raw.get("r", "")).strip(),
        type_code=str(raw.get("t", "")).strip(),
        lat=float(lat),
        lon=float(lon),
        altitude_ft=altitude,
        on_ground=on_ground,
        speed_kt=raw.get("gs"),
        track=raw.get("track", raw.get("true_heading")),
        vertical_rate=int(vr) if isinstance(vr, (int, float)) else None,
        squawk=str(raw.get("squawk", "")),
    )
    ac.distance_km = distance_km(home_lat, home_lon, ac.lat, ac.lon)
    ac.bearing = bearing_deg(home_lat, home_lon, ac.lat, ac.lon)
    return ac


def filter_and_sort(aircraft: list[Aircraft], cfg: dict) -> list[Aircraft]:
    f = cfg["filter"]
    out = []
    for ac in aircraft:
        if ac.distance_km > f["radius_km"]:
            continue
        if ac.on_ground and not f["include_ground"]:
            continue
        if ac.altitude_ft is not None and not ac.on_ground:
            if not (f["min_altitude_ft"] <= ac.altitude_ft <= f["max_altitude_ft"]):
                continue
        out.append(ac)
    out.sort(key=lambda a: a.distance_km)
    return out


# --------------------------------------------------------------------------
# Fetching
# --------------------------------------------------------------------------

class FlightFetcher:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self._route_cache: dict[str, tuple[str | None, float]] = {}

    def fetch(self) -> Snapshot:
        loc = self.cfg["location"]
        lat, lon = loc["latitude"], loc["longitude"]
        # ask for a slightly bigger circle than we show, then filter precisely
        nm = min(250, math.ceil(self.cfg["filter"]["radius_km"] / KM_PER_NM) + 1)
        errors = []
        for name in self.cfg["data"]["sources"]:
            url = SOURCES.get(name)
            if not url:
                log.warning("Unknown source %r - skipping", name)
                continue
            try:
                resp = self.session.get(
                    url.format(lat=lat, lon=lon, nm=nm),
                    timeout=self.cfg["data"]["timeout_seconds"],
                )
                resp.raise_for_status()
                payload = resp.json()
            except (requests.RequestException, ValueError) as exc:
                log.warning("Source %s failed: %s", name, exc)
                errors.append(f"{name}: {exc}")
                continue
            raw_list = payload.get("ac") or payload.get("aircraft") or []
            aircraft = [a for a in (parse_aircraft(r, lat, lon) for r in raw_list) if a]
            aircraft = filter_and_sort(aircraft, self.cfg)
            if self.cfg["data"]["lookup_routes"]:
                self._add_routes(aircraft[: self.cfg["display"]["max_list"]])
            log.info("Got %d aircraft from %s", len(aircraft), name)
            return Snapshot(aircraft, name, time.time())
        return Snapshot([], "", time.time(), error="; ".join(errors) or "no sources")

    # Route lookup: callsign -> "LUX→LHR". Cached, because routes rarely change
    # and we only want to make a handful of extra requests per refresh.
    def _add_routes(self, aircraft: list[Aircraft]) -> None:
        now = time.time()
        for ac in aircraft:
            cs = ac.callsign
            if not cs:
                continue
            cached = self._route_cache.get(cs)
            if cached and cached[1] > now:
                ac.route = cached[0]
                continue
            route, ttl = self._lookup_route(cs)
            self._route_cache[cs] = (route, now + ttl)
            ac.route = route

    def _lookup_route(self, callsign: str) -> tuple[str | None, float]:
        try:
            resp = self.session.get(ROUTE_URL.format(callsign=callsign), timeout=5)
            if resp.status_code == 404:
                return None, 6 * 3600
            resp.raise_for_status()
            fr = resp.json().get("response", {})
            fr = fr.get("flightroute") if isinstance(fr, dict) else None
            if not fr:
                return None, 6 * 3600  # unknown callsign (private / military)

            def code(ap):
                return ap.get("iata_code") or ap.get("icao_code") or "?"

            return f"{code(fr['origin'])}→{code(fr['destination'])}", 6 * 3600
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            log.debug("Route lookup failed for %s: %s", callsign, exc)
            return None, 15 * 60  # try again later


class DemoFetcher:
    """Offline fake data so you can test the layout without internet."""

    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.sample = json.loads(
            (Path(__file__).parent / "sample_data.json").read_text()
        )

    def fetch(self) -> Snapshot:
        loc = self.cfg["location"]
        aircraft = [
            a
            for a in (
                parse_aircraft(r, loc["latitude"], loc["longitude"])
                for r in self.sample["ac"]
            )
            if a
        ]
        aircraft = filter_and_sort(aircraft, self.cfg)
        for ac in aircraft:
            ac.route = self.sample.get("routes", {}).get(ac.callsign)
        return Snapshot(aircraft, "demo data", time.time())
