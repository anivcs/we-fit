
#include <Arduino.h>
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <utility/imumaths.h>
#include <BLEDevice.h>
#include <BLEServer.h>
#include <BLEUtils.h>
#include <BLE2902.h>
#include <math.h>

#include "config.h"
#include "protocol.h"

// Support either BNO055 I2C address
Adafruit_BNO055 bno28(55, 0x28, &Wire);
Adafruit_BNO055 bno29(56, 0x29, &Wire);
Adafruit_BNO055* bno = nullptr;

BLEServer* server = nullptr;
BLECharacteristic* sampleChar = nullptr;
BLECharacteristic* statusChar = nullptr;

volatile bool connected = false;

// Fusion mode: the board boots in IMU mode; the host may ask for another
uint8_t currentMode = MODE_IMU;
volatile uint8_t requestedMode = MODE_IMU;

char commandLine[16];
uint8_t commandLength = 0;

uint16_t seq = 0;
unsigned long lastSample = 0;

class ServerCallbacks : public BLEServerCallbacks {
  void onConnect(BLEServer*) override {
    connected = true;
    Serial.println("BLE: host connected");
  }

  void onDisconnect(BLEServer*) override {
    connected = false;
    Serial.println("BLE: host disconnected, advertising again");
    BLEDevice::startAdvertising();
  }
};

void requestMode(int mode) {
  if (mode == MODE_IMU || mode == MODE_NDOF) {
    requestedMode = (uint8_t)mode;
  }
}

class CommandCallbacks : public BLECharacteristicCallbacks {
  void onWrite(BLECharacteristic* characteristic) override {
    std::string value = characteristic->getValue();
    if (value.length() == 1) {
      requestMode((uint8_t)value[0]);
    }
  }
};

void haltWithError(const char* message) {
  Serial.println(message);

  while (true) {
    delay(10);
  }
}

void setupImu() {
  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(I2C_CLOCK_HZ);

  // Scan for sensor at address 0x28
  Wire.beginTransmission(0x28);
  if (Wire.endTransmission() == 0) {
    Serial.println("Device found at 0x28");
    bno = &bno28;
  }

  // Try alternative address 0x29
  if (bno == nullptr) {
    Wire.beginTransmission(0x29);

    if (Wire.endTransmission() == 0) {
      Serial.println("Device found at 0x29");
      bno = &bno29;
    }
  }

  if (bno == nullptr) {
    haltWithError("ERROR: No BNO055 I2C device found! Check VIN, GND, SDA and SCL.");
  }

  if (!bno->begin(OPERATION_MODE_IMUPLUS)) {
    haltWithError("ERROR: BNO055 initialization failed!");
  }

  Serial.println("BNO055 CONNECTED!");
}

void setupBle() {
  BLEDevice::init(BLE_DEVICE_NAME);

  server = BLEDevice::createServer();
  server->setCallbacks(new ServerCallbacks());

  BLEService* service = server->createService(SERVICE_UUID);

  sampleChar = service->createCharacteristic(
    SAMPLE_CHAR_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  sampleChar->addDescriptor(new BLE2902());

  BLECharacteristic* infoChar = service->createCharacteristic(
    INFO_CHAR_UUID, BLECharacteristic::PROPERTY_READ);

  statusChar = service->createCharacteristic(
    STATUS_CHAR_UUID, BLECharacteristic::PROPERTY_NOTIFY);
  statusChar->addDescriptor(new BLE2902());

  BLECharacteristic* commandChar = service->createCharacteristic(
    COMMAND_CHAR_UUID, BLECharacteristic::PROPERTY_WRITE);
  commandChar->setCallbacks(new CommandCallbacks());

  InfoPacket info;
  info.protocol_version = PROTOCOL_VERSION;
  info.fw_version = FW_VERSION;
  info.sample_rate_hz = SAMPLE_RATE_HZ;
  infoChar->setValue((uint8_t*)&info, sizeof(info));

  service->start();

  BLEAdvertising* advertising = BLEDevice::getAdvertising();
  advertising->addServiceUUID(SERVICE_UUID);
  advertising->setScanResponse(true);
  BLEDevice::startAdvertising();

  Serial.println("BLE advertising as " BLE_DEVICE_NAME);
}

void sendSample() {
  // Stamp before the I2C reads so t_ms marks when the sensor was read
  uint16_t sampledAt = (uint16_t)millis();

  // Acceleration without gravity, in the sensor frame
  imu::Vector<3> accel =
    bno->getVector(Adafruit_BNO055::VECTOR_LINEARACCEL);
  imu::Quaternion quat = bno->getQuat();

  uint8_t calSys, calGyro, calAccel, calMag;
  bno->getCalibration(&calSys, &calGyro, &calAccel, &calMag);

  SamplePacket packet;
  packet.seq = seq++;
  packet.t_ms = sampledAt;
  packet.accel[0] = (int16_t)lround(accel.x() * ACCEL_SCALE);
  packet.accel[1] = (int16_t)lround(accel.y() * ACCEL_SCALE);
  packet.accel[2] = (int16_t)lround(accel.z() * ACCEL_SCALE);
  packet.quat[0] = (int16_t)lround(quat.w() * QUAT_SCALE);
  packet.quat[1] = (int16_t)lround(quat.x() * QUAT_SCALE);
  packet.quat[2] = (int16_t)lround(quat.y() * QUAT_SCALE);
  packet.quat[3] = (int16_t)lround(quat.z() * QUAT_SCALE);
  packet.calib = (calSys << 6) | (calGyro << 4) | (calAccel << 2) | calMag;
  packet.flags = (currentMode == MODE_NDOF) ? FLAG_NDOF : 0;

  if (connected) {
    sampleChar->setValue((uint8_t*)&packet, sizeof(packet));
    sampleChar->notify();
  }

#if SERIAL_STREAM
  // Same raw values as the BLE packet, one text line per sample
  Serial.printf("S,%u,%u,%d,%d,%d,%d,%d,%d,%d,%u\n",
                packet.seq, packet.t_ms,
                packet.accel[0], packet.accel[1], packet.accel[2],
                packet.quat[0], packet.quat[1], packet.quat[2], packet.quat[3],
                packet.calib);
#endif
}

void sendStatus() {
  StatusPacket packet;
  packet.uptime_ms = millis();
  packet.mode = currentMode;
  packet.mag[0] = packet.mag[1] = packet.mag[2] = 0;

  // The magnetometer is powered only in NDOF mode
  if (currentMode == MODE_NDOF) {
    imu::Vector<3> mag = bno->getVector(Adafruit_BNO055::VECTOR_MAGNETOMETER);
    packet.mag[0] = (int16_t)lround(mag.x() * MAG_SCALE);
    packet.mag[1] = (int16_t)lround(mag.y() * MAG_SCALE);
    packet.mag[2] = (int16_t)lround(mag.z() * MAG_SCALE);
  }

  if (connected) {
    statusChar->setValue((uint8_t*)&packet, sizeof(packet));
    statusChar->notify();
  }

#if SERIAL_STREAM
  Serial.printf("T,%lu,%d,%d,%d,%u\n",
                (unsigned long)packet.uptime_ms,
                packet.mag[0], packet.mag[1], packet.mag[2], packet.mode);
#endif
}

// Host commands on USB serial: "M,<mode>"
void readCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\n' || c == '\r') {
      commandLine[commandLength] = '\0';
      if (commandLength > 2 && commandLine[0] == 'M' && commandLine[1] == ',') {
        requestMode(atoi(commandLine + 2));
      }
      commandLength = 0;
    } else if (commandLength < sizeof(commandLine) - 1) {
      commandLine[commandLength++] = c;
    }
  }
}

void applyMode() {
  uint8_t mode = requestedMode;
  if (mode == currentMode) {
    return;
  }

  // The BNO055 changes fusion mode through config mode. setMode() waits about 30 ms
  // each time; this is the only blocking wait outside setup().
  bno->setMode(OPERATION_MODE_CONFIG);
  bno->setMode((adafruit_bno055_opmode_t)mode);
  currentMode = mode;
  lastSample = millis();

  Serial.println(mode == MODE_NDOF ? "MODE: NDOF" : "MODE: IMU");
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("======================");
  Serial.println("WeFit controller started");
  Serial.println("======================");

  setupImu();
  setupBle();

  Serial.println("READY");
}

void loop() {
  readCommands();
  applyMode();

  unsigned long currentTime = millis();

  if (currentTime - lastSample >= SAMPLE_PERIOD_MS) {
    // Step by the period so a late loop does not stretch every later sample
    lastSample += SAMPLE_PERIOD_MS;
    if (currentTime - lastSample >= SAMPLE_PERIOD_MS) {
      lastSample = currentTime;  // fell a whole period behind; do not send a burst
    }

    // Gesture detection lives in the Python bridge; firmware only streams
    sendSample();

    if (seq % STATUS_EVERY_SAMPLES == 0) {
      sendStatus();
    }
  }
}
