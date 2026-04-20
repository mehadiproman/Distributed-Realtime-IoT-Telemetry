# Smart Environmental Monitoring & Automated Control Platform

An IoT-based real-time environmental monitoring & smart automation system for agriculture, farming, labs, & resource management.

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
IoT-Automation-Project/
│
├── .venv/                      # Python virtual environment
├── .vscode/                    # VS Code workspace settings
│
├── esp32/                      # ESP32 firmware source
│   └── esp32_client.ino        # Arduino/ESP32 IoT device code
│
├── fastapi_server/             # Main backend application
│   │
│   ├── __pycache__/            # Python cache files
│   │
│   ├── ml/                     # Machine learning module
│   │   ├── __pycache__/
│   │   ├── models/             # Trained ML models
│   │   │   ├── hum_trend.pkl
│   │   │   ├── temp_trend.pkl
│   │   │   └── watering_model.pkl
│   │   │
│   │   ├── __init__.py
│   │   ├── predict.py         # Prediction logic
│   │   └── train.py           # Model training scripts
│   │
│   ├── templates/             # Frontend HTML templates
│   │   ├── detail.html
│   │   └── graph.html
│   │
│   ├── __init__.py
│   ├── database.py            # DB connection / queries
│   ├── main.py                # FastAPI app entry point
│   └── report_generator.py    # PDF/CSV report export
│
├── scratch/                   # Temporary test/debug scripts
│   └── check_db.py
│
├── scripts/                   # Utility/helper scripts
│   ├── copy_templates.py
│   └── create_db.py
│
├── .env                       # Environment variables
├── .gitignore                 # Git ignored files
├── README.md                  # Project documentation
├── requirements.txt           # Python dependencies
│
├── test_mqtt_debug.py         # MQTT debug testing
└── test_mqtt.py               # MQTT communication testing

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

- `DB_USER` (default: ``)
- `DB_PASSWORD` (default: ``)
- `DB_NAME` (default: ``)
- `DB_HOST` (default: ``)
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
