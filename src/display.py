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
#
# Drehen: PicoGraphics kennt keine Drehung zur Laufzeit, "rotate" gibt es
# nur im Konstruktor. Zum Drehen wird das Objekt neu angelegt - mit dem
# eigenen Framebuffer (buffer=), damit kein zweiter 28,8-kB-Block noetig ist
# (im REPL bestaetigt: freier Heap ueber 8 Neuanlagen unveraendert).
# Den Destruktor (__del__) NIE selbst aufrufen: er gibt den DMA-Kanal frei.
# Riefe ihn der GC spaeter ein zweites Mal auf, koennte er den Kanal des
# neuen Objekts freigeben. Altes Objekt nur loslassen, gc.collect(), neu anlegen.

from picographics import PicoGraphics, DISPLAY_ENVIRO_PLUS, PEN_P4
from pimoroni import RGBLED
import gc
import time
import math

import config

PAGE_MAIN, PAGE_MINMAX, PAGE_WLAN, PAGE_SYSTEM = range(4)
PAGE_COUNT = 4

_FB_SIZE = 240 * 240 // 2   # PEN_P4: 4 Bit pro Pixel

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

def _load_rotation():
    try:
        with open(config.ROTATION_FILE) as f:
            rot = int(f.read().strip())
        if rot in config.ROTATIONS:
            return rot
    except Exception:
        pass
    return config.ROTATIONS[0]


def _save_rotation(rot):
    try:
        with open(config.ROTATION_FILE, "w") as f:
            f.write(str(rot))
    except Exception:
        pass


class Display:
    def __init__(self):
        # Framebuffer selbst anlegen und bei jeder Drehung wiederverwenden.
        self._fb = bytearray(_FB_SIZE)
        self.backlight_on = True
        self.rotation = _load_rotation()
        self.gfx = None
        self._create_gfx()
        self.led = RGBLED(config.LED_R, config.LED_G, config.LED_B,
                           invert=config.LED_INVERT)
        self.page = PAGE_MAIN

    def _create_gfx(self):
        """(Neu-)Anlage des Grafikobjekts in der aktuellen Lage. Palette,
        Schrift und Helligkeit haengen am Objekt und werden neu gesetzt."""
        self.gfx = None
        gc.collect()
        self.gfx = PicoGraphics(display=DISPLAY_ENVIRO_PLUS, rotate=self.rotation,
                                pen_type=PEN_P4, buffer=self._fb)
        self.width, self.height = self.gfx.get_bounds()
        self.gfx.set_font("bitmap8")
        self._make_pens()
        self.gfx.set_backlight(config.BRIGHTNESS if self.backlight_on else 0)

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

    def rotate_next(self):
        """Naechste Lage aus config.ROTATIONS. Schaltet das Display ein -
        bei dunklem Display waere die Drehung sonst nicht zu sehen."""
        rots = config.ROTATIONS
        i = rots.index(self.rotation) if self.rotation in rots else -1
        self.rotation = rots[(i + 1) % len(rots)]
        _save_rotation(self.rotation)
        self.backlight_on = True
        self._create_gfx()

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
