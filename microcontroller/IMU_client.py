"""
BLE client for the ESP32 dual-MPU6050 sketch (dual_mpu6050_ble.ino).

Connects to the device named "ESP32-IMU", subscribes to its notifications,
decodes each 17-byte packet, and calls handle_sample() for every sample.
Reconnects automatically if the connection drops.

Install:  pip install bleak
Run:      python imu_client.py
"""
import asyncio
import math
import struct

from bleak import BleakClient, BleakScanner

DEVICE_NAME = "ESP32-IMU"
TX_CHAR_UUID = "6e400003-b5a3-f393-e0a9-e50e24dcca9e"

# <  little-endian | I uint32 t_ms | B uint8 flags | 6h six int16 (milli-g)
PACKET = struct.Struct("<IB6h")

HIT_THRESHOLD_G = 0.5  # example threshold: change in acceleration per sample


def handle_sample(t_ms, imu_ok, deltas):
    """Called once per sample. Put your game-input logic here.

    t_ms    : ESP32 millis() timestamp
    imu_ok  : (bool, bool) whether IMU1 / IMU2 are responding
    deltas  : [(dax, day, daz), (dax, day, daz)] in g, change since last sample
    """
    mags = [math.sqrt(x * x + y * y + z * z) for (x, y, z) in deltas]

    line = f"t={t_ms:>9}  "
    for n in range(2):
        if imu_ok[n]:
            x, y, z = deltas[n]
            line += f"IMU{n + 1}: dax={x:+.3f} day={y:+.3f} daz={z:+.3f} dmag={mags[n]:.3f}   "
        else:
            line += f"IMU{n + 1}: --no data--   "
    print(line)

    for n in range(2):
        if imu_ok[n] and mags[n] > HIT_THRESHOLD_G:
            print(f"  >>> HIT on IMU{n + 1} (dmag {mags[n]:.2f} g)")


def on_notify(_sender, data: bytearray):
    if len(data) != PACKET.size:
        return  # ignore malformed packets
    t_ms, flags, *raw = PACKET.unpack(data)
    deltas = [tuple(v / 1000.0 for v in raw[i * 3:i * 3 + 3]) for i in range(2)]
    imu_ok = (bool(flags & 1), bool(flags & 2))
    handle_sample(t_ms, imu_ok, deltas)


async def run():
    while True:
        print(f"Scanning for '{DEVICE_NAME}'...")
        device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=10)
        if device is None:
            print("Not found. Is the ESP32 powered and not connected to another device?")
            continue

        disconnected = asyncio.Event()
        try:
            async with BleakClient(device, disconnected_callback=lambda _c: disconnected.set()) as client:
                print(f"Connected to {device.address}. Streaming (Ctrl+C to stop)...")
                await client.start_notify(TX_CHAR_UUID, on_notify)
                await disconnected.wait()
                print("Disconnected.")
        except Exception as e:
            print(f"Connection error: {e}")
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")