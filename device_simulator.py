import sys
import json
import random
import time
import queue
from PyQt5 import QtWidgets, QtCore
import threading
import websocket  # pip install websocket-client

class WebSocketThread(QtCore.QThread):
    log_signal = QtCore.pyqtSignal(str)
    status_signal = QtCore.pyqtSignal(str)
    
    def __init__(self, url, parent=None):
        super().__init__(parent)
        self.url = url
        self.ws = None
        self.running = False
        self.outbox = queue.Queue()
        self.connected = False

    def run(self):
        self.running = True
        try:
            self.ws = websocket.WebSocketApp(
                self.url,
                on_open=self.on_open,
                on_message=self.on_message,
                on_error=self.on_error,
                on_close=self.on_close
            )
            # Run the websocket in this thread
            self.ws.run_forever()
        except Exception as e:
            self.status_signal.emit(f"WebSocket error: {e}")

    def on_open(self, ws):
        self.connected = True
        self.status_signal.emit("Connected to server.")
        # Start a thread to handle outgoing messages
        threading.Thread(target=self.send_loop, daemon=True).start()

    def send_loop(self):
        while self.running and self.ws and self.connected:
            try:
                msg = self.outbox.get(timeout=0.2)
                self.ws.send(msg)
                self.log_signal.emit(f"Sent: {msg}")
            except queue.Empty:
                continue

    def send(self, msg):
        if self.connected:
            self.outbox.put(msg)
        else:
            self.status_signal.emit("Not connected. Message not sent.")

    def on_message(self, ws, message):
        self.log_signal.emit(f"Received: {message}")

    def on_error(self, ws, error):
        self.status_signal.emit(f"WebSocket Error: {error}")

    def on_close(self, ws, close_status_code, close_msg):
        self.connected = False
        self.status_signal.emit("WebSocket closed.")

    def stop(self):
        self.running = False
        if self.ws:
            try:
                self.ws.close()
            except Exception:
                pass


class SimulatorWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Access Device Simulator")
        self.resize(520, 450)

        # Settings
        self.server_ip = QtWidgets.QLineEdit("127.0.0.1")
        self.server_port = QtWidgets.QLineEdit("8765")
        self.device_serial = QtWidgets.QLineEdit("DEV123456")
        self.site_code = QtWidgets.QLineEdit("1")
        self.connect_btn = QtWidgets.QPushButton("Connect")
        self.connect_btn.clicked.connect(self.connect_ws)

        # Manual event
        self.manual_card = QtWidgets.QLineEdit()
        self.manual_card.setPlaceholderText("Card Number")
        self.manual_btn = QtWidgets.QPushButton("Send Manual Event")
        self.manual_btn.clicked.connect(self.send_manual_event)

        # Random event
        self.random_btn = QtWidgets.QPushButton("Start Random Events")
        self.random_btn.setCheckable(True)
        self.random_btn.clicked.connect(self.toggle_random_events)
        self.random_running = False

        # Log output
        self.log_text = QtWidgets.QTextEdit()
        self.log_text.setReadOnly(True)

        # Layout
        form = QtWidgets.QFormLayout()
        form.addRow("Server IP:", self.server_ip)
        form.addRow("Server Port:", self.server_port)
        form.addRow("Device Serial:", self.device_serial)
        form.addRow("Site Code:", self.site_code)
        form.addRow(self.connect_btn)
        form.addRow(QtWidgets.QLabel("---- Manual Event ----"))
        form.addRow("Card Number:", self.manual_card)
        form.addRow(self.manual_btn)
        form.addRow(QtWidgets.QLabel("---- Random Event ----"))
        form.addRow(self.random_btn)
        vbox = QtWidgets.QVBoxLayout(self)
        vbox.addLayout(form)
        vbox.addWidget(QtWidgets.QLabel("Status Log:"))
        vbox.addWidget(self.log_text)

        self.ws_thread = None
        self.random_event_timer = QtCore.QTimer()
        self.random_event_timer.timeout.connect(self.send_random_event)

    def connect_ws(self):
        if self.ws_thread:
            self.ws_thread.stop()
            self.ws_thread.wait()
            self.ws_thread = None
        ip = self.server_ip.text().strip()
        port = self.server_port.text().strip()
        ws_url = f"ws://{ip}:{port}"
        self.ws_thread = WebSocketThread(ws_url)
        self.ws_thread.log_signal.connect(self.append_log)
        self.ws_thread.status_signal.connect(self.append_log)
        self.ws_thread.start()
        self.append_log(f"Connecting to {ws_url}...")

    def append_log(self, msg):
        self.log_text.append(msg)

    def send_manual_event(self):
        card = self.manual_card.text().strip()
        if not card.isdigit():
            self.append_log("Card number must be digits only!")
            return
        msg = self.build_event_json(card)
        if self.ws_thread:
            self.ws_thread.send(msg)

    def toggle_random_events(self):
        self.random_running = not self.random_running
        if self.random_running:
            self.random_btn.setText("Stop Random Events")
            self.random_event_timer.start(2000)
        else:
            self.random_btn.setText("Start Random Events")
            self.random_event_timer.stop()

    def send_random_event(self):
        card = str(random.randint(1000, 9999))
        msg = self.build_event_json(card)
        if self.ws_thread:
            self.ws_thread.send(msg)

    def build_event_json(self, card_number):
        # This should match your protocol
        payload = {
            "cmd": "access_event",
            "device_serial": self.device_serial.text().strip(),
            "site_code": self.site_code.text().strip(),
            "card_number": card_number,
            "direction": random.choice(["in", "out"]),
            "unit_number": str(random.randint(1, 20)),
            "plate_number": random.choice(["12ج456", "45الف789", "89ب123", ""]),
            "permission": random.choice(["Open", "Limited", "Restricted"]),
            "timestamp": int(time.time())
        }
        return json.dumps(payload)

    def closeEvent(self, event):
        if self.ws_thread:
            self.ws_thread.stop()
            self.ws_thread.wait()
        self.random_event_timer.stop()
        super().closeEvent(event)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    sim = SimulatorWindow()
    sim.show()
    sys.exit(app.exec_())