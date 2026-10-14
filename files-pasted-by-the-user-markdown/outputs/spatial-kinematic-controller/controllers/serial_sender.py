"""Eight-byte, little-endian XOR-framed serial protocol (not CRC)."""
import functools
import operator
import struct
from .base_controller import BaseController, ControlState


def encode_packet(state):
    # Symmetric range -32767..32767; bit 0 means handbrake/A.
    payload = struct.pack("<hBB", round(state.roll * 32767),
                          round(state.throttle * 255), state.buttons)
    checksum = functools.reduce(operator.xor, payload, 0)
    return b"\xaa\xbb" + payload + bytes((checksum, 0xCC))


def decode_packet(packet):
    if len(packet) != 8 or packet[:2] != b"\xaa\xbb" or packet[-1] != 0xCC:
        raise ValueError("invalid serial framing")
    if packet[6] != functools.reduce(operator.xor, packet[2:6], 0):
        raise ValueError("serial XOR mismatch")
    roll, throttle, buttons = struct.unpack("<hBB", packet[2:6])
    if roll == -32768:
        raise ValueError("reserved roll value")
    return ControlState(roll / 32767, throttle / 255, buttons)


class SerialSender(BaseController):
    def __init__(self, port="COM3", baud=115200, watchdog_s=0.15, heartbeat_s=0.05):
        super().__init__(watchdog_s, heartbeat_s)
        import serial
        # write_timeout=0 prevents the inference or output worker waiting on a full OS buffer.
        self.device = serial.serial_for_url(port, baudrate=baud, timeout=0, write_timeout=0)

    def send(self, state):
        packet = encode_packet(state)
        written = self.device.write(packet)
        if written != len(packet):
            raise RuntimeError(f"partial serial packet: {written}/{len(packet)} bytes")

    def release(self):
        self.device.close()
