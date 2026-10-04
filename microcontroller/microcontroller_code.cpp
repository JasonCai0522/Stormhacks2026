/*
  Dual MPU6050 -> Bluetooth LE (ESP32)

  Based on dual_mpu6050_two_buses_diff.ino. Same wiring and self-test, but
  instead of printing once per second it streams the CHANGE in acceleration
  (sample-to-sample, in g) and gyroscope readings at ~100 Hz.

  Wiring (unchanged):
    ESP32 3V3    -> VCC on both sensors
    ESP32 GND    -> GND on both sensors
    Sensor 1: SDA -> GPIO21, SCL -> GPIO22   (bus "Wire")
    Sensor 2: SDA -> GPIO25, SCL -> GPIO26   (bus "Wire1")
    Both sensors use address 0x68 (AD0 unconnected or tied to GND)

  BLE:
    Device name : ESP32-IMU
    Service     : 6e400001-b5a3-f393-e0a9-e50e24dcca9e
    Notify char : 6e400003-b5a3-f393-e0a9-e50e24dcca9e

  Two v2 packets per sample, one per sensor. Each is 17 bytes, little-endian,
  and fits the default 20-byte BLE payload. Both have the same timestamp:
    uint32 t_ms        millis() when sampled
    uint8  flags       bit7 = v2, bit2 = sensor index (0/1), bit0 = sensor ok
    int16  d[3]        dax,day,daz (milli-g)
    int16  gyro[3]     bias-corrected gx,gy,gz (32.8 LSB per degree/second)

  Magnitude is computed on the computer side from the three axes.
  Keep sensors still at startup: self-test also estimates gyroscope bias.

  LED on GPIO 2:
    slow blink = both sensors working
    fast blink = at least one sensor missing or failing
*/
#include <Wire.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>

const int LED_PIN = 2;

const int SDA1_PIN = 21;
const int SCL1_PIN = 22;
const int SDA2_PIN = 25;
const int SCL2_PIN = 26;

const unsigned long SAMPLE_MS = 10;   // 100 samples per second

const float ACCEL_SCALE = 16384.0;    // LSB per g (+/-2g)
// GYRO_CONFIG=0x10: +/-1000 degrees/second, 32.8 LSB per degree/second.

#define BLE_NAME      "ESP32-IMU"
#define SERVICE_UUID  "6e400001-b5a3-f393-e0a9-e50e24dcca9e"
#define TX_CHAR_UUID  "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

struct Imu {
  TwoWire *bus;
  uint8_t addr;
  const char *name;
  bool ok;
  float gyroBias[3];
};

Imu imus[2] = {
  {&Wire,  0x68, "IMU1", false, {0, 0, 0}},
  {&Wire1, 0x68, "IMU2", false, {0, 0, 0}}
};

struct __attribute__((packed)) Packet {
  uint32_t t_ms;
  uint8_t  flags;
  int16_t  d[3];
  int16_t  gyro[3];
};
static_assert(sizeof(Packet) == 17, "BLE packet must fit default payload");

unsigned long lastBlink = 0, lastSample = 0, lastRetry = 0;
bool ledState = false;

float prevAccel[2][3];
bool hasPrev[2] = {false, false};

BLEServer *bleServer = nullptr;
BLECharacteristic *txChar = nullptr;
volatile bool bleConnected = false;

// ---------- BLE ----------

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer *s) override {
    bleConnected = true;
    Serial.println("BLE client connected");
  }
  void onDisconnect(BLEServer *s) override {
    bleConnected = false;
    Serial.println("BLE client disconnected, advertising again");
    BLEDevice::startAdvertising();
  }
};

void setupBle() {
  BLEDevice::init(BLE_NAME);
  bleServer = BLEDevice::createServer();
  bleServer->setCallbacks(new ServerCallbacks());

  BLEService *service = bleServer->createService(SERVICE_UUID);
  txChar = service->createCharacteristic(TX_CHAR_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  txChar->addDescriptor(new BLE2902());
  service->start();

  BLEAdvertising *adv = BLEDevice::getAdvertising();
  adv->addServiceUUID(SERVICE_UUID);
  adv->setScanResponse(true);
  BLEDevice::startAdvertising();
  Serial.println("BLE advertising as " BLE_NAME);
}

// ---------- IMU helpers (from the original sketch) ----------

bool probe(Imu &m) {
  m.bus->beginTransmission(m.addr);
  return m.bus->endTransmission() == 0;
}

bool writeRegister(Imu &m, uint8_t reg, uint8_t value) {
  m.bus->beginTransmission(m.addr);
  m.bus->write(reg);
  m.bus->write(value);
  return m.bus->endTransmission() == 0;
}

bool wake(Imu &m) {
  return writeRegister(m, 0x6B, 0x00)  // PWR_MGMT_1: clear sleep bit
      && writeRegister(m, 0x1C, 0x00)  // ACCEL_CONFIG: +/-2g
      && writeRegister(m, 0x1B, 0x10); // GYRO_CONFIG: +/-1000 degrees/second
}

int whoAmI(Imu &m) {
  m.bus->beginTransmission(m.addr);
  m.bus->write(0x75);                 // WHO_AM_I register
  if (m.bus->endTransmission(false) != 0) return -1;
  if (m.bus->requestFrom(m.addr, (uint8_t)1) != 1) return -1;
  return m.bus->read();
}

bool readRaw(Imu &m, int16_t *v) {
  m.bus->beginTransmission(m.addr);
  m.bus->write(0x3B);                 // ACCEL_XOUT_H
  if (m.bus->endTransmission(false) != 0) return false;
  if (m.bus->requestFrom(m.addr, (uint8_t)14) != 14) return false;
  for (int i = 0; i < 7; i++) {       // ax ay az temp gx gy gz
    uint8_t hi = m.bus->read();
    uint8_t lo = m.bus->read();
    v[i] = (int16_t)((hi << 8) | lo);
  }
  return true;
}

// Returns true if the sensor passes. Assumes the board is sitting still.
bool selfTest(Imu &m) {
  Serial.print("--- ");
  Serial.print(m.name);
  Serial.print(" at 0x");
  Serial.print(m.addr, HEX);
  Serial.println(" ---");

  if (!probe(m)) {
    Serial.println("FAIL: no response on I2C. Check SDA/SCL/VCC/GND wiring for this sensor.");
    return false;
  }
  Serial.println("  I2C response: OK");

  if (!wake(m)) {
    Serial.println("FAIL: could not wake the sensor.");
    return false;
  }
  delay(100);

  int id = whoAmI(m);
  Serial.print("  WHO_AM_I: 0x");
  Serial.print(id, HEX);
  Serial.println(id == 0x68 ? " (genuine MPU6050)" : " (unusual ID, may be a clone, usually still works)");

  float sumMag = 0;
  float sumGyro[3] = {0, 0, 0};
  int good = 0;
  bool allZero = true;
  for (int i = 0; i < 20; i++) {
    int16_t v[7];
    if (readRaw(m, v)) {
      float ax = v[0] / ACCEL_SCALE, ay = v[1] / ACCEL_SCALE, az = v[2] / ACCEL_SCALE;
      sumMag += sqrt(ax * ax + ay * ay + az * az);
      good++;
      for (int k = 0; k < 3; k++) sumGyro[k] += v[4 + k];
      if (v[0] || v[1] || v[2] || v[4] || v[5] || v[6]) allZero = false;
    }
    delay(10);
  }

  if (good < 20) {
    Serial.print("FAIL: only ");
    Serial.print(good);
    Serial.println("/20 reads succeeded (loose wire?).");
    return false;
  }
  if (allZero) {
    Serial.println("FAIL: every value is 0. Sensor is not producing data.");
    return false;
  }

  float mag = sumMag / good;
  Serial.print("  Accel magnitude at rest: ");
  Serial.print(mag, 3);
  Serial.println(" g (should be about 1.0)");
  if (mag < 0.8 || mag > 1.2) {
    Serial.println("WARN: magnitude is off. Keep the board still, or the sensor may be faulty.");
  }

  for (int k = 0; k < 3; k++) m.gyroBias[k] = sumGyro[k] / good;
  Serial.println("PASS (gyro bias calibrated; keep sensors still during startup)");
  return true;
}

// Fills out[0..2] with the change in acceleration (milli-g) since the last sample.
void computeDiff(int i, int16_t *raw, int16_t *out) {
  float a[3] = {raw[0] / ACCEL_SCALE, raw[1] / ACCEL_SCALE, raw[2] / ACCEL_SCALE};
  for (int k = 0; k < 3; k++) {
    float d = hasPrev[i] ? (a[k] - prevAccel[i][k]) : 0.0f;
    prevAccel[i][k] = a[k];
    out[k] = (int16_t)constrain((int)lroundf(d * 1000.0f), -32768, 32767);
  }
  hasPrev[i] = true;
}

// ---------- Arduino ----------

void setup() {
  pinMode(LED_PIN, OUTPUT);
  digitalWrite(LED_PIN, HIGH);

  Serial.begin(115200);
  delay(1000);

  Wire.begin(SDA1_PIN, SCL1_PIN);
  Wire.setClock(400000);
  Wire.setTimeOut(50);
  Wire1.begin(SDA2_PIN, SCL2_PIN);
  Wire1.setClock(400000);
  Wire1.setTimeOut(50);

  Serial.println();
  Serial.println("=== Dual MPU6050 self-test (keep both boards still) ===");
  for (int i = 0; i < 2; i++) {
    imus[i].ok = selfTest(imus[i]);
    Serial.println();
  }
  Serial.print("Result: ");
  Serial.println((imus[0].ok && imus[1].ok) ? "both sensors working" : "problem detected, see above");

  setupBle();
  Serial.println("Streaming starts once a client connects.");
  Serial.println();
}

void loop() {
  unsigned long now = millis();
  bool allOk = imus[0].ok && imus[1].ok;

  unsigned long blinkInterval = allOk ? 500 : 100;
  if (now - lastBlink >= blinkInterval) {
    lastBlink = now;
    ledState = !ledState;
    digitalWrite(LED_PIN, ledState);
  }

  // Once a second, try to recover any sensor that dropped out
  if (!allOk && now - lastRetry >= 1000) {
    lastRetry = now;
    for (int i = 0; i < 2; i++) {
      if (!imus[i].ok && probe(imus[i]) && wake(imus[i])) {
        imus[i].ok = true;
        hasPrev[i] = false;
        Serial.print(imus[i].name);
        Serial.println(" recovered");
      }
    }
  }

  if (now - lastSample < SAMPLE_MS) return;
  lastSample = now;

  for (int i = 0; i < 2; i++) {
    Packet pkt;
    memset(&pkt, 0, sizeof(pkt));
    pkt.t_ms = now;
    pkt.flags = 0x80 | (i << 2);
    int16_t raw[7];
    if (imus[i].ok && readRaw(imus[i], raw)) {
      computeDiff(i, raw, pkt.d);
      for (int k = 0; k < 3; k++) {
        long corrected = lroundf(raw[4 + k] - imus[i].gyroBias[k]);
        pkt.gyro[k] = (int16_t)constrain(corrected, -32768L, 32767L);
      }
      pkt.flags |= 1;
    } else if (imus[i].ok) {
      imus[i].ok = false;
      hasPrev[i] = false;
      Serial.print(imus[i].name);
      Serial.println(" stopped responding");
    }
    // Send failed sensors too, so the client can reset that hand's detector.
    if (bleConnected) {
      txChar->setValue((uint8_t *)&pkt, sizeof(pkt));
      txChar->notify();
    }
  }
}
