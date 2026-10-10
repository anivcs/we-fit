#pragma once

// BLE wire format. Must match .claude/docs/protocol.md and
// bridge/src/wefit_bridge/protocol.py. Bump PROTOCOL_VERSION on any layout change.

#include <stdint.h>

#define PROTOCOL_VERSION 1

#define BLE_DEVICE_NAME "WeFit"
#define SERVICE_UUID     "7e3f0001-6b1c-4f6a-9d2e-5a1c0f3b9a10"
#define SAMPLE_CHAR_UUID "7e3f0002-6b1c-4f6a-9d2e-5a1c0f3b9a10"
#define INFO_CHAR_UUID   "7e3f0003-6b1c-4f6a-9d2e-5a1c0f3b9a10"

// Scale factors: raw int16 = value * scale (these are the BNO055's native units)
#define ACCEL_SCALE 100.0    // 1 LSB = 0.01 m/s^2
#define QUAT_SCALE  16384.0  // 1 LSB = 1/16384

// Notified on SAMPLE_CHAR_UUID. 20 bytes so it fits the default BLE MTU.
struct __attribute__((packed)) SamplePacket {
  uint16_t seq;       // increments per sample, wraps
  uint16_t t_ms;      // millis() truncated, wraps every ~65 s
  int16_t accel[3];   // linear acceleration x, y, z (gravity removed)
  int16_t quat[4];    // orientation w, x, y, z
  uint8_t calib;      // sys<<6 | gyro<<4 | accel<<2 | mag
  uint8_t flags;      // reserved, 0
};
static_assert(sizeof(SamplePacket) == 20, "SamplePacket must be 20 bytes");

// Read from INFO_CHAR_UUID.
struct __attribute__((packed)) InfoPacket {
  uint8_t protocol_version;
  uint16_t fw_version;
  uint16_t sample_rate_hz;
};
static_assert(sizeof(InfoPacket) == 5, "InfoPacket must be 5 bytes");
