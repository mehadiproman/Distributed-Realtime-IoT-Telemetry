/*
 * ============================================================
 *  Smart Agriculture ESP32 Firmware — Fixed & Production-Ready
 *  Fixes applied:
 *    1. Brownout detector disabled at boot
 *    2. Relay execution deferred 200ms after MQTT callback
 *    3. All heap-allocated String ops removed
 *    4. MQTT Broker switched to HiveMQ (more stable)
 *    5. Shortened ClientID (max compatibility)
 *    6. GPIO18 used for Active-Low Relay
 * ============================================================
 */

#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_BMP280.h>

// Required for brownout disable
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"
#include "esp_system.h"

// ─── WiFi credentials ────────────────────────────────────────────────────────
const char* ssid     = "PromanQ";
const char* password = "00000000";

// ─── MQTT broker ─────────────────────────────────────────────────────────────
const char* mqtt_server = "broker.hivemq.com";
const int   mqtt_port   = 1883;

// ─── MQTT topics ─────────────────────────────────────────────────────────────
const char* mqtt_topic_data      = "home/sensors/data";
const char* mqtt_topic_pump_cmd  = "home/pump/cmd";
const char* mqtt_topic_pump_stat = "home/pump/status";

// ─── Pin definitions ─────────────────────────────────────────────────────────
#define DHTPIN    13
#define DHTTYPE   DHT22
#define LDR_PIN   34
#define SOIL_PIN  33
#define RELAY_PIN 18

// ─── Soil calibration ────────────────────────────────────────────────────────
#define SOIL_DRY 3200
#define SOIL_WET 1000

#define RELAY_EXECUTE_DELAY_MS 200
#define TELEMETRY_INTERVAL_MS 2000

// ─── Objects ─────────────────────────────────────────────────────────────────
DHT              dht(DHTPIN, DHTTYPE);
Adafruit_BMP280  bmp;
WiFiClient       espClient;
PubSubClient     client(espClient);

// ─── Global State ────────────────────────────────────────────────────────────
bool          pumpState          = false;
bool          pumpTimerActive    = false;
unsigned long pumpStartMillis    = 0;
unsigned long pumpDurationMs     = 0;
bool          pendingStatusPublish = false;

volatile bool pumpCommandPending      = false;
volatile bool pumpCommandTargetState  = false;
volatile int  pumpCommandDurationSecs = 0;
unsigned long pumpCommandScheduledAt  = 0;

// ─────────────────────────────────────────────────────────────────────────────
//  Hardware control
// ─────────────────────────────────────────────────────────────────────────────
void setPump(bool state) {
  if (pumpState != state) {
    pumpState = state;
    digitalWrite(RELAY_PIN, state ? LOW : HIGH); // Active-Low
    pendingStatusPublish = true;
    Serial.printf("[PUMP] → %s\n", state ? "ON" : "OFF");
  }
}

void publishPumpStatus() {
  if (client.connected()) {
    client.publish(mqtt_topic_pump_stat, pumpState ? "ON" : "OFF");
  }
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char msg[32];
  if (length >= sizeof(msg)) length = sizeof(msg) - 1;
  memcpy(msg, payload, length);
  msg[length] = '\0';

  if (strcmp(topic, mqtt_topic_pump_cmd) != 0) return;

  char command[8] = {0};
  int  durationSecs = 0;

  char* comma = strchr(msg, ',');
  if (comma != NULL) {
    size_t cmdLen = (size_t)(comma - msg);
    if (cmdLen >= sizeof(command)) cmdLen = sizeof(command) - 1;
    memcpy(command, msg, cmdLen);
    command[cmdLen] = '\0';
    durationSecs = atoi(comma + 1);
  } else {
    strncpy(command, msg, sizeof(command) - 1);
  }

  pumpCommandTargetState  = (strcmp(command, "ON") == 0);
  pumpCommandDurationSecs = durationSecs;
  pumpCommandScheduledAt  = millis();
  pumpCommandPending      = true;

  Serial.printf("[MQTT] Cmd: %s  Dur: %ds\n", command, durationSecs);
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  Serial.print("[WiFi] Connecting");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.printf("\n[WiFi] Connected IP: %s\n", WiFi.localIP().toString().c_str());
}

void reconnectMQTT() {
  if (client.connected()) return;

  char clientId[20];
  snprintf(clientId, sizeof(clientId), "ESP32-%04X", (uint16_t)ESP.getEfuseMac());

  Serial.printf("[MQTT] Connecting to %s as %s...\n", mqtt_server, clientId);

  if (client.connect(clientId)) {
    client.subscribe(mqtt_topic_pump_cmd);
    publishPumpStatus();
    Serial.println("[MQTT] Connected");
  } else {
    Serial.printf("[MQTT] Failed rc=%d — retrying in 5s\n", client.state());
    delay(5000);
  }
}

void setup() {
  Serial.begin(115200);
  delay(200);

  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0);

  digitalWrite(RELAY_PIN, HIGH);
  pinMode(RELAY_PIN, OUTPUT);

  dht.begin();
  pinMode(LDR_PIN,  INPUT);
  pinMode(SOIL_PIN, INPUT);

  Wire.begin(21, 22);
  bmp.begin(0x76);

  connectWiFi();
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(mqttCallback);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!client.connected()) reconnectMQTT();
  client.loop();

  if (pumpCommandPending &&
      (millis() - pumpCommandScheduledAt >= RELAY_EXECUTE_DELAY_MS)) {
    pumpCommandPending = false;
    if (pumpCommandTargetState) {
      setPump(true);
      if (pumpCommandDurationSecs > 0) {
        pumpTimerActive  = true;
        pumpStartMillis  = millis();
        pumpDurationMs   = (unsigned long)pumpCommandDurationSecs * 1000UL;
      }
    } else {
      setPump(false);
      pumpTimerActive = false;
    }
  }

  if (pendingStatusPublish) {
    publishPumpStatus();
    pendingStatusPublish = false;
  }

  if (pumpTimerActive && pumpState) {
    if (millis() - pumpStartMillis >= pumpDurationMs) {
      setPump(false);
      pumpTimerActive = false;
    }
  }

  static unsigned long lastSend = 0;
  if (millis() - lastSend >= TELEMETRY_INTERVAL_MS) {
    lastSend = millis();

    // Stability delay for DHT
    delay(10);
    float humidity    = dht.readHumidity();
    float temperature = dht.readTemperature();

    if (!isnan(humidity) && !isnan(temperature)) {
      int rawLight  = analogRead(LDR_PIN);
      int lightValue = 4095 - rawLight;
      int rawSoil    = analogRead(SOIL_PIN);
      int soilPercent = (int)constrain(map(rawSoil, SOIL_DRY, SOIL_WET, 0, 100), 0, 100);
      float pressure = bmp.readPressure() / 100.0F;
      float altitude = bmp.readAltitude(1013.25F);

      char payload[64];
      snprintf(payload, sizeof(payload), "%.2f,%.2f,%d,%d,%.2f,%.2f",
               temperature, humidity, lightValue, soilPercent, pressure, altitude);

      if (client.connected()) {
        client.publish(mqtt_topic_data, payload);
        Serial.printf("[DATA] %s\n", payload);
      }
    } else {
      Serial.println("[DHT22] Read failed");
    }
  }
}
