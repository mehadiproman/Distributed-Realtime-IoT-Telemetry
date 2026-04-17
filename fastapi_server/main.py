import asyncio
import os
import sys
import time

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

from dotenv import load_dotenv
from fastapi import FastAPI, Request, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
import socketio
import aiomqtt
import httpx

# Updated import (important if using structured project)
from fastapi_server.database import (
    init_db, get_all_sensor_data, get_sensor_data_by_id,
    get_sensor_data_within_range, create_sensor_data, delete_sensor_data,
    create_soil_data, get_all_soil_data, log_pump_event
)

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

WATERING_THRESHOLD = 30.0
AUTO_IRRIGATION_ENABLED = True

async def mqtt_loop():
    while True:
        try:
            async with aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT) as client:
                print("Connected to MQTT broker")

                await client.subscribe("home/sensors/#")
                await client.subscribe("home/pump/status")

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
                                if AUTO_IRRIGATION_ENABLED and moisture < WATERING_THRESHOLD:
                                    await client.publish("home/pump/cmd", "ON,20", qos=1)
                                    await log_pump_event("ON", "AUTO")
                            except Exception as e:
                                print(f"Soil payload error: {e}")
                                
                        elif topic_str == "home/pump/status":
                            await sio.emit("pumpData", {"state": payload})

        except aiomqtt.MqttError as err:
            print(f"MQTT error: {err}. Reconnecting in 5s...")
            await asyncio.sleep(5)

        except Exception as e:
            print(f"Unhandled error: {e}. Reconnecting in 5s...")
            await asyncio.sleep(5)

# -------------------- STARTUP --------------------

@app.on_event("startup")
async def startup_event():
    await init_db()
    asyncio.create_task(mqtt_loop())

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

# -------------------- SOCKET EVENTS --------------------

@sio.on('connect')
async def connect(sid, environ):
    print("Client connected")

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
