import os
import sqlite3
import re
from PyQt5 import QtWidgets, QtCore, QtGui

DB_PATH = "users.db"
PERMISSIONS = ["Open", "Limited", "Restricted"]

def init_db():
    if not os.path.exists(DB_PATH):
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("""
            CREATE TABLE users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL,
                card_number TEXT UNIQUE NOT NULL,
                photo BLOB,
                unit_number TEXT,
                plate_number TEXT,
                permission TEXT NOT NULL
            )
        """)
        conn.commit()
        conn.close()
    else:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        columns = [r[1] for r in c.execute("PRAGMA table_info(users)")]
        add_cols = []
        if "photo" not in columns:
            add_cols.append("ALTER TABLE users ADD COLUMN photo BLOB")
        if "unit_number" not in columns:
            add_cols.append("ALTER TABLE users ADD COLUMN unit_number TEXT")
        if "plate_number" not in columns:
            add_cols.append("ALTER TABLE users ADD COLUMN plate_number TEXT")
        if "permission" not in columns:
            add_cols.append("ALTER TABLE users ADD COLUMN permission TEXT NOT NULL DEFAULT 'Open'")
        for sql in add_cols:
            c.execute(sql)
        conn.commit()
        conn.close()

class UserManagementDialog(QtWidgets.QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("User Management")
        self.resize(700, 530)
        self.layout = QtWidgets.QVBoxLayout(self)

        # --- Editable fields area ---
        form_layout = QtWidgets.QGridLayout()
        self.edit_id = QtWidgets.QLineEdit()
        self.edit_id.setPlaceholderText("ID (auto or edit)")
        form_layout.addWidget(QtWidgets.QLabel("ID:"), 0, 0)
        form_layout.addWidget(self.edit_id, 0, 1)

        self.edit_name = QtWidgets.QLineEdit()
        form_layout.addWidget(QtWidgets.QLabel("Name:"), 0, 2)
        form_layout.addWidget(self.edit_name, 0, 3)

        self.edit_card = QtWidgets.QLineEdit()
        form_layout.addWidget(QtWidgets.QLabel("Card Number:"), 1, 0)
        form_layout.addWidget(self.edit_card, 1, 1)

        self.edit_unit = QtWidgets.QLineEdit()
        form_layout.addWidget(QtWidgets.QLabel("Unit Number:"), 1, 2)
        form_layout.addWidget(self.edit_unit, 1, 3)

        self.edit_plate = QtWidgets.QLineEdit()
        form_layout.addWidget(QtWidgets.QLabel("Plate Number:"), 2, 0)
        form_layout.addWidget(self.edit_plate, 2, 1)

        self.combo_permission = QtWidgets.QComboBox()
        self.combo_permission.addItems(PERMISSIONS)
        form_layout.addWidget(QtWidgets.QLabel("Permission:"), 2, 2)
        form_layout.addWidget(self.combo_permission, 2, 3)

        # Photo
        self.photo_label = QtWidgets.QLabel("No Photo")
        self.photo_label.setFixedSize(80, 100)
        self.photo_label.setStyleSheet("border:1px solid #999; background:#eee;")
        self.photo_label.setAlignment(QtCore.Qt.AlignCenter)
        form_layout.addWidget(self.photo_label, 0, 4, 3, 1)
        self.btn_browse_photo = QtWidgets.QPushButton("Browse Photo")
        form_layout.addWidget(self.btn_browse_photo, 3, 4)
        self.btn_browse_photo.clicked.connect(self.browse_photo)
        self.current_photo_data = None  # raw bytes

        # Add, Update, Search, Delete, Clear
        self.btn_add = QtWidgets.QPushButton("Add")
        self.btn_update = QtWidgets.QPushButton("Update")
        self.btn_search = QtWidgets.QPushButton("Search")
        self.btn_delete = QtWidgets.QPushButton("Delete")
        self.btn_clear = QtWidgets.QPushButton("Clear")
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.addWidget(self.btn_add)
        btn_layout.addWidget(self.btn_update)
        btn_layout.addWidget(self.btn_search)
        btn_layout.addWidget(self.btn_delete)
        btn_layout.addWidget(self.btn_clear)
        form_layout.addLayout(btn_layout, 4, 0, 1, 5)

        self.btn_add.clicked.connect(self.add_user)
        self.btn_update.clicked.connect(self.update_user)
        self.btn_search.clicked.connect(self.search_user)
        self.btn_delete.clicked.connect(self.delete_user)
        self.btn_clear.clicked.connect(self.clear_fields)

        self.layout.addLayout(form_layout)

        # --- Table area ---
        self.table = QtWidgets.QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "Name", "Card Number", "Unit Number", "Plate Number", "Permission", "Photo"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setSelectionBehavior(QtWidgets.QTableWidget.SelectRows)
        self.table.setEditTriggers(QtWidgets.QTableWidget.NoEditTriggers)
        self.table.setColumnWidth(6, 70)
        self.layout.addWidget(self.table)

        self.table.itemSelectionChanged.connect(self.fill_fields_from_selection)

        self.load_users()

    def browse_photo(self):
        path, _ = QtWidgets.QFileDialog.getOpenFileName(self, "Select Photo", "", "Images (*.png *.jpg *.jpeg *.bmp)")
        if path:
            pixmap = QtGui.QPixmap(path).scaled(self.photo_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation)
            self.photo_label.setPixmap(pixmap)
            with open(path, "rb") as f:
                self.current_photo_data = f.read()

    def fill_fields_from_selection(self):
        selected = self.table.selectedItems()
        if not selected:
            return
        row = self.table.currentRow()
        self.edit_id.setText(self.table.item(row, 0).text())
        self.edit_name.setText(self.table.item(row, 1).text())
        self.edit_card.setText(self.table.item(row, 2).text())
        self.edit_unit.setText(self.table.item(row, 3).text())
        self.edit_plate.setText(self.table.item(row, 4).text())
        self.combo_permission.setCurrentText(self.table.item(row, 5).text())
        # Load photo from db
        user_id = self.table.item(row, 0).text()
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT photo FROM users WHERE id=?", (user_id,))
        row_photo = c.fetchone()
        conn.close()
        if row_photo and row_photo[0]:
            pixmap = QtGui.QPixmap()
            pixmap.loadFromData(row_photo[0])
            self.photo_label.setPixmap(pixmap.scaled(self.photo_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
            self.current_photo_data = row_photo[0]
        else:
            self.photo_label.setText("No Photo")
            self.photo_label.setPixmap(QtGui.QPixmap())
            self.current_photo_data = None

    def clear_fields(self):
        self.edit_id.clear()
        self.edit_name.clear()
        self.edit_card.clear()
        self.edit_unit.clear()
        self.edit_plate.clear()
        self.combo_permission.setCurrentIndex(0)
        self.photo_label.setText("No Photo")
        self.photo_label.setPixmap(QtGui.QPixmap())
        self.current_photo_data = None
        self.table.clearSelection()

    def load_users(self, filter_clause="", params=()):
        self.table.setRowCount(0)
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        query = "SELECT id, name, card_number, unit_number, plate_number, permission, photo FROM users"
        if filter_clause:
            query += " WHERE " + filter_clause
        query += " ORDER BY id"
        for row in c.execute(query, params):
            row_idx = self.table.rowCount()
            self.table.insertRow(row_idx)
            for col_idx, value in enumerate(row[:-1]):
                self.table.setItem(row_idx, col_idx, QtWidgets.QTableWidgetItem(str(value) if value is not None else ""))
            # Photo preview
            photo_data = row[-1]
            photo_item = QtWidgets.QTableWidgetItem()
            if photo_data:
                pixmap = QtGui.QPixmap()
                pixmap.loadFromData(photo_data)
                icon = QtGui.QIcon(pixmap.scaled(48, 60, QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
                photo_item.setIcon(icon)
            else:
                photo_item.setText("No Photo")
            self.table.setItem(row_idx, 6, photo_item)
        conn.close()

    def validate_fields(self, id_val, name, card):
        # Name cannot be empty, only letters (unicode), allow spaces; must not be blank
        if not name.strip():
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Name cannot be empty.")
            return False
        # Unicode letters and spaces only
        if not re.match(r"^[^\W\d_]+(?: [^\W\d_]+)*$", name.strip(), re.UNICODE):
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Name must contain only letters and spaces.")
            return False

        # Card Number cannot be empty, only digits
        if not card.strip():
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Card Number cannot be empty.")
            return False
        if not card.isdigit():
            QtWidgets.QMessageBox.warning(self, "Validation Error", "Card Number must contain only digits.")
            return False

        # ID, if provided, must be digits between 1 and 5000
        if id_val:
            if not id_val.isdigit():
                QtWidgets.QMessageBox.warning(self, "Validation Error", "ID must contain only digits.")
                return False
            id_int = int(id_val)
            if not (1 <= id_int <= 5000):
                QtWidgets.QMessageBox.warning(self, "Validation Error", "ID must be between 1 and 5000.")
                return False
        return True

    def add_user(self):
        id_val = self.edit_id.text().strip()
        name = self.edit_name.text().strip()
        card = self.edit_card.text().strip()
        unit = self.edit_unit.text().strip()
        plate = self.edit_plate.text().strip()
        perm = self.combo_permission.currentText()
        photo = self.current_photo_data

        if not self.validate_fields(id_val, name, card):
            return

        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            # If ID is manually set, attempt to use it
            if id_val:
                c.execute("""INSERT INTO users (id, name, card_number, unit_number, plate_number, permission, photo)
                             VALUES (?, ?, ?, ?, ?, ?, ?)""",
                          (int(id_val), name, card, unit, plate, perm, photo))
            else:
                c.execute("""INSERT INTO users (name, card_number, unit_number, plate_number, permission, photo)
                             VALUES (?, ?, ?, ?, ?, ?)""",
                          (name, card, unit, plate, perm, photo))
            conn.commit()
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Error", "Card number must be unique or ID already exists.")
        finally:
            conn.close()
        self.load_users()
        self.clear_fields()

    def update_user(self):
        id_val = self.edit_id.text().strip()
        if not id_val:
            QtWidgets.QMessageBox.warning(self, "Error", "Select or enter user ID to update.")
            return
        name = self.edit_name.text().strip()
        card = self.edit_card.text().strip()
        unit = self.edit_unit.text().strip()
        plate = self.edit_plate.text().strip()
        perm = self.combo_permission.currentText()
        photo = self.current_photo_data
        if not self.validate_fields(id_val, name, card):
            return
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        try:
            c.execute("""UPDATE users SET name=?, card_number=?, unit_number=?, plate_number=?, permission=?, photo=?
                         WHERE id=?""",
                      (name, card, unit, plate, perm, photo, int(id_val)))
            if c.rowcount == 0:
                QtWidgets.QMessageBox.warning(self, "Error", "User ID does not exist.")
        except sqlite3.IntegrityError:
            QtWidgets.QMessageBox.warning(self, "Error", "Card number must be unique.")
        finally:
            conn.commit()
            conn.close()
        self.load_users()
        self.clear_fields()

    def search_user(self):
        filters = []
        params = []
        if self.edit_id.text().strip():
            filters.append("id=?")
            params.append(self.edit_id.text().strip())
        if self.edit_name.text().strip():
            filters.append("name LIKE ?")
            params.append('%'+self.edit_name.text().strip()+'%')
        if self.edit_card.text().strip():
            filters.append("card_number LIKE ?")
            params.append('%'+self.edit_card.text().strip()+'%')
        if self.edit_unit.text().strip():
            filters.append("unit_number LIKE ?")
            params.append('%'+self.edit_unit.text().strip()+'%')
        if self.edit_plate.text().strip():
            filters.append("plate_number LIKE ?")
            params.append('%'+self.edit_plate.text().strip()+'%')
        if self.combo_permission.currentText():
            filters.append("permission=?")
            params.append(self.combo_permission.currentText())
        filter_clause = " AND ".join(filters)
        self.load_users(filter_clause, tuple(params))

    def delete_user(self):
        selected = self.table.selectedItems()
        if not selected:
            # Do nothing if no row is selected
            return
        row = self.table.currentRow()
        user_id = self.table.item(row, 0).text()
        reply = QtWidgets.QMessageBox.question(self, "Delete User",
                                               "Are you sure you want to delete this user?",
                                               QtWidgets.QMessageBox.Yes | QtWidgets.QMessageBox.No)
        if reply == QtWidgets.QMessageBox.Yes:
            conn = sqlite3.connect(DB_PATH)
            c = conn.cursor()
            c.execute("DELETE FROM users WHERE id=?", (user_id,))
            conn.commit()
            conn.close()
            self.load_users()
            self.clear_fields()