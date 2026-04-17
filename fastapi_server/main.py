import asyncio
import io
import os
import sys
import time

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
    get_sensor_data_by_date_range, get_soil_data_by_date_range
)
from fastapi_server.report_generator import generate_pdf_report

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

WEATHER_API_KEY = os.getenv("WEATHER_API_KEY", "4e277f5f6b9755912b2ee93a3ae50ac6")
WEATHER_BASE_URL = "https://api.openweathermap.org/data/2.5/weather"
DEFAULT_CITY = "Dhaka"

# Simple in-memory cache: { city: { "data": {...}, "timestamp": float } }
_weather_cache: dict = {}
CACHE_TTL_SECONDS = 600  # 10 minutes

# -------------------- MODELS --------------------

class SensorDataCreate(BaseModel):
    temperature: float
    pressure: float
    airQuality: float
    lightIntensity: float

class SearchTimeRange(BaseModel):
    timeStart: float
    timeEnd: float

# -------------------- BUFFER LOGIC --------------------

async def save_avg_sensor_data(data: dict):
    global sensor_buffer
    sensor_buffer.append(data)

    if len(sensor_buffer) >= 5:
        avg_temp = sum(d["temperature"] for d in sensor_buffer) / len(sensor_buffer)
        avg_pres = sum(d["pressure"] for d in sensor_buffer) / len(sensor_buffer)
        avg_air = sum(d["airQuality"] for d in sensor_buffer) / len(sensor_buffer)
        avg_light = sum(d["lightIntensity"] for d in sensor_buffer) / len(sensor_buffer)

        data_obj = {
            "temperature": round(avg_temp, 2),
            "pressure": round(avg_pres, 2),
            "airQuality": round(avg_air, 2),
            "lightIntensity": round(avg_light, 2)
        }

        await create_sensor_data(data_obj)
        sensor_buffer.clear()

# -------------------- MQTT LOOP --------------------

PUMP_MODE = "AUTO"
current_pump_state = "OFF"
last_auto_toggle_time = 0

async def mqtt_loop():
    global current_pump_state, last_auto_toggle_time
    while True:
        try:
            async with aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT) as client:
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

                                sensor_data = {
                                    "temperature": float(vals[0]) if len(vals) > 0 else 0.0,
                                    "pressure": float(vals[1]) if len(vals) > 1 else 0.0,
                                    "airQuality": float(vals[2]) if len(vals) > 2 else 0.0,
                                    "lightIntensity": float(vals[3]) if len(vals) > 3 else 0.0
                                }

                                await sio.emit("sensorData", sensor_data)
                                await save_avg_sensor_data(sensor_data)

                            except Exception as parse_err:
                                print(f"Payload parse error: {parse_err}")
                                
                        elif topic_str == "home/sensors/soil":
                            try:
                                moisture = float(payload)
                                await create_soil_data(moisture)
                                await sio.emit("soilData", {"moisture": moisture})
                                
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
            print(f"MQTT error: {err}. Reconnecting in 5s...")
            await asyncio.sleep(5)

        except Exception as e:
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

# -------------------- ROUTES --------------------

@app.get("/")
async def root():
    return HTMLResponse('Data received', status_code=200)

@app.get("/graph", response_class=HTMLResponse)
async def graph(request: Request):
    return templates.TemplateResponse("graph.html", {"request": request})

@app.get("/detail", response_class=HTMLResponse)
async def detail(request: Request):
    data = await get_all_sensor_data(limit=100)
    return templates.TemplateResponse("detail.html", {"request": request, "data": data})

@app.get("/api/sensor")
async def api_get_sensors():
    return await get_all_sensor_data(limit=5)

@app.post("/api/sensor")
async def api_create_sensor(data: SensorDataCreate):
    return await create_sensor_data(data.dict())

@app.post("/api/sensor/search")
async def api_search_sensor(time_range: SearchTimeRange):
    return await get_sensor_data_within_range(time_range.timeStart, time_range.timeEnd)

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

# -------------------- SOCKET EVENTS --------------------

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
