# PicoEnviro+ – Indoor Environment Monitor

Indoor environment monitor built on a **Raspberry Pi Pico W** and the **Pimoroni Pico Enviro+ Pack**, written in MicroPython.

It measures temperature, humidity, air pressure, gas resistance, light and sound level, shows the values on the pack's LCD and serves a live web dashboard on your home network.

*AI-assisted hobby project.*

## Contents

- [Features](#features)
- [Hardware](#hardware)
- [Installation](#installation)
- [Controls](#controls)
- [Calibration](#calibration)
- [Watchdog](#watchdog)
- [Files](#files)
- [Related project](#related-project)
- [License](#license)

## Features

- Four LCD pages: Main, Min / Max, Wi-Fi, System
- Display turns off automatically after 2 minutes of inactivity
- RGB LED shows the air quality status as a colour
- In sleep mode the LED pulses softly in the dark and stays off in brighter light
- Web dashboard with live values (updated every 5 s) and 3-hour history charts
- JSON endpoints `/data` and `/history` for use in other tools, e.g. Home Assistant
- Pressure converted to sea level using the configured altitude
- Relative air quality (IAQ) from gas resistance, with the baseline stored in flash and a 20-minute warm-up after boot
- Humidity corrected to the calibrated temperature (Magnus formula)
- Sound level from the on-board microphone
- Wi-Fi with automatic reconnect and interface reset after repeated failures
- System page with memory diagnostics, including the largest free heap block to spot fragmentation
- Optional hardware watchdog

**Note on IAQ:** The air quality value is a *relative* score based on the range of gas resistance the sensor has seen recently. It is not Bosch's BSEC IAQ index and does not measure specific gases or CO₂.

## Hardware

| Part | Details |
|---|---|
| Raspberry Pi Pico W | RP2040 with Wi-Fi |
| Pimoroni Pico Enviro+ Pack | LCD, BME688, LTR-559 light sensor, MEMS microphone, RGB LED, four buttons – [product page](https://shop.pimoroni.com/products/pico-enviro-pack?variant=40045073662035) |

The Pico plugs directly into the Enviro+ Pack, no wiring needed. Pin assignments confirmed via REPL:

| Function | Pin |
|---|---|
| I²C (BME688 at `0x77`, LTR-559) | SDA GP4, SCL GP5 |
| RGB LED | R GP6, G GP7, B GP10 |
| Microphone | ADC0 (GP26) |
| Buttons A / B / X / Y | GP12 / GP13 / GP14 / GP15 |

Note: The blue LED channel sits on GP10, not GP8 as a text extract of the schematic suggested.

All pin assignments live in [`src/config.py`](src/config.py).

## Installation

1. Flash [Pimoroni MicroPython](https://github.com/pimoroni/pimoroni-pico) for the Pico W (tested with v1.29.0-2). It provides `picographics`, `pimoroni`, `pimoroni_i2c`, `breakout_bme68x` and `breakout_ltr559`; these libraries are not part of this repository.
2. Copy everything from the [`src`](src) folder to the root of the Pico (e.g. with Thonny), no subfolders.
3. On the Pico, rename `secrets_example.py` to `secrets.py` and enter your Wi-Fi credentials:

   ```python
   WIFI_SSID = "YourNetwork"
   WIFI_PASSWORD = "YourPassword"
   WIFI_HOSTNAME = "PicoEnviro"
   WIFI_COUNTRY = "DE"   # your country code
   ```

   **Never upload your real `secrets.py` to GitHub.**
4. Restart the Pico and press **B** to turn on Wi-Fi. The web server starts automatically once connected; the IP address appears on the Wi-Fi page.
5. Open that IP address in a browser to see the dashboard.

To start Wi-Fi automatically at boot, uncomment `WIFI_AUTOSTART = True` in `config.py`.

## Controls

| Button | Action |
|---|---|
| A | single click: backlight on/off · double click: rotate display 90° (saved across reboots) |
| B | Wi-Fi and web server on/off |
| X | next page |
| Y | previous page |

## Calibration

The offsets in `config.py` apply to one specific setup and measuring interval. Recalibrate them for your own build and location.

| Setting | Current value | Meaning |
|---|---|---|
| `TEMP_OFFSET` | 5.4 | subtracted from the raw value (self-heating, mainly from the Pico with Wi-Fi) |
| `HUMIDITY_TRIM` | 0.0 | percentage points added after the Magnus correction |
| `PRESSURE_OFFSET_HPA` | -1.0 | hPa, compared against a DWD reference station |
| `ALTITUDE` | 8 | metres above sea level, for the sea-level pressure conversion |

Findings from comparison measurements:

- With the backlight on for longer than about 20 minutes, the station reads too high.
- The sensor runs on a 3-second interval; recalibrate the temperature offset at the final location.
- After moving the station, delete `iaq_baseline.txt` on the Pico (with the program stopped) so the air quality baseline starts learning again.

## Watchdog

The watchdog reboots the Pico if the main loop hangs. It is disabled by default (`WDT_TIMEOUT_MS = 0`).

**Keep it disabled while developing with Thonny.** Once started, the watchdog cannot be switched off; stopping the program in Thonny stops feeding it, the Pico resets and Thonny loses the connection. Enable it (e.g. `8000`, maximum 8388 ms on the RP2040) only when the device runs on its own.

## Files

| File | Purpose |
|---|---|
| [`main.py`](src/main.py) | Initialisation, button handling, main loop |
| [`config.py`](src/config.py) | Central settings: pins, intervals, calibration, IAQ, Wi-Fi, watchdog |
| [`sensors.py`](src/sensors.py) | Reads BME688, LTR-559 and microphone, applies calibration |
| [`iaq.py`](src/iaq.py) | Relative air quality from gas resistance (shared with the BME690 project) |
| [`history.py`](src/history.py) | 3-hour history for the charts |
| [`system.py`](src/system.py) | Pico diagnostics: memory, flash, reset cause |
| [`display.py`](src/display.py) | LCD pages and LED control |
| [`web.py`](src/web.py) | HTML dashboard, endpoints `/data` and `/history` |
| [`wifi.py`](src/wifi.py) | Wi-Fi state machine with reconnect |
| [`secrets_example.py`](src/secrets_example.py) | Template for your Wi-Fi credentials |

The station creates `iaq_baseline.txt` on the Pico by itself; it is not part of this repository.

## Related project

[BME690_Project](https://github.com/tomlahr/BME690_Project) – indoor climate station with a BME690 sensor on a Pico 2 W, sharing the same IAQ module.

## License

[MIT](LICENSE)
