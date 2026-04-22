#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_BMP280.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// WiFi and MQTT Config
const char* ssid     = "PromanQ";
const char* password = "00000000";
const char* mqtt_server = "broker.hivemq.com";
const int   mqtt_port   = 1883;

// Topics
const char* mqtt_topic_data      = "home/sensors/data";
const char* mqtt_topic_heartbeat = "home/devices/ESP32-SENS/heartbeat";

// Pin definitions
#define DHTPIN    13
#define DHTTYPE   DHT22
#define LDR_PIN   34
#define SOIL_PIN  33

// Calibration
#define SOIL_DRY 3200
#define SOIL_WET 1000
#define TELEMETRY_INTERVAL_MS 2000
#define HEARTBEAT_INTERVAL_MS 5000

DHT              dht(DHTPIN, DHTTYPE);
Adafruit_BMP280  bmp;
WiFiClient       espClient;
PubSubClient     client(espClient);

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);
}

void reconnectMQTT() {
  while (!client.connected()) {
    if (client.connect("ESP32-SensorNode")) {
      Serial.println("[MQTT] Sensor Node Connected");
    } else {
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0); // Disable brownout
  dht.begin();
  Wire.begin(21, 22);
  bmp.begin(0x76);
  connectWiFi();
  client.setServer(mqtt_server, mqtt_port);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!client.connected()) reconnectMQTT();
  client.loop();

  static unsigned long lastTelemetry = 0;
  if (millis() - lastTelemetry >= TELEMETRY_INTERVAL_MS) {
    lastTelemetry = millis();
    float h = dht.readHumidity();
    float t = dht.readTemperature();
    if (!isnan(h) && !isnan(t)) {
      int light = 4095 - analogRead(LDR_PIN);
      int soil = (int)constrain(map(analogRead(SOIL_PIN), SOIL_DRY, SOIL_WET, 0, 100), 0, 100);
      float pres = bmp.readPressure() / 100.0F;
      float alt = bmp.readAltitude(1013.25F);
      char payload[64];
      snprintf(payload, sizeof(payload), "%.2f,%.2f,%d,%d,%.2f,%.2f", t, h, light, soil, pres, alt);
      client.publish(mqtt_topic_data, payload);
    }
  }

  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat >= HEARTBEAT_INTERVAL_MS) {
    lastHeartbeat = millis();
    long rssi = WiFi.RSSI();
    char hb[32];
    snprintf(hb, sizeof(hb), "%ld,100", rssi); // RSSI and Battery (fixed 100)
    client.publish(mqtt_topic_heartbeat, hb);
  }
}
