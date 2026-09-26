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
