import os
import csv
from datetime import datetime
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QComboBox, QLineEdit, QFileDialog,
                             QCheckBox, QTextEdit)
from PyQt5.QtCore import Qt


class ExportTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._logging = False
        self._file = None
        self._writer = None
        self._row_count = 0

        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        dest_row = QHBoxLayout()
        dest_row.addWidget(QLabel("File:"))
        self._path_edit = QLineEdit()
        self._path_edit.setReadOnly(True)
        dest_row.addWidget(self._path_edit)
        browse_btn = QPushButton("Browse")
        browse_btn.clicked.connect(self._browse)
        dest_row.addWidget(browse_btn)
        layout.addLayout(dest_row)

        fmt_row = QHBoxLayout()
        fmt_row.addWidget(QLabel("Format:"))
        self._format_combo = QComboBox()
        self._format_combo.addItems(["CSV", "TXT"])
        fmt_row.addWidget(self._format_combo)
        fmt_row.addStretch()
        self._include_ts = QCheckBox("Include timestamp")
        self._include_ts.setChecked(True)
        fmt_row.addWidget(self._include_ts)
        layout.addLayout(fmt_row)

        btn_row = QHBoxLayout()
        self._start_btn = QPushButton("▶ START LOG")
        self._start_btn.clicked.connect(self._toggle_log)
        self._stop_btn = QPushButton("■ STOP LOG")
        self._stop_btn.clicked.connect(self._toggle_log)
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

        self._log_display = QTextEdit()
        self._log_display.setReadOnly(True)
        self._log_display.setObjectName("exportLogDisplay")
        self._log_display.setMaximumHeight(100)
        layout.addWidget(self._log_display)

        layout.addStretch()

    def _browse(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Save Log File", f"adcmt_log_{datetime.now():%Y%m%d_%H%M%S}",
            "CSV Files (*.csv);;Text Files (*.txt);;All Files (*)")
        if path:
            self._path_edit.setText(path)

    def _toggle_log(self):
        if self._logging:
            self._stop()
        else:
            self._start()

    def _start(self):
        path = self._path_edit.text()
        if not path:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.warning(self, "No File", "Select a log file first")
            return
        try:
            self._file = open(path, "w", newline="")
            is_csv = self._format_combo.currentText() == "CSV"
            if is_csv:
                self._writer = csv.writer(self._file)
                header = ["Timestamp", "ChA_Value", "ChA_Unit",
                          "ChB_Value", "ChB_Unit"]
                self._writer.writerow(header)
            else:
                self._writer = None
                self._file.write(f"# ADCMT 7352A Log  Started: {datetime.now()}\n")
                self._file.write("# Timestamp\tChA_Value\tChA_Unit\tChB_Value\tChB_Unit\n")
            self._row_count = 0
            self._logging = True
            self._start_btn.setEnabled(False)
            self._stop_btn.setEnabled(True)
            self._log_display.append(f"Logging started → {os.path.basename(path)}")
        except OSError as e:
            from PyQt5.QtWidgets import QMessageBox
            QMessageBox.critical(self, "Error", f"Failed to open file:\n{e}")

    def _stop(self):
        self._logging = False
        if self._file:
            self._file.close()
            self._file = None
        self._writer = None
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._log_display.append(f"Logging stopped  ({self._row_count} rows written)")

    def write_data(self, result):
        if not self._logging or not self._file:
            return

        ch_a = result.get("A")
        ch_b = result.get("B")
        ts = datetime.now().isoformat(timespec="milliseconds")

        va = f"{ch_a[0]:.6e}" if ch_a else ""
        ua = ch_a[4].split()[-1] if ch_a and ch_a[4] else ""
        vb = f"{ch_b[0]:.6e}" if ch_b else ""
        ub = ch_b[4].split()[-1] if ch_b and ch_b[4] else ""

        if self._writer:
            self._writer.writerow([ts, va, ua, vb, ub])
        else:
            self._file.write(f"{ts}\t{va}\t{ua}\t{vb}\t{ub}\n")
        self._file.flush()
        self._row_count += 1

    def close(self):
        if self._logging:
            self._stop()
