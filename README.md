# Pico 2 W Weather Station

A MicroPython weather station for the Raspberry Pi Pico 2 W. It reads temperature, humidity, and pressure, serves a live dashboard on your local network, and uploads readings to [Weather Underground](https://www.wunderground.com/) every 5 minutes.

## Features

- **Live web dashboard** with temperature, humidity, sea-level pressure, and dew point, refreshed every 2 seconds
- **Weather Underground uploads** using the personal weather station (PWS) API, in imperial units
- **Sea-level pressure correction** based on your elevation, so WU doesn't show a false storm at altitude
- **Dew point calculation** (Magnus formula), shown on the dashboard and sent to WU
- **Non-blocking sensor reads**, so the web server stays responsive during DS18B20 conversions
- **Self-recovering Wi-Fi**: resets the CYW43 chip and reconnects after dropouts

## Hardware

| Part | Purpose | Pin |
|---|---|---|
| Raspberry Pi Pico 2 W | Microcontroller | |
| DS18B20 | Outdoor temperature | GP16 (1-Wire, needs a 4.7 kΩ pull-up to 3.3 V) |
| BME280 | Humidity and pressure | I2C0: SDA = GP0, SCL = GP1 |

The BME280 address (0x76 or 0x77) is detected automatically.

## Setup

1. Install MicroPython for the **Pico 2 W** from [micropython.org/download](https://micropython.org/download/).
2. Copy a BME280 driver to the Pico as `bme280.py`. The float version from [robert-hh's BME280 repo](https://github.com/robert-hh/BME280) works with this code.
3. Edit the settings at the top of `main.py`:

4. Save `main.py` to the Pico (the filename must be lowercase `main.py`) so it starts automatically on power-up.
5. Open the IP address printed in the serial output (for example `http://10.0.1.169`) in a browser.

## Weather Underground

Create a station in your WU account to get a station ID and station key. Use the **station key**, not your login password. Each Pico should have its own station ID, because two devices uploading to the same ID will overwrite each other's data.

A successful upload prints `200 OK` and `success` in the serial output.

## Notes
-**power:** the station runs on power from a plug
- **Pressure:** the BME280 measures station pressure. WU expects sea-level pressure, so the code converts it using `ELEVATION_M` and the current temperature.
- **Sensor placement:** keep the DS18B20 and BME280 in the same shaded, ventilated spot for an accurate dew point.
- **Credentials:** never commit real Wi-Fi or WU credentials. Keep them in a separate file that is listed in `.gitignore`.

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| Doesn't run on wall power | File isn't saved on the Pico, or isn't named exactly `main.py` |
| `WU Upload Failed: -2` | DNS or hostname problem |
| `401 Unauthorized` from WU | Wrong station ID or key |
| `[CYW43] core not in reset` / `EPERM` | Unplug the Pico fully for 10 seconds, then plug it back in |
| Pressure looks like a storm | `ELEVATION_M` isn't set, or WU is receiving station pressure |
