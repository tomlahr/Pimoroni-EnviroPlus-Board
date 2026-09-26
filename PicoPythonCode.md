# PicoEnviro+ Wetterstation – MicroPython-Code

Innenraum-Klimastation auf Basis des **Pimoroni Pico Enviro+ Pack (PIM635)** mit **Raspberry Pi Pico W**.
Misst Temperatur, Luftfeuchte, Luftdruck, Gaswiderstand (BME688), Helligkeit (LTR-559) und Geräuschpegel,
zeigt alles auf dem eingebauten Display und liefert ein Web-Dashboard im Heimnetz.

Stand: 26.09.2026 (Paket 2)

## Inhalt

- [Hardware und Firmware](#hardware-und-firmware)
- [Funktionen](#funktionen)
- [Installation](#installation)
- [secrets.py (Vorlage)](#secretspy-vorlage)
- [Bedienung](#bedienung)
- [Kalibrierung](#kalibrierung)
- [Dateien](#dateien)
- [Quellcode](#quellcode)

## Hardware und Firmware

- Raspberry Pi Pico W (RP2040)
- Pimoroni Pico Enviro+ Pack (PIM635): BME688, LTR-559, Mikrofon, 240×240-Display, RGB-LED, vier Tasten
- Firmware: Pimoroni MicroPython `picow v1.29.0-2` (enthält `picographics`, `breakout_bme68x`, `breakout_ltr559`)

## Funktionen

- Vier Display-Seiten, Backlight nur bei Bedarf, IAQ-Ampel über die RGB-LED
- Web-Dashboard mit Live-Werten (alle 5 s) und 3-h-Verläufen (jede Minute)
- Taupunkt, Dampfdruckdefizit (VPD), Wettertrend aus dem Luftdruck
- Relative Luftqualität mit Baseline im Flash (`iaq_baseline.txt`), 20 min Aufwärmphase nach dem Start
- Feuchte physikalisch korrigiert (Magnus-Formel) auf die kalibrierte Temperatur
- WLAN mit automatischer Wiederverbindung, z. B. nach nächtlicher Router-Zeitschaltung
- Speicherschonend: Framebuffer mit 4-Bit-Palette, `/history` wird stückweise gesendet

## Installation

1. Pimoroni-Firmware auf den Pico W flashen.
2. `secrets.py` nach der Vorlage unten anlegen.
3. Alle `.py`-Dateien aus diesem Dokument plus `secrets.py` ins Stammverzeichnis des Pico kopieren (z. B. mit Thonny).
4. Neu starten, WLAN mit **Taste B** einschalten. Die IP erscheint auf dem Display und in der REPL.

Soll das WLAN beim Start automatisch angehen, in `config.py` die Zeile `# WIFI_AUTOSTART = True` einkommentieren.

## secrets.py (Vorlage)

`secrets.py` gehört **nicht** ins Repository (in `.gitignore` eintragen).

```python
# secrets.py
WIFI_SSID = "DeinNetz"
WIFI_PASSWORD = "DeinPasswort"
WIFI_HOSTNAME = "PicoEnviroPlus"
WIFI_COUNTRY = "DE"   # optional, sonst gilt config.WIFI_COUNTRY_DEFAULT
```

## Bedienung

| Taste | Funktion |
|---|---|
| A | Backlight an/aus |
| B | WLAN und Webserver an/aus |
| X | nächste Seite |
| Y | vorige Seite |

Status auf dem Display: `ONLINE`, `LINK?` (verbindet), `OFFLINE` (per Taste aus) oder ein Fehlergrund:
`NOAP` Netz nicht gefunden, `AUTH` falsches Passwort, `FAIL` abgelehnt, `NOIP` keine IP per DHCP.

## Kalibrierung

Die Offsets gelten nur für eine bestimmte Aufstellung, Taktung und bei bestehender WLAN-Verbindung.

| Wert | Stand | Bedeutung |
|---|---|---|
| `TEMP_OFFSET` | 5.4 | wird vom Rohwert abgezogen (Eigenwärme von Pico, WLAN, Heizer) |
| `HUMIDITY_TRIM` | 0 | Feuchte folgt über Magnus automatisch |

Hinweise aus den Vergleichsmessungen (SwitchBot-Referenz):
- Ohne WLAN-Verbindung liest die Station gut 1 °C zu niedrig (Funkchip wärmt weniger).
- Direkte Sonne und warme Unterlagen (z. B. Metallmatten) verfälschen jede Messung.
- Seit Paket 2 läuft der Sensor im 3-s-Takt: Offset am endgültigen Standort neu abgleichen.

## Dateien

| Datei | Aufgabe |
|---|---|
| [`main.py`](#mainpy) | Hauptschleife: Startreihenfolge, Tasten, Takte, Zustand für Display und Web |
| [`config.py`](#configpy) | Zentrale Einstellungen: Pins, Takte, Kalibrierwerte, IAQ, WLAN |
| [`sensors.py`](#sensorspy) | BME688, LTR-559, Mikrofon, Taupunkt/VPD, IAQ-Einstufung, Selbsttest |
| [`iaq.py`](#iaqpy) | Relative Luftqualität aus dem Gaswiderstand (identisch im BME690-Projekt) |
| [`history.py`](#historypy) | 10-min-Trends und 3-h-Ringpuffer, stückweise JSON-Ausgabe |
| [`display.py`](#displaypy) | PicoGraphics-Seiten (PEN_P4) und IAQ-LED |
| [`web.py`](#webpy) | Nicht blockierender HTTP-Server: Dashboard, /data, /history |
| [`wifi.py`](#wifipy) | WLAN-Zustandsautomat mit Wiederverbindung |
| [`system.py`](#systempy) | RAM, größter Speicherblock, Flash, interne Temperatur, RSSI |

Nicht im Repository: `secrets.py`, `iaq_baseline.txt` (legt die Station selbst an).

## Quellcode

### `main.py`

Hauptschleife: Startreihenfolge, Tasten, Takte, Zustand für Display und Web (318 Zeilen)

```python
# main.py
# Bindet sensors.py, system.py, display.py, wifi.py, history.py und web.py
# zusammen. Kein time.sleep() fuer Wartezeiten - jede Wartezeit laeuft ueber
# ticks_ms()-Vergleiche; nur LOOP_SLEEP_MS bremst die Schleife bewusst ab.
#
# Speicher-Reihenfolge (Paket 1, 2026-09-23):
#   1. Display zuerst -> der 28,8-kB-Framebuffer bekommt einen sauberen,
#      zusammenhaengenden Platz auf dem noch unzerstueckelten Heap.
#   2. web erst DANACH importieren -> dessen HTML-Aufbau (inkl. Zwischen-
#      kopien) zerstueckelt den Heap nicht mehr vor dem Framebuffer.
#
# Zustand bei Bedarf: build_state() setzt das grosse Zustands-dict nur noch
# zusammen, wenn das Display neu zeichnet oder eine /data-Anfrage kommt -
# nicht mehr 100x pro Sekunde auf Vorrat.

import gc
import time
import machine
from pimoroni import Button

import config
import display


def format_uptime(boot_time):
    total = time.ticks_diff(time.ticks_ms(), boot_time) // 1000
    h, rem = divmod(total, 3600)
    m, s = divmod(rem, 60)
    return "{:02d}:{:02d}:{:02d}".format(h, m, s)


class EdgeButton:
    """Entprellter Tastendruck: feuert genau einmal pro physischem Druck,
    nicht wiederholt waehrend des Haltens. Kein time.sleep()."""

    def __init__(self, pin, debounce_ms=50):
        self.btn = Button(pin, invert=True)
        self.debounce_ms = debounce_ms
        self._was_pressed = False
        self._last_change = 0

    def pressed(self):
        now = time.ticks_ms()
        raw = self.btn.is_pressed
        if raw != self._was_pressed and \
           time.ticks_diff(now, self._last_change) > self.debounce_ms:
            self._last_change = now
            self._was_pressed = raw
            return raw  # True nur bei steigender Flanke (Tastendruck)
        return False


class MinMaxTracker:
    """Session-basiert - startet bei jedem Boot neu, wie im Display gezeigt."""

    def __init__(self):
        self._data = {}

    def update(self, key, value):
        lo, hi = self._data.get(key, (value, value))
        if value < lo:
            lo = value
        if value > hi:
            hi = value
        self._data[key] = (lo, hi)

    def as_dict(self):
        return dict(self._data)


def main():
    boot_time = time.ticks_ms()

    # 1. Framebuffer zuerst anlegen (siehe Kopfkommentar).
    scr = display.Display()
    scr.splash("Warte auf Sensoren...")

    # 2. Restliche Module erst jetzt laden - web.py baut beim Import sein HTML.
    import secrets
    import sensors
    import iaq as iaq_mod
    import system
    import wifi
    import history
    import web
    gc.collect()

    i2c = sensors.make_i2c()
    weather = sensors.Weather(i2c)
    weather.warmup()
    light = sensors.Light(i2c)
    mic = sensors.Microphone()
    itemp = sensors.InternalTemp()
    iaq = iaq_mod.IAQ()
    selftest = sensors.SelfTest()
    sysstats = system.SystemStats()
    net = wifi.WiFi()
    server = web.WebServer(config.WEB_PORT)

    btn_a = EdgeButton(config.BTN_A)  # Backlight an/aus
    btn_b = EdgeButton(config.BTN_B)  # WLAN an/aus
    btn_x = EdgeButton(config.BTN_X)  # naechste Seite
    btn_y = EdgeButton(config.BTN_Y)  # vorige Seite

    minmax = MinMaxTracker()
    hist_buf = history.History(("temp", "humidity", "pressure", "gas_kohm"),
                                config.HISTORY_LEN, config.HISTORY_INTERVAL_MS)
    trend_keys = ("temp", "humidity", "pressure", "gas_kohm")
    trends = {
        k: history.Trend(config.TREND_WINDOW_MS, config.TREND_SAMPLE_INTERVAL_MS)
        for k in trend_keys
    }

    # Statische Systemwerte einmalig ermitteln - aendern sich nicht zur Laufzeit.
    reset_cause = system.reset_cause()
    firmware = system.firmware_info()

    # Abgeleitete Werte: EINMAL pro Sensormessung berechnet, nicht pro
    # Schleifendurchlauf. build_state() und die LED lesen nur noch ab.
    w = None
    lux = None
    dew = None
    vpd = None
    iaq_label, iaq_color, iaq_score = "Aufwärmphase", "grey", None

    def sample_sensors(now):
        """Liest BME688 + LTR-559 und aktualisiert alle abgeleiteten Werte.
        Gibt False zurueck, wenn der BME688 nicht antwortet - dann bleiben
        die letzten gueltigen Werte stehen, statt die Schleife abzubrechen."""
        nonlocal w, lux, dew, vpd, iaq_label, iaq_color, iaq_score
        try:
            w = weather.read()
        except Exception:
            return False
        iaq.update(w["gas_kohm"], w["heater_stable"] and w["gas_valid"] is not False)
        selftest.update(w["heater_stable"], w["gas_valid"], w["gas_kohm"])
        lux = light.read()
        dew = sensors.dewpoint(w["temp"], w["humidity"])
        vpd = sensors.vpd_kpa(w["temp"], w["humidity"])
        iaq_score = iaq.score(w["gas_kohm"])
        iaq_label, iaq_color = sensors.iaq_classify(iaq_score)

        for key in trend_keys:
            minmax.update(key, w[key])
            trends[key].maybe_add(now, w[key])
        if lux is not None:
            minmax.update("lux", lux)
        minmax.update("dewpoint", dew)
        minmax.update("vpd_kpa", vpd)
        hist_buf.maybe_add(now, w)  # History liest nur ihre vier Keys
        return True

    # Erste echte Messung vor dem Loop, damit der erste Displayaufbau und
    # die erste Webantwort keine Platzhalter zeigen. Ohne BME688 gibt es
    # nichts Sinnvolles anzuzeigen - dann lieber sichtbar abbrechen.
    if not sample_sensors(time.ticks_ms()):
        scr.splash("BME688 antwortet nicht")
        raise RuntimeError("BME688: erste Messung fehlgeschlagen")
    db = mic.read_dbfs()
    minmax.update("db", db)
    internal_temp = itemp.read()
    flash_kb = system.flash_free_kb()
    mem_free = sysstats.sample()
    sysstats.probe_block()

    def build_state():
        """Zustand fuer Display UND Webserver - eine Quelle, aber nur noch
        auf Anfrage gebaut. Liest ausschliesslich bereits berechnete Werte;
        einzige Live-Abfrage ist die RSSI (nur, wenn wirklich jemand fragt)."""
        return {
            "temp": w["temp"],
            "humidity": w["humidity"],
            "pressure": w["pressure"],
            "gas_kohm": w["gas_kohm"],
            "lux": lux,
            "db": db,
            "humidity_desc": display.describe_humidity(w["humidity"]),
            "pressure_desc": display.describe_pressure(w["pressure"]),
            "light_desc": display.describe_light(lux),
            "sound_desc": mic.describe(db),
            "heater_stable": w["heater_stable"],
            "gas_valid": w["gas_valid"],
            "dewpoint": dew,
            "vpd_kpa": vpd,
            "iaq_label": iaq_label,
            "iaq_color": iaq_color,
            "iaq_score": iaq_score,
            "minmax": minmax.as_dict(),
            "trend": {k: trends[k].delta() for k in trend_keys},
            "uptime": format_uptime(boot_time),
            "wifi": {
                "connected": net.connected,
                "enabled": net.enabled,
                "note": net.note,
                "ip": net.ip,
                "ssid": net.ssid,
                "rssi": system.wlan_rssi(net.wlan),
                "hostname": secrets.WIFI_HOSTNAME,
            },
            "system": {
                "internal_temp": internal_temp,
                "mem_free": mem_free,
                "mem_free_min": sysstats.mem_free_min,
                "heap_block": sysstats.block,
                "heap_block_min": sysstats.block_min,
                "flash_free_kb": flash_kb,
                "reset_cause": reset_cause,
                "firmware": firmware,
                "selftest": selftest.status(),
            },
        }

    wdt = machine.WDT(timeout=config.WDT_TIMEOUT_MS) \
        if config.WDT_TIMEOUT_MS else None

    now0 = time.ticks_ms()
    last_sensor = last_mic = last_internal = last_display = 0
    last_system = last_probe = last_iaq_save = now0
    last_activity = now0
    force_draw = False
    last_server_try = now0

    # Optional: WLAN direkt einschalten (config.WIFI_AUTOSTART, standardmaessig aus)
    if getattr(config, "WIFI_AUTOSTART", False):
        net.enable()

    while True:
        if wdt:
            wdt.feed()

        a_pressed = btn_a.pressed()
        b_pressed = btn_b.pressed()
        x_pressed = btn_x.pressed()
        y_pressed = btn_y.pressed()

        if a_pressed:
            scr.toggle_backlight()
        if b_pressed:
            net.toggle()
            if not net.enabled:
                server.stop()
        if x_pressed:
            scr.next_page()
        if y_pressed:
            scr.prev_page()

        if a_pressed or b_pressed or x_pressed or y_pressed:
            last_activity = time.ticks_ms()
            # Sofort neu zeichnen statt bis zu 500 ms warten. Bewusst ein Flag
            # statt last_display = 0: ticks_ms() laeuft ueber, nach ~6 Tagen
            # waere ticks_diff(now, 0) negativ und das Display bliebe stehen.
            force_draw = True

        net_event = net.poll()
        if net_event == "down":
            server.stop()
        elif net_event == "up" or (
                net.connected and server.sock is None
                and time.ticks_diff(time.ticks_ms(), last_server_try) >= 5000):
            # Frischer Socket nach (Wieder-)Verbindung oder IP-Wechsel.
            # Zweite Bedingung: Selbstheilung alle 5 s, falls start() scheiterte.
            last_server_try = time.ticks_ms()
            try:
                server.start()
            except Exception as error:
                print("Server-Start fehlgeschlagen:", error)

        now = time.ticks_ms()

        if scr.backlight_on and time.ticks_diff(now, last_activity) >= config.AUTO_OFF_IDLE_MS:
            scr.toggle_backlight()

        if time.ticks_diff(now, last_sensor) >= config.SENSOR_INTERVAL_MS:
            last_sensor = now
            sample_sensors(now)

        if time.ticks_diff(now, last_mic) >= config.MIC_INTERVAL_MS:
            last_mic = now
            db = mic.read_dbfs()
            minmax.update("db", db)

        if time.ticks_diff(now, last_internal) >= config.INTERNAL_TEMP_INTERVAL_MS:
            last_internal = now
            internal_temp = itemp.read()

        if time.ticks_diff(now, last_system) >= config.SYSTEM_INTERVAL_MS:
            last_system = now
            mem_free = sysstats.sample()
            flash_kb = system.flash_free_kb()

        if time.ticks_diff(now, last_probe) >= config.HEAP_PROBE_INTERVAL_MS:
            last_probe = now
            sysstats.probe_block()

        if time.ticks_diff(now, last_iaq_save) >= config.IAQ_SAVE_INTERVAL_MS:
            last_iaq_save = now
            iaq.save()

        # LED jede Runde - das rosa "Atmen" braucht eine hohe Bildrate.
        scr.set_iaq_led(iaq_color, lux)

        try:
            server.poll(build_state, hist_buf)
        except Exception:
            pass

        if scr.backlight_on and (force_draw or
                time.ticks_diff(now, last_display) >= config.DISPLAY_INTERVAL_MS):
            last_display = now
            force_draw = False
            scr.draw(build_state())

        time.sleep_ms(config.LOOP_SLEEP_MS)


main()

# EOF 2026-09-26
```

### `config.py`

Zentrale Einstellungen: Pins, Takte, Kalibrierwerte, IAQ, WLAN (128 Zeilen)

```python
# config.py
# Zentrale Konfiguration. Alles, was du beim Kalibrieren oder Umbauen anfasst,
# steht hier - nicht verstreut im Code.

# ── I2C (BME688 + LTR-559) ────────────────────────────────
# Enviro+ Pack: Breakout-Garden-Bus auf GP4/GP5.
I2C_SDA = 4
I2C_SCL = 5
BME_ADDRESS = 0x77
# Angeglichen an das BME690-Projekt (2026-09-xx), um die Gaswiderstands-
# Charakteristik zwischen beiden Geraeten vergleichbarer zu machen.
# Bibliotheks-Default waere 300 C / 100 ms - bewusst abweichend gesetzt.
BME_HEATER_TEMP_C = 320
BME_HEATER_DURATION_MS = 150
# LTR-559 hat eine feste Adresse und wird vom Treiber selbst gesetzt.

# ── Mikrofon ──────────────────────────────────────────────
# Analoges MEMS-Mic. Laut Enviro+-Schaltplan liegt MIC_OUT auf ADC0 = GP26 (bestaetigt).
MIC_ADC_PIN = 26
MIC_SAMPLES = 512        # Samples pro Pegelmessung (Burst)
# sensors.py rechnet mit den echten 12-Bit-ADC-Werten (read_u16() >> 4),
# damit die RMS-Berechnung mit Ganzzahlen statt Heap-Floats auskommt.
# Vollausschlag daher 2048 statt 32768 - dBFS-Werte bleiben praktisch gleich.
MIC_FULLSCALE = 2048     # halber 12-Bit-ADC-Hub (0..4095)
MIC_DB_TRIM = 0.0        # optionaler Offset in dB, rein kosmetisch

# ── RGB-LED (oben mittig am LCD) ──────────────────────────
LED_R = 6
LED_G = 7
LED_B = 10               # per REPL-Test bestaetigt (nicht GP8 - die PDF-Text-
                          # extraktion des Schaltplans hatte hier geirrt)
LED_INVERT = True        # gemeinsame Anode -> invertiert ansteuern
LED_IAQ_BRIGHTNESS = 40  # 0..255, bewusst gedimmt fuer den IAQ-Status
SLEEP_LED_COLOR = (255, 182, 193)  # sanftrosa (light pink)
SLEEP_LED_PEAK = 15                # 0..255 - deutlich unter LED_IAQ_BRIGHTNESS
SLEEP_LED_PERIOD_MS = 4000         # eine volle Ein-/Ausatmung
# Ab hier gilt's als "hell genug" - LED komplett aus statt Pulsieren.
# Bewusst dieselbe Grenze wie describe_light()'s "dunkel"-Kategorie (<50 Lux).
LED_NIGHT_LUX_THRESHOLD = 50

# ── Buttons ───────────────────────────────────────────────
BTN_A = 12   # Backlight an/aus
BTN_B = 13   # WLAN/Webserver an/aus (mit LINK-Check)
BTN_X = 14   # naechste Seite
BTN_Y = 15   # vorige Seite

# ── Display ───────────────────────────────────────────────
BRIGHTNESS = 0.8         # Backlight-Helligkeit 0.0..1.0

# ── Kalibrierung Klima ────────────────────────────────────
# TEMP_OFFSET wird vom Rohwert ABGEZOGEN (Sensor liest durch Eigenwaerme zu hoch).
# Ein einziger Wert (Kalibrierpaket 2026-09-24): Die Hauptwaerme kommt vom
# gesockelten Pico (CPU + WLAN, Powersave aus) und bleibt konstant. Das
# Backlight laeuft nur kurz nach Neustart bzw. beim Nachsehen; die fruehere
# ON/OFF-Umschaltung sprang sofort, waehrend die Waerme sich ueber Minuten
# aendert, und erzeugte dadurch groessere Fehler als ein fester Wert.
# Abgleich 23./24.09. gegen SwitchBot (Fensterbank) und Wandsensor:
# +0.8/+1.0/+1.3 bzw. +1.2/+1.2/+0.8 C ueber altem OFF-Wert 4.35.
# Bei laengerem Backlight-Betrieb (>~20 min) liest das Geraet zu hoch.
TEMP_OFFSET = 5.4
# Feuchte wird physikalisch ueber Magnus auf die korrigierte Temperatur zurueckgerechnet
# (siehe sensors.py). HUMIDITY_TRIM ist nur die letzte empirische Feinjustage
# gegen dein Referenzgeraet (SwitchBot/Enviro+), additiv in %-Punkten.
HUMIDITY_TRIM = 0.0
# Hoehe ueber NN in Metern, fuer die Umrechnung auf Meeresspiegeldruck.
ALTITUDE = 8
# DWD-Vergleich (2026-09-xx): Enviro+ zeigte 1014 hPa bei 1013 hPa Referenz -> zu hoch.
PRESSURE_OFFSET_HPA = -1.0

# ── Idealbereiche fuer Ampel-Faerbung (nur Dashboard) ─────
# Innerhalb -> gruen, ausserhalb -> neutral/gelb.
TEMP_IDEAL = (20.0, 24.0)
HUMIDITY_IDEAL = (40.0, 60.0)
# Druck hat KEINEN Idealbereich - bewusst keine Ampel, Bewertung ueber Wettertrend.

# ── Relative IAQ-Baseline (Gaswiderstand) ─────────────────
# Paket 2: gemeinsames Modul iaq.py (identisch beim BME690).
IAQ_HALFLIFE_H = 6.0          # Huellkurven vergessen alte Extremwerte mit dieser Halbwertszeit
IAQ_MIN_RATIO = 2.0           # Mindestspanne hi/lo; gleichbleibende Luft zeigt "gut"
IAQ_WARMUP_S = 1200           # 20 min nach Start: Heizer kalt, Werte unbrauchbar -> "Aufwärmphase"
IAQ_BASELINE_FILE = "iaq_baseline.txt"
# Score-Schwellen (0..1) fuer Label + LED-Farbe.
IAQ_GOOD = 0.66
IAQ_OK = 0.33

# ── Verlauf (Sparklines) ──────────────────────────────────
HISTORY_LEN = 180            # Punkte; 180 x 60 s = 3 h
HISTORY_INTERVAL_MS = 60000  # ein Verlaufspunkt pro Minute

# ── Takt-Intervalle (nicht blockierend) ───────────────────
SENSOR_INTERVAL_MS = 3000    # BME/LTR lesen (Paket 2: 3 s statt 1 s -> weniger Heizerwaerme)
LOOP_SLEEP_MS = 10           # Bremse pro Schleifendurchlauf - fehlte bisher
AUTO_OFF_IDLE_MS = 2 * 60 * 1000   # Display automatisch aus nach 2 Min. Inaktivitaet
MIC_INTERVAL_MS = 500        # Pegel messen (laufend - Display UND Web zeigen ihn)
DISPLAY_INTERVAL_MS = 500    # Bildschirm neu zeichnen
INTERNAL_TEMP_INTERVAL_MS = 10000  # interne Pico-Temp, langsam wechselnd
SYSTEM_INTERVAL_MS = 2000    # RAM/Flash-Abfrage (statvfs kostet etwas)
# Groesster zusammenhaengender freier Heap-Block. Die Sonde loest bei jedem
# Fehlversuch intern eine Garbage Collection aus - deshalb seltener als RAM.
HEAP_PROBE_INTERVAL_MS = 10000
IAQ_SAVE_INTERVAL_MS = 300000  # Baseline alle 5 min auf Flash sichern
TREND_WINDOW_MS = 600000     # 10 min Fenster fuer "+x / 10 min"-Deltas
TREND_SAMPLE_INTERVAL_MS = 30000  # Trend-Snapshot alle 30 s (20 Punkte / 10 min)

# ── Webserver ─────────────────────────────────────────────
WEB_PORT = 80

# WLAN-Verhalten (gleiche Werte wie beim BME690)
WIFI_CHECK_MS = 1000       # Linkpruefung hoechstens so oft
WIFI_RETRY_MS = 15000      # ohne Verbindung: neuer Versuch nach dieser Zeit
WIFI_RESET_AFTER = 3       # nach so vielen Fehlversuchen Schnittstelle neu starten
WIFI_COUNTRY_DEFAULT = "DE"  # falls secrets.WIFI_COUNTRY fehlt
# WLAN beim Start automatisch einschalten (wie beim BME690).
# Auskommentiert = WLAN startet aus, Taste B schaltet ein.
# WIFI_AUTOSTART = True
WEB_REFRESH_S = 5            # Auto-Reload der Messwerte im Browser
WEB_CHART_REFRESH_S = 60     # Auto-Reload der Diagramme

# ── Watchdog ──────────────────────────────────────────────
# Rebootet den Pico automatisch, falls sich die Hauptschleife aufhaengt.
# 0 = deaktiviert. Max. 8388 ms auf dem RP2040.
# WAEHREND DER ENTWICKLUNG MIT THONNY AUF 0 LASSEN: einmal erzeugt, laesst
# sich der WDT nicht mehr abschalten - "Stop" in Thonny fuettert ihn nicht
# mehr, nach TIMEOUT resettet er den Chip und Thonny meldet Verbindungsverlust.
# Erst scharf schalten (z.B. 8000), wenn das Geraet eigenstaendig laeuft.
WDT_TIMEOUT_MS = 0

# EOF 2026-09-26
```

### `sensors.py`

BME688, LTR-559, Mikrofon, Taupunkt/VPD, IAQ-Einstufung, Selbsttest (241 Zeilen)

```python
# sensors.py
# Sensorschicht. Jeder Sensor kapselt sein Lesen und liefert saubere Werte
# als dict oder Zahl zurueck - kein Tupel-Entpacken mehr im Hauptcode.

import math
import machine
from machine import ADC
from pimoroni_i2c import PimoroniI2C
from breakout_bme68x import (
    BreakoutBME68X, STATUS_HEATER_STABLE,
    FILTER_COEFF_3, STANDBY_TIME_1000_MS,
    OVERSAMPLING_1X, OVERSAMPLING_2X, OVERSAMPLING_16X,
)
try:
    from breakout_bme68x import STATUS_GAS_VALID
    _HAS_GAS_VALID = True
except ImportError:
    STATUS_GAS_VALID = 0
    _HAS_GAS_VALID = False
from breakout_ltr559 import BreakoutLTR559

import config


def make_i2c():
    """Einen I2C-Bus fuer BME688 und LTR-559 erzeugen."""
    return PimoroniI2C(sda=config.I2C_SDA, scl=config.I2C_SCL)


def saturation_vapor_pressure(t):
    """Saettigungsdampfdruck nach Magnus in hPa."""
    return 6.112 * math.exp((17.62 * t) / (243.12 + t))


def dewpoint(temp_c, humidity_pct):
    """Taupunkt in C - invertierte Magnus-Formel."""
    rh = max(0.1, min(100.0, humidity_pct))
    e = (rh / 100.0) * saturation_vapor_pressure(temp_c)
    ln_ratio = math.log(e / 6.112)
    return (243.12 * ln_ratio) / (17.62 - ln_ratio)


def vpd_kpa(temp_c, humidity_pct):
    """Vapor Pressure Deficit in kPa - gebraeuchliche Einheit im Pflanzenbau."""
    es = saturation_vapor_pressure(temp_c)
    e = (humidity_pct / 100.0) * es
    return (es - e) / 10.0  # hPa -> kPa


# ══════════════════════════════════════════════════════════
#  BME688: Temperatur, Druck, Feuchte, Gas
# ══════════════════════════════════════════════════════════
class Weather:
    def __init__(self, i2c):
        self.bme = BreakoutBME68X(i2c, address=config.BME_ADDRESS)
        self.bme.configure(
            FILTER_COEFF_3, STANDBY_TIME_1000_MS,
            OVERSAMPLING_1X, OVERSAMPLING_2X, OVERSAMPLING_16X,
        )
        self.temp_offset = config.TEMP_OFFSET
        self.humidity_trim = config.HUMIDITY_TRIM
        self.altitude = config.ALTITUDE

    def warmup(self, reads=3, delay_ms=500):
        """Erste Messungen verwerfen - der Heizer braucht ein paar Zyklen."""
        import time
        for _ in range(reads):
            try:
                self.bme.read(
                    heater_temp=config.BME_HEATER_TEMP_C,
                    heater_duration=config.BME_HEATER_DURATION_MS,
                )
            except Exception:
                pass
            time.sleep_ms(delay_ms)

    def _correct_humidity(self, t_raw, rh_raw, t_corr):
        # Absolute Feuchte bleibt gleich; nur die relative Feuchte wird auf die
        # korrigierte (kuehlere) Temperatur zurueckgerechnet. Kein additiver Pfusch.
        rh = rh_raw * saturation_vapor_pressure(t_raw) / saturation_vapor_pressure(t_corr)
        rh += self.humidity_trim
        if rh > 100.0:
            rh = 100.0
        if rh < 0.0:
            rh = 0.0
        return rh

    def _sea_level(self, p_hpa, t):
        a = self.altitude
        return p_hpa + ((p_hpa * 9.80665 * a) / (287 * (273 + t + (a / 400))))

    def read(self):
        t, p, h, g, status, _, _ = self.bme.read(
            heater_temp=config.BME_HEATER_TEMP_C,
            heater_duration=config.BME_HEATER_DURATION_MS,
        )
        heater_stable = bool(status & STATUS_HEATER_STABLE)
        gas_valid = bool(status & STATUS_GAS_VALID) if _HAS_GAS_VALID else None

        t_corr = t - self.temp_offset
        return {
            "temp": t_corr,
            "temp_raw": t,
            "pressure": self._sea_level(p / 100.0, t_corr) + config.PRESSURE_OFFSET_HPA,
            "humidity": self._correct_humidity(t, h, t_corr),
            "humidity_raw": h,
            "gas_kohm": g / 1000.0,
            "heater_stable": heater_stable,
            "gas_valid": gas_valid,
        }


# ══════════════════════════════════════════════════════════
#  LTR-559: Umgebungslicht
# ══════════════════════════════════════════════════════════
class Light:
    def __init__(self, i2c):
        self.ltr = BreakoutLTR559(i2c)

    def read(self):
        r = self.ltr.get_reading()
        if r is None:
            return None
        return r[BreakoutLTR559.LUX]


# ══════════════════════════════════════════════════════════
#  Mikrofon: relativer Pegel in dBFS (0 dB = ADC-Vollausschlag)
#  Kein kalibrierter Schalldruck - bewusst als "rel." beschriftet.
# ══════════════════════════════════════════════════════════
class Microphone:
    def __init__(self):
        from array import array
        self.adc = ADC(config.MIC_ADC_PIN)
        self.n = config.MIC_SAMPLES
        self.buf = array("H", (0 for _ in range(self.n)))
        self.fullscale = config.MIC_FULLSCALE
        self.trim = config.MIC_DB_TRIM

    def read_dbfs(self):
        # Reine Ganzzahl-Rechnung: Auf dem RP2040 legt MicroPython jede Float
        # als eigenes Heap-Objekt an. Die alte Float-Schleife erzeugte pro
        # Aufruf ~1.500 Objekte (~24 kB Muell, 2x pro Sekunde) - ein
        # Hauptverdaechtiger fuer die Heap-Fragmentierung.
        # read_u16() liefert den 12-Bit-Rohwert, auf 16 Bit hochskaliert;
        # >> 4 holt den Rohwert verlustfrei zurueck.
        buf = self.buf
        adc = self.adc
        n = self.n
        for i in range(n):
            buf[i] = adc.read_u16() >> 4

        mean = (sum(buf) + n // 2) // n   # gerundet statt abgeschnitten
        sq = 0
        for v in buf:
            d = v - mean
            sq += d * d
        rms = math.sqrt(sq / n)
        # Untergrenze = alte Grenze (1 von 32768) im neuen Massstab.
        if rms < 0.0625:
            rms = 0.0625
        return 20.0 * math.log10(rms / self.fullscale) + self.trim

    def describe(self, dbfs):
        if dbfs < -50:
            return "leise"
        elif dbfs < -25:
            return "normal"
        else:
            return "laut"


# ══════════════════════════════════════════════════════════
#  Interne RP2040-Temperatur (ADC-Kanal 4)
#  Grober Indikator - liest durch Eigenerwaermung zu hoch.
#  Teilt sich den ADC mit dem Mic: nur lesen, wenn kein Mic-Sampling laeuft.
# ══════════════════════════════════════════════════════════
class InternalTemp:
    def __init__(self):
        self.adc = ADC(4)

    def read(self):
        volt = self.adc.read_u16() * 3.3 / 65535.0
        return 27.0 - (volt - 0.706) / 0.001721


# ══════════════════════════════════════════════════════════
#  Relative IAQ-Baseline
#  Gleitendes Min/Max des Gaswiderstands mit langsamem Zerfall.
#  Update nur bei stabilem Heizer UND gueltigem Gaswert.
#  Baseline ueberlebt Reboot (Flash).
# ══════════════════════════════════════════════════════════
# ══════════════════════════════════════════════════════════
#  Selbsttest-Naeherung
#  Boschs eigener Selbsttest prueft den internen Heizstrom-Regelwert
#  (idac) - der ist ueber diese Bibliothek nicht zugaenglich (bestaetigt:
#  bme.read() liefert 7 Werte, keiner davon idac). Diese Klasse prueft
#  stattdessen ueber mehrere Zyklen: Heizer stabil, Gaswert vom Sensor
#  als gueltig markiert, und der kOhm-Wert in einer plausiblen Spanne
#  (faengt einen offenen/kurzgeschlossenen Heizwiderstand ab, auch ohne
#  Zugriff auf idac).
# ══════════════════════════════════════════════════════════
class SelfTest:
    def __init__(self, window=5, gas_min_kohm=0.5, gas_max_kohm=5000.0):
        self.window = window
        self.gas_min = gas_min_kohm
        self.gas_max = gas_max_kohm
        self._results = []

    def update(self, heater_stable, gas_valid, gas_kohm):
        plausible = self.gas_min <= gas_kohm <= self.gas_max
        ok = bool(heater_stable) and plausible and (gas_valid is not False)
        self._results.append(ok)
        if len(self._results) > self.window:
            self._results.pop(0)

    @property
    def ready(self):
        return len(self._results) >= self.window

    def status(self):
        """(label, ok) - ok ist True/False/None (None = noch nicht genug Zyklen)."""
        if not self.ready:
            return "prüft...", None
        if all(self._results):
            return "OK", True
        return "Fehler", False


def iaq_classify(score):
    """(label, color_key) aus dem Score von iaq.IAQ.
    color_key: 'green' | 'yellow' | 'red' | 'grey'."""
    if score is None:
        return ("Aufwärmphase", "grey")
    if score >= config.IAQ_GOOD:
        return ("gute Luftqualität", "green")
    if score >= config.IAQ_OK:
        return ("mäßige Qualität", "yellow")
    return ("schlechte Luft", "red")

# EOF 2026-09-26
```

### `iaq.py`

Relative Luftqualität aus dem Gaswiderstand (identisch im BME690-Projekt) (112 Zeilen)

```python
# iaq.py
# Relative Luftqualitaet aus dem Gaswiderstand (BME688/BME690).
# Paket 2 (2026-09-26): gemeinsames Modul fuer Enviro+ und BME690 - beide
# Projekte enthalten diese Datei identisch.
#
# Prinzip: Zwei Huellkurven ueber den Gaswiderstand.
#   hi = "saubere Luft"   (hoechster Wert der juengeren Vergangenheit)
#   lo = "belastete Luft" (niedrigster Wert der juengeren Vergangenheit)
# Score = Lage des aktuellen Werts zwischen lo und hi, logarithmisch
# (Gaswiderstand faellt bei Belastung etwa exponentiell), 0.0 .. 1.0.
#
# Unterschiede zur alten Logik:
#   - Zerfall nach ZEIT (Halbwertszeit in Stunden), nicht pro Messung -
#     der Messtakt spielt keine Rolle mehr.
#   - Mindestspanne als Verhaeltnis hi/lo >= IAQ_MIN_RATIO. Reicht die
#     beobachtete Spanne nicht, wird lo abgesenkt, hi bleibt: gleichbleibend
#     gute Luft zeigt "gut" statt "kalibriert...".
#   - Sperrfrist nach dem Start (IAQ_WARMUP_S): der kalte Heizer liefert
#     anfangs zu niedrige Werte, die frueher die Baseline verdarben.
#   - Baseline auf Flash (IAQ_BASELINE_FILE, Format "lo,hi"), kompatibel
#     mit der bisherigen iaq_baseline.txt des Enviro+.

import math
import time

import config

_MAX_DT_S = 60      # Luecken (z. B. Sensorfehler) zaehlen hoechstens so lange


class IAQ:
    def __init__(self):
        self.ratio = config.IAQ_MIN_RATIO
        self.halflife_s = config.IAQ_HALFLIFE_H * 3600
        self.warmup_ms = config.IAQ_WARMUP_S * 1000
        self.file = config.IAQ_BASELINE_FILE
        self.lo = None
        self.hi = None
        self._t_start = time.ticks_ms()
        self._t_last = None
        self._load()

    # --- Flash --------------------------------------------------------------

    def _load(self):
        try:
            with open(self.file) as f:
                lo, hi = f.read().split(",")
            lo, hi = float(lo), float(hi)
            if 0 < lo < hi:
                self.lo, self.hi = lo, hi
                self._enforce_ratio()
        except Exception:
            self.lo = self.hi = None

    def save(self):
        if self.lo is None:
            return
        try:
            with open(self.file, "w") as f:
                f.write("{:.1f},{:.1f}".format(self.lo, self.hi))
        except Exception:
            pass

    # --- Lernen -------------------------------------------------------------

    def _enforce_ratio(self):
        if self.hi / self.lo < self.ratio:
            self.lo = self.hi / self.ratio

    @property
    def warming_up(self):
        return time.ticks_diff(time.ticks_ms(), self._t_start) < self.warmup_ms

    def update(self, gas_kohm, valid):
        """Nach jeder Messung aufrufen. valid: Gaswert gueltig und Heizer
        stabil (beide Statusbits)."""
        now = time.ticks_ms()
        last, self._t_last = self._t_last, now
        if self.warming_up or not valid or gas_kohm is None or gas_kohm <= 0:
            return
        if self.lo is None:
            self.hi = gas_kohm
            self.lo = gas_kohm / self.ratio
            return
        dt = _MAX_DT_S if last is None else min(time.ticks_diff(now, last) / 1000, _MAX_DT_S)
        keep = math.exp(-0.6931 * dt / self.halflife_s)   # 0.5 ** (dt / T_half)
        # Huellkurven: neuer Extremwert sofort, sonst langsam zum Messwert hin.
        if gas_kohm >= self.hi:
            self.hi = gas_kohm
        else:
            self.hi = gas_kohm + (self.hi - gas_kohm) * keep
        if gas_kohm <= self.lo:
            self.lo = gas_kohm
        else:
            self.lo = gas_kohm + (self.lo - gas_kohm) * keep
        self._enforce_ratio()

    # --- Auswerten ----------------------------------------------------------

    @property
    def ready(self):
        return self.lo is not None and not self.warming_up

    def score(self, gas_kohm):
        """0.0 (belastet) .. 1.0 (sauber) oder None (Aufwaermphase/ohne Daten)."""
        if not self.ready or gas_kohm is None or gas_kohm <= 0:
            return None
        s = math.log(gas_kohm / self.lo) / math.log(self.hi / self.lo)
        return 0.0 if s < 0.0 else (1.0 if s > 1.0 else s)

# EOF 2026-09-26
```

### `history.py`

10-min-Trends und 3-h-Ringpuffer, stückweise JSON-Ausgabe (85 Zeilen)

```python
# history.py
# Zeitreihen-Verwaltung fuer main.py: kurze Trend-Deltas ("+0.3 C / 10 min")
# und der lange Ringpuffer fuer die Web-Sparklines. Getrennt von sensors.py,
# weil das hier reine Zeitverwaltung ist, keine Messung.

import time
from array import array


class Trend:
    """Delta zum aeltesten Punkt im Zeitfenster."""

    def __init__(self, window_ms, sample_ms):
        self.window_ms = window_ms
        self.sample_ms = sample_ms
        self._times = []
        self._values = []
        self._last_sample = 0

    def maybe_add(self, now, value):
        if self._times and time.ticks_diff(now, self._last_sample) < self.sample_ms:
            return
        self._last_sample = now
        self._times.append(now)
        self._values.append(value)
        while self._times and time.ticks_diff(now, self._times[0]) > self.window_ms:
            self._times.pop(0)
            self._values.pop(0)

    def delta(self):
        if len(self._values) < 2:
            return None
        span = time.ticks_diff(self._times[-1], self._times[0])
        if span < self.window_ms * 0.9:
            # Fenster noch nicht voll genug - sonst zeigt "/ 10 min" einen
            # Wert, der in Wirklichkeit nur ueber ein paar Sekunden/Minuten
            # gemessen wurde (z.B. direkt nach dem Boot).
            return None
        return self._values[-1] - self._values[0]


class History:
    """Ringpuffer je Messreihe. array('f') statt Listen - spart RAM
    (4 Werte x HISTORY_LEN Punkte x 4 Byte statt Python-Objekt-Overhead)."""

    def __init__(self, keys, length, interval_ms):
        self.length = length
        self.interval_ms = interval_ms
        self.keys = keys
        self._buf = {k: array("f", (0.0 for _ in range(length))) for k in keys}
        self._count = 0
        self._head = 0
        self._last_sample = 0

    def maybe_add(self, now, values):
        if self._count and time.ticks_diff(now, self._last_sample) < self.interval_ms:
            return
        self._last_sample = now
        for k in self.keys:
            self._buf[k][self._head] = values[k]
        self._head = (self._head + 1) % self.length
        if self._count < self.length:
            self._count += 1

    def iter_json(self, key, decimals=1, per=20):
        """Paket 2: wie series_json(), aber in kleinen Stuecken (je `per`
        Werte, ca. 100-150 Byte). web.py sendet jedes Stueck sofort - der
        groesste zusammenhaengende Speicherblock fuer /history sinkt von
        rund 3-4 kB (plus Kopie) auf wenige hundert Byte. Das entschaerft
        die Heap-Fragmentierung ("Block min" 4,8 kB am 24.09.)."""
        fmt = "{:." + str(decimals) + "f}"
        buf = self._buf[key]
        n = self._count
        start = self._head if n == self.length else 0
        yield "["
        i = 0
        while i < n:
            end = min(i + per, n)
            part = ",".join(fmt.format(buf[(start + j) % self.length])
                            for j in range(i, end))
            yield part if i == 0 else "," + part
            i = end
        yield "]"

# EOF 2026-09-26
```

### `display.py`

PicoGraphics-Seiten (PEN_P4) und IAQ-LED (350 Zeilen)

```python
# display.py
# Zeichnet die vier Seiten und steuert die IAQ-LED. Kennt keine Sensor- oder
# Netzwerk-Interna - main.py fuellt pro Zyklus ein "data"-dict mit diesen Keys:
#
#   temp, humidity, pressure, gas_kohm          -> float
#   lux                                          -> float oder None
#   db                                            -> float (dBFS)
#   humidity_desc, pressure_desc, light_desc,
#   sound_desc                                    -> str (Praesentationslabel)
#   iaq_label, iaq_color                          -> str ("green"/"yellow"/"red"/"grey")
#   minmax: {"temp": (min,max), "humidity": ..., "pressure": ..., "gas_kohm": ...,
#            "lux": ..., "db": ...}
#   uptime                                        -> str "hh:mm:ss"
#   wifi: {"connected": bool, "ip": str, "ssid": str, "rssi": int|None,
#          "hostname": str}
#   system: {"internal_temp": float|None, "mem_free": int, "mem_free_min": int,
#            "flash_free_kb": int|None, "reset_cause": str, "firmware": str,
#            "heap_block": int|None, "heap_block_min": int|None}
#
# Main-Screen zeigt nur Uptime + Kurzstatus; Details leben auf den drei
# Unterseiten - das war noetig, um die Sound-Zeile ohne Ueberlauf unterzubringen.
#
# Schriftgroessen: "bitmap8" skaliert nur in ganzen Schritten (1, 2, 3 ...) -
# Bruchteile darunter rundeten bisher unbemerkt auf 1 ab. Feste Hierarchie
# jetzt: scale=2 fuer Werte/Titel, scale=1 fuer Labels/Beschreibungen/Fusszeile.
# Bitmap-Schrift zeichnet oben-links (keine Grundlinien-Ueberstand wie bei der
# fruaeheren Vektorschrift "sans") - deshalb reichen kleine y-Werte jetzt aus,
# die alte "13x scale"-Clipping-Regel entfaellt.
#
# Framebuffer: PEN_P4 (16-Farben-Palette) statt des Enviro+-Defaults
# PEN_RGB332. Halbiert den Puffer von 57.600 auf 28.800 Bytes - der Puffer
# liegt auf dem MicroPython-Heap. Grenze: maximal 16 Pens. create_pen()
# wirft ValueError, sobald die Palette voll ist -> Pens NUR in _make_pens()
# anlegen, nie in einer Zeichenroutine.
#
# Bitmap-Fonts kennen "°" und "äöüÄÖÜß" (Pimoroni-Mapping in
# unicode_sorta.hpp). "·", "µ", "±" erscheinen dagegen als Leerzeichen.

from picographics import PicoGraphics, DISPLAY_ENVIRO_PLUS, PEN_P4
from pimoroni import RGBLED
import time
import math

import config

PAGE_MAIN, PAGE_MINMAX, PAGE_WLAN, PAGE_SYSTEM = range(4)
PAGE_COUNT = 4

_IAQ_LED_RGB = {
    "green": (0, 255, 0),
    "yellow": (255, 180, 0),
    "red": (255, 0, 0),
    "grey": (80, 80, 80),
}

HEADER_BAND_H = 36  # gruene Flaeche im Header
HEADER_H = 42       # ab hier beginnt die erste Zeile
ROW_H = 34          # Hauptbildschirm-Zeilen
ROW2_H = 32         # Zeilen auf Min/Max-, WLAN-, System-Seite
FOOTER_Y = 226


def describe_humidity(rh):
    lo, hi = config.HUMIDITY_IDEAL
    return "angenehm" if lo < rh < hi else "unausgeglichen"


def describe_pressure(hpa):
    if hpa < 970:
        return "Sturm"
    elif hpa < 990:
        return "Regen"
    elif hpa < 1010:
        return "Veränderlich"
    elif hpa < 1030:
        return "Schön"
    else:
        return "Beständig"


def describe_light(lux):
    if lux is None:
        return "keine Daten"
    if lux < 50:
        return "dunkel"
    elif lux < 100:
        return "gedämpft"
    elif lux < 500:
        return "hell"
    else:
        return "sehr hell"



def wifi_status_text(wifi):
    """ONLINE / Fehler-Kurztext (NOAP, AUTH ...) bzw. LINK? / OFFLINE."""
    if wifi.get("connected"):
        return "ONLINE"
    if not wifi.get("enabled", True):
        return "OFFLINE"
    return wifi.get("note") or "LINK?"

class Display:
    def __init__(self):
        self.gfx = PicoGraphics(display=DISPLAY_ENVIRO_PLUS, rotate=0,
                                pen_type=PEN_P4)
        self.led = RGBLED(config.LED_R, config.LED_G, config.LED_B,
                           invert=config.LED_INVERT)
        self.width, self.height = self.gfx.get_bounds()
        self.gfx.set_font("bitmap8")
        self._make_pens()

        self.backlight_on = True
        self.gfx.set_backlight(config.BRIGHTNESS)
        self.page = PAGE_MAIN

    def _make_pens(self):
        g = self.gfx
        self.WHITE = g.create_pen(255, 255, 255)
        self.BLACK = g.create_pen(0, 0, 0)
        self.RED = g.create_pen(255, 70, 70)
        self.GREEN = g.create_pen(90, 220, 130)
        self.CYAN = g.create_pen(90, 200, 255)
        self.YELLOW = g.create_pen(230, 190, 40)
        self.GREY = g.create_pen(150, 150, 150)
        self.DARKGREY = g.create_pen(60, 60, 66)
        self.LIGHTGREY = self.GREY  # war farbgleich - spart einen Palettenplatz
        self.FOOTER_GREY = g.create_pen(210, 210, 210)
        self.HEADER_BG = g.create_pen(15, 40, 28)
        self._iaq_pen = {
            "green": self.GREEN, "yellow": self.YELLOW,
            "red": self.RED, "grey": self.GREY,
        }
        # Belegt: 10 von 16 Palettenplaetzen.

    # ── Steuerung ─────────────────────────────────────────
    def toggle_backlight(self):
        self.backlight_on = not self.backlight_on
        self.gfx.set_backlight(config.BRIGHTNESS if self.backlight_on else 0)

    def next_page(self):
        self.page = (self.page + 1) % PAGE_COUNT

    def prev_page(self):
        self.page = (self.page - 1) % PAGE_COUNT

    def set_iaq_led(self, color_key, lux=None):
        if not self.backlight_on:
            if lux is not None and lux >= config.LED_NIGHT_LUX_THRESHOLD:
                # Hell genug (Tageslicht/Raumbeleuchtung) - kein Pulsieren noetig,
                # komplett aus statt einer Anzeige, die im Hellen ohnehin
                # unauffaellig waere.
                self.led.set_rgb(0, 0, 0)
                return
            # "Lebt noch"-Signal statt komplett dunkel - sanftes rosa Pulsieren,
            # bewusst keine der vier IAQ-Farben (Verwechslungsgefahr mit
            # "kalibriert gerade"). Weicher Ein-/Ausklang per Kosinus statt
            # linearem Auf/Ab, damit es nicht wie ein Blinken wirkt.
            phase = (time.ticks_ms() % config.SLEEP_LED_PERIOD_MS) / config.SLEEP_LED_PERIOD_MS
            brightness = (1 - math.cos(2 * math.pi * phase)) / 2  # 0..1
            pr, pg, pb = config.SLEEP_LED_COLOR
            scale = brightness * (config.SLEEP_LED_PEAK / 255.0)
            self.led.set_rgb(int(pr * scale), int(pg * scale), int(pb * scale))
            return
        r, g, b = _IAQ_LED_RGB.get(color_key, _IAQ_LED_RGB["grey"])
        scale = config.LED_IAQ_BRIGHTNESS / 255.0
        self.led.set_rgb(int(r * scale), int(g * scale), int(b * scale))

    def splash(self, text):
        g = self.gfx
        g.set_pen(self.BLACK)
        g.clear()
        g.set_pen(self.RED)
        g.text(text, 4, 4, self.width, scale=1)
        g.update()

    # ── Zeichnen ──────────────────────────────────────────
    def draw(self, data):
        if not self.backlight_on:
            return
        g = self.gfx
        g.set_pen(self.BLACK)
        g.clear()
        if self.page == PAGE_MAIN:
            self._draw_main(data)
        elif self.page == PAGE_MINMAX:
            self._draw_minmax(data)
        elif self.page == PAGE_WLAN:
            self._draw_wlan(data)
        else:
            self._draw_system(data)
        g.update()

    def _row(self, y, value_text, desc_text, value_pen):
        g = self.gfx
        g.set_pen(value_pen)
        g.text(value_text, 4, y, self.width, scale=2)
        g.set_pen(self.WHITE)
        g.text(desc_text, 4, y + 18, self.width, scale=1)
        g.set_pen(self.DARKGREY)
        g.line(4, y + ROW_H - 4, self.width - 4, y + ROW_H - 4)

    def _draw_main(self, data):
        g = self.gfx
        g.set_pen(self.HEADER_BG)
        g.rectangle(0, 0, self.width, HEADER_BAND_H)

        temp = data.get("temp", 0.0)
        lo, hi = config.TEMP_IDEAL
        temp_pen = self.GREEN if lo <= temp <= hi else (
            self.RED if temp > hi else self.CYAN)

        g.set_pen(temp_pen)
        g.set_font("bitmap14_outline")
        g.text("{:.1f}°C".format(temp), 4, 4, self.width, scale=2)
        g.set_font("bitmap8")

        tmin, tmax = data.get("minmax", {}).get("temp", (None, None))
        if tmin is not None:
            g.set_font("bitmap6")
            g.set_pen(self.RED)
            g.text("max {:.1f}".format(tmax), 135, 2, self.width, scale=2)
            g.set_pen(self.CYAN)
            g.text("min {:.1f}".format(tmin), 135, 18, self.width, scale=2)
            g.set_font("bitmap8")

        y = HEADER_H
        self._row(y, "{:.0f}%".format(data.get("humidity", 0.0)),
                  data.get("humidity_desc", "-"), self.WHITE)
        y += ROW_H
        self._row(y, "{:.0f} hPa".format(data.get("pressure", 0.0)),
                  data.get("pressure_desc", "-"), self.WHITE)
        y += ROW_H
        lux = data.get("lux")
        lux_text = "{:.0f} Lux".format(lux) if lux is not None else "-- Lux"
        self._row(y, lux_text, data.get("light_desc", "-"), self.WHITE)
        y += ROW_H
        gas_pen = self._iaq_pen.get(data.get("iaq_color", "grey"), self.GREY)
        self._row(y, "{:.0f} kOhm".format(data.get("gas_kohm", 0.0)),
                  data.get("iaq_label", "-"), gas_pen)
        y += ROW_H
        self._row(y, "{:.0f} dB".format(data.get("db", 0.0)),
                  data.get("sound_desc", "-"), self.WHITE)

        online = data.get("wifi", {}).get("connected")
        prefix = "Laufzeit {} / ".format(data.get("uptime", "--:--:--"))
        status = wifi_status_text(data.get("wifi", {}))

        prefix_w = g.measure_text(prefix, scale=1)
        status_w = g.measure_text(status, scale=1)
        start_x = (self.width - (prefix_w + status_w)) // 2

        g.set_pen(self.FOOTER_GREY)
        g.text(prefix, start_x, FOOTER_Y, self.width, scale=1)
        g.set_pen(self.GREEN if online else self.RED)
        g.text(status, start_x + prefix_w, FOOTER_Y, self.width, scale=1)

    def _kv_page(self, title, rows):
        """rows: Liste aus (label, value_text, value_pen)."""
        g = self.gfx
        g.set_pen(self.CYAN)
        title_w = g.measure_text(title, scale=2)
        g.text(title, (self.width - title_w) // 2, 4, self.width, scale=2)
        y = 28
        for label, value_text, value_pen in rows:
            g.set_pen(self.LIGHTGREY)
            g.text(label, 4, y, self.width, scale=1)
            g.set_pen(value_pen)
            g.text(value_text, 4, y + 10, self.width, scale=2)
            g.set_pen(self.DARKGREY)
            g.line(4, y + ROW2_H - 4, self.width - 4, y + ROW2_H - 4)
            y += ROW2_H

    def _draw_minmax(self, data):
        mm = data.get("minmax", {})

        def fmt(key, decimals=1):
            lo, hi = mm.get(key, (None, None))
            if lo is None:
                return "-- / --"
            f = "{{:.{}f}}".format(decimals)
            return (f + " / " + f).format(lo, hi)

        rows = [
            ("Luftdruck (hPa)", fmt("pressure", 0), self.WHITE),
            ("Luftfeuchte (%)", fmt("humidity", 0), self.WHITE),
            ("Wettertrend", data.get("pressure_desc", "--"), self.WHITE),
            ("Gaswiderstand (kOhm)", fmt("gas_kohm", 0), self.WHITE),
            ("Licht (Lux)", fmt("lux", 0), self.WHITE),
            ("Geräuschpegel (dB)", fmt("db", 0), self.WHITE),
        ]
        self._kv_page("Min/Max", rows)

    def _draw_wlan(self, data):
        wifi = data.get("wifi", {})
        connected = wifi.get("connected", False)
        status_pen = self.GREEN if connected else self.RED
        rssi = wifi.get("rssi")
        rssi_text = "{} dBm".format(rssi) if rssi is not None else "--"

        rows = [
            ("Status", wifi_status_text(wifi), status_pen),
            ("SSID", wifi.get("ssid") or "--", self.WHITE),
            ("IP-Adresse", wifi.get("ip") or "--", self.WHITE),
            ("Signal", rssi_text, self.WHITE),
            ("Hostname", wifi.get("hostname") or "--", self.WHITE),
        ]
        self._kv_page("WLAN", rows)
        g = self.gfx
        footer_text = "Taste B: WLAN an/aus"
        footer_w = g.measure_text(footer_text, scale=1)
        g.set_pen(self.FOOTER_GREY)
        g.text(footer_text, (self.width - footer_w) // 2, FOOTER_Y, self.width, scale=1)

    def _draw_system(self, data):
        sysinfo = data.get("system", {})
        it = sysinfo.get("internal_temp")
        it_text = "{:.0f} °C (grob)".format(it) if it is not None else "--"
        mem_free = sysinfo.get("mem_free")
        mem_min = sysinfo.get("mem_free_min")
        if mem_free is not None:
            mem_text = "{:.1f} / {:.1f}".format(
                mem_free / 1024, (mem_min if mem_min is not None else mem_free) / 1024)
        else:
            mem_text = "--"
        blk = sysinfo.get("heap_block")
        blk_min = sysinfo.get("heap_block_min")
        if blk is not None:
            blk_text = "{:.1f} / {:.1f}".format(
                blk / 1024, (blk_min if blk_min is not None else blk) / 1024)
        else:
            blk_text = "--"
        flash_kb = sysinfo.get("flash_free_kb")
        flash_text = "{} kB frei".format(flash_kb) if flash_kb is not None else "--"

        st_label, st_ok = sysinfo.get("selftest", ("--", None))
        st_pen = self.GREEN if st_ok is True else (
            self.RED if st_ok is False else self.WHITE)

        rows = [
            ("Pico-Temperatur", it_text, self.WHITE),
            ("RAM frei/Min (kB)", mem_text, self.WHITE),
            ("Größter Block/Min (kB)", blk_text, self.WHITE),
            ("Flash", flash_text, self.WHITE),
            ("Reset-Ursache", sysinfo.get("reset_cause", "--"), self.WHITE),
            ("Selbsttest", st_label, st_pen),
        ]
        self._kv_page("System", rows)

# EOF 2026-09-25
```

### `web.py`

Nicht blockierender HTTP-Server: Dashboard, /data, /history (545 Zeilen)

```python
# web.py
# Nicht blockierender HTTP-Server. Kein Framework - GET-only, HTTP/1.0,
# Connection: close. Das HTML wird EINMAL beim Modulimport gebaut, nicht
# pro Request - auf dem RP2040 waere staendiges Neuzusammensetzen zu teuer.
# Danach loescht das Modul die Vorlage (_TEMPLATE), damit das HTML nicht
# doppelt (~11 kB str + ~11 kB bytes) im RAM liegt.
#
# poll() bekommt eine FUNKTION, die den Zustand baut, kein fertiges dict:
# main.py muss den Zustand so nur bei einer /data-Anfrage zusammensetzen,
# statt 100x pro Sekunde auf Vorrat.

import time
import socket
import json
import gc

import config

_CLIENT_TIMEOUT_MS = 3000  # verwaiste Verbindungen nach 3 s verwerfen
# Obergrenze fuer das Senden einer Antwort. Ohne Timeout blockiert send()
# unbegrenzt, sobald ein Client mitten in der Antwort verschwindet (Handy im
# Standby, Router-Neustart) - und friert damit die ganze Hauptschleife ein.
_SEND_TIMEOUT_S = 2

_TEMPLATE = """<!doctype html>
<html lang="de">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>PicoEnviro+</title>
<style>
  :root {
    --bg:#0d1526; --card:#141d33; --line:#1f2a44;
    --text:#c7d0e0; --muted:#7c88a3; --dim:#6b7794;
    --good:#4ec98a; --warn:#e0a13a; --bad:#e0546a; --accent:#5cc9e8;
  }
  * { box-sizing: border-box; }
  body {
    margin:0 auto; padding:20px; max-width:640px; background:var(--bg); color:var(--text);
    font-family: -apple-system, Helvetica, Arial, sans-serif;
  }
  h1 { text-align:center; font-size:20px; font-weight:500; color:var(--accent); margin:0 0 18px; }
  .grid { display:grid; grid-template-columns:1fr 1fr; gap:12px; }
  .card { background:var(--card); border-radius:12px; padding:14px; text-align:center; }
  .label { font-size:12px; letter-spacing:.08em; color:var(--muted); }
  .value { font-size:28px; font-weight:500; margin:2px 0; }
  .trend { font-size:12px; color:var(--accent); min-height:14px; }
  .minmax { font-size:12px; color:var(--dim); }
  .good { color: var(--good); }
  .warn { color: var(--warn); }
  .bad { color: var(--bad); }
  .neutral { color: var(--accent); }
  .iaqcard { margin-top:12px; }
  .iaqlabel { font-size:24px; font-weight:500; margin:2px 0; }
  .iaqsub { font-size:12px; color:var(--muted); min-height:14px; }
  .iaqstatus { font-size:11px; color:var(--dim); margin-top:2px; }
  .iaqbar { height:12px; border-radius:6px; margin:10px 0 4px;
    background:linear-gradient(90deg,#c0398a,#d98a3a,#4ec98a); position:relative; }
  .iaqmarker { position:absolute; top:-3px; width:6px; height:18px;
    background:#fff; border-radius:3px; }
  .iaqscale { display:flex; justify-content:space-between; font-size:10px; color:var(--dim); }
  h2.section { font-size:15px; font-weight:500; color:#8fa0d6; margin:22px 0 10px; }
  .chartcard { background:var(--card); border-radius:12px; padding:14px; }
  .chartrow { display:flex; justify-content:space-between; font-size:13px; }
  canvas { width:100%; height:70px; margin-top:6px; display:block; }
  footer { border-top:1px solid var(--line); margin-top:18px; padding-top:12px;
    text-align:center; font-size:11px; color:var(--dim); line-height:1.6; }
</style>
</head>
<body>
<h1>PicoEnviro+ Wetterstation</h1>
<div class="grid">
  <div class="card"><div class="label">TEMPERATUR</div>
    <div class="value" id="v-temp">--</div>
    <div class="trend" id="t-temp"></div>
    <div class="minmax" id="m-temp"></div></div>
  <div class="card"><div class="label">LUFTFEUCHTE</div>
    <div class="value" id="v-humidity">--</div>
    <div class="trend" id="t-humidity"></div>
    <div class="minmax" id="m-humidity"></div></div>
  <div class="card"><div class="label">TAUPUNKT</div>
    <div class="value neutral" id="v-dewpoint">--</div>
    <div class="minmax" id="d-dewpoint"></div></div>
  <div class="card"><div class="label">VPD</div>
    <div class="value neutral" id="v-vpd">--</div>
    <div class="minmax" id="d-vpd"></div></div>
  <div class="card"><div class="label">LUFTDRUCK</div>
    <div class="value neutral" id="v-pressure">--</div>
    <div class="trend" id="t-pressure"></div>
    <div class="minmax" id="m-pressure"></div></div>
  <div class="card"><div class="label">GASWIDERSTAND</div>
    <div class="value neutral" id="v-gas">--</div>
    <div class="trend" id="t-gas"></div>
    <div class="minmax" id="m-gas"></div></div>
  <div class="card"><div class="label">LICHT</div>
    <div class="value neutral" id="v-lux">--</div>
    <div class="minmax" id="d-lux"></div>
    <div class="minmax" id="m-lux"></div></div>
  <div class="card"><div class="label">GERÄUSCHPEGEL</div>
    <div class="value neutral" id="v-db">--</div>
    <div class="minmax" id="d-db"></div>
    <div class="minmax" id="m-db"></div></div>
</div>

<div class="card iaqcard">
  <div class="label">LUFTQUALITÄT (RELATIV)</div>
  <div class="iaqlabel" id="v-iaqlabel">--</div>
  <div class="iaqbar"><div class="iaqmarker" id="iaqmarker" style="left:0%"></div></div>
  <div class="iaqscale"><span>sehr schlecht</span><span>mäßig</span><span>gut</span></div>
  <div class="iaqsub" id="v-iaqsub"></div>
  <div class="iaqstatus" id="v-iaqstatus"></div>
</div>

<h2 class="section">Verlauf der letzten __HISTORY_HOURS__ Stunden</h2>
<div class="grid">
  <div class="chartcard">
    <div class="chartrow"><span>Temperatur</span><span id="c-temp"></span></div>
    <canvas id="chart-temp"></canvas>
  </div>
  <div class="chartcard">
    <div class="chartrow"><span>Luftfeuchte</span><span id="c-humidity"></span></div>
    <canvas id="chart-humidity"></canvas>
  </div>
  <div class="chartcard">
    <div class="chartrow"><span>Luftdruck</span><span id="c-pressure"></span></div>
    <canvas id="chart-pressure"></canvas>
  </div>
  <div class="chartcard">
    <div class="chartrow"><span>Gaswiderstand</span><span id="c-gas"></span></div>
    <canvas id="chart-gas"></canvas>
  </div>
</div>

<footer id="footer">Lade...</footer>

<script>
const REFRESH_MS = __REFRESH_MS__;
const CHART_REFRESH_MS = __CHART_REFRESH_MS__;
const TEMP_IDEAL = [__TEMP_LO__, __TEMP_HI__];
const HUM_IDEAL = [__HUM_LO__, __HUM_HI__];

function fmt(v, digits) {
  if (v === null || v === undefined) return "--";
  return v.toFixed(digits);
}

function trendText(v, unit, digits) {
  if (v === null || v === undefined) return "";
  const sign = v >= 0 ? "+" : "";
  return sign + v.toFixed(digits) + " " + unit + " / 10 min";
}

function kb(v) {
  if (v === null || v === undefined) return "--";
  return (v / 1024).toFixed(1);
}

function idealClass(v, lo, hi) {
  if (v === null || v === undefined) return "";
  return (v >= lo && v <= hi) ? "good" : "";
}

async function loadData() {
  try {
    const r = await fetch("/data");
    const d = await r.json();

    document.getElementById("v-temp").textContent = fmt(d.temp, 1) + " °C";
    document.getElementById("v-temp").className = "value " + idealClass(d.temp, TEMP_IDEAL[0], TEMP_IDEAL[1]);
    document.getElementById("t-temp").textContent = trendText(d.temp_trend, "°C", 1);
    document.getElementById("m-temp").textContent = "min " + fmt(d.temp_min,1) + " / max " + fmt(d.temp_max,1);

    document.getElementById("v-humidity").textContent = fmt(d.humidity, 0) + " %";
    document.getElementById("v-humidity").className = "value " + idealClass(d.humidity, HUM_IDEAL[0], HUM_IDEAL[1]);
    document.getElementById("t-humidity").textContent = trendText(d.humidity_trend, "%", 0);
    document.getElementById("m-humidity").textContent = "min " + fmt(d.humidity_min,0) + " / max " + fmt(d.humidity_max,0);

    document.getElementById("v-pressure").textContent = fmt(d.pressure, 0) + " hPa";
    document.getElementById("t-pressure").textContent = d.pressure_desc || "";
    document.getElementById("m-pressure").textContent = "min " + fmt(d.pressure_min,0) + " / max " + fmt(d.pressure_max,0);

    document.getElementById("v-gas").textContent = fmt(d.gas_kohm, 0) + " kOhm";
    document.getElementById("t-gas").textContent = trendText(d.gas_trend, "kOhm", 0);
    document.getElementById("m-gas").textContent = "min " + fmt(d.gas_min,0) + " / max " + fmt(d.gas_max,0);

    document.getElementById("v-lux").textContent = fmt(d.lux, 0) + " Lux";
    document.getElementById("d-lux").textContent = d.light_desc || "";
    document.getElementById("m-lux").textContent = "min " + fmt(d.lux_min,0) + " / max " + fmt(d.lux_max,0);

    document.getElementById("v-db").textContent = fmt(d.db, 0) + " dB";
    document.getElementById("d-db").textContent = d.sound_desc || "";
    document.getElementById("m-db").textContent = "min " + fmt(d.db_min,0) + " / max " + fmt(d.db_max,0);

    document.getElementById("v-dewpoint").textContent = fmt(d.dewpoint, 1) + " °C";
    document.getElementById("d-dewpoint").textContent = "min " + fmt(d.dewpoint_min,1) + " / max " + fmt(d.dewpoint_max,1);

    document.getElementById("v-vpd").textContent = fmt(d.vpd_kpa, 2) + " kPa";
    document.getElementById("d-vpd").textContent = "min " + fmt(d.vpd_min,2) + " / max " + fmt(d.vpd_max,2);

    const iaqColors = {green:"good", yellow:"warn", red:"bad", grey:""};
    const lab = document.getElementById("v-iaqlabel");
    lab.textContent = d.iaq_label || "--";
    lab.className = "iaqlabel " + (iaqColors[d.iaq_color] || "");
    const marker = document.getElementById("iaqmarker");
    if (d.iaq_score === null || d.iaq_score === undefined) {
      marker.style.left = "0%";
      document.getElementById("v-iaqsub").textContent = "Heizer wärmt auf, Bewertung ab ca. 20 min";
    } else {
      marker.style.left = Math.round(d.iaq_score * 100) + "%";
      document.getElementById("v-iaqsub").textContent = "";
    }

    const statusParts = [];
    if (d.gas_valid === true) statusParts.push("Gaswert gültig");
    else if (d.gas_valid === false) statusParts.push("Gaswert ungültig");
    if (d.heater_stable === true) statusParts.push("Heizer stabil");
    else if (d.heater_stable === false) statusParts.push("Heizer instabil");
    document.getElementById("v-iaqstatus").textContent = statusParts.join(", ");

    const status = d.online ? "ONLINE" : "LINK?";
    document.getElementById("footer").textContent =
      "Messwerte alle " + (REFRESH_MS/1000) + " s aktualisiert | Diagramme jede Minute" +
      " | IP: " + (d.ip || "--") + " | " + status +
      " | Laufzeit " + (d.uptime || "--") +
      " | Pico: ~" + fmt(d.internal_temp, 0) + " °C" +
      " | RAM frei " + kb(d.mem_free) + " (min " + kb(d.mem_free_min) + ") kB" +
      " | Block " + kb(d.heap_block) + " (min " + kb(d.heap_block_min) + ") kB";
  } catch (e) { /* naechster Versuch beim naechsten Intervall */ }
}

function drawSpark(canvas, values, color, minSpan) {
  const ctx = canvas.getContext("2d");
  const w = canvas.clientWidth || 260;
  const h = 70;
  canvas.width = w; canvas.height = h;
  ctx.clearRect(0, 0, w, h);
  if (!values || values.length < 2) return;
  let lo = Math.min.apply(null, values);
  let hi = Math.max.apply(null, values);
  // Mindesthoehe der Skala: sonst blaest die Autoskalierung Sprünge von
  // 0,1 °C oder 1 hPa auf die volle Höhe auf (Rechteck-Kurven).
  if (minSpan && hi - lo < minSpan) {
    const mid = (hi + lo) / 2;
    lo = mid - minSpan / 2; hi = mid + minSpan / 2;
  }
  const span = (hi - lo) || 1;
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  ctx.beginPath();
  values.forEach(function(v, i) {
    const x = (i / (values.length - 1)) * (w - 8) + 4;
    const y = h - 6 - ((v - lo) / span) * (h - 12);
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();
}

async function loadHistory() {
  try {
    const r = await fetch("/history");
    const h = await r.json();
    drawSpark(document.getElementById("chart-temp"), h.temp, "#d98a3a", 1.0);
    drawSpark(document.getElementById("chart-humidity"), h.humidity, "#5cc9e8", 4);
    drawSpark(document.getElementById("chart-pressure"), h.pressure, "#5cc9e8", 2);
    drawSpark(document.getElementById("chart-gas"), h.gas_kohm, "#4ec98a", 20);
    function last(arr) { return (arr && arr.length) ? arr[arr.length-1] : null; }
    document.getElementById("c-temp").textContent = fmt(last(h.temp),1) + " °C";
    document.getElementById("c-humidity").textContent = fmt(last(h.humidity),0) + " %";
    document.getElementById("c-pressure").textContent = fmt(last(h.pressure),0) + " hPa";
    document.getElementById("c-gas").textContent = fmt(last(h.gas_kohm),0) + " kOhm";
  } catch (e) { /* naechster Versuch beim naechsten Intervall */ }
}

loadData();
loadHistory();
setInterval(loadData, REFRESH_MS);
setInterval(loadHistory, CHART_REFRESH_MS);
</script>
</body>
</html>
"""


def _build_index_html():
    html = _TEMPLATE
    html = html.replace("__REFRESH_MS__", str(config.WEB_REFRESH_S * 1000))
    html = html.replace("__CHART_REFRESH_MS__", str(config.WEB_CHART_REFRESH_S * 1000))
    html = html.replace("__TEMP_LO__", str(config.TEMP_IDEAL[0]))
    html = html.replace("__TEMP_HI__", str(config.TEMP_IDEAL[1]))
    html = html.replace("__HUM_LO__", str(config.HUMIDITY_IDEAL[0]))
    html = html.replace("__HUM_HI__", str(config.HUMIDITY_IDEAL[1]))
    hours = (config.HISTORY_LEN * config.HISTORY_INTERVAL_MS) // 3600000
    html = html.replace("__HISTORY_HOURS__", str(hours))
    return html.encode("utf-8")


# Einmal beim Modulimport gebaut - jede Anfrage bekommt dieselben Bytes.
_INDEX_HTML = _build_index_html()
# Vorlage wird nicht mehr gebraucht - freigeben statt doppelt vorhalten.
del _TEMPLATE
gc.collect()


def _data_payload(state):
    mm = state.get("minmax", {})

    def mm_get(key):
        return mm.get(key, (None, None))

    temp_min, temp_max = mm_get("temp")
    hum_min, hum_max = mm_get("humidity")
    pres_min, pres_max = mm_get("pressure")
    gas_min, gas_max = mm_get("gas_kohm")
    lux_min, lux_max = mm_get("lux")
    db_min, db_max = mm_get("db")
    dew_min, dew_max = mm_get("dewpoint")
    vpd_min, vpd_max = mm_get("vpd_kpa")

    wifi = state.get("wifi", {})
    sysinfo = state.get("system", {})
    trend = state.get("trend", {})

    payload = {
        "temp": state.get("temp"), "temp_min": temp_min, "temp_max": temp_max,
        "temp_trend": trend.get("temp"),
        "humidity": state.get("humidity"), "humidity_min": hum_min, "humidity_max": hum_max,
        "humidity_trend": trend.get("humidity"),
        "pressure": state.get("pressure"), "pressure_min": pres_min, "pressure_max": pres_max,
        "pressure_trend": trend.get("pressure"),
        "gas_kohm": state.get("gas_kohm"), "gas_min": gas_min, "gas_max": gas_max,
        "gas_trend": trend.get("gas_kohm"),
        "lux": state.get("lux"), "lux_min": lux_min, "lux_max": lux_max,
        "db": state.get("db"), "db_min": db_min, "db_max": db_max,
        "dewpoint": state.get("dewpoint"), "dewpoint_min": dew_min, "dewpoint_max": dew_max,
        "vpd_kpa": state.get("vpd_kpa"), "vpd_min": vpd_min, "vpd_max": vpd_max,
        "humidity_desc": state.get("humidity_desc"),
        "pressure_desc": state.get("pressure_desc"),
        "light_desc": state.get("light_desc"),
        "sound_desc": state.get("sound_desc"),
        "iaq_label": state.get("iaq_label"),
        "iaq_color": state.get("iaq_color"),
        "iaq_score": state.get("iaq_score"),
        "gas_valid": state.get("gas_valid"),
        "heater_stable": state.get("heater_stable"),
        "uptime": state.get("uptime"),
        "ip": wifi.get("ip"),
        "online": wifi.get("connected"),
        "hostname": wifi.get("hostname"),
        "internal_temp": sysinfo.get("internal_temp"),
        "mem_free": sysinfo.get("mem_free"),
        "mem_free_min": sysinfo.get("mem_free_min"),
        "heap_block": sysinfo.get("heap_block"),
        "heap_block_min": sysinfo.get("heap_block_min"),
    }
    return json.dumps(payload).encode("utf-8")


def _history_chunks(hist_buf):
    """Paket 2: /history als Folge kleiner Textstuecke statt eines grossen
    Blocks (siehe History.iter_json). Druck jetzt mit einer Nachkommastelle,
    sonst springt das Diagramm in ganzen hPa-Stufen."""
    gc.collect()
    yield '{{"interval_s":{},"temp":'.format(config.HISTORY_INTERVAL_MS // 1000)
    for part in hist_buf.iter_json("temp", 1):
        yield part
    yield ',"humidity":'
    for part in hist_buf.iter_json("humidity", 0):
        yield part
    yield ',"pressure":'
    for part in hist_buf.iter_json("pressure", 1):
        yield part
    yield ',"gas_kohm":'
    for part in hist_buf.iter_json("gas_kohm", 0):
        yield part
    yield "}"


def _send_all(conn, data):
    """send() darf weniger Bytes schreiben als uebergeben - Standardverhalten,
    kein Fehler. Ohne diese Schleife wird der Rest einer mehrere KB grossen
    Antwort (das Dashboard-HTML) stillschweigend verworfen, sobald der
    TCP-Sendepuffer kurzzeitig voll ist."""
    sent = 0
    total = len(data)
    mv = memoryview(data)
    while sent < total:
        n = conn.send(mv[sent:])
        if not n:
            break
        sent += n


def _drain(conn):
    """Restliche, noch ungelesene Anfragedaten verwerfen, bevor die
    Verbindung geschlossen wird. Sonst schickt lwIP beim close() ein RST
    statt eines sauberen FIN, sobald noch Bytes im Socket-Puffer liegen -
    der Browser meldet dann ERR_CONNECTION_RESET, selbst wenn die Antwort
    laengst vollstaendig angekommen ist."""
    try:
        conn.setblocking(False)
        for _ in range(8):
            chunk = conn.recv(256)
            if not chunk:
                break
    except Exception:
        pass


class WebServer:
    """Roher, nicht blockierender HTTP-Server. GET-only, HTTP/1.0,
    Connection: close - reicht fuer ein lokales Dashboard."""

    def __init__(self, port):
        self.port = port
        self.sock = None
        self.request_count = 0
        self._clients = []  # Liste aus [conn, buf, start_ms]

    def start(self):
        self.stop()
        addr = socket.getaddrinfo("0.0.0.0", self.port)[0][-1]
        s = socket.socket()
        try:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        except Exception:
            pass
        s.bind(addr)
        s.listen(2)
        s.setblocking(False)
        self.sock = s

    def stop(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None
        for entry in self._clients:
            try:
                entry[0].close()
            except Exception:
                pass
        self._clients = []

    def poll(self, state_fn, hist_buf):
        """state_fn: Funktion ohne Argumente, die das Zustands-dict liefert.
        Wird nur fuer /data aufgerufen."""
        if self.sock is None:
            return
        now = time.ticks_ms()

        try:
            conn, _addr = self.sock.accept()
            conn.setblocking(False)
            self._clients.append([conn, b"", now])
        except OSError:
            pass  # kein wartender Client - normal bei non-blocking accept()

        still_open = []
        for entry in self._clients:
            conn, buf, started = entry
            try:
                chunk = conn.recv(256)
                if chunk:
                    buf += chunk
                    entry[1] = buf
            except OSError:
                pass  # gerade nichts zu lesen - normal

            timed_out = time.ticks_diff(now, started) > _CLIENT_TIMEOUT_MS
            if b"\r\n" in buf or timed_out:
                try:
                    self._respond(conn, buf, state_fn, hist_buf)
                except Exception:
                    pass
                _drain(conn)
                try:
                    conn.close()
                except Exception:
                    pass
            else:
                still_open.append(entry)
        self._clients = still_open

    def _respond(self, conn, buf, state_fn, hist_buf):
        try:
            line = buf.split(b"\r\n", 1)[0].decode()
            path = line.split(" ")[1]
        except Exception:
            path = "/"

        self.request_count += 1

        try:
            if path == "/" or path.startswith("/index"):
                status, ctype, body = 200, "text/html; charset=utf-8", _INDEX_HTML
            elif path.startswith("/data"):
                status, ctype, body = 200, "application/json", _data_payload(state_fn())
            elif path.startswith("/history"):
                # Gestreamt: ohne Content-Length, Ende = Verbindungsende
                # (HTTP/1.0, Connection: close - fuer Browser zulaessig).
                status, ctype, body = 200, "application/json", None
            else:
                status, ctype, body = 404, "text/plain", b"Not found"
        except Exception:
            # Ein Fehler beim Zusammenbauen der Antwort darf niemals die
            # Hauptschleife mitreissen - lieber eine 500-Antwort als ein
            # eingefrorenes Geraet.
            status, ctype, body = 500, "text/plain", b"Internal error"

        # UTF-8-Byte-Laenge, nicht Zeichenlaenge - sonst falscher Content-Length
        # sobald irgendwo ein Mehrbyte-Zeichen auftaucht.
        reason = {200: "OK", 404: "Not Found", 500: "Internal Server Error"}.get(status, "OK")
        if body is None:
            header = (
                "HTTP/1.0 {} {}\r\n"
                "Content-Type: {}\r\n"
                "Cache-Control: no-store\r\n"
                "Connection: close\r\n\r\n"
            ).format(status, reason, ctype)
        else:
            header = (
                "HTTP/1.0 {} {}\r\n"
                "Content-Type: {}\r\n"
                "Content-Length: {}\r\n"
                "Connection: close\r\n\r\n"
            ).format(status, reason, ctype, len(body))
        # Fuer den Versand auf blockierend MIT Obergrenze umschalten: eine
        # mehrere KB grosse Antwort (das Dashboard-HTML) passt oft nicht in
        # einen einzigen nicht blockierenden send()-Aufruf. Der Timeout
        # verhindert, dass ein verschwundener Client die Schleife einfriert -
        # send() wirft dann OSError, das except unten faengt es ab.
        try:
            conn.settimeout(_SEND_TIMEOUT_S)
            _send_all(conn, header.encode("utf-8"))
            if body is None:
                for part in _history_chunks(hist_buf):
                    _send_all(conn, part.encode("utf-8"))
            else:
                _send_all(conn, body)
        except Exception:
            pass

# EOF 2026-09-26
```

### `wifi.py`

WLAN-Zustandsautomat mit Wiederverbindung (208 Zeilen)

```python
# wifi.py
# Nicht blockierender WLAN-Zustandsautomat fuer das Enviro+.
#
# WLAN-Angleich (2026-09-25): gleiches Verhalten wie beim BME690
# (dortiges wifi.py), angepasst an die Klassenstruktur dieses Projekts.
# Drei Zustaende:
#   OFF        - WLAN aus (Taste B)
#   CONNECTING - Verbindung laeuft, alle WIFI_RETRY_MS neuer Versuch
#   CONNECTED  - verbunden
# Verhalten bei Linkverlust bzw. WLAN-Zeitschaltung des Routers:
#   - Link wird hoechstens alle WIFI_CHECK_MS geprueft,
#   - Linkverlust -> poll() meldet "down" (main.py schliesst den Server),
#     dann Neuverbindung,
#   - jeder Fehlversuch schreibt den Funkchip-Status in die REPL und als
#     Kurztext auf Display/Status-Seite (self.note: NOAP, AUTH, FAIL ...),
#   - vor jedem neuen connect() wird die alte Verbindung getrennt,
#   - nach WIFI_RESET_AFTER Fehlversuchen wird die Schnittstelle komplett
#     aus- und wieder eingeschaltet (entspricht zweimal Taste B),
#   - Rueckkehr oder geaenderte IP -> poll() meldet "up" (main.py oeffnet
#     einen frischen Server-Socket).
# Laendercode wird VOR dem Einschalten des Funkchips gesetzt; scheitert das,
# steht es in der REPL.
# Bewusst NICHT angeglichen: Powersave (pm). Das Enviro+ laeuft weiter mit
# dem Firmware-Standard, weil die Kalibrierung (TEMP_OFFSET) unter genau
# diesem Waermezustand entstand. Der BME690 laeuft mit Powersave aus.

import time
import network

import config
import secrets

_OFF = "off"
_CONNECTING = "connecting"
_CONNECTED = "connected"


def _country_code():
    return getattr(secrets, "WIFI_COUNTRY", config.WIFI_COUNTRY_DEFAULT)


class WiFi:
    def __init__(self):
        self.wlan = None
        self.state = _OFF
        self.note = ""          # Kurztext fuer Display, leer = kein Fehler
        self._ip = None         # zuletzt gemeldete IP
        self._t_connect = 0
        self._t_check = 0
        self._fails = 0
        self._country_reported = False

    # --- intern -----------------------------------------------------------

    def _set_country(self):
        code = _country_code()
        for mod_name in ("network", "rp2"):
            try:
                mod = network if mod_name == "network" else __import__("rp2")
                mod.country(code)
                return
            except Exception:
                pass
        if not self._country_reported:
            print("WLAN: Laendercode", code, "liess sich nicht setzen -",
                  "Kanal 12/13 evtl. unsichtbar")
            self._country_reported = True

    def _status_text(self):
        try:
            st = self.wlan.status()
        except Exception:
            return "?", "Status nicht lesbar"
        table = (
            (getattr(network, "STAT_WRONG_PASSWORD", -3), "AUTH", "falsches Passwort"),
            (getattr(network, "STAT_NO_AP_FOUND", -2), "NOAP", "Netz nicht gefunden"),
            (getattr(network, "STAT_CONNECT_FAIL", -1), "FAIL", "Verbindung abgelehnt"),
            (getattr(network, "STAT_IDLE", 0), "IDLE", "kein Versuch aktiv"),
            (getattr(network, "STAT_CONNECTING", 1), "JOIN", "verbindet noch"),
            (2, "NOIP", "verbunden, aber keine IP (DHCP)"),
        )
        for code, short, text in table:
            if st == code:
                return short, text + " (" + str(st) + ")"
        return "S" + str(st), "Status " + str(st)

    def _power_up(self):
        """Schnittstelle sauber aus- und wieder einschalten. Blockiert kurz
        (ca. 0,2 s), laeuft nur beim Einschalten und nach Fehlversuchen."""
        self._set_country()
        if self.wlan is None:
            self.wlan = network.WLAN(network.STA_IF)
        try:
            self.wlan.disconnect()
        except Exception:
            pass
        self.wlan.active(False)
        time.sleep_ms(200)
        self.wlan.active(True)
        try:
            self.wlan.config(hostname=secrets.WIFI_HOSTNAME)
        except Exception:
            pass

    def _start_connect(self):
        try:
            self.wlan.disconnect()   # alten, evtl. haengenden Versuch beenden
        except Exception:
            pass
        try:
            self.wlan.connect(secrets.WIFI_SSID, secrets.WIFI_PASSWORD)
        except Exception as error:
            print("WLAN-Connect-Fehler:", error)
        self.state = _CONNECTING
        self._t_connect = time.ticks_ms()

    # --- oeffentlich ------------------------------------------------------

    def enable(self):
        self._power_up()
        self.note = ""
        self._ip = None
        self._fails = 0
        self._start_connect()
        print("WLAN: verbinde...")

    def disable(self):
        if self.wlan is not None:
            try:
                self.wlan.disconnect()
                self.wlan.active(False)
            except Exception:
                pass
        self.state = _OFF
        self.note = ""
        self._ip = None
        print("WLAN deaktiviert")

    def toggle(self):
        if self.state == _OFF:
            self.enable()
        else:
            self.disable()

    def poll(self):
        """Jede Schleifenrunde aufrufen, kehrt sofort zurueck.
        Rueckgabe: "up" (Server oeffnen), "down" (Server schliessen), None."""
        if self.state == _OFF:
            return None
        now = time.ticks_ms()
        if time.ticks_diff(now, self._t_check) < config.WIFI_CHECK_MS:
            return None
        self._t_check = now

        linked = self.wlan.isconnected()

        if self.state == _CONNECTING:
            if linked:
                self.state = _CONNECTED
                self._ip = self.wlan.ifconfig()[0]
                self._fails = 0
                self.note = ""
                print("Webserver: http://" + self._ip)
                return "up"
            if time.ticks_diff(now, self._t_connect) > config.WIFI_RETRY_MS:
                self._fails += 1
                short, text = self._status_text()
                self.note = short
                print("WLAN: Versuch", self._fails, "erfolglos -", text)
                if self._fails % config.WIFI_RESET_AFTER == 0:
                    print("WLAN: setze Schnittstelle zurueck")
                    try:
                        self._power_up()
                    except Exception as error:
                        print("WLAN-Reset fehlgeschlagen:", error)
                self._start_connect()
            return None

        # _CONNECTED
        if not linked:
            print("WLAN: Verbindung verloren, verbinde neu...")
            self._ip = None
            self._start_connect()
            return "down"
        ip = self.wlan.ifconfig()[0]
        if ip != self._ip:
            print("WLAN: IP", ip, "- Server-Socket neu oeffnen")
            self._ip = ip
            return "up"
        return None

    @property
    def enabled(self):
        return self.state != _OFF

    @property
    def connected(self):
        return self.state == _CONNECTED

    @property
    def ip(self):
        return self._ip if self.connected else None

    @property
    def ssid(self):
        return secrets.WIFI_SSID if self.enabled else None

# EOF 2026-09-25
```

### `system.py`

RAM, größter Speicherblock, Flash, interne Temperatur, RSSI (91 Zeilen)

```python
# system.py
# Misst den Pico selbst, nicht die Umwelt - bewusst getrennt von sensors.py.
# Wird von der System-Seite in display.py und spaeter vom Webserver genutzt.

import gc
import os
import machine

_RESET_CAUSE_NAMES = (
    ("PWRON_RESET", "Power-On"),
    ("HARD_RESET", "Hard-Reset"),
    ("WDT_RESET", "Watchdog"),
    ("DEEPSLEEP_RESET", "Deep-Sleep"),
    ("SOFT_RESET", "Soft-Reset"),
)
_RESET_CAUSES = {}
for _name, _label in _RESET_CAUSE_NAMES:
    if hasattr(machine, _name):
        _RESET_CAUSES[getattr(machine, _name)] = _label


class SystemStats:
    """Haelt die ueber die Laufzeit beobachteten RAM-Tiefstaende fest.
    Session-basiert, wie die Sensor-Min/Max-Werte - kein Flash-Verschleiss."""

    def __init__(self):
        self.mem_free_min = None
        self.block = None
        self.block_min = None

    def sample(self):
        gc.collect()
        free = gc.mem_free()
        if self.mem_free_min is None or free < self.mem_free_min:
            self.mem_free_min = free
        return free

    def probe_block(self):
        """Groessten zusammenhaengenden freien Heap-Block messen.
        mem_free() zeigt nur die Summe aller Luecken - bei fragmentiertem
        Heap kann genug frei sein und trotzdem jede groessere Allokation
        scheitern. Genau das misst diese Sonde."""
        gc.collect()
        self.block = largest_free_block()
        if self.block_min is None or self.block < self.block_min:
            self.block_min = self.block
        return self.block


def largest_free_block(step=256):
    """Binaersuche per Probe-Allokation. Jeder Fehlversuch kostet intern
    eine Garbage Collection - deshalb nur alle paar Sekunden aufrufen."""
    lo, hi = 0, gc.mem_free()
    while hi - lo > step:
        mid = (lo + hi) // 2
        try:
            b = bytearray(mid)
            del b
            lo = mid
        except MemoryError:
            hi = mid
    return lo


def reset_cause():
    return _RESET_CAUSES.get(machine.reset_cause(), "unbekannt")


def flash_free_kb():
    try:
        st = os.statvfs("/")
        return (st[0] * st[3]) // 1024
    except Exception:
        return None


def firmware_info():
    u = os.uname()
    return "{} {}".format(u.sysname, u.release)


def wlan_rssi(wlan):
    """wlan: aktives network.WLAN(STA_IF) oder None, falls nicht verbunden."""
    if wlan is None or not wlan.isconnected():
        return None
    try:
        return wlan.status("rssi")
    except Exception:
        return None

# EOF 2026-09-23
```

