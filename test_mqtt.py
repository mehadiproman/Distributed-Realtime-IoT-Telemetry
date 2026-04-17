import sys
import asyncio
import aiomqtt

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def main():
    async with aiomqtt.Client(hostname="test.mosquitto.org", port=1883) as client:
        await client.subscribe("home/sensors/#")
        print("Connected to test.mosquitto.org and subscribed to home/sensors/#")
        async with client.messages() as messages:
            async for message in messages:
                print(f"[{message.topic}] {message.payload.decode()}")

asyncio.run(main())
