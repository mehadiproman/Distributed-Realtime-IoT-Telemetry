import asyncio
import io
import os
import sys
import time
from datetime import datetime

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import socketio
import aiomqtt
import httpx

# Updated import (important if using structured project)
from fastapi_server.database import (
    init_db, get_all_sensor_data, get_sensor_data_by_id,
    get_sensor_data_within_range, create_sensor_data, delete_sensor_data,
    create_soil_data, get_all_soil_data, log_pump_event,
    update_device_status, mark_offline_devices, get_all_devices,
    get_pump_mode, set_pump_mode,
    get_sensor_data_by_date_range, get_soil_data_by_date_range,
    get_system_metrics, bst_tz,
    get_history_stats, get_cleanup_preview, delete_old_telemetry,
    get_retention_settings, set_retention_settings
)
from fastapi_server.report_generator import generate_pdf_report
try:
    from fastapi_server.ml.predict import engine as ml_engine
except ImportError:
    ml_engine = None

# Load environment variables from .env file
load_dotenv()

app = FastAPI()

sio = socketio.AsyncServer(async_mode='asgi', cors_allowed_origins='*')
socket_app = socketio.ASGIApp(sio, other_asgi_app=app)

templates = Jinja2Templates(directory="fastapi_server/templates")

# Configuration
MQTT_BROKER = "test.mosquitto.org"
MQTT_PORT = 1883

sensor_buffer = []

# -------------------- WEATHER CONFIG --------------------

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY")
WEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
DEFAULT_CITY = "Dhaka"

# Simple in-memory cache: { city: { "data": {...}, "timestamp": float } }
_weather_cache: dict = {}
CACHE_TTL_SECONDS = 600  # 10 minutes

# -------------------- MODELS --------------------

class SensorDataCreate(BaseModel):
    temperature: float
    humidity: float
    pressure: float
    altitude: float
    lightLevel: float

class SearchTimeRange(BaseModel):
    timeStart: float
    timeEnd: float
    limit: int = 20
    offset: int = 0

# -------------------- BUFFER LOGIC --------------------

async def save_avg_sensor_data(data: dict):
    global sensor_buffer
    sensor_buffer.append(data)

    if len(sensor_buffer) >= 5:
        # Use .get with 0.0 fallback to prevent 'airQuality' or other missing key errors
        avg_temp = sum(d.get("temperature", 0.0) for d in sensor_buffer) / len(sensor_buffer)
        avg_pres = sum(d.get("pressure", 0.0) for d in sensor_buffer) / len(sensor_buffer)
        avg_light = sum(d.get("lightLevel", 0.0) for d in sensor_buffer) / len(sensor_buffer)

        data_obj = {
            "temperature": round(avg_temp, 2),
            "pressure": round(avg_pres, 2),
            "airQuality": 0.0, # Removed hardware sensor
            "lightIntensity": round(avg_light, 2)
        }

        await create_sensor_data(data_obj)
        sensor_buffer.clear()

# -------------------- MQTT LOOP --------------------

PUMP_MODE = "AUTO"
current_pump_state = "OFF"
last_auto_toggle_time = 0
mqtt_connected_status = False

async def mqtt_loop():
    global current_pump_state, last_auto_toggle_time, mqtt_connected_status
    while True:
        try:
            async with aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT) as client:
                mqtt_connected_status = True
                print("Connected to MQTT broker")

                await client.subscribe("home/sensors/#")
                await client.subscribe("home/pump/status")
                await client.subscribe("home/devices/+/heartbeat")

                # ✅ CORRECT FIX
                async with client.messages() as messages:
                    async for message in messages:
                        topic_str = str(message.topic)
                        payload = message.payload.decode()
                        
                        if topic_str == "home/sensors/data":
                            print(f"Received: {payload}")
                            try:
                                vals = payload.split(',')
                                if len(vals) < 1:
                                    raise ValueError("Invalid payload format")

                                # Exact User-Defined Mapping:
                                # [0]Temp, [1]Hum, [2]Light, [3]Soil, [4]Pres, [5]Alt
                                sensor_data = {
                                    "temperature": float(vals[0]) if len(vals) > 0 else 0.0,
                                    "humidity": float(vals[1]) if len(vals) > 1 else 0.0,
                                    "lightLevel": float(vals[2]) if len(vals) > 2 else 0.0,
                                    "pressure": float(vals[4]) if len(vals) > 4 else 0.0,
                                    "altitude": float(vals[5]) if len(vals) > 5 else 0.0
                                }

                                await sio.emit("sensorData", sensor_data)
                                await save_avg_sensor_data(sensor_data)

                                # Soil Moisture at index 3
                                if len(vals) > 3:
                                    try:
                                        soil_data = float(vals[3])
                                        await sio.emit("soilData", {"moisture": soil_data})
                                        await create_soil_data(soil_data)
                                    except: pass
                                
                                # Auto-capture device from general sensor topic if heartbeat hasn't reached us yet
                                await update_device_status("Legacy-ESP32", 100.0, 100.0, "online")

                            except Exception as parse_err:
                                print(f"Payload parse error: {parse_err}")
                                
                        elif topic_str == "home/sensors/soil":
                            try:
                                moisture = float(payload)
                                await create_soil_data(moisture)
                                await sio.emit("soilData", {"moisture": moisture})
                                
                                # Auto-capture device status
                                await update_device_status("Legacy-ESP32", 100.0, 100.0, "online")
                                
                                # Auto irrigation logic
                                if PUMP_MODE == "AUTO":
                                    now = time.time()
                                    if now - last_auto_toggle_time > 10:  # 10s cooldown
                                        if moisture < 30.0 and current_pump_state == "OFF":
                                            await client.publish("home/pump/cmd", "ON,30", qos=1)
                                            await log_pump_event("ON", "AUTO")
                                            last_auto_toggle_time = now
                                        elif moisture > 60.0 and current_pump_state == "ON":
                                            await client.publish("home/pump/cmd", "OFF,0", qos=1)
                                            await log_pump_event("OFF", "AUTO")
                                            last_auto_toggle_time = now
                            except Exception as e:
                                print(f"Soil payload error: {e}")
                                
                        elif topic_str == "home/pump/status":
                            current_pump_state = payload
                            await sio.emit("pumpData", {"state": payload, "reason": PUMP_MODE})
                            
                        elif topic_str.startswith("home/devices/") and topic_str.endswith("/heartbeat"):
                            try:
                                device_id = topic_str.split("/")[2]
                                parts = payload.split(",")
                                wifi = float(parts[0]) if len(parts) > 0 else 0.0
                                batt = float(parts[1]) if len(parts) > 1 else 0.0
                                await update_device_status(device_id, wifi, batt, "online")
                            except Exception as e:
                                print(f"Heartbeat parse error: {e}")

        except aiomqtt.MqttError as err:
            mqtt_connected_status = False
            print(f"MQTT error: {err}. Reconnecting in 5s...")
            await asyncio.sleep(5)

        except Exception as e:
            mqtt_connected_status = False
            print(f"Unhandled error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

# -------------------- STARTUP --------------------

async def heartbeat_monitor():
    while True:
        try:
            # Check for offline devices
            await mark_offline_devices(30)
            
            # Fetch and broadcast all device states
            devices = await get_all_devices()
            
            formatted_devices = []
            for d in devices:
                formatted_devices.append({
                    "device_id": d["device_id"],
                    "last_seen": d["last_seen"].isoformat() if d["last_seen"] else None,
                    "wifi_signal": float(d["wifi_signal"]) if d["wifi_signal"] is not None else None,
                    "battery_level": float(d["battery_level"]) if d["battery_level"] is not None else None,
                    "status": d["status"]
                })
            
            await sio.emit("deviceStatus", formatted_devices)
            
            await asyncio.sleep(5)
        except Exception as e:
            print(f"Heartbeat monitor error: {e}")
            await asyncio.sleep(5)

@app.on_event("startup")
async def startup_event():
    global PUMP_MODE
    await init_db()
    PUMP_MODE = await get_pump_mode()
    asyncio.create_task(mqtt_loop())
    asyncio.create_task(heartbeat_monitor())
    asyncio.create_task(auto_cleanup_task())

# -------------------- ROUTES --------------------

@app.get("/")
async def root():
    return HTMLResponse('Data received', status_code=200)

@app.get("/graph", response_class=HTMLResponse)
async def graph(request: Request):
    return templates.TemplateResponse("graph.html", {"request": request})

@app.get("/detail", response_class=HTMLResponse)
async def detail(request: Request):
    # Default to 'All Records' (large range) for initial load to ensure Load More works by default
    data = await get_sensor_data_within_range(time_end_hrs=87600, limit=20, offset=0)
    return templates.TemplateResponse("detail.html", {"request": request, "data": data})

@app.get("/api/sensor")
async def api_get_sensors():
    return await get_all_sensor_data(limit=5)

@app.post("/api/sensor")
async def api_create_sensor(data: SensorDataCreate):
    return await create_sensor_data(data.dict())

@app.post("/api/sensor/search")
async def api_search_sensor(time_range: SearchTimeRange):
    return await get_sensor_data_within_range(time_range.timeEnd, time_range.limit, time_range.offset)

@app.get("/api/sensor/{item_id}")
async def api_get_sensor_by_id(item_id: int):
    return await get_sensor_data_by_id(item_id)

@app.delete("/api/sensor/{item_id}")
async def api_delete_sensor(item_id: int):
    return await delete_sensor_data(item_id)

@app.get("/weather")
async def get_weather(city: str = Query(default=None)):
    """Fetch current weather from OpenWeatherMap with 10-min caching."""
    target_city = city or DEFAULT_CITY
    cache_key = target_city.lower().strip()

    # Check in-memory cache
    cached = _weather_cache.get(cache_key)
    if cached and (time.time() - cached["timestamp"] < CACHE_TTL_SECONDS):
        return cached["data"]

    # Validate API key exists
    if not WEATHER_API_KEY or WEATHER_API_KEY == "your_openweathermap_api_key_here":
        return JSONResponse(
            status_code=500,
            content={"detail": "Weather API key not configured. Set WEATHER_API_KEY in .env"}
        )

    try:
        # Call OpenWeatherMap API using async httpx client
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(
                WEATHER_BASE_URL,
                params={
                    "q": target_city,
                    "appid": WEATHER_API_KEY,
                    "units": "metric"
                }
            )

        # If upstream API returns non-200, relay a clean error
        if response.status_code != 200:
            return JSONResponse(
                status_code=500,
                content={"detail": "Weather API error"}
            )

        raw = response.json()

        # Build a clean, frontend-friendly response
        weather_data = {
            "city": raw.get("name", target_city),
            "temperature": raw["main"]["temp"],
            "feels_like": raw["main"]["feels_like"],
            "humidity": raw["main"]["humidity"],
            "pressure": raw["main"]["pressure"],
            "weather": raw["weather"][0]["main"],
            "description": raw["weather"][0]["description"],
            "wind_speed": raw["wind"]["speed"]
        }

        # Store in cache
        _weather_cache[cache_key] = {
            "data": weather_data,
            "timestamp": time.time()
        }

        return weather_data

    except httpx.TimeoutException:
        return JSONResponse(
            status_code=500,
            content={"detail": "Weather API timeout"}
        )
    except Exception as e:
        # Log but don't crash the server
        print(f"Weather fetch error: {e}")
        return JSONResponse(
            status_code=500,
            content={"detail": "Weather API error"}
        )

# -------------------- EXPORT ROUTES --------------------

@app.get("/api/export/pdf")
async def export_pdf(
    start: str = Query(..., description="Start date YYYY-MM-DD"),
    end: str = Query(..., description="End date YYYY-MM-DD")
):
    """Generate and return a PDF telemetry report for the given date range."""
    from datetime import datetime, timezone
    try:
        start_dt = datetime.strptime(start, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        end_dt = datetime.strptime(end, "%Y-%m-%d").replace(
            hour=23, minute=59, second=59, tzinfo=timezone.utc
        )
    except ValueError:
        return JSONResponse(status_code=400, content={"detail": "Invalid date format. Use YYYY-MM-DD."})

    if start_dt > end_dt:
        return JSONResponse(status_code=400, content={"detail": "Start date must be before end date."})

    sensor_data = await get_sensor_data_by_date_range(start_dt, end_dt)
    soil_data = await get_soil_data_by_date_range(start_dt, end_dt)

    pdf_bytes = generate_pdf_report(sensor_data, soil_data, start, end)

    filename = f"IoT_Report_{start}_to_{end}.pdf"
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

# -------------------- PREDICTION ROUTES --------------------

@app.get("/api/predict/summary")
async def get_prediction_summary():
    """Fetch recent data and generate ML predictions."""
    if not ml_engine:
        return JSONResponse(status_code=503, content={"detail": "Prediction motor not available"})
    
    # Need at least 4 recent sensor records for trend analysis (current + 3 lags)
    sensors = await get_all_sensor_data(limit=10)
    soil = await get_all_soil_data(limit=5)
    
    if len(sensors) < 5 or len(soil) < 1:
        return JSONResponse(status_code=200, content={
            "error": "Insufficient data for prediction",
            "needs_more_data": True
        })
    
    try:
        # Reload models if they weren't ready at startup
        if not ml_engine.models:
            ml_engine.load_models()
            
        summary = ml_engine.get_summary(sensors, soil)
        return summary
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/api/system/status")
async def get_system_status():
    """Returns real-time health and connectivity metrics for the infrastructure."""
    start_time = time.time()
    try:
        db_metrics = await get_system_metrics()
        response_ms = int((time.time() - start_time) * 1000)
        
        # Determine last sync text
        last_sync_text = "Never"
        if db_metrics['last_sync']:
            diff = datetime.now(bst_tz) - db_metrics['last_sync']
            seconds = int(diff.total_seconds())
            if seconds < 60: last_sync_text = f"{seconds}s ago"
            elif seconds < 3600: last_sync_text = f"{seconds//60}m ago"
            else: last_sync_text = f"{seconds//3600}h ago"

        return {
            "api_server": "online",
            "response_ms": response_ms,
            "mqtt": "connected" if mqtt_connected_status else "offline",
            "database": "healthy",
            "active_devices": db_metrics['active_devices'],
            "active_device_ids": db_metrics['active_device_ids'],
            "total_devices": db_metrics['total_devices'],
            "offline_devices": db_metrics['offline_devices'],
            "last_telemetry": last_sync_text,
            "records_today": db_metrics['records_today'],
            "timestamp": datetime.now(bst_tz).isoformat()
        }
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e), "database": "error"})

@app.get("/api/history/stats")
async def api_history_stats():
    """Returns detailed database statistics for the retention manager."""
    try:
        stats = await get_history_stats()
        return stats
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/api/history/cleanup-preview")
async def api_cleanup_preview(days: int = Query(30, ge=1)):
    """Previews how many records would be removed for a given retention period."""
    try:
        preview = await get_cleanup_preview(days)
        return preview
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.delete("/api/history/cleanup")
async def api_cleanup_execute(days: int = Query(30, ge=1)):
    """Executes the cleanup process for records older than X days."""
    try:
        result = await delete_old_telemetry(days)
        return result
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

@app.get("/api/history/settings")
async def api_get_retention_settings():
    """Returns the current auto-cleanup configuration."""
    try:
        return await get_retention_settings()
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

class RetentionSettings(BaseModel):
    enabled: bool
    days: int

@app.post("/api/history/settings")
async def api_post_retention_settings(data: RetentionSettings):
    """Updates the auto-cleanup configuration."""
    try:
        return await set_retention_settings(data.enabled, data.days)
    except Exception as e:
        return JSONResponse(status_code=500, content={"detail": str(e)})

# -------------------- BACKGROUND TASKS --------------------

async def auto_cleanup_task():
    """Background task that runs once every 24 hours to clean up old telemetry."""
    while True:
        try:
            settings = await get_retention_settings()
            if settings["enabled"]:
                print(f"DEBUG: Running scheduled cleanup (older than {settings['days']} days)...")
                result = await delete_old_telemetry(settings["days"])
                print(f"DEBUG: Auto-cleanup complete. Deleted {result['total_deleted']} records.")
            
            # Wait 24 hours (86400 seconds)
            await asyncio.sleep(86400)
        except Exception as e:
            print(f"Auto-cleanup error: {e}")
            await asyncio.sleep(3600)  # Retry in 1 hour on error


@sio.on('connect')
async def connect(sid, environ):
    print("Client connected")
    await sio.emit('pumpModeUpdate', {"mode": PUMP_MODE}, to=sid)

@sio.on('setPumpMode')
async def handle_set_pump_mode(sid, data):
    global PUMP_MODE
    mode = data.get("mode", "AUTO")
    PUMP_MODE = mode
    await set_pump_mode(mode)
    await sio.emit('pumpModeUpdate', {"mode": mode})

@sio.on('checkBoxData')
async def handle_checkbox(sid, data):
    print(f"Checkbox data: {data}")

    await sio.emit('x', "ack", to=sid)

    try:
        async with aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT) as client:
            await client.publish("esp/cmd", payload=str(data))
    except Exception as e:
        print(f"MQTT publish error: {e}")

@sio.on('pumpCommand')
async def handle_pump_cmd(sid, data):
    print(f"Manual pump trigger: {data}")
    state = data.get("state", "OFF")
    duration = data.get("duration", 30)
    try:
        async with aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT) as client:
            await client.publish("home/pump/cmd", payload=f"{state},{duration}")
            await log_pump_event(state, "MANUAL")
    except Exception as e:
        print(f"Pump MQTT error: {e}")

@sio.on('searchTimeRange')
async def handle_search(sid, data):
    try:
        time_start = float(data.get("timeStart", 0))
        time_end = float(data.get("timeEnd", 0))

        records = await get_sensor_data_within_range(time_start, time_end)

        formatted = []
        for r in records:
            # Strictly construct primitive dict mapping to avoid hidden Decimal/Datetime serialization crashes
            formatted.append({
                "id": int(r.get("id", 0)),
                "timestamp": r.get("timestamp").isoformat() if r.get("timestamp") else None,
                "temperature": float(r.get("temperature", 0)),
                "pressure": float(r.get("pressure", 0)),
                "air_quality": float(r.get("air_quality", 0)),
                "light_intensity": float(r.get("light_intensity", 0))
            })

        
        print(f"Emitting recRange with {len(formatted)} records to {sid}")
        await sio.emit('recRange', formatted, to=sid)
    except Exception as e:
        import traceback
        print(f"Error in handle_search: {e}")
        traceback.print_exc()
