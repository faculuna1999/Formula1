"""Aplicacion de campeonato estilo Formula 1 para 20 participantes."""

import base64
import hashlib
import json
import logging
import os
import re
import secrets
import time
from datetime import date, datetime, timedelta
from functools import wraps
from pathlib import Path
from urllib.parse import quote

import requests
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

CLOUDINARY_CLOUD_NAME = os.getenv("CLOUDINARY_CLOUD_NAME", "").strip()
CLOUDINARY_API_KEY = os.getenv("CLOUDINARY_API_KEY", "").strip()
CLOUDINARY_API_SECRET = os.getenv("CLOUDINARY_API_SECRET", "").strip()
COMISARIO_PUBLIC_ID = "facu-demo/comisario"
STATE_PUBLIC_ID = "facu-demo/state/season.json"
TV_VIDEO_CATEGORIES = {
    "epic_fails": "Epic fails",
    "mejores_adelantamientos": "Mejores adelantamientos",
}
REMOTE_STATE_SYNC_ENABLED = os.getenv("REMOTE_STATE_SYNC", "true").strip().lower() not in {"0", "false", "no"}

_CLOUDINARY_CACHE = {
    "expires_at": 0,
    "resources": {},
}

_CLOUDINARY_TV_CACHE = {
    "expires_at": 0,
    "clips": {},
}


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


def cloudinary_is_configured():
    return bool(CLOUDINARY_CLOUD_NAME and CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET)


def remote_state_is_configured():
    return REMOTE_STATE_SYNC_ENABLED and cloudinary_is_configured()


def slugify_identifier(value):
    text = (value or "").strip().lower()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-") or "unknown"


def player_public_id(player_name):
    return f"facu-demo/players/{slugify_identifier(player_name)}"


def clip_public_id(category, title):
    category_slug = slugify_identifier(category)
    title_slug = slugify_identifier(title)[:40]
    return f"facu-demo/tv/{category_slug}/{int(time.time())}-{title_slug}"


CATEGORY_SLUG_TO_KEY = {slugify_identifier(key): key for key in TV_VIDEO_CATEGORIES}


def sanitize_cloudinary_context_value(value):
    text = (value or "").strip()
    # Cloudinary context uses key=value|key=value syntax.
    return text.replace("|", " ").replace("=", "-")[:200]


def parse_data_image(data_url):
    match = re.match(r"^data:(image/[a-zA-Z0-9.+-]+);base64,(.+)$", data_url or "", re.DOTALL)
    if not match:
        return None, None, None

    mime_type = match.group(1).lower()
    raw_base64 = match.group(2)
    try:
        binary = base64.b64decode(raw_base64, validate=True)
    except Exception:
        return None, None, None

    extension_map = {
        "image/jpeg": "jpg",
        "image/jpg": "jpg",
        "image/png": "png",
        "image/webp": "webp",
        "image/gif": "gif",
    }
    ext = extension_map.get(mime_type, "jpg")
    return mime_type, ext, binary


def sign_cloudinary_params(params):
    sorted_items = sorted((key, value) for key, value in params.items() if value is not None and value != "")
    payload = "&".join(f"{key}={value}" for key, value in sorted_items)
    return hashlib.sha1(f"{payload}{CLOUDINARY_API_SECRET}".encode("utf-8")).hexdigest()


def upload_data_image_to_cloudinary(data_url, public_id):
    mime_type, ext, binary = parse_data_image(data_url)
    if mime_type is None or binary is None:
        raise ValueError("La imagen no tiene un formato data URL valido.")

    if not cloudinary_is_configured():
        raise RuntimeError("Cloudinary no esta configurado.")

    upload_url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/image/upload"
    timestamp = int(time.time())
    params_to_sign = {
        "timestamp": timestamp,
        "public_id": public_id,
        "overwrite": "true",
        "invalidate": "true",
    }
    signature = sign_cloudinary_params(params_to_sign)

    payload = {
        **params_to_sign,
        "api_key": CLOUDINARY_API_KEY,
        "signature": signature,
    }
    files = {
        "file": (f"upload.{ext}", binary, mime_type),
    }

    response = requests.post(upload_url, data=payload, files=files, timeout=45)
    if response.status_code >= 400:
        raise RuntimeError(f"Cloudinary error ({response.status_code}): {response.text[:250]}")

    data = response.json()
    secure_url = data.get("secure_url")
    if not isinstance(secure_url, str) or not secure_url.strip():
        raise RuntimeError("Cloudinary no devolvio secure_url.")

    return secure_url.strip()


def upload_binary_to_cloudinary(binary, mime_type, filename, public_id, resource_type, extra_upload_params=None):
    if not cloudinary_is_configured():
        raise RuntimeError("Cloudinary no esta configurado.")

    upload_url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/{resource_type}/upload"
    timestamp = int(time.time())
    params_to_sign = {
        "timestamp": timestamp,
        "public_id": public_id,
        "overwrite": "true",
        "invalidate": "true",
    }
    if isinstance(extra_upload_params, dict):
        for key, value in extra_upload_params.items():
            if value is None:
                continue
            text_value = str(value).strip()
            if not text_value:
                continue
            # Cloudinary requires additional upload parameters to be part of the signature.
            params_to_sign[key] = text_value

    signature = sign_cloudinary_params(params_to_sign)

    payload = {
        **params_to_sign,
        "api_key": CLOUDINARY_API_KEY,
        "signature": signature,
    }
    files = {
        "file": (filename, binary, mime_type),
    }

    response = requests.post(upload_url, data=payload, files=files, timeout=90)
    if response.status_code >= 400:
        raise RuntimeError(f"Cloudinary error ({response.status_code}): {response.text[:250]}")

    data = response.json()
    secure_url = data.get("secure_url")
    if not isinstance(secure_url, str) or not secure_url.strip():
        raise RuntimeError("Cloudinary no devolvio secure_url.")

    return secure_url.strip()


def upload_state_to_cloudinary(state):
    payload = json.dumps(state, indent=2).encode("utf-8")
    upload_binary_to_cloudinary(
        binary=payload,
        mime_type="application/json",
        filename="season.json",
        public_id=STATE_PUBLIC_ID,
        resource_type="raw",
    )


def load_state_from_cloudinary():
    if not remote_state_is_configured():
        return None

    resource_url = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/resources/raw/upload"
    response = requests.get(
        resource_url,
        params={
            "prefix": "facu-demo/state/",
            "max_results": 100,
        },
        auth=(CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET),
        timeout=30,
    )
    if response.status_code >= 400:
        logger.warning("No se pudo consultar el estado remoto en Cloudinary: %s", response.text[:250])
        return None

    resources = response.json().get("resources") or []
    secure_url = ""
    for resource in resources:
        if (resource.get("public_id") or "").strip() == STATE_PUBLIC_ID:
            secure_url = (resource.get("secure_url") or "").strip()
            break
    if not secure_url:
        logger.warning("Cloudinary no devolvio secure_url para el estado remoto.")
        return None

    download_response = requests.get(secure_url, timeout=30)
    if download_response.status_code >= 400:
        logger.warning("No se pudo descargar el estado remoto desde Cloudinary: %s", download_response.text[:250])
        return None

    try:
        return download_response.json()
    except json.JSONDecodeError:
        logger.warning("El estado remoto de Cloudinary no es JSON valido.")
        return None


def normalize_tv_clips(raw):
    if not isinstance(raw, dict):
        return {key: [] for key in TV_VIDEO_CATEGORIES}

    normalized = {}
    for category in TV_VIDEO_CATEGORIES:
        items = raw.get(category, [])
        if not isinstance(items, list):
            normalized[category] = []
            continue

        safe_items = []
        for item in items:
            if not isinstance(item, dict):
                continue
            title = (item.get("title") or "").strip()
            video_url = (item.get("video_url") or "").strip()
            participants = (item.get("participants") or "").strip()
            race = (item.get("race") or "").strip()
            clip_id = (item.get("id") or "").strip()
            public_id = (item.get("public_id") or "").strip()
            created_at = (item.get("created_at") or "").strip()
            if not title or not video_url:
                continue
            if not (video_url.startswith("http://") or video_url.startswith("https://")):
                continue
            safe_items.append(
                {
                    "id": clip_id or secrets.token_hex(8),
                    "title": title[:120],
                    "participants": participants[:160],
                    "race": race[:100],
                    "video_url": video_url,
                    "public_id": public_id[:180],
                    "created_at": created_at,
                }
            )

        normalized[category] = safe_items[:30]

    return normalized


def recover_tv_clips_from_cloudinary(force=False):
    if not cloudinary_is_configured():
        return {key: [] for key in TV_VIDEO_CATEGORIES}

    now = time.time()
    if not force and _CLOUDINARY_TV_CACHE["expires_at"] > now:
        return _CLOUDINARY_TV_CACHE["clips"]

    recovered = {key: [] for key in TV_VIDEO_CATEGORIES}
    endpoint = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/resources/video/upload"
    cursor = None

    while True:
        params = {
            "prefix": "facu-demo/tv/",
            "max_results": 200,
            "context": True,
        }
        if cursor:
            params["next_cursor"] = cursor

        response = requests.get(
            endpoint,
            params=params,
            auth=(CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET),
            timeout=30,
        )
        if response.status_code >= 400:
            logger.warning("No se pudieron listar clips TV de Cloudinary: %s", response.text[:250])
            break

        data = response.json()
        for item in data.get("resources", []):
            public_id = (item.get("public_id") or "").strip()
            secure_url = (item.get("secure_url") or "").strip()
            if not public_id.startswith("facu-demo/tv/") or not secure_url:
                continue

            parts = public_id.split("/")
            if len(parts) < 4:
                continue
            category_slug = parts[2].strip().lower()
            category_key = CATEGORY_SLUG_TO_KEY.get(category_slug)
            if not category_key:
                continue

            context_custom = (((item.get("context") or {}).get("custom") or {}))
            title = (context_custom.get("title") or "").strip()
            participants = (context_custom.get("participants") or "").strip()
            race = (context_custom.get("race") or "").strip()
            created_at = (context_custom.get("created_at") or item.get("created_at") or "").strip()

            if not title:
                tail = parts[-1]
                title = re.sub(r"^\d+-", "", tail).replace("-", " ").strip() or "Clip"

            recovered[category_key].append(
                {
                    "id": (item.get("asset_id") or public_id or secrets.token_hex(8)).strip(),
                    "title": title[:120],
                    "participants": participants[:160],
                    "race": race[:100],
                    "video_url": secure_url,
                    "public_id": public_id,
                    "created_at": created_at,
                }
            )

        cursor = data.get("next_cursor")
        if not cursor:
            break

    for category_key in recovered:
        recovered[category_key].sort(key=lambda row: row.get("created_at", ""), reverse=True)
        recovered[category_key] = recovered[category_key][:30]

    _CLOUDINARY_TV_CACHE["clips"] = recovered
    _CLOUDINARY_TV_CACHE["expires_at"] = now + 120
    return recovered


def fetch_cloudinary_resources_map(force=False):
    if not cloudinary_is_configured():
        return {}

    now = time.time()
    if not force and _CLOUDINARY_CACHE["expires_at"] > now:
        return _CLOUDINARY_CACHE["resources"]

    resources_map = {}
    endpoint = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/resources/image/upload"
    cursor = None

    while True:
        params = {
            "prefix": "facu-demo/",
            "max_results": 200,
        }
        if cursor:
            params["next_cursor"] = cursor

        response = requests.get(
            endpoint,
            params=params,
            auth=(CLOUDINARY_API_KEY, CLOUDINARY_API_SECRET),
            timeout=30,
        )
        if response.status_code >= 400:
            logger.warning("No se pudieron listar recursos de Cloudinary: %s", response.text[:250])
            break

        data = response.json()
        for item in data.get("resources", []):
            public_id = item.get("public_id")
            secure_url = item.get("secure_url")
            if isinstance(public_id, str) and isinstance(secure_url, str):
                resources_map[public_id] = secure_url

        cursor = data.get("next_cursor")
        if not cursor:
            break

    _CLOUDINARY_CACHE["resources"] = resources_map
    _CLOUDINARY_CACHE["expires_at"] = now + 120
    return resources_map


def delete_cloudinary_video(public_id):
    if not cloudinary_is_configured():
        raise RuntimeError("Cloudinary no esta configurado.")

    timestamp = int(time.time())
    params_to_sign = {
        "public_id": public_id,
        "timestamp": timestamp,
        "invalidate": "true",
    }
    signature = sign_cloudinary_params(params_to_sign)
    payload = {
        **params_to_sign,
        "api_key": CLOUDINARY_API_KEY,
        "signature": signature,
    }

    endpoint = f"https://api.cloudinary.com/v1_1/{CLOUDINARY_CLOUD_NAME}/video/destroy"
    response = requests.post(endpoint, data=payload, timeout=30)
    if response.status_code >= 400:
        raise RuntimeError(f"Cloudinary destroy error ({response.status_code}): {response.text[:250]}")

    data = response.json()
    # Cloudinary may return 'ok' or 'not found'. Both are safe for idempotent delete.
    result = (data.get("result") or "").strip().lower()
    if result not in {"ok", "not found"}:
        raise RuntimeError(f"Cloudinary no pudo eliminar el video: {data}")


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
        "comisario_image": "",
        "tv_clips": {key: [] for key in TV_VIDEO_CATEGORIES},
        "dates": {},
        "teams": teams_map,
    }


def write_local_state(state):
    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(json.dumps(state, indent=2), encoding="utf-8")


def save_state(state):
    write_local_state(state)
    if remote_state_is_configured():
        upload_state_to_cloudinary(state)


def load_seed_state():
    if not DATA_SEED_FILE.exists():
        return None

    try:
        return json.loads(DATA_SEED_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Archivo seed invalido. Se recrea estado por defecto.")
        return None


def normalize_state(state):
    if not isinstance(state, dict):
        state = build_default_state()

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
    state["comisario_image"] = state.get("comisario_image", "") if isinstance(state.get("comisario_image", ""), str) else ""
    state["tv_clips"] = normalize_tv_clips(state.get("tv_clips", {}))
    state["dates"] = state.get("dates", {})
    state["season_start_date"] = state.get("season_start_date", next_monday().isoformat())
    cloudinary_resources = fetch_cloudinary_resources_map() if cloudinary_is_configured() else {}
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
        else:
            player_image_url = cloudinary_resources.get(player_public_id(name))
            if isinstance(player_image_url, str) and player_image_url.strip():
                new_images[name] = player_image_url
    state["teams"] = new_teams
    state["player_images"] = new_images
    existing_bios = state.get("player_bios", {})
    new_bios = {}
    for name in state["participants"]:
        if isinstance(existing_bios.get(name), dict):
            new_bios[name] = existing_bios[name]
    state["player_bios"] = new_bios

    if (not state["comisario_image"]) and cloudinary_resources:
        comisario_url = cloudinary_resources.get(COMISARIO_PUBLIC_ID)
        if isinstance(comisario_url, str) and comisario_url.strip():
            state["comisario_image"] = comisario_url

    has_any_tv_clip = any(state["tv_clips"].get(category) for category in TV_VIDEO_CATEGORIES)
    if cloudinary_is_configured() and not has_any_tv_clip:
        state["tv_clips"] = recover_tv_clips_from_cloudinary()

    return state


def load_state():
    if not DATA_FILE.exists():
        state = load_state_from_cloudinary()
        if state is None:
            state = load_seed_state() or build_default_state()
        state = normalize_state(state)
        write_local_state(state)
        return state

    try:
        state = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        logger.warning("Archivo de estado invalido. Se recrea estado por defecto.")
        state = load_state_from_cloudinary() or load_seed_state() or build_default_state()
        state = normalize_state(state)
        write_local_state(state)
        return state
    return normalize_state(state)


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


def validate_classification(classification, participants, allow_partial=False):
    if not isinstance(classification, list):
        return "La clasificacion debe ser una lista de nombres."

    cleaned = [item.strip() for item in classification if isinstance(item, str)]
    num_participants = len(participants)
    if not cleaned:
        return "La clasificacion debe incluir al menos una posicion."

    if not allow_partial and len(cleaned) != num_participants:
        return f"La clasificacion debe tener exactamente {num_participants} posiciones."

    if allow_partial and len(cleaned) > num_participants:
        return f"La clasificacion no puede tener mas de {num_participants} posiciones."

    if any(not name for name in cleaned):
        return "La clasificacion contiene nombres vacios."

    cleaned_set = set(cleaned)
    participants_set = set(participants)
    if not cleaned_set.issubset(participants_set):
        extras = sorted(cleaned_set - participants_set)
        return f"Nombres no registrados: {', '.join(extras)}"

    if not allow_partial and cleaned_set != participants_set:
        missing = sorted(participants_set - cleaned_set)
        return f"Faltan participantes: {', '.join(missing)}"

    if len(cleaned_set) != len(cleaned):
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
        "comisario_image": state["comisario_image"],
        "tv_clips": state["tv_clips"],
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
            preferred_image = preferred_image.strip()
            if preferred_image.startswith("data:image/"):
                if cloudinary_is_configured():
                    try:
                        uploaded_url = upload_data_image_to_cloudinary(preferred_image, player_public_id(name))
                        new_images[name] = uploaded_url
                    except Exception as error:
                        logger.warning("No se pudo subir imagen de %s a Cloudinary: %s", name, error)
                        return jsonify({"status": "error", "message": f"No se pudo subir la imagen de {name}."}), 400
                else:
                    new_images[name] = preferred_image
            elif preferred_image.startswith("http://") or preferred_image.startswith("https://"):
                new_images[name] = preferred_image
            else:
                return jsonify({"status": "error", "message": f"Formato de imagen invalido para {name}."}), 400
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


@app.route("/api/comisario-image", methods=["POST"])
@app.route(f"{script_name}/api/comisario-image", methods=["POST"])
@login_required
def api_update_comisario_image():
    data = request.get_json(silent=True) or {}
    image_data = data.get("image")

    if image_data is None:
        return jsonify({"status": "error", "message": "Falta image en el body."}), 400

    if not isinstance(image_data, str):
        return jsonify({"status": "error", "message": "image debe ser string."}), 400

    image_data = image_data.strip()
    if len(image_data) > 3_000_000:
        return jsonify({"status": "error", "message": "La imagen es demasiado grande."}), 400

    if image_data:
        if image_data.startswith("data:image/"):
            if cloudinary_is_configured():
                try:
                    image_data = upload_data_image_to_cloudinary(image_data, COMISARIO_PUBLIC_ID)
                except Exception as error:
                    logger.warning("No se pudo subir imagen del comisario a Cloudinary: %s", error)
                    return jsonify({"status": "error", "message": "No se pudo subir la imagen del comisario."}), 400
        elif not (image_data.startswith("http://") or image_data.startswith("https://")):
            return jsonify({"status": "error", "message": "Formato de imagen invalido."}), 400

    state = load_state()
    state["comisario_image"] = image_data
    save_state(state)
    return jsonify({"status": "success", "message": "Foto del comisario guardada correctamente."}), 200


@app.route("/api/tv-clips", methods=["POST"])
@app.route(f"{script_name}/api/tv-clips", methods=["POST"])
@login_required
def api_create_tv_clip():
    form_data = request.form if request.form else {}
    json_data = request.get_json(silent=True) or {}

    category = (form_data.get("category") or json_data.get("category") or "").strip().lower()
    if category not in TV_VIDEO_CATEGORIES:
        return jsonify({"status": "error", "message": "Categoria invalida."}), 400

    title = (form_data.get("title") or json_data.get("title") or "").strip()
    if not title:
        return jsonify({"status": "error", "message": "El titulo es obligatorio."}), 400

    participants = (form_data.get("participants") or json_data.get("participants") or "").strip()
    if len(participants) > 160:
        return jsonify({"status": "error", "message": "Participantes demasiado largo."}), 400

    race = (form_data.get("race") or json_data.get("race") or "").strip()
    if len(race) > 100:
        return jsonify({"status": "error", "message": "Nombre de carrera demasiado largo."}), 400

    video_url = ""
    uploaded_file = request.files.get("video")
    if uploaded_file and uploaded_file.filename:
        mime_type = (uploaded_file.mimetype or "").lower()
        if not mime_type.startswith("video/"):
            return jsonify({"status": "error", "message": "El archivo debe ser un video."}), 400

        binary = uploaded_file.read()
        if not binary:
            return jsonify({"status": "error", "message": "No se pudo leer el video."}), 400
        if len(binary) > 120 * 1024 * 1024:
            return jsonify({"status": "error", "message": "El video supera el limite de 120MB."}), 400

        if not cloudinary_is_configured():
            return jsonify({"status": "error", "message": "Cloudinary no esta configurado para subir videos."}), 400

        public_id = clip_public_id(category, title)
        created_at = datetime.utcnow().replace(microsecond=0).isoformat() + "Z"
        try:
            video_url = upload_binary_to_cloudinary(
                binary=binary,
                mime_type=mime_type,
                filename=uploaded_file.filename,
                public_id=public_id,
                resource_type="video",
                extra_upload_params={
                    "context": (
                        f"title={sanitize_cloudinary_context_value(title)}|"
                        f"participants={sanitize_cloudinary_context_value(participants)}|"
                        f"race={sanitize_cloudinary_context_value(race)}|"
                        f"created_at={sanitize_cloudinary_context_value(created_at)}"
                    ),
                },
            )
        except Exception as error:
            logger.warning("No se pudo subir clip de TV a Cloudinary: %s", error)
            return jsonify({"status": "error", "message": "No se pudo subir el video a Cloudinary."}), 400
    else:
        maybe_url = (form_data.get("video_url") or json_data.get("video_url") or "").strip()
        if maybe_url.startswith("http://") or maybe_url.startswith("https://"):
            video_url = maybe_url
        else:
            return jsonify({"status": "error", "message": "Debes adjuntar un video o URL valida."}), 400

    state = load_state()
    state["tv_clips"] = normalize_tv_clips(state.get("tv_clips", {}))

    new_clip = {
        "id": secrets.token_hex(8),
        "title": title[:120],
        "participants": participants[:160],
        "race": race[:100],
        "video_url": video_url,
        "public_id": public_id if 'public_id' in locals() else "",
        "created_at": created_at if 'created_at' in locals() else datetime.utcnow().replace(microsecond=0).isoformat() + "Z",
    }
    state["tv_clips"][category].insert(0, new_clip)
    state["tv_clips"][category] = state["tv_clips"][category][:30]

    save_state(state)
    return jsonify({"status": "success", "message": "Clip cargado correctamente.", "clip": new_clip}), 200


@app.route("/api/tv-clips", methods=["DELETE"])
@app.route(f"{script_name}/api/tv-clips", methods=["DELETE"])
@login_required
def api_delete_tv_clip():
    data = request.get_json(silent=True) or {}
    category = (data.get("category") or "").strip().lower()
    clip_id = (data.get("clip_id") or "").strip()

    if category not in TV_VIDEO_CATEGORIES:
        return jsonify({"status": "error", "message": "Categoria invalida."}), 400
    if not clip_id:
        return jsonify({"status": "error", "message": "Falta clip_id."}), 400

    state = load_state()
    state["tv_clips"] = normalize_tv_clips(state.get("tv_clips", {}))
    current_list = state["tv_clips"].get(category, [])

    target_index = None
    target_clip = None
    for idx, clip in enumerate(current_list):
        if (clip.get("id") or "").strip() == clip_id:
            target_index = idx
            target_clip = clip
            break

    if target_index is None:
        return jsonify({"status": "error", "message": "Clip no encontrado."}), 404

    public_id = (target_clip.get("public_id") or "").strip()
    if public_id and cloudinary_is_configured():
        try:
            delete_cloudinary_video(public_id)
        except Exception as error:
            logger.warning("No se pudo eliminar clip en Cloudinary (%s): %s", public_id, error)
            return jsonify({"status": "error", "message": "No se pudo eliminar el video en Cloudinary."}), 400

    current_list.pop(target_index)
    state["tv_clips"][category] = current_list
    save_state(state)

    # Invalidate cache to ensure next recovery/list reflects deletion.
    _CLOUDINARY_TV_CACHE["expires_at"] = 0

    return jsonify({"status": "success", "message": "Clip eliminado correctamente."}), 200


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
        q_err = validate_classification(qualifying, state["participants"], allow_partial=True)
        if q_err:
            return jsonify({"status": "error", "message": f"Clasificacion (qualy): {q_err}"}), 400
        state["qualifying"][str(race_index)] = qualifying
    if qualifying_details is not None:
        state["qualifying_details"][str(race_index)] = qualifying_details

    # Resultado de carrera — opcional
    classification = data.get("classification")
    race_details = data.get("race_details")
    participants_in_race = data.get("participants_in_race")
    
    # Validar lista opcional de participantes que corrieron (para DNS de no participantes)
    if participants_in_race is not None:
        if not isinstance(participants_in_race, list):
            return jsonify({"status": "error", "message": "participants_in_race debe ser una lista."}), 400
        for driver_name in participants_in_race:
            if driver_name not in state["participants"]:
                return jsonify({"status": "error", "message": f"Piloto no registrado en participants_in_race: {driver_name}"}), 400
    
    if race_details is not None:
        if not isinstance(race_details, dict):
            return jsonify({"status": "error", "message": "race_details debe ser un objeto."}), 400
        for driver_name, detail in race_details.items():
            if driver_name not in state["participants"]:
                return jsonify({"status": "error", "message": f"Piloto no registrado en carrera: {driver_name}"}), 400
            if not isinstance(detail, dict):
                return jsonify({"status": "error", "message": "Cada detalle de carrera debe ser un objeto."}), 400
            detail["status"] = normalize_race_status(detail.get("status"))
    else:
        race_details = {}
    
    # Si se especifica participants_in_race, agregar DNS para pilotos que no corrieron
    if participants_in_race is not None:
        for driver_name in state["participants"]:
            if driver_name not in participants_in_race:
                # Piloto no corrio: marcar como DNS
                if driver_name not in race_details:
                    race_details[driver_name] = {}
                race_details[driver_name]["status"] = "DNS"
    
    if classification is not None:
        r_err = validate_classification(classification, state["participants"], allow_partial=True)
        if r_err:
            return jsonify({"status": "error", "message": f"Resultado de carrera: {r_err}"}), 400

        classified_drivers = set(classification)
        for driver_name in state["participants"]:
            if driver_name not in classified_drivers:
                if driver_name not in race_details:
                    race_details[driver_name] = {}
                race_details[driver_name]["status"] = "DNS"

        state["results"][str(race_index)] = classification
    if race_details:
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
