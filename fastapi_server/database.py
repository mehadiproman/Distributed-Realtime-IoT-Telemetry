import asyncpg
from datetime import timedelta, timezone

# Define Bangladesh Standard Time (UTC+6)
bst_tz = timezone(timedelta(hours=6))

DB_CONFIG = {
    "user": "postgres",
    "password": "1234",
    "database": "home",
    "host": "127.0.0.1",
    "port": 5432
}

pool = None

def _format_record(r):
    if not r: return None
    d = dict(r)
    if d.get("timestamp"):
        try:
            d["timestamp"] = d["timestamp"].astimezone(bst_tz)
        except Exception:
            # Fallback if datetime is mysteriously naive
            d["timestamp"] = d["timestamp"].replace(tzinfo=timezone.utc).astimezone(bst_tz)
    return d

async def init_db():
    global pool
    pool = await asyncpg.create_pool(**DB_CONFIG)
    async with pool.acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS sensor_data (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                temperature NUMERIC,
                pressure NUMERIC,
                air_quality NUMERIC,
                light_intensity NUMERIC
            );
            CREATE TABLE IF NOT EXISTS soil_data (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                moisture NUMERIC
            );
            CREATE TABLE IF NOT EXISTS pump_events (
                id SERIAL PRIMARY KEY,
                timestamp TIMESTAMPTZ DEFAULT NOW(),
                state VARCHAR(10),
                trigger_type VARCHAR(20)
            );
        """)

async def get_all_sensor_data(limit=100):
    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT * FROM sensor_data ORDER BY timestamp DESC LIMIT $1;", limit)
        return [_format_record(r) for r in records]

async def get_sensor_data_by_id(record_id: int):
    async with pool.acquire() as conn:
        record = await conn.fetchrow("SELECT * FROM sensor_data WHERE id = $1;", record_id)
        return _format_record(record)

async def get_sensor_data_within_range(time_start_hrs: float, time_end_hrs: float):
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT * FROM sensor_data
            WHERE timestamp >= NOW() - (interval '1 hour' * $1)
            ORDER BY timestamp DESC;
        """, time_end_hrs)
        return [_format_record(r) for r in records]

async def create_sensor_data(data: dict):
    query = """
        INSERT INTO sensor_data (temperature, pressure, air_quality, light_intensity)
        VALUES ($1, $2, $3, $4) RETURNING *;
    """
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            query, 
            data.get('temperature', 0), 
            data.get('pressure', 0), 
            data.get('airQuality', 0), 
            data.get('lightIntensity', 0)
        )
        return _format_record(record)

async def delete_sensor_data(record_id: int):
    async with pool.acquire() as conn:
        record = await conn.fetchrow("DELETE FROM sensor_data WHERE id = $1 RETURNING *;", record_id)
        return _format_record(record)

async def create_soil_data(moisture: float):
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "INSERT INTO soil_data (moisture) VALUES ($1) RETURNING *;", moisture
        )
        return _format_record(record)

async def get_all_soil_data(limit=100):
    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT * FROM soil_data ORDER BY timestamp DESC LIMIT $1;", limit)
        return [_format_record(r) for r in records]

async def log_pump_event(state: str, trigger: str):
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            "INSERT INTO pump_events (state, trigger_type) VALUES ($1, $2) RETURNING *;", state, trigger
        )
        return _format_record(record)
