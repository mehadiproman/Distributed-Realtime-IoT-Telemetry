#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>

const char* ssid = "PromanQ";
const char* password = "00000000";

const char* mqtt_server = "test.mosquitto.org";
const int mqtt_port = 1883;
const char* mqtt_topic = "home/sensors/data";

#define DHTPIN 4
#define DHTTYPE DHT22

DHT dht(DHTPIN, DHTTYPE);

WiFiClient espClient;
PubSubClient client(espClient);

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  Serial.print("Connecting WiFi");

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }

  Serial.println();
  Serial.println("WiFi Connected");
  Serial.print("IP: ");
  Serial.println(WiFi.localIP());
}

void reconnectMQTT() {
  while (!client.connected()) {
    Serial.print("Connecting MQTT...");

    String clientId = "ESP32-" + String((uint32_t)ESP.getEfuseMac(), HEX);

    if (client.connect(clientId.c_str())) {
      Serial.println("Connected");
    } else {
      Serial.print("Failed rc=");
      Serial.println(client.state());
      delay(3000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  dht.begin();

  connectWiFi();

  client.setServer(mqtt_server, mqtt_port);
  client.setKeepAlive(60);
}

void loop() {

  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }

  if (!client.connected()) {
    reconnectMQTT();
  }

  client.loop();

  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat >= 5000) {
    lastHeartbeat = millis();
    String deviceId = "ESP32-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    String heartbeatTopic = "home/devices/" + deviceId + "/heartbeat";
    int rssi = WiFi.RSSI();
    String hbPayload = String(rssi) + ",100";
    client.publish(heartbeatTopic.c_str(), hbPayload.c_str());
  }

  static unsigned long lastSend = 0;

  if (millis() - lastSend >= 2000) {

    lastSend = millis();

    float humidity = dht.readHumidity();
    float temperature = dht.readTemperature();

    if (!isnan(humidity) && !isnan(temperature)) {

      String payload =
        String(temperature, 2) + "," +
        String(humidity, 2);

      client.publish(mqtt_topic, payload.c_str());

      Serial.print("Sent: ");
      Serial.println(payload);
    }
  }
}