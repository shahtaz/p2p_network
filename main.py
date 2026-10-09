import queue
import threading
import tkinter as tk
from tkinter import ttk, filedialog, messagebox

from p2p_node import P2PNode


class P2PApplication:
    def __init__(self, root):
        self.root = root
        self.root.title("P2P Network - File Sharing")
        self.root.geometry("950x650")
        self.root.minsize(800, 550)

        self.node = None
        self.events = queue.Queue()
        self.peer_ids = []

        self._build_interface()
        self.root.after(100, self._process_events)
        self.root.protocol("WM_DELETE_WINDOW", self._close_application)

    def _build_interface(self):
        # Peer configuration
        config = ttk.LabelFrame(
            self.root, text="My Peer", padding=10
        )
        config.pack(fill="x", padx=10, pady=5)

        ttk.Label(config, text="Name:").grid(
            row=0, column=0, padx=5, pady=5
        )

        self.name_entry = ttk.Entry(config, width=18)
        self.name_entry.insert(0, "Peer")
        self.name_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(config, text="Port:").grid(
            row=0, column=2, padx=5, pady=5
        )

        self.port_entry = ttk.Entry(config, width=10)
        self.port_entry.insert(0, "5000")
        self.port_entry.grid(row=0, column=3, padx=5, pady=5)

        self.start_button = ttk.Button(
            config,
            text="Start Peer",
            command=self._start_peer,
        )
        self.start_button.grid(row=0, column=4, padx=5)

        self.stop_button = ttk.Button(
            config,
            text="Stop Peer",
            command=self._stop_peer,
            state="disabled",
        )
        self.stop_button.grid(row=0, column=5, padx=5)

        # Connect to another peer
        connect_frame = ttk.LabelFrame(
            self.root, text="Connect to Another Peer", padding=10
        )
        connect_frame.pack(fill="x", padx=10, pady=5)

        ttk.Label(connect_frame, text="IP Address:").grid(
            row=0, column=0, padx=5, pady=5
        )

        self.ip_entry = ttk.Entry(connect_frame, width=22)
        self.ip_entry.insert(0, "127.0.0.1")
        self.ip_entry.grid(row=0, column=1, padx=5, pady=5)

        ttk.Label(connect_frame, text="Port:").grid(
            row=0, column=2, padx=5, pady=5
        )

        self.remote_port_entry = ttk.Entry(
            connect_frame, width=10
        )
        self.remote_port_entry.insert(0, "5001")
        self.remote_port_entry.grid(
            row=0, column=3, padx=5, pady=5
        )

        self.connect_button = ttk.Button(
            connect_frame,
            text="Connect",
            command=self._connect_peer,
            state="disabled",
        )
        self.connect_button.grid(row=0, column=4, padx=5)

        # Main area: connected peers and event log
        content = ttk.Frame(self.root)
        content.pack(fill="both", expand=True, padx=10, pady=5)

        peers_frame = ttk.LabelFrame(
            content, text="Connected Peers", padding=8
        )
        peers_frame.pack(side="left", fill="y", padx=(0, 5))

        self.peer_list = tk.Listbox(
            peers_frame, width=25, height=20,
            exportselection=False
        )
        self.peer_list.pack(fill="both", expand=True)

        log_frame = ttk.LabelFrame(
            content, text="Messages / Events", padding=8
        )
        log_frame.pack(side="left", fill="both", expand=True)

        self.event_log = tk.Text(
            log_frame, wrap="word", state="disabled"
        )
        self.event_log.pack(side="left", fill="both", expand=True)

        scrollbar = ttk.Scrollbar(
            log_frame, command=self.event_log.yview
        )
        scrollbar.pack(side="right", fill="y")
        self.event_log.configure(yscrollcommand=scrollbar.set)

        # Text messaging
        message_frame = ttk.LabelFrame(
            self.root, text="Send Text Message", padding=10
        )
        message_frame.pack(fill="x", padx=10, pady=5)

        self.message_entry = ttk.Entry(message_frame)
        self.message_entry.pack(
            side="left", fill="x", expand=True, padx=5
        )
        self.message_entry.bind(
            "<Return>", lambda event: self._send_text()
        )

        self.send_button = ttk.Button(
            message_frame,
            text="Send",
            command=self._send_text,
            state="disabled",
        )
        self.send_button.pack(side="left", padx=5)

        # File transfer
        file_frame = ttk.Frame(self.root)
        file_frame.pack(fill="x", padx=10, pady=5)

        self.file_button = ttk.Button(
            file_frame,
            text="Choose File & Send",
            command=self._send_file,
            state="disabled",
        )
        self.file_button.pack(side="left", padx=5)

        self.status_label = ttk.Label(
            file_frame, text="Peer is not running"
        )
        self.status_label.pack(side="left", padx=10)

    def _run_in_background(self, function, *args):
        """Run a (possibly slow) network call without freezing the window.

        Results come back through the node's callbacks, which put events
        on the queue, so Tkinter is still only updated from the main thread.
        """
        threading.Thread(
            target=function, args=args, daemon=True
        ).start()

    def _start_peer(self):
        name = self.name_entry.get().strip()

        try:
            port = int(self.port_entry.get())

            if not name:
                raise ValueError("Peer name cannot be empty")

            if not 1 <= port <= 65535:
                raise ValueError("Port must be between 1 and 65535")

        except ValueError as error:
            messagebox.showerror("Invalid Input", str(error))
            return

        node = P2PNode(
            name=name,
            port=port,
            on_message=lambda sender, message: self.events.put(
                ("message", sender, message)
            ),
            on_peer_update=lambda peers: self.events.put(
                ("peers", peers)
            ),
            on_event=lambda text: self.events.put(
                ("event", text)
            ),
        )

        try:
            node.start()
        except OSError as error:
            messagebox.showerror(
                "Startup Failed", str(error)
            )
            return

        self.node = node

        self.name_entry.configure(state="disabled")
        self.port_entry.configure(state="disabled")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")
        self.connect_button.configure(state="normal")
        self.status_label.configure(
            text=f"Running on port {node.port}"
        )

    def _connect_peer(self):
        if not self.node:
            return

        host = self.ip_entry.get().strip()

        try:
            port = int(self.remote_port_entry.get())

            if not host:
                raise ValueError("IP address cannot be empty")

            if not 1 <= port <= 65535:
                raise ValueError("Port must be between 1 and 65535")

        except ValueError as error:
            messagebox.showerror("Invalid Input", str(error))
            return

        # Connecting can take up to 10 seconds, so don't block the GUI.
        self._run_in_background(self.node.connect_to_peer, host, port)

    def _selected_peer_id(self):
        selection = self.peer_list.curselection()

        if not selection:
            messagebox.showwarning(
                "Select Peer",
                "Please select a connected peer first.",
            )
            return None

        return self.peer_ids[selection[0]]

    def _send_text(self):
        if not self.node:
            return

        peer_id = self._selected_peer_id()

        if peer_id is None:
            return

        message = self.message_entry.get().strip()

        if not message:
            return

        self.message_entry.delete(0, tk.END)
        self._run_in_background(self.node.send_text, peer_id, message)

    def _send_file(self):
        if not self.node:
            return

        peer_id = self._selected_peer_id()

        if peer_id is None:
            return

        file_path = filedialog.askopenfilename(
            title="Select a file to send"
        )

        if file_path:
            # Large files take time, so transfer in the background.
            self._run_in_background(
                self.node.send_file, peer_id, file_path
            )

    def _stop_peer(self):
        if self.node:
            self.node.stop()
            self.node = None

        self.name_entry.configure(state="normal")
        self.port_entry.configure(state="normal")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")
        self.connect_button.configure(state="disabled")

        self.send_button.configure(state="disabled")
        self.file_button.configure(state="disabled")

        self.peer_list.delete(0, tk.END)
        self.peer_ids.clear()

        self.status_label.configure(text="Peer is not running")

    def _process_events(self):
        # All Tkinter updates happen on the main thread.
        while True:
            try:
                event = self.events.get_nowait()
            except queue.Empty:
                break

            event_type = event[0]

            if event_type == "event":
                self._append_log(event[1])

            elif event_type == "message":
                sender, message = event[1], event[2]
                self._append_log(
                    f"{sender} -> You: {message.get('message', '')}"
                )

            elif event_type == "peers":
                self._update_peer_list(event[1])

        self.root.after(100, self._process_events)

    def _update_peer_list(self, peers):
        selected_id = None
        selection = self.peer_list.curselection()

        if selection:
            selected_id = self.peer_ids[selection[0]]

        self.peer_list.delete(0, tk.END)
        self.peer_ids = []

        for peer_id, peer in peers.items():
            self.peer_ids.append(peer_id)
            self.peer_list.insert(
                tk.END,
                f"{peer['name']} [{peer_id}]"
            )

            if peer_id == selected_id:
                self.peer_list.selection_set(tk.END)

        connected = bool(peers) and self.node is not None
        state = "normal" if connected else "disabled"

        self.send_button.configure(state=state)
        self.file_button.configure(state=state)

    def _append_log(self, message):
        self.event_log.configure(state="normal")
        self.event_log.insert(tk.END, message + "\n")
        self.event_log.see(tk.END)
        self.event_log.configure(state="disabled")

    def _close_application(self):
        if self.node:
            self.node.stop()

        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    app = P2PApplication(root)
    root.mainloop()