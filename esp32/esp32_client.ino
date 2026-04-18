#include <WiFi.h>
#include <PubSubClient.h>
#include <DHT.h>
#include <Wire.h>
#include <Adafruit_BMP280.h>

const char* ssid = "PromanQ";
const char* password = "00000000";

const char* mqtt_server = "test.mosquitto.org";
const int mqtt_port = 1883;
const char* mqtt_topic = "home/sensors/data";

#define DHTPIN 13
#define DHTTYPE DHT22
#define LDR_PIN 34
#define SOIL_PIN 33

#define SOIL_DRY 3200
#define SOIL_WET 1000

DHT dht(DHTPIN, DHTTYPE);
Adafruit_BMP280 bmp;

WiFiClient espClient;
PubSubClient client(espClient);

void connectWiFi() {
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);

  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
  }
}

void reconnectMQTT() {
  while (!client.connected()) {
    String clientId = "ESP32-" + String((uint32_t)ESP.getEfuseMac(), HEX);
    client.connect(clientId.c_str());
    delay(1000);
  }
}

void setup() {
  Serial.begin(115200);

  dht.begin();

  pinMode(LDR_PIN, INPUT);
  pinMode(SOIL_PIN, INPUT);

  Wire.begin(21, 22);

  if (bmp.begin(0x76)) {
    Serial.println("BMP280 found at 0x76");
  }
  else if (bmp.begin(0x77)) {
    Serial.println("BMP280 found at 0x77");
  }
  else {
    Serial.println("BMP280 not found");
  }

  connectWiFi();
  client.setServer(mqtt_server, mqtt_port);
}

void loop() {

  if (WiFi.status() != WL_CONNECTED) connectWiFi();
  if (!client.connected()) reconnectMQTT();

  client.loop();

  static unsigned long lastSend = 0;

  if (millis() - lastSend >= 2000) {

    lastSend = millis();

    // DHT22
    float humidity = dht.readHumidity();
    float temperature = dht.readTemperature();

    // LDR
    int rawLight = analogRead(LDR_PIN);
    int lightValue = 4095 - rawLight;

    // Soil
    int rawSoil = analogRead(SOIL_PIN);
    int soilPercent = map(rawSoil, SOIL_DRY, SOIL_WET, 0, 100);
    soilPercent = constrain(soilPercent, 0, 100);

    // BMP280
    float pressure = bmp.readPressure() / 100.0F;
    float altitude = bmp.readAltitude(1013.25);

    if (isnan(pressure)) pressure = -1;
    if (isnan(altitude)) altitude = -1;

    // Publish
    if (!isnan(humidity) && !isnan(temperature)) {

      String payload =
        String(temperature, 2) + "," +
        String(humidity, 2) + "," +
        String(lightValue) + "," +
        String(soilPercent) + "," +
        String(pressure, 2) + "," +
        String(altitude, 2);

      client.publish(mqtt_topic, payload.c_str());

      Serial.print("Sent: ");
      Serial.println(payload);
    }
  }
}