import logging
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QLineEdit, QTextEdit, QCompleter)
from PyQt5.QtCore import Qt, QStringListModel

log = logging.getLogger(__name__)

SUGGESTIONS = [
    "*RST", "H1", "H0",
    "DE0", "DE1", "SD0", "SD1", "SD2",
    "INIC1", "TRS0", "TRS1",
    "ERR?", "IDN?",
    "DSP1,F1", "DSP1,F2", "DSP1,F3", "DSP1,F4",
    "DSP1,F5", "DSP1,F6", "DSP1,F7", "DSP1,F8",
    "DSP1,F9", "DSP1,F10", "DSP1,F11",
    "DSP2,F12", "DSP2,F35", "DSP2,F36", "DSP2,F37",
    "DSP1,R0", "DSP1,R1", "DSP1,R2", "DSP1,R3", "DSP1,R4",
    "DSP1,R5", "DSP1,R6", "DSP1,R7", "DSP1,R8", "DSP1,R9",
    "DSP1,PR0", "DSP1,PR1", "DSP1,PR2", "DSP1,PR3", "DSP1,PR4",
    "DSP1,RE0", "DSP1,RE1", "DSP1,RE2", "DSP1,RE3", "DSP1,RE4",
    "DSP1,RE5", "DSP1,RE6", "DSP1,RE7", "DSP1,RE8",
    "DSP1,AZ0", "DSP1,AZ1",
    "DSP1,NL0", "DSP1,NL1",
    "DSP1,SM0", "DSP1,SM1",
    "DSP1,CO0", "DSP1,CO1",
    "DSP1,MN0", "DSP1,MN1",
    "DSP2,PR0", "DSP2,PR1", "DSP2,PR2", "DSP2,PR3", "DSP2,PR4",
    "DSP2,AZ0", "DSP2,AZ1",
]


class ConsoleTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._instrument = None
        self._history = []
        self._history_pos = -1

        layout = QVBoxLayout(self)
        layout.setSpacing(4)

        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setObjectName("consoleOutput")
        layout.addWidget(self._output, 1)

        input_row = QHBoxLayout()
        self._input = QLineEdit()
        self._input.setPlaceholderText("Enter ADC command...")
        self._input.setObjectName("consoleInput")
        completer = QCompleter(SUGGESTIONS)
        completer.setCaseSensitivity(Qt.CaseInsensitive)
        self._input.setCompleter(completer)
        self._input.returnPressed.connect(self._send_command)
        input_row.addWidget(self._input, 1)

        self._send_btn = QPushButton("Send")
        self._send_btn.clicked.connect(self._send_command)
        input_row.addWidget(self._send_btn)

        clear_btn = QPushButton("Clear")
        clear_btn.clicked.connect(lambda: self._output.clear())
        input_row.addWidget(clear_btn)

        layout.addLayout(input_row)

    def set_instrument(self, instrument):
        self._instrument = instrument

    def _send_command(self):
        if not self._instrument or not self._instrument.connected:
            self._output.append("! Not connected")
            return

        cmd = self._input.text().strip()
        if not cmd:
            return

        self._history.append(cmd)
        self._history_pos = len(self._history)
        self._input.clear()

        self._output.append(f">> {cmd}")
        try:
            reply = self._instrument.query(cmd)
            if reply:
                self._output.append(f"<< {reply}")
            else:
                self._output.append("<< (no response)")
        except Exception as e:
            self._output.append(f"! Error: {e}")
            log.error("Console command failed: %s", e)

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Up:
            if self._history_pos > 0:
                self._history_pos -= 1
                self._input.setText(self._history[self._history_pos])
        elif event.key() == Qt.Key_Down:
            if self._history_pos < len(self._history) - 1:
                self._history_pos += 1
                self._input.setText(self._history[self._history_pos])
            else:
                self._history_pos = len(self._history)
                self._input.clear()
        else:
            super().keyPressEvent(event)
