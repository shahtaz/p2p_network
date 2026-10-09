import json
import struct

MAX_MESSAGE_SIZE = 1024 * 1024  # 1 MB limit for JSON control messages


class ProtocolError(Exception):
    """Raised when a received message is malformed."""


def send_message(sock, message):
    """Encode a dictionary as JSON and send it with a 4-byte length header."""
    data = json.dumps(message).encode("utf-8")
    if len(data) > MAX_MESSAGE_SIZE:
        raise ValueError("Message too large")
    sock.sendall(struct.pack("!I", len(data)) + data)


def receive_exact(sock, size):
    """Receive exactly the requested number of bytes."""
    data = bytearray()
    while len(data) < size:
        chunk = sock.recv(size - len(data))
        if not chunk:
            raise ConnectionError("Peer disconnected")
        data.extend(chunk)
    return bytes(data)


def receive_message(sock):
    """Receive a framed JSON message and decode it into a dictionary."""
    header = receive_exact(sock, 4)
    message_size = struct.unpack("!I", header)[0]

    if message_size > MAX_MESSAGE_SIZE:
        raise ProtocolError(f"Message size {message_size} exceeds limit")

    data = receive_exact(sock, message_size)
    try:
        message = json.loads(data.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        raise ProtocolError(f"Invalid message: {e}")

    if not isinstance(message, dict) or "type" not in message:
        raise ProtocolError("Message missing 'type' field")
    return message