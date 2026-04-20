"""
Diagnostic test to check MQTT connection and message reception
"""
import sys
import asyncio
import aiomqtt

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsSelectorEventLoopPolicy())

async def test_mqtt():
    MQTT_BROKER = "test.mosquitto.org"
    MQTT_PORT = 1883
    
    print(f"Testing MQTT connection to {MQTT_BROKER}:{MQTT_PORT}...")
    
    try:
        async with aiomqtt.Client(hostname=MQTT_BROKER, port=MQTT_PORT) as client:
            print("✅ Connected to MQTT broker")
            
            print("Subscribing to topics...")
            await client.subscribe("home/sensors/#")
            await client.subscribe("home/pump/status")
            print("✅ Subscribed to topics")
            
            print("\nListening for messages (30 seconds timeout)...\n")
            
            try:
                async with asyncio.timeout(30):  # 30 second timeout
                    async with client.messages() as messages:
                        async for message in messages:
                            topic = str(message.topic)
                            payload = message.payload.decode()
                            print(f"📨 {topic}: {payload}")
            except asyncio.TimeoutError:
                print("\n⏱️  No messages received in 30 seconds")
                print("This means:")
                print("  1. MQTT broker is working ✅")
                print("  2. But ESP32 is NOT publishing data ❌")
                print("  3. Check your ESP32 code and MQTT topic names")
                
    except Exception as e:
        print(f"❌ MQTT Error: {e}")
        print("This means:")
        print("  1. Cannot connect to MQTT broker")
        print("  2. Check broker address and network connectivity")

if __name__ == "__main__":
    asyncio.run(test_mqtt())
