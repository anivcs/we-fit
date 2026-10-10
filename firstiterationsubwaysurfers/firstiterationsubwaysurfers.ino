
#include <Wire.h>
#include <Adafruit_Sensor.h>
#include <Adafruit_BNO055.h>
#include <utility/imumaths.h>
#include <math.h>

// ESP32 connections
#define SDA_PIN 21
#define SCL_PIN 22

// Support either BNO055 I2C address
Adafruit_BNO055 bno28(55, 0x28, &Wire);
Adafruit_BNO055 bno29(56, 0x29, &Wire);
Adafruit_BNO055* bno = nullptr;

// Movement sensitivity (m/s^2)
const float SIDE_THRESHOLD = 2.0;
const float UP_THRESHOLD = 2.5;

// Minimum 1 second between movements
const unsigned long COOLDOWN = 1000;

unsigned long lastMovement = 0;
unsigned long lastPrint = 0;

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
  Serial.println("Keep the sensor still for 2 seconds.");

  delay(2000);

  Serial.println("READY TO DETECT MOVEMENT!");
}

void loop() {

  // Get acceleration without gravity
  imu::Vector<3> accel =
    bno->getVector(Adafruit_BNO055::VECTOR_LINEARACCEL);

  float x = accel.x();
  float y = accel.y();
  float z = accel.z();

  unsigned long currentTime = millis();

  // Print live acceleration readings
  if (currentTime - lastPrint >= 200) {
    Serial.print("X: ");
    Serial.print(x, 2);

    Serial.print(" | Y: ");
    Serial.print(y, 2);

    Serial.print(" | Z: ");
    Serial.println(z, 2);

    lastPrint = currentTime;
  }

  // Detect movements with a 1-second cooldown
  if (currentTime - lastMovement >= COOLDOWN) {

    // UP = Positive Z acceleration
    if (z > UP_THRESHOLD &&
        z > fabs(x) &&
        z > fabs(y)) {

      Serial.println(">>> UP <<<");
      lastMovement = currentTime;
    }

    // RIGHT = Positive X acceleration
    else if (x > SIDE_THRESHOLD &&
             x > fabs(y) &&
             x > fabs(z)) {

      Serial.println(">>> RIGHT <<<");
      lastMovement = currentTime;
    }

    // LEFT = Negative X acceleration
    else if (x < -SIDE_THRESHOLD &&
             -x > fabs(y) &&
             -x > fabs(z)) {

      Serial.println(">>> LEFT <<<");
      lastMovement = currentTime;
    }
  }

  delay(20);
}
