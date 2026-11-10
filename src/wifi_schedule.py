# wifi_schedule.py
# WLAN-Nachtabschaltung passend zur FRITZ!Box-Zeitschaltung.
# IDENTISCH in beiden Projekten (Enviro+ und BME690) - Aenderungen immer an
# beide Repos geben, wie bei iaq.py.
#
# Ablauf:
#   - Sobald WLAN verbunden ist, wird die Uhrzeit per NTP geholt (Server der
#     Reihe nach aus NTP_HOSTS) und danach alle NTP_RESYNC_MS erneut.
#   - Aus der UTC-Zeit wird die deutsche Ortszeit berechnet (MEZ/MESZ nach
#     EU-Regel; MicroPython kennt keine Zeitzonen).
#   - update() meldet "off" bzw. "on", wenn der WLAN-Zustand nicht zum
#     Zeitfenster passt. main.py schaltet dann.
#   - Ohne Uhrzeit (Neustart in der Nacht) schaltet der Zeitplan nichts: WLAN
#     bleibt an und versucht es weiter, bis die FRITZ!Box wieder sendet.
#   - manual() (Taste B bzw. CTRL) setzt den Zeitplan bis zum naechsten
#     Schaltpunkt aus.
#
# Die Uhr laeuft auf beiden Boards aus dem 12-MHz-Quarz (RP2350: Pico-SDK
# stellt den Zaehler auf den Quarz um). Abweichung ueber die Nacht ohne
# Abgleich: deutlich unter einer Sekunde.

import time

try:
    import ntptime
except ImportError:
    ntptime = None

_CHECK_MS = 1000   # Zeitfenster hoechstens einmal pro Sekunde pruefen


def _last_sunday(year, month):
    """Tag des letzten Sonntags im Monat (nur fuer Monate mit 31 Tagen)."""
    t = time.mktime((year, month, 31, 12, 0, 0, 0, 0))
    weekday = time.localtime(t)[6]   # 0 = Montag ... 6 = Sonntag
    return 31 - (weekday + 1) % 7


def local_time():
    """Deutsche Ortszeit als localtime-Tupel. Die interne Uhr steht nach
    ntptime.settime() auf UTC. Umstellung jeweils 01:00 UTC am letzten
    Sonntag im Maerz bzw. Oktober."""
    utc = time.time()
    year = time.localtime(utc)[0]
    start = time.mktime((year, 3, _last_sunday(year, 3), 1, 0, 0, 0, 0))
    end = time.mktime((year, 10, _last_sunday(year, 10), 1, 0, 0, 0, 0))
    offset = 7200 if start <= utc < end else 3600
    return time.localtime(utc + offset)


class WifiSchedule:
    def __init__(self, off_from, off_until, ntp_hosts, resync_ms, retry_ms):
        self._from = off_from[0] * 60 + off_from[1]
        self._until = off_until[0] * 60 + off_until[1]
        self._hosts = ntp_hosts
        self._resync_ms = resync_ms
        self._retry_ms = retry_ms
        self.synced = False
        self.override = False
        self._want = None        # zuletzt gueltiger Sollzustand (True = an)
        self._in_off = False
        self._t_check = time.ticks_ms()
        self._t_sync = 0
        self._t_try = 0
        self._tried = False
        if ntptime is None:
            print("Zeitplan: Modul ntptime fehlt - WLAN-Zeitplan inaktiv")

    def _sync(self):
        if ntptime is None:
            return False
        for host in self._hosts:
            try:
                ntptime.host = host
                ntptime.settime()
                lt = local_time()
                print("Zeitplan: Uhrzeit von %s, Ortszeit %02d:%02d" % (host, lt[3], lt[4]))
                return True
            except Exception as error:
                print("Zeitplan: NTP", host, "fehlgeschlagen:", error)
        return False

    def _is_off(self, minute):
        if self._from <= self._until:
            return self._from <= minute < self._until
        return minute >= self._from or minute < self._until   # ueber Mitternacht

    def update(self, enabled, connected):
        """Jede Schleifenrunde aufrufen, kehrt meist sofort zurueck.
        Rueckgabe: "on", "off" oder None."""
        now = time.ticks_ms()
        if time.ticks_diff(now, self._t_check) < _CHECK_MS:
            return None
        self._t_check = now

        if connected:
            due = not self.synced or time.ticks_diff(now, self._t_sync) >= self._resync_ms
            if due and (not self._tried or time.ticks_diff(now, self._t_try) >= self._retry_ms):
                self._tried = True
                self._t_try = now
                if self._sync():
                    self.synced = True
                    self._t_sync = time.ticks_ms()

        if not self.synced:
            return None

        lt = local_time()
        self._in_off = self._is_off(lt[3] * 60 + lt[4])
        want = not self._in_off
        if want != self._want:
            if self._want is not None:
                self.override = False   # Schaltpunkt erreicht: Eingriff endet
            self._want = want
        if self.override or want == enabled:
            return None
        print("Zeitplan: WLAN", "an" if want else "aus")
        return "on" if want else "off"

    def manual(self):
        """Manueller Eingriff per Taste - gilt bis zum naechsten Schaltpunkt."""
        self.override = True

    def status_text(self):
        """Kurztext fuer die WLAN-Seite."""
        if ntptime is None:
            return "kein NTP"
        if not self.synced:
            return "keine Uhrzeit"
        edge = self._until if self._in_off else self._from
        if self.override:
            return "manuell bis %02d:%02d" % (edge // 60, edge % 60)
        return "aus %02d:%02d-%02d:%02d" % (self._from // 60, self._from % 60,
                                          self._until // 60, self._until % 60)

# EOF 2026-11-11
