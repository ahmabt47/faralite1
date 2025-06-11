import sys
import datetime
import json
import threading
import asyncio
import os
import sqlite3
import uuid

from PyQt5 import QtWidgets, QtGui, QtCore
import jdatetime
import cv2
import numpy as np
import websockets

from user_management import init_db, UserManagementDialog

FARSI_TEXTS = {
    "dashboard": "کنترل دسترسی فرالایت",
    "entrance": "ورودی",
    "exit": "خروجی",
    "last_inout": "آخرین ورود/خروج",
    "no_feed": "بدون تصویر زنده",
    "no_image": "بدون تصویر",
    "live_logs": "گزارش ورود/خروج",
    "settings": "تنظیمات",
    "user_mgmt": "مدیریت کاربران",
    "reports": "گزارش‌ها",
    "logout": "خروج",
    "device_status": "وضعیت دستگاه: {}",
    "online": "آنلاین",
    "offline": "آفلاین",
    "last_sync_date": "تاریخ همگام‌سازی:",
    "last_sync_time": "زمان همگام‌سازی:",
    "language": "زبان:",
    "english": "انگلیسی",
    "farsi": "فارسی",
    "table_headers": [
        "تاریخ", "زمان", "نام کاربر", "کد کاربر",
        "جهت", "واحد", "پلاک", "دسترسی", "وضعیت", "کد دستگاه"
    ]
}

EN_TEXTS = {
    "dashboard": "Faralite Access Control",
    "entrance": "Entrance",
    "exit": "Exit",
    "last_inout": "Last In/Out",
    "no_feed": "No feed",
    "no_image": "No image",
    "live_logs": "Live Access Logs",
    "settings": "Settings",
    "user_mgmt": "User Management",
    "reports": "Reports",
    "logout": "Logout",
    "device_status": "Device Status: {}",
    "online": "Online",
    "offline": "Offline",
    "last_sync_date": "Last Sync Date:",
    "last_sync_time": "Last Sync Time:",
    "language": "Language:",
    "english": "English",
    "farsi": "فارسی",
    "table_headers": [
        "Date", "Time", "User Name", "User ID",
        "Direction", "Unit", "Plate", "Permission", "Status", "Device Code"
    ]
}

PHOTO_SAVE_DIR = "photos"
os.makedirs(PHOTO_SAVE_DIR, exist_ok=True)

def get_datetimes(lang, dt=None):
    now = dt if dt else datetime.datetime.now()
    if lang == "fa":
        jnow = jdatetime.datetime.fromgregorian(datetime=now)
        date_str = jnow.strftime("%Y/%m/%d")
        time_str = now.strftime("%H:%M:%S")
    else:
        date_str = now.strftime("%Y-%m-%d")
        time_str = now.strftime("%H:%M:%S")
    return date_str, time_str

def save_photo(image_np, direction, timestamp, device_serial):
    filename = f"{device_serial}_{direction}_{timestamp}_{uuid.uuid4().hex[:8]}.jpg"
    filepath = os.path.join(PHOTO_SAVE_DIR, filename)
    cv2.imwrite(filepath, image_np)
    return filepath

def insert_log_to_db(date, time, user_name, user_id, direction, unit, plate, permission, device_serial, photo_path, raw_data):
    conn = sqlite3.connect("users.db")
    c = conn.cursor()
    c.execute(
        """CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date TEXT, time TEXT, user_name TEXT, user_id TEXT,
            direction TEXT, unit TEXT, plate TEXT, permission TEXT,
            device_serial TEXT, photo_path TEXT, raw_data TEXT
        )"""
    )
    c.execute(
        """INSERT INTO logs
            (date, time, user_name, user_id, direction, unit, plate, permission, device_serial, photo_path, raw_data)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (date, time, user_name, user_id, direction, unit, plate, permission, device_serial, photo_path, raw_data)
    )
    conn.commit()
    conn.close()

class CameraThread(QtCore.QThread):
    image_update = QtCore.pyqtSignal(QtGui.QImage, np.ndarray)
    error = QtCore.pyqtSignal(str)

    def __init__(self, camera_url, width=320, height=180, parent=None):
        super().__init__(parent)
        self.camera_url = camera_url
        self.width = width
        self.height = height
        self.running = False

    def run(self):
        self.running = True
        cap = cv2.VideoCapture(self.camera_url)
        if not cap.isOpened():
            self.error.emit("Failed to open camera stream")
            return
        while self.running:
            ret, frame = cap.read()
            if not ret:
                self.error.emit("No frame received")
                break
            rgb_image = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            h, w, ch = rgb_image.shape
            bytes_per_line = ch * w
            qt_image = QtGui.QImage(rgb_image.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
            scaled_image = qt_image.scaled(self.width, self.height, QtCore.Qt.KeepAspectRatio)
            self.image_update.emit(scaled_image, rgb_image.copy())
            self.msleep(30)
        cap.release()

    def stop(self):
        self.running = False
        self.wait()

class WebSocketServerThread(QtCore.QThread):
    log_received = QtCore.pyqtSignal(dict)
    device_status_changed = QtCore.pyqtSignal(set)

    def __init__(self, host="0.0.0.0", port=8765, parent=None):
        super().__init__(parent)
        self.host = host
        self.port = port
        self._stop_event = threading.Event()
        self.connected_devices = set()
        self._lock = threading.Lock()

    async def ws_handler(self, websocket, path=None):  # path=None for compatibility
        device_serial = None
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except Exception:
                    continue
                if not device_serial:
                    device_serial = data.get("device_serial", None)
                    if device_serial:
                        with self._lock:
                            self.connected_devices.add(device_serial)
                        self.device_status_changed.emit(self.connected_devices.copy())
                self.log_received.emit(data)
        finally:
            if device_serial:
                with self._lock:
                    self.connected_devices.discard(device_serial)
                self.device_status_changed.emit(self.connected_devices.copy())

    async def start_server(self):
        async with websockets.serve(self.ws_handler, self.host, self.port):
            while not self._stop_event.is_set():
                await asyncio.sleep(0.2)

    def run(self):
        asyncio.run(self.start_server())

    def stop(self):
        self._stop_event.set()
        self.wait()

class MainDashboard(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_language = "en"
        self.setWindowTitle(EN_TEXTS["dashboard"])
        self.resize(1400, 900)
        self.latest_entrance_frame = None
        self.latest_exit_frame = None

        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        self.vbox = QtWidgets.QVBoxLayout(central)

        self.top_bar = QtWidgets.QHBoxLayout()
        self.lbl_title = QtWidgets.QLabel(EN_TEXTS["dashboard"])
        self.lbl_title.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.top_bar.addWidget(self.lbl_title)
        self.status_frame = QtWidgets.QFrame()
        self.status_frame.setFixedSize(20, 20)
        self.status_frame.setStyleSheet("background: red; border-radius: 10px;")
        self.top_bar.addWidget(self.status_frame)
        self.lbl_status = QtWidgets.QLabel(EN_TEXTS["device_status"].format(EN_TEXTS["offline"]))
        self.top_bar.addWidget(self.lbl_status)
        self.top_bar.addStretch()
        self.btn_settings = QtWidgets.QPushButton(EN_TEXTS["settings"])
        self.btn_user_mgmt = QtWidgets.QPushButton(EN_TEXTS["user_mgmt"])
        self.btn_reports = QtWidgets.QPushButton(EN_TEXTS["reports"])
        self.btn_logout = QtWidgets.QPushButton(EN_TEXTS["logout"])
        self.btn_settings.clicked.connect(self.open_settings)
        self.btn_user_mgmt.clicked.connect(self.open_user_management)
        self.btn_reports.clicked.connect(self.open_reports)
        self.btn_logout.clicked.connect(self.logout)
        self.top_bar.addWidget(self.btn_settings)
        self.top_bar.addWidget(self.btn_user_mgmt)
        self.top_bar.addWidget(self.btn_reports)
        self.top_bar.addWidget(self.btn_logout)
        self.vbox.addLayout(self.top_bar)

        self.middle = QtWidgets.QHBoxLayout()
        self.cam_vbox = QtWidgets.QVBoxLayout()
        self.cam_vbox.setSpacing(10)
        self.cam_vbox.setContentsMargins(0, 0, 0, 0)

        self.lbl_entrance = QtWidgets.QLabel(EN_TEXTS["entrance"])
        self.lbl_entrance.setStyleSheet("font-size: 14px;")
        self.cam_vbox.addWidget(self.lbl_entrance)
        self.entranceCameraFeed = QtWidgets.QLabel(EN_TEXTS["no_feed"])
        self.entranceCameraFeed.setFixedSize(320, 180)
        self.entranceCameraFeed.setStyleSheet("background: #333; color: #fff; border: 1px solid #999;")
        self.entranceCameraFeed.setAlignment(QtCore.Qt.AlignCenter)
        self.cam_vbox.addWidget(self.entranceCameraFeed)

        self.lbl_exit = QtWidgets.QLabel(EN_TEXTS["exit"])
        self.lbl_exit.setStyleSheet("font-size: 14px;")
        self.cam_vbox.addWidget(self.lbl_exit)
        self.exitCameraFeed = QtWidgets.QLabel(EN_TEXTS["no_feed"])
        self.exitCameraFeed.setFixedSize(320, 180)
        self.exitCameraFeed.setStyleSheet("background: #333; color: #fff; border: 1px solid #999;")
        self.exitCameraFeed.setAlignment(QtCore.Qt.AlignCenter)
        self.cam_vbox.addWidget(self.exitCameraFeed)

        self.lbl_last_inout = QtWidgets.QLabel(EN_TEXTS["last_inout"])
        self.lbl_last_inout.setStyleSheet("font-size: 14px;")
        self.cam_vbox.addWidget(self.lbl_last_inout)
        self.lastInOutImage = QtWidgets.QLabel(EN_TEXTS["no_image"])
        self.lastInOutImage.setFixedSize(320, 180)
        self.lastInOutImage.setStyleSheet("background: #222; color: #fff; border: 2px solid #39f;")
        self.lastInOutImage.setAlignment(QtCore.Qt.AlignCenter)
        self.cam_vbox.addWidget(self.lastInOutImage)
        self.cam_vbox.addStretch()
        self.middle.addLayout(self.cam_vbox, 1)

        self.logs_vbox = QtWidgets.QVBoxLayout()
        self.lbl_live_logs = QtWidgets.QLabel(EN_TEXTS["live_logs"])
        self.lbl_live_logs.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.logs_vbox.addWidget(self.lbl_live_logs)
        log_headers = [
            EN_TEXTS["table_headers"][0],  # Date
            EN_TEXTS["table_headers"][1],  # Time
            EN_TEXTS["table_headers"][2],  # User Name
            EN_TEXTS["table_headers"][3],  # User ID
            EN_TEXTS["table_headers"][4],  # Direction
            EN_TEXTS["table_headers"][5],  # Unit
            EN_TEXTS["table_headers"][6],  # Plate
            EN_TEXTS["table_headers"][7],  # Permission
        ]
        self.logTable = QtWidgets.QTableWidget(0, len(log_headers))
        self.logTable.setHorizontalHeaderLabels(log_headers)
        self.logTable.horizontalHeader().setStretchLastSection(True)
        self.logTable.setEditTriggers(QtWidgets.QAbstractItemView.NoEditTriggers)
        self.logTable.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Expanding)
        farsi_font = QtGui.QFont("Tahoma")
        self.logTable.setFont(farsi_font)
        self.logs_vbox.addWidget(self.logTable)
        bold_font = QtGui.QFont()
        bold_font.setBold(True)
        for i in range(self.logTable.columnCount()):
            item = self.logTable.horizontalHeaderItem(i)
            if item:
                item.setFont(bold_font)
        self.middle.addLayout(self.logs_vbox, 2)

        self.vbox.addLayout(self.middle, 1)

        self.bottom_bar = QtWidgets.QHBoxLayout()
        self.lbl_sync_date = QtWidgets.QLabel(EN_TEXTS["last_sync_date"] + " --")
        self.lbl_sync_time = QtWidgets.QLabel(EN_TEXTS["last_sync_time"] + " --")
        self.bottom_bar.addWidget(self.lbl_sync_date)
        self.bottom_bar.addWidget(self.lbl_sync_time)
        self.bottom_bar.addStretch()
        self.lbl_language = QtWidgets.QLabel(EN_TEXTS["language"])
        self.bottom_bar.addWidget(self.lbl_language)
        self.combo_lang = QtWidgets.QComboBox()
        self.combo_lang.addItems([EN_TEXTS["english"], EN_TEXTS["farsi"]])
        self.combo_lang.currentIndexChanged.connect(self.change_language)
        self.bottom_bar.addWidget(self.combo_lang)
        self.vbox.addLayout(self.bottom_bar)

        self.entrance_camera_thread = CameraThread("rtsp://192.168.2.18:8080/h264.sdp")
        self.entrance_camera_thread.image_update.connect(self.update_entrance_camera)
        self.entrance_camera_thread.error.connect(self.entrance_error)
        self.entrance_camera_thread.start()

        self.exit_camera_thread = CameraThread("rtsp://192.168.2.18:8080/h264.sdp")
        self.exit_camera_thread.image_update.connect(self.update_exit_camera)
        self.exit_camera_thread.error.connect(self.exit_error)
        self.exit_camera_thread.start()

        self.ws_server_thread = WebSocketServerThread()
        self.ws_server_thread.log_received.connect(self.on_log_received)
        self.ws_server_thread.device_status_changed.connect(self.on_device_status_changed)
        self.ws_server_thread.start()

    def on_device_status_changed(self, device_serials):
        texts = FARSI_TEXTS if self.current_language == "fa" else EN_TEXTS
        if device_serials:
            status_text = texts["online"]
            device_list = "، ".join(device_serials) if self.current_language == "fa" else ", ".join(device_serials)
            self.status_frame.setStyleSheet("background: green; border-radius: 10px;")
            self.lbl_status.setText(f"{texts['device_status'].format(status_text)} | {device_list}")
        else:
            status_text = texts["offline"]
            self.status_frame.setStyleSheet("background: red; border-radius: 10px;")
            self.lbl_status.setText(texts["device_status"].format(status_text))

    def entrance_error(self, msg):
        self.entranceCameraFeed.setText(FARSI_TEXTS["no_feed"] if self.current_language == "fa" else EN_TEXTS["no_feed"])

    def exit_error(self, msg):
        self.exitCameraFeed.setText(FARSI_TEXTS["no_feed"] if self.current_language == "fa" else EN_TEXTS["no_feed"])

    def update_entrance_camera(self, image, raw_frame):
        self.entranceCameraFeed.setPixmap(QtGui.QPixmap.fromImage(image))
        self.latest_entrance_frame = raw_frame

    def update_exit_camera(self, image, raw_frame):
        self.exitCameraFeed.setPixmap(QtGui.QPixmap.fromImage(image))
        self.latest_exit_frame = raw_frame

    def closeEvent(self, event):
        self.entrance_camera_thread.stop()
        self.exit_camera_thread.stop()
        self.ws_server_thread.stop()
        super().closeEvent(event)

    def on_log_received(self, data):
        dt = datetime.datetime.fromtimestamp(data.get("timestamp", datetime.datetime.now().timestamp()))
        date, time_str = get_datetimes(self.current_language, dt)
        user_name = data.get("user_name", "")
        user_id = data.get("user_id", data.get("card_number", ""))
        device_direction = data.get("direction", "in")
        direction_text = "ورود" if (self.current_language == "fa" and device_direction.lower() == "in") else (
            "خروج" if self.current_language == "fa" else ("In" if device_direction.lower() == "in" else "Out"))
        unit = data.get("unit_number", "")
        plate = data.get("plate_number", "")
        permission = data.get("permission", "")
        device_serial = data.get("device_serial", "")

        # If possible, look up user info by card_number
        try:
            conn = sqlite3.connect("users.db")
            c = conn.cursor()
            c.execute("SELECT name, id, unit_number, plate_number, permission FROM users WHERE card_number=?", (data.get("card_number", ""),))
            row = c.fetchone()
            conn.close()
            if row:
                user_name, db_id, db_unit, db_plate, db_perm = row
                if not user_id: user_id = db_id
                if not unit: unit = db_unit
                if not plate: plate = db_plate
                if not permission: permission = db_perm
        except Exception:
            pass

        # Save photo if possible
        frame = self.latest_entrance_frame if device_direction.lower() == "in" else self.latest_exit_frame
        photo_path = ""
        if frame is not None:
            photo_path = save_photo(
                frame, device_direction, data.get("timestamp", int(dt.timestamp())), device_serial
            )

        # Save log (including photo path) to database
        insert_log_to_db(
            date, time_str, user_name, user_id, direction_text, unit, plate, permission, device_serial,
            photo_path, json.dumps(data, ensure_ascii=False)
        )

        # Build the row values (exclude status/device code)
        row_values = [
            date, time_str, user_name, str(user_id), direction_text, unit, plate, permission
        ]
        self.logTable.insertRow(0)
        row_count = self.logTable.rowCount()
        for row in range(row_count):
            # The oldest log is at the bottom, which gets No. 1
            index_number = row_count - row
            index_item = QtWidgets.QTableWidgetItem(str(index_number))
            index_item.setTextAlignment(QtCore.Qt.AlignCenter)
            font = QtGui.QFont("Tahoma")
            font.setBold(True)
            index_item.setFont(font)
            self.logTable.setVerticalHeaderItem(row, index_item)
        for i, val in enumerate(row_values):
            item = QtWidgets.QTableWidgetItem()
            # Direction column: show arrow icon
            if i == 4:
                arrow_char = "→" if device_direction.lower() == "in" else "←"
                item.setText(arrow_char)
                if device_direction.lower() == "in":
                    item.setForeground(QtGui.QBrush(QtGui.QColor("green")))
                else:
                    item.setForeground(QtGui.QBrush(QtGui.QColor("blue")))
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                font = QtGui.QFont("Tahoma")
                font.setPointSize(14)
                font.setBold(True)
                item.setFont(font)
            # Permission column: color code
            elif i == 7:
                item.setText(str(val))
                if permission.lower() == "open":
                    item.setForeground(QtGui.QBrush(QtGui.QColor("green")))
                elif permission.lower() == "limited":
                    item.setForeground(QtGui.QBrush(QtGui.QColor("blue")))
                elif permission.lower() == "restricted":
                    item.setForeground(QtGui.QBrush(QtGui.QColor("red")))
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                font = QtGui.QFont("Tahoma")
                font.setBold(True)
                item.setFont(font)
            else:
                item.setText(str(val))
                item.setTextAlignment(QtCore.Qt.AlignCenter)
                item.setFont(QtGui.QFont("Tahoma"))
            self.logTable.setItem(0, i, item)

        self.capture_picture_for_log(direction_text)

    def capture_picture_for_log(self, direction):
        if direction in ["In", "ورود"]:
            frame = self.latest_entrance_frame
        else:
            frame = self.latest_exit_frame

        if frame is not None:
            h, w, ch = frame.shape
            bytes_per_line = ch * w
            qt_image = QtGui.QImage(
                frame.data, w, h, bytes_per_line, QtGui.QImage.Format_RGB888)
            scaled_img = qt_image.scaled(320, 180, QtCore.Qt.KeepAspectRatio)
            self.lastInOutImage.setPixmap(QtGui.QPixmap.fromImage(scaled_img))
        else:
            texts = FARSI_TEXTS if self.current_language == "fa" else EN_TEXTS
            self.lastInOutImage.setText(texts["no_image"])

    def change_language(self, index):
        if index == 1:
            self.current_language = "fa"
            self.setLayoutDirection(QtCore.Qt.RightToLeft)
            texts = FARSI_TEXTS
        else:
            self.current_language = "en"
            self.setLayoutDirection(QtCore.Qt.LeftToRight)
            texts = EN_TEXTS

        self.setWindowTitle(texts["dashboard"])
        self.lbl_title.setText(texts["dashboard"])
        self.lbl_entrance.setText(texts["entrance"])
        self.lbl_exit.setText(texts["exit"])
        self.lbl_last_inout.setText(texts["last_inout"])
        self.entranceCameraFeed.setText(texts["no_feed"])
        self.exitCameraFeed.setText(texts["no_feed"])
        self.lastInOutImage.setText(texts["no_image"])
        self.lbl_live_logs.setText(texts["live_logs"])
        self.btn_settings.setText(texts["settings"])
        self.btn_user_mgmt.setText(texts["user_mgmt"])
        self.btn_reports.setText(texts["reports"])
        self.btn_logout.setText(texts["logout"])
        offline_txt = texts["offline"]
        self.lbl_status.setText(texts["device_status"].format(offline_txt))
        self.lbl_sync_date.setText(texts["last_sync_date"] + " --")
        self.lbl_sync_time.setText(texts["last_sync_time"] + " --")
        self.lbl_language.setText(texts["language"])
        self.combo_lang.setItemText(0, EN_TEXTS["english"])
        self.combo_lang.setItemText(1, EN_TEXTS["farsi"])
        log_headers = [
            texts["table_headers"][0],
            texts["table_headers"][1],
            texts["table_headers"][2],
            texts["table_headers"][3],
            texts["table_headers"][4],
            texts["table_headers"][5],
            texts["table_headers"][6],
            texts["table_headers"][7],
        ]
        self.logTable.setHorizontalHeaderLabels(log_headers)
        font = QtGui.QFont("Tahoma") if self.current_language == "fa" else QtGui.QFont()
        self.logTable.setFont(font)
        if self.current_language == "fa":
            for col in range(self.logTable.columnCount()):
                self.logTable.horizontalHeaderItem(col).setTextAlignment(QtCore.Qt.AlignRight)
        else:
            for col in range(self.logTable.columnCount()):
                self.logTable.horizontalHeaderItem(col).setTextAlignment(QtCore.Qt.AlignLeft)

    def open_settings(self):
        QtWidgets.QMessageBox.information(self, "Settings", "Settings dialog not implemented.")

    def open_user_management(self):
        dlg = UserManagementDialog(self)
        dlg.exec_()

    def open_reports(self):
        QtWidgets.QMessageBox.information(self, "Reports", "Reports dialog not implemented.")

    def logout(self):
        QtWidgets.QMessageBox.information(self, "Logout", "Logout not implemented.")

if __name__ == "__main__":
    # Requires: pip install websockets PyQt5 opencv-python jdatetime
    init_db()
    app = QtWidgets.QApplication(sys.argv)
    window = MainDashboard()
    QtCore.QTimer.singleShot(0, window.showMaximized)
    sys.exit(app.exec_())