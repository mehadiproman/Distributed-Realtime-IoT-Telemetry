import asyncpg
from datetime import datetime, timedelta, timezone

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
    
    if d.get("last_seen"):
        try:
            d["last_seen"] = d["last_seen"].astimezone(bst_tz)
        except Exception:
            d["last_seen"] = d["last_seen"].replace(tzinfo=timezone.utc).astimezone(bst_tz)

    # Convert Decimal to float for JSON/ML compatibility
    for key in ["temperature", "humidity", "pressure", "air_quality", "light_intensity", "moisture", "wifi_signal", "battery_level"]:
        if d.get(key) is not None:
            d[key] = float(d[key])
            
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
                humidity NUMERIC,
                pressure NUMERIC,
                air_quality NUMERIC,
                light_intensity NUMERIC
            );
            DO $$ 
            BEGIN 
                IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='sensor_data' AND column_name='humidity') THEN
                    ALTER TABLE sensor_data ADD COLUMN humidity NUMERIC;
                END IF;
            END $$;

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
            CREATE TABLE IF NOT EXISTS device_status (
                device_id VARCHAR(50) PRIMARY KEY,
                last_seen TIMESTAMPTZ DEFAULT NOW(),
                wifi_signal NUMERIC,
                battery_level NUMERIC,
                status VARCHAR(20) DEFAULT 'offline'
            );
            CREATE TABLE IF NOT EXISTS system_settings (
                key VARCHAR(50) PRIMARY KEY,
                value VARCHAR(50)
            );
            INSERT INTO system_settings (key, value) VALUES ('pump_mode', 'AUTO') ON CONFLICT DO NOTHING;
            INSERT INTO system_settings (key, value) VALUES ('auto_cleanup_enabled', 'false') ON CONFLICT DO NOTHING;
            INSERT INTO system_settings (key, value) VALUES ('auto_cleanup_days', '30') ON CONFLICT DO NOTHING;
        """)

async def get_all_sensor_data(limit=100):
    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT * FROM sensor_data ORDER BY timestamp DESC LIMIT $1;", limit)
        return [_format_record(r) for r in records]

async def get_sensor_data_by_id(record_id: int):
    async with pool.acquire() as conn:
        record = await conn.fetchrow("SELECT * FROM sensor_data WHERE id = $1;", record_id)
        return _format_record(record)

async def get_sensor_data_within_range(time_end_hrs: float, limit: int = 20, offset: int = 0):
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT * FROM sensor_data
            WHERE timestamp >= NOW() - (interval '1 hour' * $1)
            ORDER BY timestamp DESC
            LIMIT $2 OFFSET $3;
        """, time_end_hrs, limit, offset)
        return [_format_record(r) for r in records]

async def create_sensor_data(data: dict):
    query = """
        INSERT INTO sensor_data (temperature, humidity, pressure, air_quality, light_intensity)
        VALUES ($1, $2, $3, $4, $5) RETURNING *;
    """
    async with pool.acquire() as conn:
        record = await conn.fetchrow(
            query, 
            data.get('temperature', 0), 
            data.get('humidity', 0),
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

async def update_device_status(device_id: str, wifi: float, battery: float, status: str):
    async with pool.acquire() as conn:
        record = await conn.fetchrow("""
            INSERT INTO device_status (device_id, last_seen, wifi_signal, battery_level, status)
            VALUES ($1, NOW(), $2, $3, $4)
            ON CONFLICT (device_id) DO UPDATE SET
                last_seen = NOW(),
                wifi_signal = EXCLUDED.wifi_signal,
                battery_level = EXCLUDED.battery_level,
                status = EXCLUDED.status
            RETURNING *;
        """, device_id, wifi, battery, status)
        return _format_record(record)

async def mark_offline_devices(timeout_seconds: int):
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            UPDATE device_status
            SET status = 'offline'
            WHERE status = 'online' AND NOW() - last_seen > interval '1 second' * $1
            RETURNING *;
        """, timeout_seconds)
        return [_format_record(r) for r in records]

async def get_all_devices():
    async with pool.acquire() as conn:
        records = await conn.fetch("SELECT * FROM device_status ORDER BY last_seen DESC;")
        return [_format_record(r) for r in records]

async def get_pump_mode():
    async with pool.acquire() as conn:
        record = await conn.fetchrow("SELECT value FROM system_settings WHERE key = 'pump_mode';")
        return record['value'] if record else 'AUTO'

async def set_pump_mode(mode: str):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE system_settings SET value = $1 WHERE key = 'pump_mode';", mode)
        return mode

async def get_retention_settings():
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT key, value FROM system_settings WHERE key IN ('auto_cleanup_enabled', 'auto_cleanup_days');")
        settings = {r['key']: r['value'] for r in rows}
        return {
            "enabled": settings.get('auto_cleanup_enabled') == 'true',
            "days": int(settings.get('auto_cleanup_days', 30))
        }

async def set_retention_settings(enabled: bool, days: int):
    async with pool.acquire() as conn:
        await conn.execute("UPDATE system_settings SET value = $1 WHERE key = 'auto_cleanup_enabled';", 'true' if enabled else 'false')
        await conn.execute("UPDATE system_settings SET value = $1 WHERE key = 'auto_cleanup_days';", str(days))
        return {"enabled": enabled, "days": days}

async def get_sensor_data_by_date_range(start_dt, end_dt):
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT * FROM sensor_data
            WHERE timestamp >= $1 AND timestamp <= $2
            ORDER BY timestamp ASC;
        """, start_dt, end_dt)
        return [_format_record(r) for r in records]

async def get_soil_data_by_date_range(start_dt, end_dt):
    async with pool.acquire() as conn:
        records = await conn.fetch("""
            SELECT * FROM soil_data
            WHERE timestamp >= $1 AND timestamp <= $2
            ORDER BY timestamp ASC;
        """, start_dt, end_dt)
        return [_format_record(r) for r in records]

async def get_history_stats():
    """Returns database statistics for telemetry storage."""
    async with pool.acquire() as conn:
        stats = {}
        
        # Total rows
        stats['sensor_rows'] = await conn.fetchval("SELECT COUNT(*) FROM sensor_data;")
        stats['soil_rows'] = await conn.fetchval("SELECT COUNT(*) FROM soil_data;")
        stats['total_rows'] = stats['sensor_rows'] + stats['soil_rows']
        
        # Estimated storage in MB (pg_total_relation_size includes data and indexes)
        size_bytes = await conn.fetchval("""
            SELECT COALESCE(pg_total_relation_size('sensor_data'), 0) + 
                   COALESCE(pg_total_relation_size('soil_data'), 0);
        """)
        stats['storage_mb'] = round(size_bytes / (1024 * 1024), 2)
        
        # Date range
        range_data = await conn.fetchrow("""
            SELECT MIN(min_t) as oldest, MAX(max_t) as newest FROM (
                SELECT MIN(timestamp) as min_t, MAX(timestamp) as max_t FROM sensor_data
                UNION ALL
                SELECT MIN(timestamp) as min_t, MAX(timestamp) as max_t FROM soil_data
            ) as combined;
        """)
        stats['oldest_record'] = range_data['oldest'].astimezone(bst_tz) if range_data['oldest'] else None
        stats['newest_record'] = range_data['newest'].astimezone(bst_tz) if range_data['newest'] else None
        
        # Avg rows per day (estimated from oldest record)
        if stats['oldest_record'] and stats['total_rows'] > 0:
            days_diff = (stats['newest_record'] - stats['oldest_record']).days or 1
            stats['avg_per_day'] = int(stats['total_rows'] / days_diff)
        else:
            stats['avg_per_day'] = 0
            
        return stats

async def get_cleanup_preview(days: int):
    """Counts how many records would be deleted if cleaning up older than X days."""
    async with pool.acquire() as conn:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        sensor_count = await conn.fetchval("SELECT COUNT(*) FROM sensor_data WHERE timestamp < $1;", cutoff)
        soil_count = await conn.fetchval("SELECT COUNT(*) FROM soil_data WHERE timestamp < $1;", cutoff)
        
        return {
            "days": days,
            "sensor_deleted": sensor_count,
            "soil_deleted": soil_count,
            "total_deleted": sensor_count + soil_count,
            "cutoff_date": cutoff.astimezone(bst_tz).isoformat()
        }

async def delete_old_telemetry(days: int):
    """Safely deletes telemetry data older than X days."""
    async with pool.acquire() as conn:
        cutoff = datetime.now(timezone.utc) - timedelta(days=days)
        
        async with conn.transaction():
            deleted_sensor = await conn.execute("DELETE FROM sensor_data WHERE timestamp < $1;", cutoff)
            deleted_soil = await conn.execute("DELETE FROM soil_data WHERE timestamp < $1;", cutoff)
            
            # Simple parsing: "DELETE 123" -> 123
            count_sensor = int(deleted_sensor.split()[1])
            count_soil = int(deleted_soil.split()[1])
            
            return {
                "sensor_deleted": count_sensor,
                "soil_deleted": count_soil,
                "total_deleted": count_sensor + count_soil,
                "timestamp": datetime.now(bst_tz).isoformat()
            }

async def get_system_metrics():
    async with pool.acquire() as conn:
        metrics = {}
        
        # Device counts and IDs
        devices = await conn.fetch("SELECT device_id, status FROM device_status;")
        metrics['total_devices'] = len(devices)
        active_list = [d['device_id'] for d in devices if d['status'] == 'online']
        metrics['active_devices'] = len(active_list)
        metrics['active_device_ids'] = active_list
        metrics['offline_devices'] = metrics['total_devices'] - metrics['active_devices']
        
        # Last Telemetry
        last_sync = await conn.fetchval("""
            SELECT MAX(timestamp) FROM (
                SELECT timestamp FROM sensor_data
                UNION ALL
                SELECT timestamp FROM soil_data
            ) AS combined;
        """)
        metrics['last_sync'] = last_sync.astimezone(bst_tz) if last_sync else None
        
        # Records today (last 24h)
        metrics['records_today'] = await conn.fetchval("""
            SELECT COUNT(*) FROM (
                SELECT id FROM sensor_data WHERE timestamp > NOW() - interval '24 hours'
                UNION ALL
                SELECT id FROM soil_data WHERE timestamp > NOW() - interval '24 hours'
            ) AS combined;
        """)
        
        return metrics
