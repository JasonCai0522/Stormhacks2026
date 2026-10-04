"""
BLE client for the ESP32 dual-MPU6050 sketch (dual_mpu6050_ble.ino).

Connects to the device named "ESP32-IMU", subscribes to its notifications,
decodes legacy dual-accel packets or pairs of v2 accel+gyro packets, and calls
handle_sample() for every complete sample. All packets are 17 bytes.
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
GYRO_SCALE = 32.8  # Firmware GYRO_CONFIG=0x10 (+/-1000 degrees/second)
_pending = {}  # v2 timestamp -> the two hand packets; never mix timestamps

HIT_THRESHOLD_G = 0.5  # example threshold: change in acceleration per sample


def handle_sample(t_ms, imu_ok, deltas, gyros=None):
    """Called once per sample. Put your game-input logic here.

    t_ms    : ESP32 millis() timestamp
    imu_ok  : (bool, bool) whether IMU1 / IMU2 are responding
    deltas  : [(dax, day, daz), (dax, day, daz)] in g, change since last sample
    gyros   : [(gx, gy, gz), (gx, gy, gz)] in degrees/second, or None (legacy)
    """
    mags = [math.sqrt(x * x + y * y + z * z) for (x, y, z) in deltas]

    line = f"t={t_ms:>9}  "
    for n in range(2):
        if imu_ok[n]:
            x, y, z = deltas[n]
            line += f"IMU{n + 1}: dax={x:+.3f} day={y:+.3f} daz={z:+.3f} dmag={mags[n]:.3f}   "
        else:
            line += f"IMU{n + 1}: --no data--   "
    #print(line)

    for n in range(2):
        if imu_ok[n] and mags[n] > HIT_THRESHOLD_G:
            #print(f"  >>> HIT on IMU{n + 1} (dmag {mags[n]:.2f} g)")
            pass


def on_notify(_sender, data: bytearray):
    if len(data) != PACKET.size:
        return  # ignore malformed packets
    t_ms, flags, *raw = PACKET.unpack(data)
    if flags & 0x80:
        if flags & ~0x85:
            return  # Unknown v2 flags, not a supported hand packet.
        hand = (flags >> 2) & 1
        sample = (bool(flags & 1), tuple(v / 1000.0 for v in raw[:3]),
                  tuple(v / GYRO_SCALE for v in raw[3:]))
        hands = _pending.setdefault(t_ms, {})
        hands[hand] = sample
        if len(hands) == 2:
            del _pending[t_ms]
            handle_sample(t_ms, tuple(hands[i][0] for i in range(2)),
                          [hands[i][1] for i in range(2)],
                          [hands[i][2] for i in range(2)])
        # Dropped halves must not grow the buffer indefinitely.
        while len(_pending) > 8:
            del _pending[next(iter(_pending))]
        return
    if flags & ~0x03:
        return
    deltas = [tuple(v / 1000.0 for v in raw[i * 3:i * 3 + 3]) for i in range(2)]
    imu_ok = (bool(flags & 1), bool(flags & 2))
    handle_sample(t_ms, imu_ok, deltas)


async def run(on_disconnect=None):
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
                _pending.clear()
                await client.start_notify(TX_CHAR_UUID, on_notify)
                await disconnected.wait()
                print("Disconnected.")
        except Exception as e:
            print(f"Connection error: {e}")
        finally:
            _pending.clear()
            if on_disconnect is not None:
                on_disconnect()
        await asyncio.sleep(1)


if __name__ == "__main__":
    try:
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\nStopped.")
