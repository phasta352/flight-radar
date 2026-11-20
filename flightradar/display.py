"""Output drivers: save a PNG preview, or draw on a Waveshare e-Paper HAT."""
from __future__ import annotations

import importlib
import logging

from PIL import Image

log = logging.getLogger(__name__)


class PreviewDisplay:
    """Saves each frame as a PNG. Use this on your laptop to test."""

    def __init__(self, cfg: dict):
        d = cfg["display"]
        self.width, self.height = d["width"], d["height"]
        self.path = d["preview_path"]
        self.rotate = d.get("rotate", 0)

    def show(self, img: Image.Image) -> None:
        if self.rotate:
            img = img.rotate(self.rotate, expand=True)
        img.save(self.path)
        log.info("Saved preview to %s", self.path)

    def close(self) -> None:
        pass


class WaveshareDisplay:
    """Draws on a Waveshare e-Paper display via its official Python driver.

    `model` is the driver module name inside the waveshare_epd package,
    e.g. "epd7in5_V2" for the 7.5 inch V2 black/white HAT. The name is
    printed on a sticker on the back of the display / in its wiki page.
    """

    def __init__(self, cfg: dict):
        model = cfg["display"]["model"]
        try:
            module = importlib.import_module(f"waveshare_epd.{model}")
        except ImportError as exc:
            raise SystemExit(
                f"Could not load Waveshare driver '{model}': {exc}\n"
                "Did install.sh run successfully? Is the model name right?"
            ) from exc
        self.epd = module.EPD()
        # Waveshare reports width/height in the panel's native orientation.
        # We always draw landscape and rotate if the panel is portrait.
        self.native_w, self.native_h = self.epd.width, self.epd.height
        self.width = max(self.native_w, self.native_h)
        self.height = min(self.native_w, self.native_h)
        self.rotate = cfg["display"].get("rotate", 0)
        log.info("Waveshare %s ready (%dx%d)", model, self.width, self.height)

    def show(self, img: Image.Image) -> None:
        if self.native_w < self.native_h:
            img = img.rotate(90, expand=True)
        if self.rotate:
            img = img.rotate(self.rotate, expand=True)
        self.epd.init()             # wake up the panel
        self.epd.display(self.epd.getbuffer(img))
        self.epd.sleep()            # deep sleep between updates: protects the panel

    def close(self) -> None:
        try:
            self.epd.init()
            self.epd.Clear()        # leave a blank screen (avoids ghosting/burn-in)
            self.epd.sleep()
        except Exception as exc:  # noqa: BLE001 - best effort on shutdown
            log.warning("Could not clear display: %s", exc)


def make_display(cfg: dict):
    driver = cfg["display"]["driver"]
    if driver == "preview":
        return PreviewDisplay(cfg)
    if driver == "waveshare":
        return WaveshareDisplay(cfg)
    raise SystemExit(f"Unknown display driver {driver!r} (use 'preview' or 'waveshare')")
