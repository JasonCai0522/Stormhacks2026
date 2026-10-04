"""ESP32 Bluetooth receiver, shared by the controller and standalone listener."""

import time

PORT = "COM4"
BAUD = 115200


class BluetoothReceiver:
    """Expose received newline-delimited packets as strings.

    The current Bluetooth connection uses a serial COM port. Keep transport
    changes here as the microcontroller implementation develops.
    """

    def __init__(self, port=PORT, baud=BAUD, timeout=0.05):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self.connection = None
        self._buffer = bytearray()
        self._discarding = False

    def __enter__(self):
        import serial

        print(f"Connecting to ESP32 on {self.port}...")
        self.connection = serial.Serial(self.port, self.baud, timeout=self.timeout)
        try:
            time.sleep(1)
        except BaseException:
            self.close()
            raise
        print("Connected! Listening for wireless packets...")
        return self

    def read_message(self):
        """Return one complete packet, or None on timeout/incomplete input."""
        data = self.connection.readline(1025)
        if not data:
            return None
        complete = data.endswith(b"\n")
        if not self._discarding:
            self._buffer.extend(data)
            if len(self._buffer) > 1024:
                self._buffer.clear()
                self._discarding = True
        if not complete:
            return None
        message = None
        if not self._discarding:
            message = self._buffer.decode("utf-8", errors="replace").strip() or None
        self._buffer.clear()
        self._discarding = False
        return message

    def close(self):
        if self.connection is not None:
            self.connection.close()
            self.connection = None

    def __exit__(self, exc_type, exc_value, traceback):
        self.close()


def main():
    import serial

    try:
        with BluetoothReceiver() as receiver:
            while True:
                message = receiver.read_message()
                if message:
                    print(f"[ESP32 -> PC]: {message}")
    except serial.SerialException as exc:
        print(f"Serial Error: {exc}")
    except KeyboardInterrupt:
        print("\nStopping...")
    finally:
        print("Port closed.")


if __name__ == "__main__":
    main()
