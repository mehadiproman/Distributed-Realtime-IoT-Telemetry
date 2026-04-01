#include <WiFi.h>
#include <HTTPClient.h>
#include <PubSubClient.h>
#include <ESP32Servo.h>


// Defing wifi and MQTT credentials
const char * ssid = "galaxy";
const char * pswrd = "22224444";
const char * mqtt_server = "10.0.0.53";
// const char * mqtt_server = "192.168.122.1";


//Defin Pins of peripherals
const int tempPin   =    32;
const int presPin   =    33;
const int airPin    =    12;
const int lightPin  =    14;
const int SOIL_PIN  =    34;
const int RELAY_PIN =    26;

Servo myServo; // create a servo object
int servoPin = 13;


// Setup Wifi and MQTT Client
WiFiClient espClient;
PubSubClient client(espClient);

unsigned long pump_off_time = 0;
bool is_pump_on = false;
unsigned long last_publish = 0;

void setup_wifi(){
  delay(10);
  Serial.print("Connecting to ");
  Serial.println(ssid);

  WiFi.begin(ssid, pswrd);

  while (WiFi.status() != WL_CONNECTED){
    delay(500);
    Serial.print(".");
  }
  Serial.print("");
  Serial.println("WiFi connected");

}



void reconnect(){
  // Loop until we're reconnected
  while(!client.connected()){
    Serial.print("Attempting MQTT connection...");
    // Attempt to connect
    if(client.connect("ESP32Client")){
      Serial.println("connected");

      // suscribe to the topic from the broker
      client.subscribe("esp/cmd");
      client.subscribe("home/pump/cmd");
    } else {
      Serial.print("failed, rc=");
      Serial.print(client.state());
      Serial.println(" try again in 5 seconds");
      delay(5000); // try to reconnect in 5 seconds
    }
  }
}



// callback function tohandle incoming messages
void callback(char * topic, byte * payload, unsigned int length){
  // Serial.print("Message arrived on topic: ");
  // Serial.print(topic);
  // Serial.print(". Message: ");
  String message;
  for(int i=0; i < length; i++){
    message += (char)payload[i];
  }
  Serial.println(message);

  // Handle the received messages
  if (String(topic) == "esp/cmd"){
    Serial.println("Received message: " + message);
    // Add code here to handle specific commands
    parseStr(message);
  } else if (String(topic) == "home/pump/cmd") {
    Serial.println("Pump Command: " + message);
    int commaIndex = message.indexOf(',');
    String state = message;
    int duration = 30; // default 30s
    if (commaIndex != -1) {
      state = message.substring(0, commaIndex);
      duration = message.substring(commaIndex + 1).toInt();
    }
    
    if (state == "ON") {
      digitalWrite(RELAY_PIN, HIGH);
      is_pump_on = true;
      pump_off_time = millis() + (duration * 1000);
      client.publish("home/pump/status", "ON", true);
    } else {
      digitalWrite(RELAY_PIN, LOW);
      is_pump_on = false;
      client.publish("home/pump/status", "OFF", true);
    }
  }
}


void parseStr(const String& str) {
  // Find the position of the comma
  int commaIndex = str.indexOf(',');

  // Extract the text and state parts
  String sensorName = str.substring(0, commaIndex);
  int pinState = str.substring(commaIndex + 1).toInt();
  Serial.println("sensorName-> " + sensorName + ", pinState-> " + pinState);

  // Use a more compact switch-case statement
  if (sensorName == "temperature") {
    digitalWrite(tempPin, pinState);
  } else if (sensorName == "pressure") {
    digitalWrite(presPin, pinState);
  } else if (sensorName == "air") {
    //digitalWrite(airPin, pinState);
    run_servo(pinState);
  } else if (sensorName == "light") {
    digitalWrite(lightPin, pinState);
  } else {
    // Handle unknown sensor names if needed
  }
}










void setup() {
  // put your setup code here, to run once:
  Serial.begin(115200);
  setup_wifi();
  client.setServer(mqtt_server, 1883);
  client.setCallback(callback);

  myServo.attach(servoPin); // attach servo
  // set the peripheral pins as outputs
  pinMode(tempPin, OUTPUT);
  pinMode(presPin, OUTPUT);
  pinMode(airPin, OUTPUT);
  pinMode(lightPin, OUTPUT);
  pinMode(SOIL_PIN, INPUT);
  pinMode(RELAY_PIN, OUTPUT);
  digitalWrite(RELAY_PIN, LOW);

}

void loop() {
  // put your main code here, to run repeatedly:
  if(!client.connected()){
    reconnect();
  }
  client.loop();

  unsigned long current_time = millis();
  
  if (is_pump_on && current_time >= pump_off_time) {
    digitalWrite(RELAY_PIN, LOW);
    is_pump_on = false;
    client.publish("home/pump/status", "OFF", true);
  }

  if (current_time - last_publish >= 5000) {
    //run_servo();

    // Simulate sensor reading
    // float temperature = 25.0 + (rand() % 100) / 10.0;
    float temperature = random(0, 100) + random(0, 100) / 100.0; 
    float pressure = random(0, 1000) + random(0, 100) / 100.0; 
    float airQuality = random(0, 500) + random(0, 100) / 100.0; 
    float light = random(0, 100) + random(0, 100) / 100.0; 
    // String temp_str = String(temperature);

     // Combine all sensor values into a single comma-separated string using String()
    String payload = String(temperature) + "," + 
                     String(pressure) + "," + 
                     String(airQuality) + "," + 
                     String(light);

    // publish temperature to MQTT topic
    // client.publish("h/l/t", temp_str.c_str());
    client.publish("home/sensors/data", payload.c_str());
    Serial.print("Sensor data sent4: ");
    Serial.println(payload);
    
    // Soil moisture reading
    int raw_val = analogRead(SOIL_PIN);
    float moisture = map(raw_val, 4095, 0, 0, 100); 
    if (moisture < 0) moisture = 0;
    if (moisture > 100) moisture = 100;
    client.publish("home/sensors/soil", String(moisture).c_str());
    
    last_publish = current_time;
  }
}

void run_servo(int value){
  if (value == 0){
     myServo.write(0);
  } else {
    myServo.write(180);
    //delay(1000);
  }

}
