import asyncio
import asyncpg

async def main():
    try:
        # Connect to the default 'postgres' database to create the new one
        conn = await asyncpg.connect(
            user="postgres", 
            password="1234", 
            database="postgres", 
            host="127.0.0.1"
        )
        
        # CREATE DATABASE cannot be executed inside a transaction block natively, 
        # but asyncpg default connection is fine as long as we don't start a transaction directly.
        await conn.execute('CREATE DATABASE home;')
        print("✅ Database 'home' created successfully!")
        
        await conn.close()
    except asyncpg.exceptions.DuplicateDatabaseError:
        print("✅ Database 'home' already exists.")
    except Exception as e:
        print(f"❌ Error creating database: {e}")

if __name__ == "__main__":
    asyncio.run(main())
