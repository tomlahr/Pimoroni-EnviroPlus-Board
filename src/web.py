# web.py
# Nicht blockierender HTTP-Server. Kein Framework - GET-only, HTTP/1.0,
# Connection: close. Die Dashboard-Seite liegt als index.html im Flash und
# wird pro Abruf in ~1-kB-Stuecken gestreamt - kein grosser RAM-Block, weder
# beim Start noch dauerhaft (siehe _index_chunks()).
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

# Dashboard-Seite (2026-11-11): liegt als index.html im Flash und wird beim
# Abruf zeilenweise gelesen, Platzhalter ersetzt und in ~1-kB-Stuecken
# gesendet. Vorher wurde sie beim Import als EIN 11,7-kB-Block gebaut - acht
# Kopien durch replace()/encode() - und belegte danach dauerhaft 11,7 kB. Auf
# dem RP2040 mit zerstueckeltem Heap endete das im MemoryError beim Start.
_INDEX_FILE = "index.html"
_CHUNK = 1024


def _placeholders():
    hours = (config.HISTORY_LEN * config.HISTORY_INTERVAL_MS) // 3600000
    return (
        (b"__REFRESH_MS__", str(config.WEB_REFRESH_S * 1000).encode()),
        (b"__CHART_REFRESH_MS__", str(config.WEB_CHART_REFRESH_S * 1000).encode()),
        (b"__TEMP_LO__", str(config.TEMP_IDEAL[0]).encode()),
        (b"__TEMP_HI__", str(config.TEMP_IDEAL[1]).encode()),
        (b"__HUM_LO__", str(config.HUMIDITY_IDEAL[0]).encode()),
        (b"__HUM_HI__", str(config.HUMIDITY_IDEAL[1]).encode()),
        (b"__HISTORY_HOURS__", str(hours).encode()),
    )


_PLACEHOLDERS = _placeholders()


def _index_exists():
    try:
        with open(_INDEX_FILE, "rb"):
            return True
    except OSError:
        return False


def _index_chunks():
    """index.html in ~1-kB-Stuecken. Platzhalter stehen immer innerhalb
    einer Zeile, deshalb wird zeilenweise ersetzt."""
    buf = bytearray()
    with open(_INDEX_FILE, "rb") as f:
        while True:
            line = f.readline()
            if not line:
                break
            if b"__" in line:
                for key, val in _PLACEHOLDERS:
                    line = line.replace(key, val)
            buf += line
            if len(buf) >= _CHUNK:
                yield buf
                buf = bytearray()
    if buf:
        yield buf
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
        stream = None

        try:
            if path == "/" or path.startswith("/index"):
                if _index_exists():
                    # Gestreamt aus dem Flash, siehe _index_chunks().
                    status, ctype, body = 200, "text/html; charset=utf-8", None
                    stream = _index_chunks()
                else:
                    status, ctype, body = 500, "text/plain", b"index.html fehlt"
            elif path.startswith("/data"):
                status, ctype, body = 200, "application/json", _data_payload(state_fn())
            elif path.startswith("/history"):
                # Gestreamt: ohne Content-Length, Ende = Verbindungsende
                # (HTTP/1.0, Connection: close - fuer Browser zulaessig).
                status, ctype, body = 200, "application/json", None
                stream = (p.encode("utf-8") for p in _history_chunks(hist_buf))
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
                for part in stream:
                    _send_all(conn, part)
            else:
                _send_all(conn, body)
        except Exception:
            pass

# EOF 2026-11-11
