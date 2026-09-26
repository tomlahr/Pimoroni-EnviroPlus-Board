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
