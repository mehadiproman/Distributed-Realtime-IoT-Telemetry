import asyncio
import asyncpg

DB_CONFIG = {
    "user": "postgres",
    "password": "1234",
    "database": "home",
    "host": "127.0.0.1",
    "port": 5432
}

async def check():
    conn = await asyncpg.connect(**DB_CONFIG)
    sensor_count = await conn.fetchval("SELECT COUNT(*) FROM sensor_data")
    soil_count = await conn.fetchval("SELECT COUNT(*) FROM soil_data")
    print(f"Sensor rows: {sensor_count}")
    print(f"Soil rows: {soil_count}")
    
    if sensor_count > 0:
        latest_sensors = await conn.fetch("SELECT * FROM sensor_data ORDER BY timestamp DESC LIMIT 5")
        for r in latest_sensors:
            print(dict(r))
            
    await conn.close()

asyncio.run(check())
