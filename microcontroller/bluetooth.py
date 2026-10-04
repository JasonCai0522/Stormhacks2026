import serial
import time

PORT = "COM4"
BAUD = 115200

print(f"Connecting to ESP32 on {PORT}...")

try:
    # timeout=2 means ser.readline() blocks until a newline '\n' arrives,
    # or yields after 2 seconds if the line isn't finished yet.
    ser = serial.Serial(PORT, BAUD, timeout=2)
    time.sleep(1)
    print("Connected! Listening for wireless packets...\n")

    while True:
        line = ser.readline().decode("utf-8", errors="replace").strip()
        if line:
            print(f"[ESP32 -> PC]: {line}")

except serial.SerialException as e:
    print(f"Serial Error: {e}")
except KeyboardInterrupt:
    print("\nStopping...")
finally:
    if "ser" in locals() and ser.is_open:
        ser.close()
        print("Port closed.")