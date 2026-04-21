import asyncio
import asyncpg

async def main():
    conn = await asyncpg.connect('postgresql://postgres:1234@127.0.0.1:5432/home')
    rows = await conn.fetch("SELECT pid, state, query FROM pg_stat_activity WHERE state != 'idle'")
    for r in rows:
        print(dict(r))
    await conn.close()

asyncio.run(main())
