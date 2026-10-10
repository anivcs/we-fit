
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <utility/imumaths.h>
#include <math.h>

// ESP32 connections
#define SDA_PIN 21
#define SCL_PIN 22

// Support both BNO055 I2C addresses
Adafruit_BNO055 bno28(55, 0x28, &Wire);
Adafruit_BNO055 bno29(56, 0x29, &Wire);
Adafruit_BNO055* bno = nullptr;

// Movement sensitivity (m/s^2)
const float SIDE_THRESHOLD = 4.0;
const float UP_THRESHOLD = 7.0;
const float DOWN_THRESHOLD = 4;

// Return-to-rest sensitivity
const float RESET_THRESHOLD = 1.0;

// Minimum time between commands
const unsigned long COOLDOWN = 500;

unsigned long lastMovement = 0;
unsigned long lastPrint = 0;

bool readyForMovement = true;
unsigned long restStart = 0;

void setup() {
  Serial.begin(115200);
  delay(2000);

  Serial.println();
  Serial.println("======================");
  Serial.println("ESP32 STARTED!");
  Serial.println("Checking BNO055...");
  Serial.println("======================");

  Wire.begin(SDA_PIN, SCL_PIN);
  Wire.setClock(100000);

  // Search address 0x28
  Wire.beginTransmission(0x28);

  if (Wire.endTransmission() == 0) {
    Serial.println("Device found at 0x28");
    bno = &bno28;
  }

  // Search address 0x29
  if (bno == nullptr) {
    Wire.beginTransmission(0x29);

    if (Wire.endTransmission() == 0) {
      Serial.println("Device found at 0x29");
      bno = &bno29;
    }
  }

  if (bno == nullptr) {
    Serial.println("ERROR: No BNO055 I2C device found!");
    Serial.println("Check VIN, GND, SDA and SCL.");

    while (true) {
      delay(1000);
    }
  }

  Serial.println("Initializing sensor...");

  if (!bno->begin(OPERATION_MODE_IMUPLUS)) {
    Serial.println("ERROR: BNO055 initialization failed!");

    while (true) {
      delay(1000);
    }
  }

  Serial.println("BNO055 CONNECTED!");
  Serial.println("Keep sensor still for 2 seconds.");

  delay(2000);

  Serial.println("READY TO DETECT MOVEMENT!");
}

void loop() {

  // Read linear acceleration without gravity
  imu::Vector<3> accel =
    bno->getVector(Adafruit_BNO055::VECTOR_LINEARACCEL);

  float x = accel.x();
  float y = accel.y();
  float z = accel.z();

  unsigned long currentTime = millis();

  // Print acceleration readings
  if (currentTime - lastPrint >= 200) {
    Serial.print("X: ");
    Serial.print(x, 2);

    Serial.print(" | Y: ");
    Serial.print(y, 2);

    Serial.print(" | Z: ");
    Serial.println(z, 2);

    lastPrint = currentTime;
  }

  // Check whether sensor has returned to rest
  bool atRest =
    fabs(x) < RESET_THRESHOLD &&
    fabs(y) < RESET_THRESHOLD &&
    fabs(z) < RESET_THRESHOLD;

  if (atRest) {
    if (restStart == 0) {
      restStart = currentTime;
    }

    // Require 150 ms of stillness
    if (currentTime - restStart >= 150) {
      readyForMovement = true;
    }
  } else {
    restStart = 0;
  }

  // Detect one movement at a time
  if (readyForMovement &&
      currentTime - lastMovement >= COOLDOWN) {

    // UP = Positive Z acceleration
    if (z > UP_THRESHOLD &&
        z > fabs(x) &&
        z > fabs(y)) {

      Serial.println(">>> UP <<<");
      lastMovement = currentTime;
      readyForMovement = false;
    }

    // DOWN = Negative Z acceleration
    else if (z < -DOWN_THRESHOLD &&
             -z > fabs(x) &&
             -z > fabs(y)) {

      Serial.println(">>> DOWN <<<");
      lastMovement = currentTime;
      readyForMovement = false;
    }

    // RIGHT = Positive X acceleration
    else if (x > SIDE_THRESHOLD &&
             x > fabs(y) &&
             x > fabs(z)) {

      Serial.println(">>> RIGHT <<<");
      lastMovement = currentTime;
      readyForMovement = false;
    }

    // LEFT = Negative X acceleration
    else if (x < -SIDE_THRESHOLD &&
             -x > fabs(y) &&
             -x > fabs(z)) {

      Serial.println(">>> LEFT <<<");
      lastMovement = currentTime;
      readyForMovement = false;
    }
  }

  delay(20);
}
