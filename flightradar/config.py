"""Loads config.toml into a simple dictionary with defaults filled in."""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

DEFAULTS = {
    "location": {"name": "Home", "latitude": 49.6116, "longitude": 6.1319},
    "filter": {
        "radius_km": 12,
        "min_altitude_ft": 0,
        "max_altitude_ft": 60000,
        "include_ground": False,
    },
    "data": {
        "sources": ["airplanes.live", "adsb.fi", "adsb.lol"],
        "lookup_routes": True,
        "timeout_seconds": 10,
    },
    "overhead": {
        "enabled": True,
        "radius_km": 1.5,
        "lead_seconds": 30,
        "poll_seconds": 10,
        "min_refresh_gap_seconds": 15,
        "display_delay_seconds": 4,
    },
    "map": {
        "runways": [
            {"name": "LUX", "ends": [[49.617669, 6.187456], [49.635528, 6.235556]],
             "labels": ["06", "24"], "width_m": 60},
        ],
        "trail": True,
    },
    "display": {
        "driver": "preview",
        "mode": "list",
        "model": "epd7in5_V2",
        "width": 800,
        "height": 480,
        "preview_path": "preview.png",
        "refresh_seconds": 45,
        "max_list": 6,
        "units": "aviation",
        "rotate": 0,
    },
}


def load_config(path: str | Path) -> dict:
    cfg = copy.deepcopy(DEFAULTS)
    path = Path(path)
    if path.exists():
        with path.open("rb") as f:
            user = tomllib.load(f)
        for section, values in user.items():
            cfg.setdefault(section, {}).update(values)
    return cfg
