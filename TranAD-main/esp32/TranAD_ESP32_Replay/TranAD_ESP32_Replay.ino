#include <WiFi.h>
#include <PubSubClient.h>
#include <ArduinoJson.h>
#include <esp_timer.h>
#include <pgmspace.h>

// Copy generated replay header here before building:
// source: data/synthetic/esp32_replay.h
#include "esp32_replay.h"

// ===================== User Config =====================
static const char* WIFI_SSID = "Tu Taaru Vapar";
static const char* WIFI_PASSWORD = "veersharma";

static const uint16_t MQTT_PORT = 1883;
static const char* MQTT_TOPIC = "esp32/telemetry";
static const char* MQTT_CLIENT_ID = "tranad-esp32-device";
static const char* SOURCE_ID = "esp32-001";
static const uint16_t MQTT_BUFFER_SIZE = 4096;
static const char* MQTT_BROKER_PRIMARY = "10.59.244.47";
static const char* MQTT_BROKER_FALLBACK = "broker.hivemq.com";
static const uint8_t MQTT_CONNECT_RETRIES_BEFORE_FAILOVER = 5;

// Match backend ingest cadence expectations.
static const uint32_t PUBLISH_INTERVAL_MS = 500;

// ===================== Runtime =====================
WiFiClient wifiClient;
PubSubClient mqttClient(wifiClient);

uint32_t frameIndex = 0;
uint64_t seqId = 0;
uint64_t nextPublishAtMs = 0;
const char* mqttBrokerCandidates[] = {MQTT_BROKER_PRIMARY, MQTT_BROKER_FALLBACK};
static const uint8_t MQTT_BROKER_COUNT = sizeof(mqttBrokerCandidates) / sizeof(mqttBrokerCandidates[0]);
uint8_t mqttBrokerIndex = 0;
// Keep JSON and payload buffers off the loop task stack to avoid runtime instability.
StaticJsonDocument<MQTT_BUFFER_SIZE> telemetryDoc;
char telemetryPayload[MQTT_BUFFER_SIZE];

static inline float replayValue(uint32_t frame, uint32_t ch) {
  int16_t q = (int16_t)pgm_read_word(&(ESP32_REPLAY_DATA[frame][ch]));
  float scale = pgm_read_float(&(ESP32_REPLAY_SCALES[ch]));
  float offset = pgm_read_float(&(ESP32_REPLAY_OFFSETS[ch]));
  return ((float)q * scale) + offset;
}

void connectWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    return;
  }

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("[ESP32] Connecting WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println();
  Serial.print("[ESP32] WiFi connected. IP=");
  Serial.println(WiFi.localIP());
}

void connectMQTT() {
  uint8_t failedAttempts = 0;
  while (!mqttClient.connected()) {
    Serial.print("[ESP32] Connecting MQTT...");
    Serial.print(mqttBrokerCandidates[mqttBrokerIndex]);
    Serial.print(":");
    Serial.print(MQTT_PORT);
    Serial.print(" ");
    if (mqttClient.connect(MQTT_CLIENT_ID)) {
      Serial.println("connected");
      return;
    }
    Serial.print("failed rc=");
    Serial.println(mqttClient.state());
    failedAttempts += 1;
    if (MQTT_BROKER_COUNT > 1 && failedAttempts >= MQTT_CONNECT_RETRIES_BEFORE_FAILOVER) {
      failedAttempts = 0;
      mqttBrokerIndex = (uint8_t)((mqttBrokerIndex + 1U) % MQTT_BROKER_COUNT);
      mqttClient.setServer(mqttBrokerCandidates[mqttBrokerIndex], MQTT_PORT);
      Serial.print("[ESP32] switching MQTT broker -> ");
      Serial.println(mqttBrokerCandidates[mqttBrokerIndex]);
    }
    delay(1500);
  }
}

bool publishFrame() {
  uint64_t nowMs = (uint64_t)(esp_timer_get_time() / 1000ULL);
  telemetryDoc.clear();
  telemetryDoc["timestamp_ms"] = nowMs;
  telemetryDoc["source_id"] = SOURCE_ID;
  telemetryDoc["seq_id"] = seqId;

  JsonArray sensors = telemetryDoc.createNestedArray("sensors");
  for (uint32_t ch = 0; ch < ESP32_REPLAY_CHANNELS; ++ch) {
    sensors.add(replayValue(frameIndex, ch));
  }

  size_t n = serializeJson(telemetryDoc, telemetryPayload, sizeof(telemetryPayload));
  if (n == 0) {
    Serial.println("[ESP32] JSON serialization failed");
    return false;
  }
  if (n >= sizeof(telemetryPayload) - 1U) {
    Serial.println("[ESP32] payload truncated: increase MQTT_BUFFER_SIZE");
    return false;
  }

  bool ok = mqttClient.publish(MQTT_TOPIC, (const uint8_t*)telemetryPayload, n, false);
  if (!ok) {
    Serial.print("[ESP32] publish failed, mqtt state=");
    Serial.println(mqttClient.state());
    return false;
  }

  if ((seqId % 20ULL) == 0ULL) {
    Serial.print("[ESP32] published seq=");
    Serial.print(seqId);
    Serial.print(" frame=");
    Serial.print(frameIndex);
    Serial.print(" channels=");
    Serial.println(ESP32_REPLAY_CHANNELS);
  }

  seqId += 1ULL;
  frameIndex = (frameIndex + 1U) % (uint32_t)ESP32_REPLAY_FRAMES;
  return true;
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("[ESP32] boot");
  Serial.print("[ESP32] primary broker=");
  Serial.println(MQTT_BROKER_PRIMARY);
  Serial.print("[ESP32] fallback broker=");
  Serial.println(MQTT_BROKER_FALLBACK);
  Serial.print("[ESP32] mqtt port=");
  Serial.println(MQTT_PORT);
  Serial.print("[ESP32] topic=");
  Serial.println(MQTT_TOPIC);

  mqttClient.setServer(mqttBrokerCandidates[mqttBrokerIndex], MQTT_PORT);
  mqttClient.setKeepAlive(30);
  mqttClient.setSocketTimeout(5);
  bool mqttBufferOk = mqttClient.setBufferSize(MQTT_BUFFER_SIZE);
  Serial.print("[ESP32] mqtt buffer set to ");
  Serial.print(MQTT_BUFFER_SIZE);
  Serial.print(" bytes, ok=");
  Serial.println(mqttBufferOk ? "true" : "false");

  connectWiFi();
  connectMQTT();

  nextPublishAtMs = (uint64_t)(esp_timer_get_time() / 1000ULL);
  Serial.println("[ESP32] replay publisher started");
}

void loop() {
  if (WiFi.status() != WL_CONNECTED) {
    connectWiFi();
  }
  if (!mqttClient.connected()) {
    connectMQTT();
  }

  mqttClient.loop();

  uint64_t nowMs = (uint64_t)(esp_timer_get_time() / 1000ULL);
  if (nowMs >= nextPublishAtMs) {
    publishFrame();
    nextPublishAtMs += (uint64_t)PUBLISH_INTERVAL_MS;

    // If loop lagged too much, resync to avoid burst flood.
    if (nowMs > nextPublishAtMs + 5000ULL) {
      nextPublishAtMs = nowMs + (uint64_t)PUBLISH_INTERVAL_MS;
    }
  }
}
