from flask import Flask, render_template_string, jsonify
import requests
import time
import json
import os
from datetime import datetime, timezone

app = Flask(__name__)

# ─── Config ───────────────────────────────────────────────────────────────────
API_NAME    = "Open-Meteo Weather API"
API_URL     = "https://api.open-meteo.com/v1/forecast"
API_PARAMS  = {
    "latitude": 48.8566,
    "longitude": 2.3522,
    "current": "temperature_2m,wind_speed_10m,weathercode",
    "timezone": "Europe/Paris"
}
RESULTS_FILE = "/tmp/test_results.json"
MAX_HISTORY  = 50

# ─── Helpers ──────────────────────────────────────────────────────────────────

def load_results():
    if os.path.exists(RESULTS_FILE):
        with open(RESULTS_FILE) as f:
            return json.load(f)
    return []

def save_results(results):
    with open(RESULTS_FILE, "w") as f:
        json.dump(results[-MAX_HISTORY:], f)

def run_tests():
    """Execute all QoS tests against the API and return a result dict."""
    result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "tests": [],
        "metrics": {}
    }

    # ── Test 1 : Reachability & status code ──────────────────────────────────
    start = time.time()
    try:
        r = requests.get(API_URL, params=API_PARAMS, timeout=10)
        latency = round((time.time() - start) * 1000, 1)
        status_ok = r.status_code == 200

        result["tests"].append({
            "name": "HTTP 200 OK",
            "status": "PASS" if status_ok else "FAIL",
            "detail": f"Status code: {r.status_code}"
        })
        result["metrics"]["latency_ms"] = latency
        result["metrics"]["status_code"] = r.status_code

    except requests.exceptions.Timeout:
        latency = round((time.time() - start) * 1000, 1)
        result["tests"].append({"name": "HTTP 200 OK", "status": "FAIL", "detail": "Timeout after 10 s"})
        result["metrics"]["latency_ms"] = latency
        result["metrics"]["status_code"] = None
        result["metrics"]["valid_json"] = False
        result["metrics"]["required_fields"] = False
        result["metrics"]["temp_in_range"] = False
        result["metrics"]["wind_positive"] = False
        return result

    except Exception as e:
        result["tests"].append({"name": "HTTP 200 OK", "status": "FAIL", "detail": str(e)})
        result["metrics"] = {"latency_ms": None, "status_code": None}
        return result

    # ── Test 2 : Valid JSON ───────────────────────────────────────────────────
    try:
        data = r.json()
        valid_json = True
    except Exception:
        data = {}
        valid_json = False

    result["tests"].append({
        "name": "Valid JSON",
        "status": "PASS" if valid_json else "FAIL",
        "detail": "Response is parseable JSON" if valid_json else "Could not parse JSON"
    })
    result["metrics"]["valid_json"] = valid_json

    if not valid_json:
        return result

    # ── Test 3 : Required fields ──────────────────────────────────────────────
    required = ["latitude", "longitude", "current"]
    missing  = [k for k in required if k not in data]
    has_fields = len(missing) == 0

    result["tests"].append({
        "name": "Required fields present",
        "status": "PASS" if has_fields else "FAIL",
        "detail": "All fields OK" if has_fields else f"Missing: {missing}"
    })
    result["metrics"]["required_fields"] = has_fields

    # ── Test 4 : Temperature in plausible range ───────────────────────────────
    try:
        temp = data["current"]["temperature_2m"]
        in_range = -60 <= temp <= 60
        result["tests"].append({
            "name": "Temperature in range (-60 / +60 °C)",
            "status": "PASS" if in_range else "FAIL",
            "detail": f"temperature_2m = {temp} °C"
        })
        result["metrics"]["temperature_2m"] = temp
        result["metrics"]["temp_in_range"] = in_range
    except (KeyError, TypeError):
        result["tests"].append({"name": "Temperature in range", "status": "FAIL", "detail": "Field missing"})
        result["metrics"]["temp_in_range"] = False

    # ── Test 5 : Wind speed ≥ 0 ───────────────────────────────────────────────
    try:
        wind = data["current"]["wind_speed_10m"]
        wind_ok = wind >= 0
        result["tests"].append({
            "name": "Wind speed ≥ 0 km/h",
            "status": "PASS" if wind_ok else "FAIL",
            "detail": f"wind_speed_10m = {wind} km/h"
        })
        result["metrics"]["wind_speed_10m"] = wind
        result["metrics"]["wind_positive"] = wind_ok
    except (KeyError, TypeError):
        result["tests"].append({"name": "Wind speed ≥ 0", "status": "FAIL", "detail": "Field missing"})
        result["metrics"]["wind_positive"] = False

    # ── Test 6 : Latency < 2000 ms ────────────────────────────────────────────
    latency_ok = latency < 2000
    result["tests"].append({
        "name": "Latency < 2000 ms",
        "status": "PASS" if latency_ok else "FAIL",
        "detail": f"{latency} ms"
    })

    # ── Summary ───────────────────────────────────────────────────────────────
    total  = len(result["tests"])
    passed = sum(1 for t in result["tests"] if t["status"] == "PASS")
    result["summary"] = {"total": total, "passed": passed, "failed": total - passed}
    result["overall"] = "PASS" if passed == total else "FAIL"

    return result


# ─── Routes ───────────────────────────────────────────────────────────────────

@app.route("/run")
def run():
    result = run_tests()
    history = load_results()
    history.append(result)
    save_results(history)
    return jsonify(result)

@app.route("/api/results")
def api_results():
    return jsonify(load_results())

@app.route("/")
def index():
    history = load_results()

    # Compute QoS stats
    total_runs  = len(history)
    pass_runs   = sum(1 for r in history if r.get("overall") == "PASS")
    availability = round(pass_runs / total_runs * 100, 1) if total_runs else 0

    latencies = [r["metrics"].get("latency_ms") for r in history if r.get("metrics", {}).get("latency_ms") is not None]
    avg_latency = round(sum(latencies) / len(latencies), 1) if latencies else 0
    max_latency = round(max(latencies), 1) if latencies else 0
    min_latency = round(min(latencies), 1) if latencies else 0

    last = history[-1] if history else None

    HTML = r"""<!DOCTYPE html>
<html lang="fr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>API Monitor — Open-Meteo</title>
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=DM+Sans:wght@300;500;700&display=swap" rel="stylesheet">
<style>
  :root {
    --bg: #0b0f1a;
    --panel: #111827;
    --border: #1f2d45;
    --accent: #00e5ff;
    --accent2: #ff6b35;
    --pass: #22d3a5;
    --fail: #ff4d6d;
    --text: #e2eaf8;
    --muted: #5c7094;
    --mono: 'Space Mono', monospace;
    --sans: 'DM Sans', sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--sans);
    min-height: 100vh;
  }

  /* Grid background */
  body::before {
    content: '';
    position: fixed;
    inset: 0;
    background-image:
      linear-gradient(rgba(0,229,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,229,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
  }

  header {
    border-bottom: 1px solid var(--border);
    padding: 1.5rem 2rem;
    display: flex;
    align-items: center;
    justify-content: space-between;
    position: sticky; top: 0;
    background: rgba(11,15,26,0.92);
    backdrop-filter: blur(8px);
    z-index: 100;
  }
  .logo {
    font-family: var(--mono);
    font-size: 1rem;
    color: var(--accent);
    letter-spacing: .05em;
  }
  .logo span { color: var(--muted); }

  .status-pill {
    font-family: var(--mono);
    font-size: .75rem;
    padding: .3rem .9rem;
    border-radius: 999px;
    letter-spacing: .1em;
    font-weight: 700;
  }
  .status-pill.pass { background: rgba(34,211,165,.15); color: var(--pass); border: 1px solid var(--pass); }
  .status-pill.fail { background: rgba(255,77,109,.15); color: var(--fail); border: 1px solid var(--fail); }
  .status-pill.none { background: rgba(92,112,148,.15); color: var(--muted); border: 1px solid var(--muted); }

  main { max-width: 1100px; margin: 0 auto; padding: 2.5rem 2rem 4rem; }

  h1 { font-size: 2rem; font-weight: 700; margin-bottom: .3rem; }
  .subtitle { color: var(--muted); font-size: .9rem; font-family: var(--mono); }

  /* KPI row */
  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 1rem;
    margin: 2.5rem 0;
  }
  .kpi {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.4rem 1.6rem;
    position: relative;
    overflow: hidden;
  }
  .kpi::after {
    content: '';
    position: absolute;
    top: 0; left: 0; right: 0;
    height: 2px;
    background: var(--accent);
    opacity: .6;
  }
  .kpi-label {
    font-size: .72rem;
    font-family: var(--mono);
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .12em;
    margin-bottom: .6rem;
  }
  .kpi-value {
    font-family: var(--mono);
    font-size: 2rem;
    font-weight: 700;
    color: var(--accent);
    line-height: 1;
  }
  .kpi-value.good { color: var(--pass); }
  .kpi-value.warn { color: var(--accent2); }
  .kpi-unit { font-size: .8rem; color: var(--muted); margin-top: .3rem; font-family: var(--mono); }

  /* Run button */
  .actions { display: flex; gap: 1rem; margin-bottom: 2rem; align-items: center; }
  .btn {
    font-family: var(--mono);
    font-size: .82rem;
    font-weight: 700;
    letter-spacing: .08em;
    padding: .75rem 1.8rem;
    border-radius: 8px;
    border: none;
    cursor: pointer;
    transition: all .2s;
    text-decoration: none;
  }
  .btn-primary {
    background: var(--accent);
    color: var(--bg);
  }
  .btn-primary:hover { background: #33eeff; transform: translateY(-1px); box-shadow: 0 4px 20px rgba(0,229,255,.3); }
  .btn-ghost {
    background: transparent;
    color: var(--muted);
    border: 1px solid var(--border);
  }
  .btn-ghost:hover { color: var(--text); border-color: var(--muted); }

  /* Two-column layout */
  .grid-2 { display: grid; grid-template-columns: 1fr 1fr; gap: 1.5rem; margin-bottom: 2rem; }
  @media (max-width: 720px) { .grid-2 { grid-template-columns: 1fr; } }

  .card {
    background: var(--panel);
    border: 1px solid var(--border);
    border-radius: 12px;
    padding: 1.5rem;
  }
  .card-title {
    font-family: var(--mono);
    font-size: .75rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .12em;
    margin-bottom: 1.2rem;
    display: flex;
    align-items: center;
    gap: .5rem;
  }
  .card-title::before {
    content: '';
    width: 6px; height: 6px;
    border-radius: 50%;
    background: var(--accent);
    display: inline-block;
  }

  /* Test table */
  .test-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: .65rem 0;
    border-bottom: 1px solid var(--border);
    font-size: .88rem;
  }
  .test-row:last-child { border-bottom: none; }
  .test-name { color: var(--text); flex: 1; }
  .test-detail { color: var(--muted); font-size: .8rem; font-family: var(--mono); margin: 0 1rem; }
  .badge {
    font-family: var(--mono);
    font-size: .68rem;
    font-weight: 700;
    padding: .25rem .7rem;
    border-radius: 4px;
    letter-spacing: .08em;
    min-width: 50px;
    text-align: center;
  }
  .badge.pass { background: rgba(34,211,165,.15); color: var(--pass); }
  .badge.fail { background: rgba(255,77,109,.15); color: var(--fail); }

  /* History table */
  .hist-table { width: 100%; border-collapse: collapse; font-size: .82rem; }
  .hist-table th {
    font-family: var(--mono);
    font-size: .68rem;
    color: var(--muted);
    text-transform: uppercase;
    letter-spacing: .1em;
    text-align: left;
    padding: .5rem .8rem;
    border-bottom: 1px solid var(--border);
  }
  .hist-table td {
    padding: .55rem .8rem;
    border-bottom: 1px solid rgba(31,45,69,.5);
    font-family: var(--mono);
    color: var(--muted);
  }
  .hist-table tr:last-child td { border-bottom: none; }
  .hist-table tr:hover td { background: rgba(0,229,255,.03); }
  td.ts { color: var(--text); font-size: .78rem; }

  /* Latency sparkline area */
  .spark-wrap { margin-top: .5rem; }
  .spark-bar-row { display: flex; align-items: flex-end; gap: 3px; height: 60px; }
  .spark-bar {
    flex: 1;
    background: var(--accent);
    opacity: .5;
    border-radius: 3px 3px 0 0;
    min-height: 2px;
    transition: opacity .2s;
    position: relative;
  }
  .spark-bar:hover { opacity: 1; }
  .spark-label { font-family: var(--mono); font-size: .65rem; color: var(--muted); text-align: center; margin-top: .3rem; }

  /* Responsive */
  @media (max-width: 500px) {
    .hist-table th:nth-child(3),
    .hist-table td:nth-child(3) { display: none; }
  }

  .ts-now { font-family: var(--mono); font-size: .75rem; color: var(--muted); }

  .empty { color: var(--muted); font-family: var(--mono); font-size: .85rem; text-align: center; padding: 2rem 0; }
</style>
</head>
<body>

<header>
  <div class="logo">// <span>api</span>monitor<span>.py</span></div>
  <div>
    {% if last %}
      <span class="status-pill {{ 'pass' if last.overall == 'PASS' else 'fail' }}">
        {{ last.overall }}
      </span>
    {% else %}
      <span class="status-pill none">NO DATA</span>
    {% endif %}
  </div>
</header>

<main>
  <h1>{{ api_name }}</h1>
  <p class="subtitle">{{ api_url }}</p>

  <div class="kpi-grid">
    <div class="kpi">
      <div class="kpi-label">Disponibilité</div>
      <div class="kpi-value {{ 'good' if availability >= 90 else 'warn' }}">{{ availability }}</div>
      <div class="kpi-unit">% ({{ pass_runs }}/{{ total_runs }} runs)</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Latence moy.</div>
      <div class="kpi-value {{ 'good' if avg_latency < 800 else 'warn' }}">{{ avg_latency }}</div>
      <div class="kpi-unit">ms</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Latence min/max</div>
      <div class="kpi-value" style="font-size:1.3rem">{{ min_latency }}&nbsp;/&nbsp;{{ max_latency }}</div>
      <div class="kpi-unit">ms</div>
    </div>
    <div class="kpi">
      <div class="kpi-label">Executions</div>
      <div class="kpi-value">{{ total_runs }}</div>
      <div class="kpi-unit">tests enregistrés</div>
    </div>
  </div>

  <div class="actions">
    <a href="/run" class="btn btn-primary">▶ LANCER UN TEST</a>
    <a href="/api/results" class="btn btn-ghost">JSON RAW</a>
    <span class="ts-now" id="clock"></span>
  </div>

  <div class="grid-2">

    <!-- Last test results -->
    <div class="card">
      <div class="card-title">Dernier test</div>
      {% if last %}
        {% for t in last.tests %}
        <div class="test-row">
          <span class="test-name">{{ t.name }}</span>
          <span class="test-detail">{{ t.detail }}</span>
          <span class="badge {{ 'pass' if t.status == 'PASS' else 'fail' }}">{{ t.status }}</span>
        </div>
        {% endfor %}
        <div style="margin-top:1rem; font-family:var(--mono); font-size:.72rem; color:var(--muted);">
          {{ last.timestamp }}
        </div>
      {% else %}
        <div class="empty">Aucun test encore lancé.<br>Cliquez sur ▶ LANCER UN TEST</div>
      {% endif %}
    </div>

    <!-- Latency sparkline -->
    <div class="card">
      <div class="card-title">Historique latences</div>
      {% if latencies %}
      <div class="spark-wrap">
        <div class="spark-bar-row">
          {% set max_l = latencies | max %}
          {% for l in latencies[-30:] %}
          <div class="spark-bar"
               style="height: {{ [(l / max_l * 100), 4] | max }}%;"
               title="{{ l }} ms"></div>
          {% endfor %}
        </div>
        <div class="spark-label">← {{ [latencies|length, 30]|min }} dernières mesures (ms)</div>
      </div>
      {% else %}
        <div class="empty">Pas encore de données.</div>
      {% endif %}
    </div>

  </div>

  <!-- History table -->
  <div class="card">
    <div class="card-title">Tableau des résultats</div>
    {% if history %}
    <table class="hist-table">
      <thead>
        <tr>
          <th>Timestamp (UTC)</th>
          <th>Résultat</th>
          <th>Latence</th>
          <th>Tests</th>
          <th>HTTP</th>
        </tr>
      </thead>
      <tbody>
        {% for r in history | reverse %}
        <tr>
          <td class="ts">{{ r.timestamp[:19].replace('T',' ') }}</td>
          <td><span class="badge {{ 'pass' if r.overall == 'PASS' else 'fail' }}">{{ r.get('overall','?') }}</span></td>
          <td>{{ r.metrics.get('latency_ms','—') }} ms</td>
          <td>{{ r.summary.passed }}/{{ r.summary.total }}</td>
          <td>{{ r.metrics.get('status_code','—') }}</td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
    {% else %}
      <div class="empty">Aucun historique disponible.</div>
    {% endif %}
  </div>

</main>

<script>
  // Live clock
  function tick() {
    const el = document.getElementById('clock');
    if (el) el.textContent = new Date().toUTCString();
  }
  tick(); setInterval(tick, 1000);
</script>
</body>
</html>"""

    return render_template_string(
        HTML,
        api_name=API_NAME,
        api_url=API_URL,
        history=history,
        last=last,
        availability=availability,
        avg_latency=avg_latency,
        min_latency=min_latency,
        max_latency=max_latency,
        total_runs=total_runs,
        pass_runs=pass_runs,
        latencies=latencies
    )


if __name__ == "__main__":
    app.run(debug=True)
