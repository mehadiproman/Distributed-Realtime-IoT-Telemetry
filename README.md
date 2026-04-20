````md
# Smart Environmental Monitoring & Automated Control Platform

An advanced IoT-based real-time environmental monitoring and smart automation system designed for agriculture, farming, laboratories, smart homes, and resource-efficient environments.

This platform combines **ESP32 hardware**, **MQTT communication**, **FastAPI backend services**, **PostgreSQL storage**, **interactive dashboards**, and **AI-assisted predictions** to create a complete end-to-end telemetry solution.

---

## Overview

Traditional monitoring often depends on manual checking, delayed responses, and guess-based decisions.

This project solves that by providing:

- Real-time sensor monitoring
- Historical telemetry analytics
- Smart irrigation automation
- Live dashboards
- Report generation
- Predictive insights from historical data
- Expandable IoT architecture

---

## Key Features

### Real-Time Monitoring

Continuously receives telemetry from ESP32 devices using MQTT.

Tracks:

- Temperature
- Humidity
- Light Intensity
- Soil Moisture
- Device activity status

---

### Smart Automation

Supports intelligent control logic such as:

- Auto Pump ON when soil moisture is low
- Auto Pump OFF when moisture reaches threshold
- Manual / Auto control modes
- Future-ready fan automation support

---

### Live Dashboard

Modern web dashboard with:

- Real-time sensor cards
- Weather integration
- Prediction widgets
- System health status
- Telemetry charts
- Connected device indicators

---

### Historical Analytics

View past records with:

- Date filters
- Pagination
- Searchable telemetry logs
- Trend analysis

---

### Export Reports

Generate downloadable reports in professional format:

- PDF reports
- Sensor summaries
- Time-range based exports

---

### Data Retention Management

Prevent database overload using smart cleanup policies:

- Keep last X days
- Auto cleanup mode
- Storage usage stats
- Preview deletions safely

---

### AI / ML Prediction Layer

Uses trained models for:

- Temperature trend prediction
- Humidity forecasting
- Irrigation recommendations

---

## Technology Stack

### Backend

- Python 3.10+
- FastAPI
- Socket.IO
- AsyncIO

### Database

- PostgreSQL
- asyncpg

### Communication

- MQTT
- aiomqtt

### Frontend

- HTML
- CSS
- JavaScript
- Jinja2 Templates

### Data / ML

- Pandas
- scikit-learn
- joblib

### Hardware

- ESP32
- DHT22 Sensor
- LDR Sensor
- Soil Moisture Sensor
- Relay / Pump Module

---

## Project Structure

```text
IoT-Automation-Project/
│
├── .venv/
├── .vscode/
│
├── esp32/
│   └── esp32_client.ino
│
├── fastapi_server/
│   │
│   ├── ml/
│   │   ├── models/
│   │   │   ├── hum_trend.pkl
│   │   │   ├── temp_trend.pkl
│   │   │   └── watering_model.pkl
│   │   ├── predict.py
│   │   └── train.py
│   │
│   ├── templates/
│   │   ├── graph.html
│   │   └── detail.html
│   │
│   ├── database.py
│   ├── main.py
│   └── report_generator.py
│
├── scripts/
│   ├── create_db.py
│   └── copy_templates.py
│
├── scratch/
│   └── check_db.py
│
├── .env
├── .gitignore
├── README.md
├── requirements.txt
├── test_mqtt.py
└── test_mqtt_debug.py
````

---

## Installation

### 1. Clone Repository

```bash
git clone <your-repo-url>
cd IoT-Automation-Project
```

---

### 2. Create Virtual Environment

```bash
python -m venv .venv
```

Activate:

#### Windows

```bash
.venv\Scripts\activate
```

#### Linux / macOS

```bash
source .venv/bin/activate
```

---

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

---

### 4. Configure Environment Variables

Create `.env`

```env
DB_USER=postgres
DB_PASSWORD=yourpassword
DB_NAME=home
DB_HOST=localhost
DB_PORT=5432

MQTT_BROKER=test.mosquitto.org
MQTT_PORT=1883

DEFAULT_CITY=Dhaka
WEATHER_API_KEY=your_api_key
```

---

### 5. Start PostgreSQL

Ensure PostgreSQL is running and database exists.

---

## Run Application

```bash
uvicorn fastapi_server.main:socket_app --reload
```

---

## Open in Browser

### Live Dashboard

```text
http://127.0.0.1:8000/graph
```

### Detailed Logs / Retention Panel

```text
http://127.0.0.1:8000/detail
```

---

## ESP32 Telemetry Format

ESP32 publishes:

```text
temperature,humidity,light,soil
```

Example:

```text
33.20,65.10,820,48
```

---

## Optional ML Training

```bash
python -m fastapi_server.ml.train
```

Prediction endpoint:

```text
GET /api/predict/summary
```

---

## Use Cases

### Smart Agriculture

* Auto irrigation
* Soil moisture optimization
* Climate monitoring

### Smart Home

* Plant care automation
* Room environment tracking

### Laboratories

* Controlled condition monitoring

### Warehouses

* Humidity / temperature surveillance

---

## Future Enhancements

* Smart fan automation
* Telegram / SMS alerts
* Multi-device node support
* Mobile app
* Cloud deployment
* Advanced anomaly detection
* Solar-powered sensor nodes

---

## Notes

* Tables auto-create on startup
* MQTT ingestion runs in background
* Socket updates are real-time
* Cleanup tools prevent DB overload
* Easily extendable architecture

---

## Author

**Mehadi Hasan Proman**

Built with passion for IoT, automation, and intelligent systems.

```
```
