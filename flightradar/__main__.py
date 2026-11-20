"""Entry point:  python -m flightradar [--config config.toml] [--once] [--demo]"""
from __future__ import annotations

import argparse
import logging
import signal
import sys
import time

from .config import load_config
from .data import DemoFetcher, FlightFetcher
from .display import make_display
from .render import Renderer

log = logging.getLogger("flightradar")


def main() -> int:
    ap = argparse.ArgumentParser(description="E-ink flight radar")
    ap.add_argument("--config", default="config.toml", help="path to config file")
    ap.add_argument("--once", action="store_true", help="draw one frame and exit")
    ap.add_argument("--demo", action="store_true", help="use built-in fake aircraft (no internet)")
    ap.add_argument("--driver", choices=["preview", "waveshare"], help="override display driver")
    ap.add_argument("--mode", choices=["list", "nearest"], help="override display mode")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    cfg = load_config(args.config)
    if args.driver:
        cfg["display"]["driver"] = args.driver
    if args.mode:
        cfg["display"]["mode"] = args.mode

    fetcher = DemoFetcher(cfg) if args.demo else FlightFetcher(cfg)
    display = make_display(cfg)
    renderer = Renderer(cfg)
    interval = max(30, int(cfg["display"]["refresh_seconds"]))

    # Shut down cleanly when systemd stops us (SIGTERM) or on Ctrl+C.
    def stop(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, stop)

    last_was_empty = False
    try:
        while True:
            started = time.monotonic()
            snap = fetcher.fetch()
            empty = not snap.aircraft
            # Skip redundant refreshes of an empty sky: saves flashing at night.
            if not (empty and last_was_empty and not args.once):
                img = renderer.render(snap, display.width, display.height)
                display.show(img)
            last_was_empty = empty
            if args.once:
                break
            time.sleep(max(1, interval - (time.monotonic() - started)))
    except KeyboardInterrupt:
        log.info("Stopping")
        if not args.once:
            display.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
