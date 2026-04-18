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
CORS(app, supports_credentials=True)

# Clave secreta para firmar sesiones — fija para que las sesiones sobrevivan reinicios
_secret_key_file = Path(__file__).parent / ".secret_key"
if not _secret_key_file.exists():
    _secret_key_file.write_text(secrets.token_hex(32))
app.secret_key = os.getenv("SECRET_KEY") or _secret_key_file.read_text().strip()

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

BASE_DIR = Path(__file__).parent
DATA_FILE = BASE_DIR / "data/season.json"
DATA_SEED_FILE = BASE_DIR / "data/season.seed.json"
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

TEAMS = [
    "Red Bull Racing",
    "McLaren",
    "Ferrari",
    "Mercedes",
    "Aston Martin",
    "Alpine",
    "Haas",
    "Williams",
    "Racing Bulls",
    "Kick Sauber",
]

TEAM_ALIASES = {
    "Audi": "Kick Sauber",
}


def default_participants():
    return []


def next_monday(start=None):
    today = start or date.today()
    days_ahead = (7 - today.weekday()) % 7
    if days_ahead == 0:
        days_ahead = 7
    return today + timedelta(days=days_ahead)


def build_default_state():
    configured_start = parse_iso_date(os.getenv("SEASON_START_DATE"))
    participants = default_participants()
    # Distribute participants across teams (2 per team for 20 participants and 10 teams)
    teams_map = {}
    for idx, name in enumerate(participants):
        team_idx = idx % len(TEAMS)
        teams_map[name] = TEAMS[team_idx]
    
    return {
        "participants": participants,
        "season_start_date": (configured_start or next_monday()).isoformat(),
        "tracks": TRACKS,
        "results": {},
        "qualifying": {},
        "qualifying_details": {},
        "race_details": {},
        "player_images": {},
        "player_bios": {},
        "dates": {},
        "teams": teams_map,
    }


def save_state(state):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_seed_state():
    if not DATA_SEED_FILE.exists():
        return None

    try:
        return json.loads(DATA_SEED_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Archivo seed invalido. Se recrea estado por defecto.")
        return None


def load_state():
    if not DATA_FILE.exists():
        state = load_seed_state() or build_default_state()
        save_state(state)
        return state

    try:
        state = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Archivo de estado invalido. Se recrea estado por defecto.")
        state = load_seed_state() or build_default_state()
        save_state(state)
        return state

    participants = state.get("participants", [])
    if not isinstance(participants, list):
        state["participants"] = default_participants()
    else:
        cleaned_participants = [name.strip() for name in participants if isinstance(name, str) and name.strip()]
        lowered = [name.lower() for name in cleaned_participants]
        has_unique_names = len(set(lowered)) == len(cleaned_participants)
        valid_count = len(cleaned_participants) == 0 or (2 <= len(cleaned_participants) <= 20)
        if has_unique_names and valid_count:
            state["participants"] = cleaned_participants
        else:
            state["participants"] = default_participants()

    state["tracks"] = state.get("tracks", TRACKS)
    state["results"] = state.get("results", {})
    state["qualifying"] = state.get("qualifying", {})
    state["qualifying_details"] = state.get("qualifying_details", {})
    state["race_details"] = state.get("race_details", {})
    state["player_images"] = state.get("player_images", {})
    state["player_bios"] = state.get("player_bios", {})
    state["dates"] = state.get("dates", {})
    state["season_start_date"] = state.get("season_start_date", next_monday().isoformat())
    # Ensure teams are assigned for all participants
    existing_teams = state.get("teams", {})
    existing_images = state.get("player_images", {})
    new_teams = {}
    new_images = {}
    for idx, name in enumerate(state["participants"]):
        normalized_team = canonical_team_name(existing_teams.get(name))
        if normalized_team not in TEAMS:
            normalized_team = TEAMS[idx % len(TEAMS)]
        new_teams[name] = normalized_team
        image_value = existing_images.get(name)
        if isinstance(image_value, str) and image_value.strip():
            new_images[name] = image_value
    state["teams"] = new_teams
    state["player_images"] = new_images
    existing_bios = state.get("player_bios", {})
    new_bios = {}
    for name in state["participants"]:
        if isinstance(existing_bios.get(name), dict):
            new_bios[name] = existing_bios[name]
    state["player_bios"] = new_bios
    return state


def normalize_participants(raw_names):
    names = [name.strip() for name in raw_names if isinstance(name, str) and name.strip()]
    if len(names) < 2 or len(names) > 20:
        return None, "Debes ingresar entre 2 y 20 participantes."

    lowered = [name.lower() for name in names]
    if len(set(lowered)) != len(names):
        return None, "Los nombres deben ser unicos."

    return names, None


def parse_iso_date(raw):
    try:
        return datetime.strptime(raw, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def canonical_team_name(raw_team):
    if not isinstance(raw_team, str):
        return None
    cleaned = raw_team.strip()
    return TEAM_ALIASES.get(cleaned, cleaned)


def normalize_race_status(raw_status):
    if not isinstance(raw_status, str):
        return "FINISHED"
    status = raw_status.strip().upper()
    if status in {"DNF", "DNS"}:
        return status
    return "FINISHED"


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
    num_participants = len(participants)
    if len(cleaned) != num_participants:
        return f"La clasificacion debe tener exactamente {num_participants} posiciones."

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

    if len(cleaned_set) != num_participants:
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
        race_key = str(race_idx)
        detailed_race = state.get("race_details", {}).get(race_key)

        if isinstance(detailed_race, dict) and detailed_race:
            ordered_rows = []
            for driver_name, detail in detailed_race.items():
                if driver_name not in stats or not isinstance(detail, dict):
                    continue
                position = detail.get("position")
                if not isinstance(position, int):
                    continue
                status = normalize_race_status(detail.get("status"))
                ordered_rows.append((position, driver_name, status))

            ordered_rows.sort(key=lambda row: row[0])

            for pos, name, status in ordered_rows:
                if status in {"DNF", "DNS"}:
                    continue
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
            continue

        classification = state["results"].get(race_key)
        if not classification:
            continue

        for pos, name in enumerate(classification, start=1):
            if name not in stats:
                continue
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


def compute_teams_leaderboard(state, driver_leaderboard):
    """Compute constructors championship standings from driver standings."""
    teams_stats = {}
    
    # Initialize teams
    for team_name in TEAMS:
        teams_stats[team_name] = {
            "name": team_name,
            "points": 0,
            "wins": 0,
            "podiums": 0,
            "top10": 0,
            "drivers": [],
        }
    
    # Aggregate driver stats by team
    for driver in driver_leaderboard:
        driver_name = driver["name"]
        team_name = canonical_team_name(state["teams"].get(driver_name, "Unknown"))
        
        if team_name in teams_stats:
            teams_stats[team_name]["points"] += driver["points"]
            teams_stats[team_name]["wins"] += driver["wins"]
            teams_stats[team_name]["podiums"] += driver["podiums"]
            teams_stats[team_name]["top10"] += driver["top10"]
            teams_stats[team_name]["drivers"].append(driver_name)
    
    # Filter out empty teams and convert to list
    teams_list = [team for team in teams_stats.values() if team["drivers"]]
    
    # Sort by points (then wins, podiums as tiebreakers)
    teams_list.sort(
        key=lambda item: (
            -item["points"],
            -item["wins"],
            -item["podiums"],
            item["name"].lower(),
        )
    )
    
    # Add rank
    for idx, team in enumerate(teams_list, start=1):
        team["rank"] = idx
    
    return teams_list

def get_state_payload():
    state = load_state()
    schedule = build_schedule(state)
    leaderboard = compute_leaderboard(state)
    teams_leaderboard = compute_teams_leaderboard(state, leaderboard)
    completed_races = sum(1 for race in schedule if race["has_result"])
    next_race = next((race for race in schedule if not race["has_result"]), None)

    return {
        "participants": state["participants"],
        "season_start_date": state["season_start_date"],
        "points_system": POINTS_BY_POSITION,
        "schedule": schedule,
        "results": state["results"],
        "qualifying": state["qualifying"],
        "qualifying_details": state["qualifying_details"],
        "race_details": state["race_details"],
        "dates": state["dates"],
        "leaderboard": leaderboard,
        "teams": state["teams"],
        "player_images": state["player_images"],
        "player_bios": state["player_bios"],
        "teams_leaderboard": teams_leaderboard,
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

    provided_teams = data.get("teams")
    if provided_teams is not None and not isinstance(provided_teams, dict):
        return jsonify({"status": "error", "message": "teams debe ser un diccionario de participante: equipo."}), 400

    provided_images = data.get("player_images")
    if provided_images is not None and not isinstance(provided_images, dict):
        return jsonify({"status": "error", "message": "player_images debe ser un diccionario de participante: imagen."}), 400

    season_start_date = parse_iso_date(data.get("season_start_date"))
    if data.get("season_start_date") and season_start_date is None:
        return jsonify({"status": "error", "message": "Fecha invalida. Usa formato YYYY-MM-DD."}), 400

    state = load_state()
    existing_teams = state.get("teams", {})
    existing_images = state.get("player_images", {})
    state["participants"] = participants
    new_teams = {}
    new_images = {}
    for idx, name in enumerate(participants):
        preferred_team = canonical_team_name((provided_teams or {}).get(name))
        if preferred_team is not None and preferred_team not in TEAMS:
            return jsonify({"status": "error", "message": f"Equipo desconocido: {preferred_team}"}), 400
        current_team = canonical_team_name(existing_teams.get(name))
        if current_team not in TEAMS:
            current_team = TEAMS[idx % len(TEAMS)]
        new_teams[name] = preferred_team or current_team

        preferred_image = (provided_images or {}).get(name)
        if preferred_image is not None and not isinstance(preferred_image, str):
            return jsonify({"status": "error", "message": f"Imagen invalida para {name}."}), 400
        if isinstance(preferred_image, str) and preferred_image.strip():
            new_images[name] = preferred_image.strip()
        elif isinstance(existing_images.get(name), str) and existing_images.get(name).strip():
            new_images[name] = existing_images.get(name).strip()
    state["teams"] = new_teams
    state["player_images"] = new_images
    if season_start_date is not None:
        state["season_start_date"] = season_start_date.isoformat()

    save_state(state)
    return jsonify({"status": "success", "message": "Participantes guardados correctamente."}), 200


@app.route("/api/player-profile", methods=["POST"])
@app.route(f"{script_name}/api/player-profile", methods=["POST"])
@login_required
def api_update_player_profile():
    data = request.get_json() or {}
    player_name = data.get("name", "").strip()
    profile_data = data.get("profile", {})

    if not player_name:
        return jsonify({"status": "error", "message": "Falta nombre del jugador."}), 400

    state = load_state()
    if player_name not in state["participants"]:
        return jsonify({"status": "error", "message": "Jugador no encontrado."}), 404

    if not isinstance(profile_data, dict):
        return jsonify({"status": "error", "message": "Datos de perfil invalidos."}), 400

    state["player_bios"][player_name] = profile_data
    save_state(state)
    return jsonify({"status": "success", "message": "Perfil actualizado correctamente."}), 200


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
    qualifying_details = data.get("qualifying_details")
    if qualifying_details is not None:
        if not isinstance(qualifying_details, dict):
            return jsonify({"status": "error", "message": "qualifying_details debe ser un objeto."}), 400
        for driver_name in qualifying_details.keys():
            if driver_name not in state["participants"]:
                return jsonify({"status": "error", "message": f"Piloto no registrado en qualy: {driver_name}"}), 400
    if qualifying is not None:
        q_err = validate_classification(qualifying, state["participants"])
        if q_err:
            return jsonify({"status": "error", "message": f"Clasificacion (qualy): {q_err}"}), 400
        state["qualifying"][str(race_index)] = qualifying
    if qualifying_details is not None:
        state["qualifying_details"][str(race_index)] = qualifying_details

    # Resultado de carrera — opcional
    classification = data.get("classification")
    race_details = data.get("race_details")
    if race_details is not None:
        if not isinstance(race_details, dict):
            return jsonify({"status": "error", "message": "race_details debe ser un objeto."}), 400
        for driver_name, detail in race_details.items():
            if driver_name not in state["participants"]:
                return jsonify({"status": "error", "message": f"Piloto no registrado en carrera: {driver_name}"}), 400
            if not isinstance(detail, dict):
                return jsonify({"status": "error", "message": "Cada detalle de carrera debe ser un objeto."}), 400
            detail["status"] = normalize_race_status(detail.get("status"))
    if classification is not None:
        r_err = validate_classification(classification, state["participants"])
        if r_err:
            return jsonify({"status": "error", "message": f"Resultado de carrera: {r_err}"}), 400
        state["results"][str(race_index)] = classification
    if race_details is not None:
        state["race_details"][str(race_index)] = race_details

    save_state(state)
    return jsonify({"status": "success", "message": "Datos guardados correctamente."}), 200


@app.route("/api/reset", methods=["POST"])
@app.route(f"{script_name}/api/reset", methods=["POST"])
@login_required
def api_reset_results():
    state = load_state()
    state["results"] = {}
    state["qualifying"] = {}
    state["qualifying_details"] = {}
    state["race_details"] = {}
    state["dates"] = {}
    save_state(state)
    return jsonify({"status": "success", "message": "Se reiniciaron los resultados del campeonato."}), 200


@app.route("/api/teams", methods=["POST"])
@app.route(f"{script_name}/api/teams", methods=["POST"])
@login_required
def api_update_teams():
    """Update team assignments for participants."""
    data = request.get_json(silent=True) or {}
    teams_map = data.get("teams", {})
    
    if not isinstance(teams_map, dict):
        return jsonify({"status": "error", "message": "teams debe ser un diccionario de participante: equipo."}), 400
    
    state = load_state()
    
    # Validate that all participants have a team assignment
    for participant in state["participants"]:
        if participant not in teams_map:
            return jsonify({"status": "error", "message": f"Falta asignar equipo a {participant}."}), 400
        
        assigned_team = canonical_team_name(teams_map[participant])
        if assigned_team not in TEAMS:
            return jsonify({"status": "error", "message": f"Equipo desconocido: {assigned_team}"}), 400
        teams_map[participant] = assigned_team
    
    state["teams"] = teams_map
    save_state(state)
    return jsonify({"status": "success", "message": "Equipos asignados correctamente."}), 200

if __name__ == "__main__":
    host = os.getenv("FLASK_HOST", "0.0.0.0")
    port = int(os.getenv("PORT") or os.getenv("FLASK_PORT", 3000))
    debug = os.getenv("FLASK_ENV", "production") == "development"

    logger.info("Iniciando campeonato F1 en %s:%s", host, port)
    logger.info("Prefix activo: %s", script_name)
    app.run(host=host, port=port, debug=debug)
