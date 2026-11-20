"""Loads config.toml into a simple dictionary with defaults filled in."""
from __future__ import annotations

import copy
import tomllib
from pathlib import Path

DEFAULTS = {
    "location": {"name": "Home", "latitude": 49.6116, "longitude": 6.1319},
    "filter": {
        "radius_km": 25,
        "min_altitude_ft": 0,
        "max_altitude_ft": 60000,
        "include_ground": False,
    },
    "data": {
        "sources": ["airplanes.live", "adsb.fi", "adsb.lol"],
        "lookup_routes": True,
        "timeout_seconds": 10,
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
