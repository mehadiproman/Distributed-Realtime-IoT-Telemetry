#include <WiFi.h>
#include <PubSubClient.h>
#include "soc/soc.h"
#include "soc/rtc_cntl_reg.h"

// WiFi and MQTT Config
const char* ssid     = "PromanQ";
const char* password = "00000000";
const char* mqtt_server = "broker.hivemq.com";
const int   mqtt_port   = 1883;

// Topics
const char* mqtt_topic_pump_cmd  = "home/pump/cmd";
const char* mqtt_topic_pump_stat = "home/pump/status";
const char* mqtt_topic_heartbeat = "home/devices/ESP32-ACTU/heartbeat";

// Pin definition
#define RELAY_PIN 18

WiFiClient espClient;
PubSubClient client(espClient);

bool pumpState = false;

void setPump(bool state) {
  pumpState = state;
  digitalWrite(RELAY_PIN, state ? LOW : HIGH); // Active-Low
  client.publish(mqtt_topic_pump_stat, state ? "ON" : "OFF");
  Serial.printf("[ACTUATOR] Pump → %s\n", state ? "ON" : "OFF");
}

void mqttCallback(char* topic, byte* payload, unsigned int length) {
  char msg[16];
  if (length >= sizeof(msg)) length = sizeof(msg) - 1;
  memcpy(msg, payload, length);
  msg[length] = '\0';

  if (strcmp(topic, mqtt_topic_pump_cmd) == 0) {
    if (strstr(msg, "ON")) setPump(true);
    else if (strstr(msg, "OFF")) setPump(false);
  }
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) return;
  WiFi.begin(ssid, password);
  while (WiFi.status() != WL_CONNECTED) delay(500);
}

void reconnectMQTT() {
  while (!client.connected()) {
    if (client.connect("ESP32-ActuatorNode")) {
      client.subscribe(mqtt_topic_pump_cmd);
      Serial.println("[MQTT] Actuator Node Connected");
    } else {
      delay(5000);
    }
  }
}

void setup() {
  Serial.begin(115200);
  WRITE_PERI_REG(RTC_CNTL_BROWN_OUT_REG, 0); 
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, HIGH); // Default OFF
  connectWiFi();
  client.setServer(mqtt_server, mqtt_port);
  client.setCallback(mqttCallback);
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!client.connected()) reconnectMQTT();
  client.loop();

  static unsigned long lastHeartbeat = 0;
  if (millis() - lastHeartbeat >= 5000) {
    lastHeartbeat = millis();
    long rssi = WiFi.RSSI();
    char hb[32];
    snprintf(hb, sizeof(hb), "%ld,100", rssi);
    client.publish(mqtt_topic_heartbeat, hb);
  }
}
