# ✈ Raspberry Pi E-Ink Flight Radar

A Raspberry Pi with an e-ink screen that shows the aircraft flying over you right now: a radar view on the left, and the nearest flights on the right with callsign, route, aircraft type, altitude, speed and distance.

![Preview](docs/preview.png)

*(This picture was made with the built-in demo data. The real screen shows live traffic.)*

Flight data comes from free community ADS-B networks ([airplanes.live](https://airplanes.live), [adsb.fi](https://adsb.fi), [adsb.lol](https://adsb.lol)), and routes come from [adsbdb.com](https://www.adsbdb.com). You don't need an API key or account. If one source is down, the app tries the next one.

---

## 1. What to buy

| Part | Notes |
|---|---|
| **Raspberry Pi Zero 2 WH** | The "H" means the GPIO pin header comes pre-soldered, so you don't need to solder anything. A Pi 3, 4 or 5 works too. |
| **Waveshare 7.5inch e-Paper HAT (V2)**, 800×480, black/white | The "HAT" version plugs straight onto the Pi's pins. Other Waveshare sizes also work (see section 6). |
| **microSD card**, 16 GB or larger | |
| **Power supply** | Zero 2 W: 5 V / 2.5 A **micro-USB**. Pi 4/5: the official USB-C supply. |
| Optional: a photo frame | Many people mount the 7.5" panel in an IKEA-style frame. |

## 2. Assemble the hardware (power OFF)

1. The display comes as two parts: a thin **glass panel** with a ribbon cable, and a small **driver board (the HAT)**. Lift the little black latch on the HAT's connector, slide the ribbon in (contacts facing the board), and press the latch down. Go gently, because the ribbon is fragile.
2. Some driver boards have small switches. Set them as the [Waveshare wiki page for your display](https://www.waveshare.com/wiki/7.5inch_e-Paper_HAT_Manual) says (usually 4-line SPI).
3. Push the HAT onto the Pi's 40-pin header so it lines up with the board.

## 3. Set up the Raspberry Pi

1. On your computer, install **[Raspberry Pi Imager](https://www.raspberrypi.com/software/)** and insert the microSD card.
2. Choose your Pi model, then **Raspberry Pi OS Lite (64-bit)**. You don't need a desktop, because you'll control the Pi from your computer over Wi-Fi.
3. When Imager offers to **customise settings**, set:
   - hostname: `flightradar`
   - a username and password (write them down)
   - your Wi-Fi name and password, and your country
   - **enable SSH** (password authentication)
4. Write the card, put it in the Pi, and plug in the power. The first boot takes a couple of minutes.
5. From your computer, open a terminal (on Windows: PowerShell; on Mac: Terminal) and connect:
   ```bash
   ssh yourusername@flightradar.local
   ```
   Type `yes` the first time, then your password. You're now typing commands on the Pi.

## 4. Install the app on the Pi

```bash
sudo apt-get update && sudo apt-get install -y git
git clone https://github.com/phasta352/flight-radar.git
cd flight-radar
bash install.sh
sudo reboot
```

`install.sh` enables the SPI interface, installs the libraries, downloads the Waveshare driver, and sets the app up to start automatically on boot.

## 5. Configure and test

Reconnect with `ssh` after the reboot, then:

```bash
cd flight-radar
nano config.toml          # set your latitude/longitude and radius. Ctrl+O saves, Ctrl+X exits
.venv/bin/python -m flightradar --once      # draws one frame on the screen
sudo systemctl start flightradar            # run continuously (also starts on every boot)
```

Useful commands:

| What | Command |
|---|---|
| See live logs | `journalctl -u flightradar -f` |
| Restart after changing config | `sudo systemctl restart flightradar` |
| Stop | `sudo systemctl stop flightradar` |
| Update to the latest code | `cd ~/flight-radar && git pull && sudo systemctl restart flightradar` |

## 6. Configuration

Everything lives in [`config.toml`](config.toml). The settings you're most likely to change:

- **`latitude` / `longitude`**: your home. In Google Maps, right-click your house and click the numbers to copy them.
- **`radius_km`**: how far around you to look. 15–30 km feels like "overhead"; 50+ km shows more traffic.
- **`min_altitude_ft`**: raise it to hide helicopters and light aircraft.
- **`refresh_seconds`**: e-ink flashes black/white on each full refresh. 60–180 s is a good balance.
- **`model`**: the Waveshare driver name. Some common ones:

  | Display | `model` |
  |---|---|
  | 7.5" V2 (800×480) | `epd7in5_V2` |
  | 7.5" HD (880×528) | `epd7in5_HD` |
  | 5.83" V2 (648×480) | `epd5in83_V2` |
  | 4.2" V2 (400×300) | `epd4in2_V2` |

  The layout is built for 800×480. Smaller screens work but will feel cramped, so lower `max_list` to 3–4.

## 7. Try it on your computer first (optional)

You don't need the Pi to see what the app does. With Python 3.11+:

```bash
git clone https://github.com/phasta352/flight-radar.git && cd flight-radar
python3 -m venv .venv && source .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python -m flightradar --demo --once     # fake aircraft → preview.png
python -m flightradar --once            # live aircraft around you → preview.png
```

Open `preview.png` to see exactly what the e-ink screen would show.

## Troubleshooting

- **Screen stays blank**: check that SPI is on (`ls /dev/spi*` should list devices), that you rebooted after `install.sh`, that the ribbon is seated, and that `model` matches your display.
- **"Can't reach flight data"**: check the Pi's internet with `ping -c 3 api.airplanes.live`.
- **No routes shown**: private, military and some cargo flights have no published route. That's normal.
- **Faint ghost images**: normal for e-ink. The app does a full refresh each time and blanks the screen when stopped.

## How the code is organised

```
flightradar/
  __main__.py   main loop: fetch → render → display → sleep
  config.py     reads config.toml
  data.py       downloads aircraft, computes distance/bearing, filters, looks up routes
  render.py     draws the 1-bit image with Pillow (radar + list)
  display.py    "preview" (saves PNG) and "waveshare" (real screen) drivers
  sample_data.json   fake aircraft for --demo
install.sh      one-time Raspberry Pi setup + systemd service
```

Please respect the data providers: the free APIs are for **non-commercial use** and are rate-limited (about 1 request/second). This app makes one request every couple of minutes. If you enjoy the app, consider [feeding data](https://airplanes.live) back to the network with a cheap USB SDR receiver.
