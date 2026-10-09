import os
import socket
import threading
import uuid
from contextlib import suppress

from protocol import send_message, receive_message

CHUNK_SIZE = 64 * 1024
HANDSHAKE_TIMEOUT = 10


class P2PNode:
    def __init__(self, name, port, on_message=None, on_peer_update=None, on_event=None):
        self.name = name
        self.port = int(port)
        self.peer_id = uuid.uuid4().hex[:8]

        self.on_message = on_message
        self.on_peer_update = on_peer_update
        self.on_event = on_event

        self.server_socket = None
        self.running = False

        self.peers = {}
        self.peers_lock = threading.Lock()

        self.download_dir = "downloads"
        os.makedirs(self.download_dir, exist_ok=True)

    # ---------- helpers ----------

    @staticmethod
    def _close(sock):
        with suppress(OSError):
            sock.shutdown(socket.SHUT_RDWR)
        with suppress(OSError):
            sock.close()

    def _call(self, callback, *args):
        """Run a UI callback without letting its errors kill a network thread."""
        if callback:
            try:
                callback(*args)
            except Exception as error:
                print(f"Callback error: {error}")

    def _emit_event(self, message):
        print(message)
        self._call(self.on_event, message)

    def _notify_peers(self):
        self._call(self.on_peer_update, self.get_peers())

    def _hello(self, kind):
        return {
            "type": kind,
            "peer_id": self.peer_id,
            "peer_name": self.name,
            "port": self.port,
        }

    def _get_peer(self, peer_id):
        with self.peers_lock:
            return self.peers.get(peer_id)

    def get_peers(self):
        with self.peers_lock:
            return {
                pid: {k: p[k] for k in ("peer_id", "name", "host", "port")}
                for pid, p in self.peers.items()
            }

    # ---------- server role ----------

    def start(self):
        if self.running:
            return

        server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind(("0.0.0.0", self.port))
            server.listen()
            server.settimeout(1.0)
        except OSError as error:
            server.close()
            self._emit_event(f"Server startup failed: {error}")
            raise

        self.server_socket = server
        self.port = server.getsockname()[1]
        self.running = True

        threading.Thread(
            target=self._accept_connections, args=(server,), daemon=True
        ).start()
        self._emit_event(f"Peer '{self.name}' started on port {self.port}")

    def _accept_connections(self, server):
        # Loop ends when stop() replaces self.server_socket.
        while self.server_socket is server:
            try:
                connection, address = server.accept()
            except socket.timeout:
                continue
            except OSError:
                if self.server_socket is server:
                    self._emit_event("Server connection error")
                break

            threading.Thread(
                target=self._handle_connection,
                args=(connection, address, False),
                daemon=True,
            ).start()

    # ---------- client role ----------

    def connect_to_peer(self, host, port):
        connection = None
        try:
            port = int(port)
            if not 0 < port < 65536:
                raise ValueError("Port must be between 1 and 65535")

            connection = socket.create_connection((host, port), timeout=HANDSHAKE_TIMEOUT)
            send_message(connection, self._hello("hello"))
        except (OSError, ValueError) as error:
            if connection:
                self._close(connection)
            self._emit_event(f"Connection failed: {error}")
            return

        threading.Thread(
            target=self._handle_connection,
            args=(connection, (host, port), True),
            daemon=True,
        ).start()
        self._emit_event(f"Connecting to {host}:{port}")

    # ---------- per-connection thread ----------

    def _handle_connection(self, connection, address, expect_ack):
        peer_id = None

        try:
            # HELLO handshake (with a timeout so a silent peer can't hang us).
            connection.settimeout(HANDSHAKE_TIMEOUT)
            message = receive_message(connection)

            expected = "hello_ack" if expect_ack else "hello"
            if message.get("type") != expected:
                raise ValueError(f"Expected {expected}")

            peer_id = message.get("peer_id")
            peer_name = message.get("peer_name")
            if not peer_id or not peer_name or peer_id == self.peer_id:
                raise ValueError("Invalid peer information")

            if not expect_ack:
                send_message(connection, self._hello("hello_ack"))

            connection.settimeout(None)

            peer = {
                "peer_id": peer_id,
                "name": peer_name,
                "host": address[0],
                "port": int(message.get("port", 0)),
                "socket": connection,
                "lock": threading.Lock(),
            }

            with self.peers_lock:
                old_peer = self.peers.get(peer_id)
                self.peers[peer_id] = peer
            if old_peer:
                self._close(old_peer["socket"])

            self._emit_event(f"Connected to {peer_name} ({peer_id})")
            self._notify_peers()

            # Receive until the connection closes.
            while self.running:
                message = receive_message(connection)
                kind = message.get("type")

                if kind == "text":
                    self._call(self.on_message, peer_name, message)
                elif kind == "file":
                    self._receive_file(connection, peer_name, message)
                else:
                    self._emit_event(f"Unknown message type: {kind}")

        except Exception as error:  # disconnects, bad messages, timeouts
            if self.running:
                self._emit_event(f"Connection with {address[0]} ended: {error}")

        finally:
            with self.peers_lock:
                # Don't remove a newer connection for the same peer.
                removed = (
                    peer_id in self.peers
                    and self.peers[peer_id]["socket"] is connection
                )
                if removed:
                    del self.peers[peer_id]
            if removed:  # notify outside the lock (get_peers takes it again)
                self._notify_peers()
            self._close(connection)

    # ---------- sending ----------

    def _send(self, peer_id, action, send):
        """Look up the peer, run send(socket) under its lock, report errors."""
        peer = self._get_peer(peer_id)
        if not peer:
            self._emit_event("Please select a connected peer")
            return None

        try:
            with peer["lock"]:  # keeps metadata + file bytes together
                send(peer["socket"])
            return peer
        except (OSError, ValueError) as error:
            self._emit_event(f"{action} failed: {error}")
            return None

    def send_text(self, peer_id, message):
        peer = self._send(
            peer_id,
            "Message sending",
            lambda sock: send_message(
                sock,
                {
                    "type": "text",
                    "sender_id": self.peer_id,
                    "sender_name": self.name,
                    "message": message,
                },
            ),
        )
        if peer:
            self._emit_event(f"You -> {peer['name']}: {message}")
        return peer is not None

    def send_file(self, peer_id, file_path):
        if not os.path.isfile(file_path):
            self._emit_event("File does not exist")
            return False

        filename = os.path.basename(file_path)

        def transfer(sock):
            with open(file_path, "rb") as file:
                send_message(
                    sock,
                    {
                        "type": "file",
                        "sender_id": self.peer_id,
                        "sender_name": self.name,
                        "filename": filename,
                        "filesize": os.fstat(file.fileno()).st_size,
                    },
                )
                while chunk := file.read(CHUNK_SIZE):
                    sock.sendall(chunk)

        peer = self._send(peer_id, "File sending", transfer)
        if peer:
            self._emit_event(f"File sent to {peer['name']}: {filename}")
        return peer is not None

    # ---------- receiving files ----------

    def _receive_file(self, connection, sender_name, message):
        filename = os.path.basename(str(message.get("filename", "")))
        filesize = message.get("filesize")

        if (
            not filename
            or not isinstance(filesize, int)
            or isinstance(filesize, bool)
            or filesize < 0
        ):
            raise ValueError("Invalid file metadata")

        # Pick a name that doesn't overwrite an existing download.
        base, extension = os.path.splitext(filename)
        save_path = os.path.join(self.download_dir, filename)
        counter = 1
        while os.path.exists(save_path):
            save_path = os.path.join(self.download_dir, f"{base}_{counter}{extension}")
            counter += 1

        try:
            with open(save_path, "wb") as file:
                remaining = filesize
                while remaining > 0:
                    chunk = connection.recv(min(CHUNK_SIZE, remaining))
                    if not chunk:
                        raise ConnectionError("Peer disconnected during file transfer")
                    file.write(chunk)
                    remaining -= len(chunk)
        except Exception:
            os.remove(save_path)  # don't keep a half-written file
            raise

        self._emit_event(
            f"File received from {sender_name}: {os.path.basename(save_path)}"
        )

    # ---------- shutdown ----------

    def stop(self):
        self.running = False

        server, self.server_socket = self.server_socket, None
        if server:
            self._close(server)

        with self.peers_lock:
            peers = list(self.peers.values())
            self.peers.clear()

        for peer in peers:
            self._close(peer["socket"])

        self._notify_peers()
        self._emit_event("Peer stopped")