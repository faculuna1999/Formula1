# Facu Demo - Campeonato Formula 1

Aplicacion web en Python (Flask) para gestionar un campeonato de 20 participantes con formato de puntuacion oficial F1.

## Funcionalidades

- Carga de 20 participantes con nombre personalizado.
- Calendario de pistas vigente (24 carreras) con una carrera por semana.
- Registro de clasificacion final por carrera (posiciones 1 a 20).
- Suma automatica de puntos con sistema F1:
  - 25, 18, 15, 12, 10, 8, 6, 4, 2, 1.
- Tabla de posiciones en tiempo real.
- Soporte para despliegue bajo prefijo /facu-demo (Coolify).
- Persistencia local en data/season.json.

## Requisitos

- Python 3.11+
- Docker (opcional, para despliegue/contenedor)

## Ejecutar en local

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python3 app.py
```

La app queda en:
- http://localhost:3000/
- http://localhost:3000/facu-demo/

## Ejecutar con Docker Compose

```bash
docker-compose up --build
```

## Variables de entorno

- FLASK_ENV: production/development.
- FLASK_HOST: host de escucha (default 0.0.0.0).
- FLASK_PORT: puerto (default 3000).
- SCRIPT_NAME: prefijo para proxy (default /facu-demo).
- SEASON_START_DATE: fecha de inicio del campeonato en formato YYYY-MM-DD.

## API principal

- GET /facu-demo/api/state
  - Retorna estado completo: participantes, calendario, resultados y tabla.

- POST /facu-demo/api/participants
  - Guarda lista de participantes y reinicia resultados.
  - Body:

```json
{
  "participants": ["Jugador 1", "Jugador 2", "..."],
  "season_start_date": "2026-04-20"
}
```

- POST /facu-demo/api/results
  - Guarda resultado de una carrera.
  - Body:

```json
{
  "race_index": 0,
  "classification": ["Jugador 1", "Jugador 2", "..."]
}
```

- POST /facu-demo/api/reset
  - Reinicia resultados del campeonato.

- GET /facu-demo/health
  - Health check para Coolify.

## Despliegue en Coolify

- Puerto de app: 3000.
- Health check: /facu-demo/health.
- URL publica esperada: https://tu-dominio/facu-demo/

## Notas

- Si el proxy hace strip del prefijo, la app tambien expone rutas sin prefijo para evitar loops.
- El archivo data/season.json es runtime local y esta ignorado en git.
