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

    # Overhead alerts: check the data often, but only redraw the (slow, flashy)
    # e-ink screen on the regular interval or just before a plane arrives.
    ov = cfg["overhead"]
    poll = max(5, int(ov["poll_seconds"])) if ov["enabled"] else interval
    lead = ov["lead_seconds"] + ov["display_delay_seconds"]
    min_gap = ov["min_refresh_gap_seconds"]
    announced: dict[str, float] = {}   # aircraft already shown as "overhead soon"
    last_refresh = None
    last_was_empty = False
    try:
        while True:
            started = time.monotonic()
            snap = fetcher.fetch()
            now = time.monotonic()
            announced = {h: t for h, t in announced.items() if t > now}
            due = [a for a in snap.aircraft
                   if a.overhead_in is not None and a.overhead_in <= lead
                   and a.hex not in announced]
            since = None if last_refresh is None else now - last_refresh
            regular = since is None or since >= interval
            early = bool(due) and (since is None or since >= min_gap)
            # If a plane will need an early refresh in the next few seconds,
            # hold the regular one and do a single refresh at the right moment.
            upcoming = [a.overhead_in - lead for a in snap.aircraft
                        if a.overhead_in is not None and a.hex not in announced
                        and a.overhead_in > lead]
            if regular and not early and since is not None and upcoming \
                    and min(upcoming) <= min_gap:
                regular = False
            empty = not snap.aircraft

            if args.once or regular or early:
                # Skip redundant refreshes of an empty sky: saves flashing at night.
                if args.once or not (empty and last_was_empty):
                    if early and not regular:
                        log.info("Early refresh: %s overhead in ~%.0f s",
                                 due[0].label, due[0].overhead_in)
                    img = renderer.render(snap, display.width, display.height)
                    display.show(img)
                    last_refresh = now
                    # planes already shown as arriving don't trigger another redraw
                    for a in snap.aircraft:
                        if a.overhead_in is not None and a.overhead_in <= lead + poll:
                            announced[a.hex] = now + a.overhead_in + 60
                last_was_empty = empty
            if args.once:
                break
            # Sleep until the next poll, or wake up exactly when a plane will be
            # `lead` seconds away, whichever comes first.
            wait = poll - (time.monotonic() - started)
            if last_refresh is not None:   # don't overshoot the regular refresh
                wait = min(wait, interval - (time.monotonic() - last_refresh))
            for a in snap.aircraft:
                if a.overhead_in is not None and a.hex not in announced:
                    until = a.overhead_in - lead - (time.monotonic() - now)
                    if 0 < until < wait:
                        wait = until
            time.sleep(max(1, wait))
    except KeyboardInterrupt:
        log.info("Stopping")
        if not args.once:
            display.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
