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
