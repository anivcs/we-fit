#pragma once

// ESP32 connections
#define SDA_PIN 21
#define SCL_PIN 22
#define I2C_CLOCK_HZ 100000

// Sampling
#define SAMPLE_RATE_HZ 50
#define SAMPLE_PERIOD_MS (1000 / SAMPLE_RATE_HZ)

// Print every sample on the USB serial port as well as sending it over BLE
#define SERIAL_STREAM 1

// Reported in the info characteristic
#define FW_VERSION 2
