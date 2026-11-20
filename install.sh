#!/usr/bin/env bash
# One-time setup on the Raspberry Pi. Run from inside the project folder:
#     cd ~/flight-radar && bash install.sh
set -euo pipefail

APP_DIR="$(cd "$(dirname "$0")" && pwd)"
APP_USER="$(whoami)"
cd "$APP_DIR"

echo "==> 1/5 Enabling the SPI interface (the display talks over SPI)"
sudo raspi-config nonint do_spi 0

echo "==> 2/5 Installing system packages"
sudo apt-get update
sudo apt-get install -y git python3-venv python3-pil python3-numpy python3-requests \
    python3-gpiozero python3-lgpio python3-spidev fonts-dejavu-core

echo "==> 3/5 Creating Python virtual environment (.venv)"
# --system-site-packages lets the venv use the hardware libraries installed above
python3 -m venv --system-site-packages .venv

echo "==> 4/5 Downloading the Waveshare e-Paper driver"
if [ ! -d waveshare_epd ]; then
    TMP="$(mktemp -d)"
    # sparse checkout: only fetch the Python driver, not the whole (large) repo
    git clone --depth 1 --filter=blob:none --sparse \
        https://github.com/waveshareteam/e-Paper.git "$TMP/e-Paper"
    git -C "$TMP/e-Paper" sparse-checkout set RaspberryPi_JetsonNano/python/lib
    cp -r "$TMP/e-Paper/RaspberryPi_JetsonNano/python/lib/waveshare_epd" .
    rm -rf "$TMP"
fi

# switch the config from "preview" to the real display
sed -i 's/^driver = "preview"/driver = "waveshare"/' config.toml

echo "==> 5/5 Installing the background service (starts on boot)"
sudo tee /etc/systemd/system/flightradar.service > /dev/null <<EOF
[Unit]
Description=E-ink flight radar
After=network-online.target
Wants=network-online.target

[Service]
User=$APP_USER
WorkingDirectory=$APP_DIR
ExecStart=$APP_DIR/.venv/bin/python -m flightradar
Restart=always
RestartSec=30

[Install]
WantedBy=multi-user.target
EOF
sudo systemctl daemon-reload
sudo systemctl enable flightradar

echo
echo "Done! Next steps:"
echo "  1. Edit config.toml (your location, display model):  nano config.toml"
echo "  2. Test once:   .venv/bin/python -m flightradar --once"
echo "  3. Start:       sudo systemctl start flightradar"
echo "  Logs:           journalctl -u flightradar -f"
echo "If this was the first time enabling SPI, run 'sudo reboot' before testing."
