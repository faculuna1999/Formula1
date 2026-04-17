"""Aplicacion de campeonato estilo Formula 1 para 20 participantes."""

import hashlib
import json
import logging
import os
import secrets
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path

from flask import Flask, jsonify, render_template, request, session
from flask_cors import CORS

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
CORS(app)

# Clave secreta para firmar sesiones (se genera aleatoria si no se configura)
app.secret_key = os.getenv("SECRET_KEY") or secrets.token_hex(32)

# Credenciales de acceso configurables por variables de entorno
ADMIN_USER = os.getenv("ADMIN_USER", "admin")
_raw_password = os.getenv("ADMIN_PASSWORD", "f1demo2025")
ADMIN_PASSWORD_HASH = hashlib.sha256(_raw_password.encode()).hexdigest()


def login_required(f):
    """Decorador que protege endpoints de escritura."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("authenticated"):
            return jsonify({"status": "error", "message": "Se requiere autenticacion.", "auth_required": True}), 401
        return f(*args, **kwargs)
    return decorated


script_name = os.getenv("SCRIPT_NAME", "facu-demo").strip()
if not script_name.startswith("/"):
    script_name = f"/{script_name}"
script_name = script_name.rstrip("/") or "/facu-demo"
app.config["APPLICATION_ROOT"] = script_name

DATA_FILE = Path("data/season.json")
POINTS_BY_POSITION = {
    1: 25,
    2: 18,
    3: 15,
    4: 12,
    5: 10,
    6: 8,
    7: 6,
    8: 4,
    9: 2,
    10: 1,
}

TRACKS = [
    # R1 — 16 Mar — Australia
    "Albert Park Circuit",
    # R2 — 23 Mar — China
    "Shanghai International Circuit",
    # R3 — 6 Abr — Japón
    "Suzuka Circuit",
    # R4 — 13 Abr — Bahréin
    "Bahrain International Circuit",
    # R5 — 20 Abr — Arabia Saudita
    "Jeddah Corniche Circuit",
    # R6 — 4 May — Miami
    "Miami International Autodrome",
    # R7 — 18 May — Emilia Romagna
    "Autodromo Enzo e Dino Ferrari (Imola)",
    # R8 — 25 May — Mónaco
    "Circuit de Monaco",
    # R9 — 1 Jun — España
    "Circuit de Barcelona-Catalunya",
    # R10 — 15 Jun — Canadá
    "Circuit Gilles Villeneuve",
    # R11 — 29 Jun — Austria
    "Red Bull Ring",
    # R12 — 6 Jul — Gran Bretaña
    "Silverstone Circuit",
    # R13 — 27 Jul — Bélgica
    "Circuit de Spa-Francorchamps",
    # R14 — 3 Ago — Hungría
    "Hungaroring",
    # R15 — 31 Ago — Países Bajos
    "Circuit Zandvoort",
    # R16 — 7 Sep — Italia
    "Autodromo Nazionale Monza",
    # R17 — 21 Sep — Azerbaiyán
    "Baku City Circuit",
    # R18 — 5 Oct — Singapur
    "Marina Bay Street Circuit",
    # R19 — 19 Oct — Estados Unidos
    "Circuit of the Americas",
    # R20 — 26 Oct — México
    "Autodromo Hermanos Rodriguez",
    # R21 — 9 Nov — Brasil
    "Interlagos (Sao Paulo)",
    # R22 — 22 Nov — Las Vegas
    "Las Vegas Strip Circuit",
    # R23 — 30 Nov — Qatar
    "Lusail International Circuit",
    # R24 — 7 Dic — Abu Dabi
    "Yas Marina Circuit",
]


def default_participants():
    return [f"Participante {idx}" for idx in range(1, 21)]


def next_monday(start=None):
    today = start or date.today()
    days_ahead = (7 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def build_default_state():
    configured_start = parse_iso_date(os.getenv("SEASON_START_DATE"))
    return {
        "participants": default_participants(),
        "season_start_date": (configured_start or next_monday()).isoformat(),
        "tracks": TRACKS,
        "results": {},
        "qualifying": {},
        "dates": {},
    }


def save_state(state):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_state():
    if not DATA_FILE.exists():
        state = build_default_state()
        save_state(state)
        return state

    try:
        state = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Archivo de estado invalido. Se recrea estado por defecto.")
        state = build_default_state()
        save_state(state)
        return state

    participants = state.get("participants", [])
    if len(participants) != 20:
        state["participants"] = default_participants()

    state["tracks"] = state.get("tracks", TRACKS)
    state["results"] = state.get("results", {})
    state["qualifying"] = state.get("qualifying", {})
    state["dates"] = state.get("dates", {})
    state["season_start_date"] = state.get("season_start_date", next_monday().isoformat())
    return state


def normalize_participants(raw_names):
    names = [name.strip() for name in raw_names if isinstance(name, str)]
    if len(names) != 20:
        return None, "Debes ingresar exactamente 20 participantes."
    if any(not name for name in names):
        return None, "Todos los nombres deben estar completos."

    lowered = [name.lower() for name in names]
    if len(set(lowered)) != 20:
        return None, "Los nombres deben ser unicos."

    return names, None


def parse_iso_date(raw):
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def build_schedule(state):
    start = parse_iso_date(state.get("season_start_date")) or next_monday()
    races = []
    for idx, track_name in enumerate(state["tracks"]):
        fallback_date = (start + timedelta(days=7 * idx)).isoformat()
        race_date = state["dates"].get(str(idx)) or fallback_date
        races.append(
            {
                "race_index": idx,
                "round": idx + 1,
                "track": track_name,
                "date": race_date,
                "has_result": str(idx) in state["results"],
                "has_qualifying": str(idx) in state["qualifying"],
            }
        )
    return races


def validate_classification(classification, participants):
    if not isinstance(classification, list):
        return "La clasificacion debe ser una lista de nombres."

    cleaned = [item.strip() for item in classification if isinstance(item, str)]
    if len(cleaned) != 20:
        return "La clasificacion debe tener exactamente 20 posiciones."

    if any(not name for name in cleaned):
        return "La clasificacion contiene nombres vacios."

    cleaned_set = set(cleaned)
    participants_set = set(participants)
    if cleaned_set != participants_set:
        missing = sorted(participants_set - cleaned_set)
        extras = sorted(cleaned_set - participants_set)
        message_parts = []
        if missing:
            message_parts.append(f"Faltan participantes: {', '.join(missing)}")
        if extras:
            message_parts.append(f"Nombres no registrados: {', '.join(extras)}")
        return "; ".join(message_parts)

    if len(cleaned_set) != 20:
        return "Hay nombres repetidos en la clasificacion."

    return None


def compute_leaderboard(state):
    stats = {}
    for name in state["participants"]:
        stats[name] = {
            "name": name,
            "points": 0,
            "wins": 0,
            "podiums": 0,
            "top10": 0,
            "best_finish": 99,
            "races_finished": 0,
            "position_history": [],
        }

    for race_idx in range(len(state["tracks"])):
        classification = state["results"].get(str(race_idx))
        if not classification:
            continue

        for pos, name in enumerate(classification, start=1):
            driver_stats = stats[name]
            driver_stats["points"] += POINTS_BY_POSITION.get(pos, 0)
            driver_stats["races_finished"] += 1
            driver_stats["best_finish"] = min(driver_stats["best_finish"], pos)
            driver_stats["position_history"].append(pos)
            if pos == 1:
                driver_stats["wins"] += 1
            if pos <= 3:
                driver_stats["podiums"] += 1
            if pos <= 10:
                driver_stats["top10"] += 1

    leaderboard = list(stats.values())
    leaderboard.sort(
        key=lambda item: (
            -item["points"],
            -item["wins"],
            -item["podiums"],
            item["best_finish"],
            item["name"].lower(),
        )
    )

    for idx, row in enumerate(leaderboard, start=1):
        row["rank"] = idx
        if row["best_finish"] == 99:
            row["best_finish"] = None

    return leaderboard


def get_state_payload():
    state = load_state()
    schedule = build_schedule(state)
    leaderboard = compute_leaderboard(state)
    completed_races = sum(1 for race in schedule if race["has_result"])
    next_race = next((race for race in schedule if not race["has_result"]), None)

    return {
        "participants": state["participants"],
        "season_start_date": state["season_start_date"],
        "points_system": POINTS_BY_POSITION,
        "schedule": schedule,
        "results": state["results"],
        "qualifying": state["qualifying"],
        "dates": state["dates"],
        "leaderboard": leaderboard,
        "completed_races": completed_races,
        "total_races": len(schedule),
        "next_race": next_race,
        "prefix": script_name,
    }


@app.route("/")
@app.route(f"{script_name}/")
def index():
    return render_template("index.html", prefix=script_name)


@app.route("/api/login", methods=["POST"])
@app.route(f"{script_name}/api/login", methods=["POST"])
def api_login():
    data = request.get_json(silent=True) or {}
    username = (data.get("username") or "").strip()
    password = data.get("password") or ""
    password_hash = hashlib.sha256(password.encode()).hexdigest()

    if username == ADMIN_USER and password_hash == ADMIN_PASSWORD_HASH:
        session["authenticated"] = True
        session.permanent = False
        return jsonify({"status": "success", "message": "Sesion iniciada."}), 200

    return jsonify({"status": "error", "message": "Usuario o contraseña incorrectos."}), 401


@app.route("/api/logout", methods=["POST"])
@app.route(f"{script_name}/api/logout", methods=["POST"])
def api_logout():
    session.clear()
    return jsonify({"status": "success", "message": "Sesion cerrada."}), 200


@app.route("/api/auth-status", methods=["GET"])
@app.route(f"{script_name}/api/auth-status", methods=["GET"])
def api_auth_status():
    return jsonify({"authenticated": bool(session.get("authenticated"))}), 200


@app.route("/health")
@app.route(f"{script_name}/health")
def health():
    return jsonify({"status": "healthy", "timestamp": datetime.now().isoformat()}), 200


@app.route("/api/state", methods=["GET"])
@app.route(f"{script_name}/api/state", methods=["GET"])
def api_state():
    return jsonify(get_state_payload()), 200


@app.route("/api/participants", methods=["POST"])
@app.route(f"{script_name}/api/participants", methods=["POST"])
@login_required
def api_update_participants():
    data = request.get_json(silent=True) or {}
    participants, err = normalize_participants(data.get("participants", []))
    if err:
        return jsonify({"status": "error", "message": err}), 400

    season_start_date = parse_iso_date(data.get("season_start_date"))
    if data.get("season_start_date") and season_start_date is None:
        return jsonify({"status": "error", "message": "Fecha invalida. Usa formato YYYY-MM-DD."}), 400

    state = load_state()
    state["participants"] = participants
    state["results"] = {}
    state["qualifying"] = {}
    state["dates"] = {}
    if season_start_date is not None:
        state["season_start_date"] = season_start_date.isoformat()

    save_state(state)
    return jsonify({"status": "success", "message": "Participantes guardados y campeonato reiniciado."}), 200


@app.route("/api/results", methods=["POST"])
@app.route(f"{script_name}/api/results", methods=["POST"])
@login_required
def api_set_result():
    data = request.get_json(silent=True) or {}

    race_index = data.get("race_index")
    if not isinstance(race_index, int):
        return jsonify({"status": "error", "message": "race_index debe ser un numero entero."}), 400

    state = load_state()
    if race_index < 0 or race_index >= len(state["tracks"]):
        return jsonify({"status": "error", "message": "race_index fuera de rango."}), 400

    # Fecha personalizada (opcional)
    custom_date = parse_iso_date(data.get("date"))
    if data.get("date") and custom_date is None:
        return jsonify({"status": "error", "message": "Fecha invalida. Usa formato YYYY-MM-DD."}), 400
    if custom_date:
        state["dates"][str(race_index)] = custom_date.isoformat()

    # Clasificacion (qualy) — opcional
    qualifying = data.get("qualifying")
    if qualifying is not None:
        q_err = validate_classification(qualifying, state["participants"])
        if q_err:
            return jsonify({"status": "error", "message": f"Clasificacion (qualy): {q_err}"}), 400
        state["qualifying"][str(race_index)] = qualifying

    # Resultado de carrera — opcional
    classification = data.get("classification")
    if classification is not None:
        r_err = validate_classification(classification, state["participants"])
        if r_err:
            return jsonify({"status": "error", "message": f"Resultado de carrera: {r_err}"}), 400
        state["results"][str(race_index)] = classification

    save_state(state)
    return jsonify({"status": "success", "message": "Datos guardados correctamente."}), 200


@app.route("/api/reset", methods=["POST"])
@app.route(f"{script_name}/api/reset", methods=["POST"])
@login_required
def api_reset_results():
    state = load_state()
    state["results"] = {}
    state["qualifying"] = {}
    state["dates"] = {}
    save_state(state)
    return jsonify({"status": "success", "message": "Se reiniciaron los resultados del campeonato."}), 200


if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("FLASK_PORT", 3000))
    debug = os.getenv("FLASK_ENV", "production") == "development"

    logger.info("Iniciando campeonato F1 en %s:%s", host, port)
    logger.info("Prefix activo: %s", script_name)
    app.run(host=host, port=port, debug=debug)
