# IoT Automation Project Draft II

Real-time IoT telemetry platform built with ESP32 + FastAPI + PostgreSQL + MQTT.

## What It Does

- Streams telemetry from ESP32 over MQTT.
- Aggregates and stores sensor + soil data in PostgreSQL.
- Shows live and historical dashboards through FastAPI templates.
- Supports pump control (manual and auto mode).
- Provides weather integration, PDF export, and retention cleanup APIs.
- Includes optional ML prediction summaries from historical telemetry.

## Tech Stack

- Python 3.10+
- FastAPI + Socket.IO
- PostgreSQL (asyncpg)
- MQTT (aiomqtt, default broker test.mosquitto.org)
- Jinja2 templates
- Pandas + scikit-learn + joblib (prediction models)

## Project Structure

- `fastapi_server/main.py`: API, Socket.IO events, MQTT loop, background tasks
- `fastapi_server/database.py`: async DB schema and query helpers
- `fastapi_server/report_generator.py`: PDF report generation
- `fastapi_server/ml/train.py`: model training pipeline
- `fastapi_server/ml/predict.py`: inference engine
- `fastapi_server/templates/graph.html`: live dashboard
- `fastapi_server/templates/detail.html`: history, retention, export dashboard
- `esp32/esp32_client.ino`: ESP32 sketch

## Setup

1. Create and activate virtual environment.
2. Install dependencies:

```bash
pip install -r requirements.txt
```

3. Ensure PostgreSQL is running and database exists (default: `home`).
4. Configure environment variables in `.env`.

### Environment Variables

Database:

- `DB_USER` (default: `postgres`)
- `DB_PASSWORD` (default: `1234`)
- `DB_NAME` (default: `home`)
- `DB_HOST` (default: `127.0.0.1`)
- `DB_PORT` (default: `5432`)

MQTT and app:

- `MQTT_BROKER` (default: `test.mosquitto.org`)
- `MQTT_PORT` (default: `1883`)
- `DEFAULT_CITY` (default: `Dhaka`)
- `WEATHER_API_KEY` (required for `/weather` endpoint)

## Run

From repository root:

```bash
uvicorn fastapi_server.main:socket_app --reload
```

Open:

- `http://127.0.0.1:8000/graph` for live dashboard
- `http://127.0.0.1:8000/detail` for historical data and retention manager

## Optional: Train ML Models

```bash
python -m fastapi_server.ml.train
```

After training, prediction API:

- `GET /api/predict/summary`

## Notes

- Database tables are auto-created on startup.
- Background tasks now shut down gracefully with the app lifecycle.
- Historical socket search supports proper limit/offset pagination.
