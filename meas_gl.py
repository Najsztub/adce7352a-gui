import sys
import re
import pyvisa
import numpy as np

from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QPainter, QColor
# Add QOpenGLWidget to your existing QtWidgets import
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QComboBox, QLabel, QGroupBox, 
                             QLCDNumber, QLineEdit, QStatusBar, QFormLayout, QCheckBox, QMessageBox,
                             QOpenGLWidget, QTabWidget, QSpinBox, QDoubleSpinBox, QListWidget, 
                             QListWidgetItem, QTextEdit)
from OpenGL.GL import *
from OpenGL.GL import GL_TEXTURE_2D

from mock import MockDMMDevice

# =============================================================================
# ADC COMMAND MAPPINGS (Based on Manual Section 6.6.3)
# =============================================================================
ADC_FUNCS = {
    "DCV-Ach": "F1", "ACV-Ach": "F2", "2WΩ-Ach": "F3", "DCI-Ach": "F5",
    "ACI-Ach": "F6", "ACV+DC-Ach": "F7", "ACI+DC-Ach": "F8",
    "DCV-Bch": "F12", "DIODE-Ach": "F13", "LP-2WΩ-Ach": "F20",
    "CONT-Ach": "F22", "DCI-Bch": "F35", "ACI-Bch": "F36",
    "ACI+DC-Bch": "F37", "TEMP": "F40", "FREQ-Ach": "F50"
}

# User-readable function labels
FUNC_LABELS = {
    "DCV-Ach": "DC Voltage - Channel A",
    "ACV-Ach": "AC Voltage - Channel A",
    "2WΩ-Ach": "2-Wire Resistance - Channel A",
    "DCI-Ach": "DC Current - Channel A",
    "ACI-Ach": "AC Current - Channel A",
    "ACV+DC-Ach": "AC+DC Voltage - Channel A",
    "ACI+DC-Ach": "AC+DC Current - Channel A",
    "DCV-Bch": "DC Voltage - Channel B",
    "DIODE-Ach": "Diode Test - Channel A",
    "LP-2WΩ-Ach": "2-Wire Resistance (Low Power) - Channel A",
    "CONT-Ach": "Continuity - Channel A",
    "DCI-Bch": "DC Current - Channel B",
    "ACI-Bch": "AC Current - Channel B",
    "ACI+DC-Bch": "AC+DC Current - Channel B",
    "TEMP": "Temperature",
    "FREQ-Ach": "Frequency - Channel A"
}

ADC_RANGES = {"AUTO": "R0", "R1": "R1", "R2": "R2", "R3": "R3", 
              "R4": "R4", "R5": "R5", "R6": "R6", "R7": "R7", "R8": "R8", "R9": "R9"}
ADC_RATES = {"FAST": "PR1", "MED": "PR2", "SLOW1": "PR3", "SLOW2": "PR4"}
ADC_TRIGS = {"IMM": "TRS0", "MAN": "TRS1", "EXT": "TRS2", "BUS": "TRS3"}

# Digits  RE3..RE5  (§6.6.3)
DIGITS_CMD  = ["RE3", "RE4", "RE5"]
DIGITS_DISP = ["3½", "4½", "5½"]

OVERLOAD_THRESHOLD = 9.9e+9

SUB_LABELS = {
    "_": "",     "O": " [OL]",    "H": " [HI]",  "P": " [PASS]",
    "L": " [LO]", "N": " [NULL]",  "S": " [SCALE]", "B": " [dB]",
    "W": " [dBm]", "E": " [Err]",  "M": " [MAX]",  "I": " [MIN]",
    "A": " [AVG]", "D": " [CALC2]",
}

HDR_LABELS = {
    "DCV": "DC Volt", "ACV": "AC Volt", "ADV": "AC+DC Volt",
    "R2W": "2W Res", "R2L": "LP-2W", "DCI": "DC Curr",
    "ACI": "AC Curr", "ADI": "AC+DC Curr", "FRQ": "Freq",
    "DOD": "Diode",  "RCT": "Cont",  "TC_": "Temp",
    "BDV": "DC Volt B", "BDI": "DC Curr B", "BAI": "AC Curr B", "BCI": "AC+DC Curr B",
}

FUNCTIONS = {
    "F1":  ("DCV  Ach",          "V",
            [("Auto", "R0"), ("200 mV", "R3"), ("2 V", "R4"),
             ("20 V", "R5"), ("200 V", "R6"), ("1000 V", "R7")], "DCV"),
    "F2":  ("ACV  Ach",           "V",
            [("Auto", "R0"), ("200 mV", "R3"), ("2 V", "R4"),
             ("20 V", "R5"), ("200 V", "R6"), ("700 V", "R7")], "ACV"),
    "F7":  ("ACV AC+DC  Ach",     "V",
            [("Auto", "R0"), ("200 mV", "R3"), ("2 V", "R4"),
             ("20 V", "R5"), ("200 V", "R6"), ("700 V", "R7")], "ADV"),
    "F3":  ("2W Ω  Ach",          "Ω",
            [("Auto", "R0"), ("200 Ω", "R3"), ("2 kΩ", "R4"), ("20 kΩ", "R5"),
             ("200 kΩ", "R6"), ("2 MΩ", "R7"), ("20 MΩ", "R8"), ("200 MΩ", "R9")], "R2W"),
    "F20": ("LP-2W Ω  Ach",       "Ω",
            [("Auto", "R0"), ("200 Ω", "R3"), ("2 kΩ", "R4"), ("20 kΩ", "R5"),
             ("200 kΩ", "R6"), ("2 MΩ", "R7"), ("20 MΩ", "R8")], "R2L"),
    "F5":  ("DCI  Ach",           "A",
            [("Auto", "R0"), ("2000 nA", "R1"), ("20 µA", "R2"), ("200 µA", "R3"),
             ("2 mA", "R4"), ("20 mA", "R5"), ("200 mA", "R6"), ("2000 mA", "R7")], "DCI"),
    "F6":  ("ACI  Ach",           "A",
            [("Auto", "R0"), ("200 µA", "R3"), ("2 mA", "R4"),
             ("20 mA", "R5"), ("200 mA", "R6"), ("2000 mA", "R7")], "ACI"),
    "F8":  ("ACI AC+DC  Ach",     "A",
            [("Auto", "R0"), ("200 µA", "R3"), ("2 mA", "R4"),
             ("20 mA", "R5"), ("200 mA", "R6"), ("2000 mA", "R7")], "ADI"),
    "F50": ("FREQ  Ach",          "Hz", [("Auto", "R0")], "FRQ"),
    "F13": ("DIODE  Ach",         "V",  [("—", "")],      "DOD"),
    "F22": ("CONT  Ach",          "Ω",  [("—", "")],      "RCT"),
    "F40": ("TEMP",               "°C", [("—", "")],      "TC_"),
    "F12": ("DCV  Bch",           "V",
            [("Auto", "R0"), ("200 mV", "R3"), ("2 V", "R4"),
             ("20 V", "R5"), ("200 V", "R6")], "BDV"),
    "F35": ("DCI  Bch",           "A",  [("10 A", "R8")], "BDI"),
    "F36": ("ACI  Bch",           "A",  [("10 A", "R8")], "BAI"),
    "F37": ("ACI AC+DC  Bch",     "A",  [("10 A", "R8")], "BCI"),
}


# =============================================================================
# Response parser (§6.6.2)
# Header ON (H1):  "DCV_  +3.29860E+00"   or  "DCV_  -0.00123E+00"
# Header OFF (H0): "+3.29860E+00"
# Overload:        9.99999E+37
# =============================================================================
_HDR_RE = re.compile(r'^([A-Z0-9_]{3})([A-Z_])\s+([-+]?\d[\d.]*E[+-]\d+)\s*$')
_NUM_RE = re.compile(r'^([-+]?\d[\d.]*E[+-]\d+)')

def _cur_fkey(func_label):
    for k, v in FUNCTIONS.items():
        if v[0] == func_label:
            return k
    return "F1"

def _si_fmt(val, unit):
    if val == 0:
        return f"0.000 {unit}"
    a = abs(val)
    for scale, pfx in [(1e12,"T"),(1e9,"G"),(1e6,"M"),(1e3,"k"),
                       (1,""),(1e-3,"m"),(1e-6,"µ"),(1e-9,"n"),(1e-12,"p")]:
        if a >= scale * 0.9999:
            return f"{val/scale:.5g} {pfx}{unit}"
    return f"{val:.5E} {unit}"

def parse_adc_response(raw, func_key="F1"):
    """Returns (value, main_hdr, sub_hdr, is_overload, display_str, desc_str)."""
    raw = raw.strip()
    main_h, sub_h = "", "_"
    m = _HDR_RE.match(raw)
    if m:
        main_h = m.group(1)
        sub_h  = m.group(2)
        num_s  = m.group(3)
    else:
        nm = _NUM_RE.match(raw)
        num_s = nm.group(1) if nm else raw
    try:
        val = float(num_s)
    except ValueError:
        return 0.0, main_h, sub_h, False, raw, raw
    is_ol = val >= OVERLOAD_THRESHOLD
    unit  = FUNCTIONS.get(func_key, ("", "V", "", "DCV"))[1]
    disp  = "OVERLOAD" if is_ol else _si_fmt(val, unit)
    desc  = HDR_LABELS.get(main_h, main_h) + SUB_LABELS.get(sub_h, f" [{sub_h}]")
    return val, main_h, sub_h, is_ol, disp, desc

# =============================================================================
# OPENGL LIVE PLOT WIDGET
# =============================================================================
class DMMGLPlot(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data_a = np.zeros(200)
        self.data_b = np.zeros(200)
        self.min_val, self.max_val = -1.0, 1.0
        self.min_val_default = -1.0
        self.max_val_default = 1.0
        self.setMinimumHeight(150)
        
        # Annotation support
        self.annotations = []  # List of (x, y, text, color) tuples
        self.enable_annotations = False
        self.stats_display = {}  # Dict for statistics display
        
        # Channel enable flags
        self.enable_a = True
        self.enable_b = False
        
        # Axis labels
        self.x_label = "Time (samples)"
        self.y_label = "Value"
        
        # Zoom and pan support
        self.zoom_level = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self.setMouseTracking(True)

    def set_channel_enabled(self, channel, enabled):
        """Set whether a channel should be plotted."""
        if channel == "A":
            self.enable_a = enabled
        elif channel == "B":
            self.enable_b = enabled
        self.update()
    
    def reset_zoom(self):
        """Reset zoom and pan to default state."""
        self.zoom_level = 1.0
        self.pan_x = 0.0
        self.pan_y = 0.0
        self.update()
    
    def wheelEvent(self, event):
        """Handle mouse wheel zoom."""
        if event.angleDelta().y() > 0:
            # Scroll up: zoom in
            self.zoom_level *= 1.1
        else:
            # Scroll down: zoom out
            self.zoom_level /= 1.1
        # Clamp zoom level
        self.zoom_level = np.clip(self.zoom_level, 0.1, 10.0)
        self.update()
        event.accept()

    def update_readings(self, val_a, val_b):
        # Shift buffer and insert new value
        self.data_a = np.roll(self.data_a, -1)
        self.data_b = np.roll(self.data_b, -1)
        self.data_a[-1] = val_a
        self.data_b[-1] = val_b
        
        # Update auto-scale bounds with only enabled channels
        vals_to_use = []
        if self.enable_a:
            vals_to_use.extend(self.data_a)
        if self.enable_b:
            vals_to_use.extend(self.data_b)
        
        if vals_to_use:
            all_vals = np.array(vals_to_use)
            valid = all_vals[np.isfinite(all_vals)]
            if len(valid) > 0:
                min_v = np.min(valid)
                max_v = np.max(valid)
                # Add 10% margin
                margin = (max_v - min_v) * 0.1
                if margin == 0:
                    margin = 0.5
                self.min_val_default = min_v - margin
                self.max_val_default = max_v + margin
            else:
                self.min_val_default, self.max_val_default = -1.0, 1.0
        else:
            self.min_val_default, self.max_val_default = -1.0, 1.0
        
        # Apply zoom to the defaults
        center_y = (self.min_val_default + self.max_val_default) / 2
        height = self.max_val_default - self.min_val_default
        zoomed_height = height / self.zoom_level
        self.min_val = center_y - zoomed_height / 2 + self.pan_y
        self.max_val = center_y + zoomed_height / 2 + self.pan_y
        
        self.update()
    
    def add_annotation(self, x, y, text, color=(1.0, 1.0, 1.0)):
        """Add an annotation to the plot."""
        self.annotations.append((x, y, text, color))
        self.update()
    
    def clear_annotations(self):
        """Clear all annotations."""
        self.annotations.clear()
        self.update()
    
    def render_labels(self):
        """Render axis labels and values using QPainter."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(painter.font())
        
        w, h = self.width(), self.height()
        left_margin = 50
        bottom_margin = 30
        
        # Draw Y-axis values on the left
        painter.setPen(QColor(128, 128, 128))
        y_step = (self.max_val - self.min_val) / 5
        for i in range(6):
            y_val = self.min_val + i * y_step
            # Screen position
            y_screen = h - bottom_margin - (i / 5) * (h - bottom_margin)
            label = f"{y_val:.2g}"
            painter.drawText(5, int(y_screen) - 5, 40, 20, Qt.AlignRight, label)
        
        # Draw X-axis label at bottom
        painter.drawText(w - 120, h - 5, self.x_label)
        
        # Draw Y-axis label on left (rotated)
        painter.save()
        painter.translate(15, h // 2)
        painter.rotate(-90)
        painter.drawText(0, 0, self.y_label)
        painter.restore()
        
        # Draw annotation text labels
        if self.enable_annotations and self.annotations:
            painter.setPen(QColor(200, 200, 100))
            for x, y, text, _ in self.annotations:
                # Convert GL coordinates to screen coordinates
                x_norm = (x / 200.0) * (w - left_margin) + left_margin
                y_norm = h - bottom_margin - ((y - self.min_val) / (self.max_val - self.min_val)) * (h - bottom_margin)
                if 0 <= x_norm < w and 0 <= y_norm < h:
                    # Show both annotation text and value
                    value_text = f"{text}: {y:.6g}"
                    painter.drawText(int(x_norm) + 5, int(y_norm) - 10, value_text)
        
        painter.end()
    
    def set_statistics(self, stats_dict):
        """Update statistics for display."""
        self.stats_display = stats_dict
        self.update()

    def initializeGL(self):
        glClearColor(0.06, 0.07, 0.10, 1.0)
        glEnable(GL_LINE_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)

    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT)
        width, height = self.width(), self.height()
        
        # Dynamic Ortho Projection
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(0, 200, self.min_val, self.max_val, -1, 1)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        # Draw Grid
        glColor3f(0.15, 0.16, 0.20)
        glBegin(GL_LINES)
        for x in range(0, 201, 20):
            glVertex2f(x, self.min_val)
            glVertex2f(x, self.max_val)
        step = (self.max_val - self.min_val) / 5
        for y in np.arange(self.min_val, self.max_val + step/2, step):
            glVertex2f(0, y)
            glVertex2f(200, y)
        glEnd()

        # Plot Channel A (Green) - only if enabled
        if self.enable_a:
            glColor3f(0.0, 1.0, 0.5)
            glLineWidth(2.0)
            glBegin(GL_LINE_STRIP)
            for i, val in enumerate(self.data_a):
                if np.isfinite(val): glVertex2f(i, val)
            glEnd()

        # Plot Channel B (Cyan) - only if enabled
        if self.enable_b:
            glColor3f(0.0, 0.85, 1.0)
            glLineWidth(2.0)
            glBegin(GL_LINE_STRIP)
            for i, val in enumerate(self.data_b):
                if np.isfinite(val): glVertex2f(i, val)
            glEnd()
        
        # Draw Annotations
        if self.enable_annotations:
            glLineWidth(1.0)
            for x, y, text, color in self.annotations:
                # Draw vertical line at annotation point
                glColor3f(*color)
                glBegin(GL_LINES)
                glVertex2f(x, self.min_val)
                glVertex2f(x, self.max_val)
                glEnd()
                # Draw marker point
                glPointSize(8.0)
                glBegin(GL_POINTS)
                glVertex2f(x, y)
                glEnd()
        
        # Render text labels using QPainter
        self.render_labels()

# =============================================================================
# MAIN APPLICATION WINDOW
# =============================================================================
class ADCMT7352GUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADCMT 7352A/E Controller (ADC Lang)")
        self.resize(1000, 700)
        self.inst = None
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_readings)
        self.is_continuous = False
        self.use_mock = False
        self.default_digits = 2  # 4½ digits (RE4)
        self.init_ui()
        self.statusBar().showMessage("Ready. Select device and click Connect.")
        
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QHBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # Left panel for settings and controls
        left_panel = self.create_left_panel()
        left_panel.setFixedWidth(280)
        main_layout.addWidget(left_panel)

        # Right panel for tabs (visualization and console)
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self.tabs = QTabWidget()
        
        # Tab 1: OpenGL Plot
        self.tab_plot = QWidget()
        plot_layout = QVBoxLayout(self.tab_plot)
        
        # Create plot widget first
        self.gl_plot = DMMGLPlot()
        
        # Button toolbar
        btn_layout = QHBoxLayout()
        self.btn_auto_zoom = QPushButton("Auto Zoom")
        self.btn_auto_zoom.clicked.connect(self.gl_plot.reset_zoom)
        btn_layout.addWidget(self.btn_auto_zoom)
        btn_layout.addStretch()
        plot_layout.addLayout(btn_layout)
        
        plot_layout.addWidget(self.gl_plot, 1)
        self.tabs.addTab(self.tab_plot, "Live Plot")
        
        # Tab 2: Measurements & Statistics
        self.tab_meas = self.create_measurements_tab()
        self.tabs.addTab(self.tab_meas, "Measurements")
        
        # Tab 3: ADC Console
        self.tab_console = self.create_console_tab()
        self.tabs.addTab(self.tab_console, "ADC Console")
        
        right_layout.addWidget(self.tabs)
        main_layout.addWidget(right_panel, 1)

    def create_left_panel(self):
        """Create the left panel with all settings and controls."""
        panel = QWidget()
        panel.setStyleSheet("#leftPanel { background-color: #0d1117; }")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        # Title
        title = QLabel("◈ ADCMT 7352A")
        title.setStyleSheet("font-size: 16px; font-weight: bold; color: #c9d1d9;")
        layout.addWidget(title)

        subtitle = QLabel("Digital Multimeter [ADC mode]")
        subtitle.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(subtitle)

        # Status indicator
        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setStyleSheet("color: #f85149; font-weight: bold;")
        self.status_dot = QLabel("●")
        self.status_dot.setStyleSheet("color: #f85149; font-size: 14px;")

        status_bar = QWidget()
        sb_layout = QHBoxLayout(status_bar)
        sb_layout.addWidget(self.status_dot)
        sb_layout.addWidget(self.status_label)
        sb_layout.addStretch()
        layout.addWidget(status_bar)

        # Connection settings card
        layout.addWidget(self.create_connection_card())
        
        # Channel A configuration card
        layout.addWidget(self.create_channel_card("Channel A (DSP1)", "A"))
        
        # Digits selection card
        layout.addWidget(self.create_digits_card())
        
        # Channel B configuration card  
        layout.addWidget(self.create_channel_card("Channel B (DSP2)", "B"))

        # LCD Displays card
        layout.addWidget(self.create_display_card())

        # Control buttons card
        layout.addWidget(self.create_control_card())

        layout.addStretch()
        return panel

    def create_connection_card(self):
        """Create the connection settings card."""
        group = QGroupBox("CONNECTION")
        group.setStyleSheet("""
            QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 8px; padding-top: 6px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; font-weight: bold; }
        """)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 12, 10, 10)

        # Device selection
        device_layout = QHBoxLayout()
        device_layout.addWidget(QLabel("Device:"))
        self.cb_device = QComboBox()
        self.cb_device.addItems(["Real Device (VISA)", "Mock Device (Testing)"])
        self.cb_device.currentIndexChanged.connect(self.on_device_changed)
        device_layout.addWidget(self.cb_device)
        layout.addLayout(device_layout)

        # Resource string
        res_layout = QHBoxLayout()
        res_layout.addWidget(QLabel("Resource:"))
        self.res_input = QLineEdit("TCPIP0::10.1.1.138::5025::SOCKET")
        self.res_input.setPlaceholderText("VISA Resource String")
        res_layout.addWidget(self.res_input, 1)
        layout.addLayout(res_layout)

        # Connect button
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.toggle_connection)
        layout.addWidget(self.btn_connect)

        return group

    def create_channel_card(self, title, channel):
        """Create a channel configuration card."""
        group = QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 8px; padding-top: 6px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; font-weight: bold; }
        """)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 12, 10, 10)

        # Enable checkbox
        cb_enable = QCheckBox("Enable Channel")
        cb_enable.setChecked(channel == "A")
        setattr(self, f"chk_enable_{channel}", cb_enable)
        layout.addWidget(cb_enable)

        # Function selection
        func_layout = QHBoxLayout()
        func_layout.addWidget(QLabel("Function:"))
        cb_func = QComboBox()
        cb_func.addItems(ADC_FUNCS.keys())
        setattr(self, f"cb_func_{channel}", cb_func)
        func_layout.addWidget(cb_func)
        layout.addLayout(func_layout)

        # Function description
        label_display = QLabel()
        label_display.setStyleSheet("color: #888;")
        setattr(self, f"lbl_func_{channel}", label_display)
        layout.addWidget(label_display)
        cb_func.currentTextChanged.connect(
            lambda text: self.update_function_label(channel, text))
        self.update_function_label(channel, cb_func.currentText())

        # Range selection
        range_layout = QHBoxLayout()
        range_layout.addWidget(QLabel("Range:"))
        cb_range = QComboBox()
        cb_range.addItems(ADC_RANGES.keys())
        setattr(self, f"cb_rng_{channel}", cb_range)
        range_layout.addWidget(cb_range)
        layout.addLayout(range_layout)

        # Rate selection
        rate_layout = QHBoxLayout()
        rate_layout.addWidget(QLabel("Rate:"))
        cb_rate = QComboBox()
        cb_rate.addItems(ADC_RATES.keys())
        cb_rate.setCurrentIndex(3)  # Default to SLOW2
        setattr(self, f"cb_rate_{channel}", cb_rate)
        rate_layout.addWidget(cb_rate)
        layout.addLayout(rate_layout)

        # Trigger selection
        trig_layout = QHBoxLayout()
        trig_layout.addWidget(QLabel("Trigger:"))
        cb_trig = QComboBox()
        cb_trig.addItems(ADC_TRIGS.keys())
        setattr(self, f"cb_trig_{channel}", cb_trig)
        trig_layout.addWidget(cb_trig)
        layout.addLayout(trig_layout)

        return group

    def create_digits_card(self):
        """Create the digits selection card."""
        group = QGroupBox("DIGITS")
        group.setStyleSheet("""
            QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 8px; padding-top: 6px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; font-weight: bold; }
        """)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 12, 10, 10)

        # Digits selection
        digits_layout = QHBoxLayout()
        digits_layout.addWidget(QLabel("Digits:"))
        cb_digits = QComboBox()
        cb_digits.addItems(DIGITS_DISP)
        cb_digits.setCurrentIndex(self.default_digits)
        self.cb_digits = cb_digits
        digits_layout.addWidget(cb_digits)
        layout.addLayout(digits_layout)

        return group

    def create_display_card(self):
        """Create the LCD display card."""
        group = QGroupBox("LIVE READINGS")
        group.setStyleSheet("""
            QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 8px; padding-top: 6px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; font-weight: bold; }
        """)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 12, 10, 10)

        # Channel A display
        a_layout = QVBoxLayout()
        a_layout.addWidget(QLabel("Channel A:"))
        self.lbl_a = QLabel("--")
        self.lbl_a.setStyleSheet("font-family: monospace; font-size: 16px; color: #00ff80; padding: 8px; background-color: #0d1117; border: 1px solid #30363d; border-radius: 3px;")
        self.lbl_a.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_a.setMinimumHeight(50)
        a_layout.addWidget(self.lbl_a)
        layout.addLayout(a_layout)

        # Channel B display
        b_layout = QVBoxLayout()
        b_layout.addWidget(QLabel("Channel B:"))
        self.lbl_b = QLabel("--")
        self.lbl_b.setStyleSheet("font-family: monospace; font-size: 16px; color: #00d9ff; padding: 8px; background-color: #0d1117; border: 1px solid #30363d; border-radius: 3px;")
        self.lbl_b.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.lbl_b.setMinimumHeight(50)
        b_layout.addWidget(self.lbl_b)
        layout.addLayout(b_layout)

        return group

    def create_control_card(self):
        """Create the control buttons card."""
        group = QGroupBox("CONTROLS")
        group.setStyleSheet("""
            QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 8px; padding-top: 6px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; font-weight: bold; }
        """)
        layout = QVBoxLayout(group)
        layout.setContentsMargins(10, 12, 10, 10)

        # Apply settings button
        self.btn_apply = QPushButton("Apply Settings")
        self.btn_apply.clicked.connect(self.apply_settings)
        layout.addWidget(self.btn_apply)

        # Command buttons
        cmd_layout = QHBoxLayout()
        self.btn_init = QPushButton("Initiate (INI)")
        self.btn_init.clicked.connect(lambda: self.send_cmd("INI"))
        cmd_layout.addWidget(self.btn_init)

        self.btn_abort = QPushButton("Abort (ABO)")
        self.btn_abort.clicked.connect(lambda: self.send_cmd("ABO"))
        cmd_layout.addWidget(self.btn_abort)
        layout.addLayout(cmd_layout)

        # Continuous read checkbox
        self.chk_cont = QCheckBox("Continuous Read")
        self.chk_cont.stateChanged.connect(self.toggle_continuous)
        layout.addWidget(self.chk_cont)

        return group

    def create_channel_tab(self, title, channel):
        """Create a configuration tab for a channel."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        grp = QGroupBox(title)
        form = QFormLayout()
        
        # Enable/Disable checkbox
        cb_enable = QCheckBox("Enable Channel")
        cb_enable.setChecked(channel == "A")
        setattr(self, f"chk_enable_{channel}", cb_enable)
        form.addRow("Enabled:", cb_enable)
        
        # Function selection
        cb_func = QComboBox()
        cb_func.addItems(ADC_FUNCS.keys())
        # Set meaningful display text
        cb_func.setMaxVisibleItems(10)
        setattr(self, f"cb_func_{channel}", cb_func)
        form.addRow("Function:", cb_func)
        
        # Add user-readable label display
        label_display = QLabel()
        label_display.setStyleSheet("color: #888;")
        setattr(self, f"lbl_func_{channel}", label_display)
        form.addRow("Description:", label_display)
        cb_func.currentTextChanged.connect(
            lambda text: self.update_function_label(channel, text))
        self.update_function_label(channel, cb_func.currentText())
        
        # Range selection
        cb_range = QComboBox()
        cb_range.addItems(ADC_RANGES.keys())
        setattr(self, f"cb_rng_{channel}", cb_range)
        form.addRow("Range:", cb_range)
        
        # Rate selection
        cb_rate = QComboBox()
        cb_rate.addItems(ADC_RATES.keys())
        setattr(self, f"cb_rate_{channel}", cb_rate)
        form.addRow("Rate:", cb_rate)
        
        # Trigger selection
        cb_trig = QComboBox()
        cb_trig.addItems(ADC_TRIGS.keys())
        setattr(self, f"cb_trig_{channel}", cb_trig)
        form.addRow("Trigger:", cb_trig)
        
        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        
        return widget
    
    def update_function_label(self, channel, func_code):
        """Update the user-readable function label."""
        label_widget = getattr(self, f"lbl_func_{channel}", None)
        if label_widget and func_code in FUNC_LABELS:
            label_widget.setText(FUNC_LABELS[func_code])
    
    def create_measurements_tab(self):
        """Create the measurements and statistics tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Statistics display
        stats_grp = QGroupBox("Data Statistics")
        stats_layout = QFormLayout()
        
        self.lbl_stat_min = QLabel("N/A")
        self.lbl_stat_max = QLabel("N/A")
        self.lbl_stat_avg = QLabel("N/A")
        self.lbl_stat_med = QLabel("N/A")
        self.lbl_stat_std = QLabel("N/A")
        self.lbl_stat_p10 = QLabel("N/A")
        self.lbl_stat_p90 = QLabel("N/A")
        
        stats_layout.addRow("Minimum:", self.lbl_stat_min)
        stats_layout.addRow("Maximum:", self.lbl_stat_max)
        stats_layout.addRow("Average:", self.lbl_stat_avg)
        stats_layout.addRow("Median:", self.lbl_stat_med)
        stats_layout.addRow("Std Dev:", self.lbl_stat_std)
        stats_layout.addRow("10th %ile:", self.lbl_stat_p10)
        stats_layout.addRow("90th %ile:", self.lbl_stat_p90)
        
        stats_grp.setLayout(stats_layout)
        layout.addWidget(stats_grp)
        
        # Annotation options
        annot_grp = QGroupBox("Graph Annotations")
        annot_layout = QFormLayout()
        
        self.chk_annot_enable = QCheckBox("Enable Annotations")
        self.chk_annot_enable.stateChanged.connect(self.toggle_annotations)
        annot_layout.addRow(self.chk_annot_enable)
        
        annot_grp.setLayout(annot_layout)
        layout.addWidget(annot_grp)
        
        # Statistics checkboxes for annotation
        annot_select_grp = QGroupBox("Annotation Sources")
        annot_select_layout = QFormLayout()
        
        self.chk_annot_min = QCheckBox("Mark Minimum")
        self.chk_annot_max = QCheckBox("Mark Maximum")
        self.chk_annot_avg = QCheckBox("Mark Average")
        
        annot_select_layout.addRow(self.chk_annot_min)
        annot_select_layout.addRow(self.chk_annot_max)
        annot_select_layout.addRow(self.chk_annot_avg)
        
        annot_select_grp.setLayout(annot_select_layout)
        layout.addWidget(annot_select_grp)
        
        layout.addStretch()
        return widget
    
    def create_console_tab(self):
        """Create the ADC console tab for debugging and manual commands."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        # Command input area
        cmd_layout = QHBoxLayout()
        
        cmd_layout.addWidget(QLabel("CMD:"))
        
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText("Enter ADC command...")
        self.cmd_edit.returnPressed.connect(self.send_console_cmd)
        cmd_layout.addWidget(self.cmd_edit, 1)
        
        self.send_btn = QPushButton("SEND")
        self.send_btn.clicked.connect(self.send_console_cmd)
        cmd_layout.addWidget(self.send_btn)
        
        self.clear_console_btn = QPushButton("CLEAR")
        self.clear_console_btn.clicked.connect(self.clear_console)
        cmd_layout.addWidget(self.clear_console_btn)
        
        self.rst_btn = QPushButton("*RST")
        self.rst_btn.setStyleSheet("color: #f85149;")
        self.rst_btn.clicked.connect(lambda: self.send_cmd("*RST"))
        cmd_layout.addWidget(self.rst_btn)
        
        self.cls_btn = QPushButton("*CLS")
        self.cls_btn.setStyleSheet("color: #d29922;")
        self.cls_btn.clicked.connect(lambda: self.send_cmd("*CLS"))
        cmd_layout.addWidget(self.cls_btn)
        
        layout.addLayout(cmd_layout)

        # Console output area
        self.console_text = QTextEdit()
        self.console_text.setReadOnly(True)
        self.console_text.setStyleSheet("""
            QTextEdit { background-color: #0d1117; color: #c9d1d9; 
                       font-family: Consolas, monospace; font-size: 10px; }
        """)
        layout.addWidget(self.console_text)

        # Initialize console with info
        self.log_console("ADCMT 7352A [ADC mode, \\r\\n termination]", "info")
        self.log_console("Free-run: instrument streams data → bare read() used for acquisition.", "info")

        return widget
    
    def on_device_changed(self, index):
        """Handle device selection change."""
        self.use_mock = (index == 1)
        self.res_input.setEnabled(index == 0)
    
    def toggle_annotations(self, state):
        """Enable/disable annotations on the plot."""
        self.gl_plot.enable_annotations = (state == 2)  # Qt.CheckState.Checked
        if not self.gl_plot.enable_annotations:
            self.gl_plot.clear_annotations()
        self.gl_plot.update()
    
    def update_statistics(self):
        """Calculate and display statistics."""
        data_a = self.gl_plot.data_a[self.gl_plot.data_a != 0]
        data_b = self.gl_plot.data_b[self.gl_plot.data_b != 0]
        
        # Use channel A for now
        valid_data = data_a[np.isfinite(data_a)]
        
        if len(valid_data) > 0:
            self.lbl_stat_min.setText(f"{np.min(valid_data):.6f}")
            self.lbl_stat_max.setText(f"{np.max(valid_data):.6f}")
            self.lbl_stat_avg.setText(f"{np.mean(valid_data):.6f}")
            self.lbl_stat_med.setText(f"{np.median(valid_data):.6f}")
            self.lbl_stat_std.setText(f"{np.std(valid_data):.6f}")
            self.lbl_stat_p10.setText(f"{np.percentile(valid_data, 10):.6f}")
            self.lbl_stat_p90.setText(f"{np.percentile(valid_data, 90):.6f}")
            
            # Add annotations if enabled
            if self.gl_plot.enable_annotations:
                self.gl_plot.clear_annotations()
                if self.chk_annot_min.isChecked():
                    min_idx = np.argmin(valid_data)
                    self.gl_plot.add_annotation(min_idx, np.min(valid_data), 
                                               "Min", (1.0, 0.0, 0.0))
                if self.chk_annot_max.isChecked():
                    max_idx = np.argmax(valid_data)
                    self.gl_plot.add_annotation(max_idx, np.max(valid_data), 
                                               "Max", (0.0, 1.0, 0.0))
                if self.chk_annot_avg.isChecked():
                    avg_val = np.mean(valid_data)
                    self.gl_plot.add_annotation(100, avg_val, "Avg", (1.0, 1.0, 0.0))

    # =============================================================================
    # CONSOLE & DEBUGGING METHODS
    # =============================================================================
    def log_console(self, text, tag="info"):
        """Log a message to the console with timestamp and color coding."""
        if not hasattr(self, 'console_text') or self.console_text is None:
            return
        
        colors = {
            "info": "#8b949e", 
            "cmd": "#58a6ff", 
            "resp": "#c9d1d9",
            "err": "#f85149", 
            "ok": "#3fb950"
        }
        color = colors.get(tag, "#c9d1d9")
        
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        
        # Append to console with color styling
        current_text = self.console_text.toPlainText()
        new_text = f"[{timestamp}] {text}\n"
        self.console_text.setPlainText(current_text + new_text)
        
        # Auto-scroll to bottom
        scrollbar = self.console_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def send_console_cmd(self):
        """Send a command from the console input."""
        cmd = self.cmd_edit.text().strip()
        if not cmd:
            return
        
        if not self.inst:
            self.log_console("Not connected", "err")
            return
        
        self.log_console(f">> {cmd}", "cmd")
        
        try:
            if cmd.endswith("?"):
                resp = self.inst.query(cmd)
                if resp:
                    self.log_console(f"<< {resp}", "resp")
                else:
                    self.log_console("<< (empty)", "err")
            else:
                self.inst.write(cmd)
                # Check for errors
                err_resp = self.inst.query("ERR?")
                if err_resp and not err_resp.startswith("+000"):
                    self.log_console(f"   ERR? -> {err_resp}", "err")
                else:
                    self.log_console(f"Sent: {cmd}", "ok")
        except Exception as e:
            self.log_console(f"Error: {e}", "err")
        
        self.cmd_edit.clear()
    
    def clear_console(self):
        """Clear the console output."""
        if hasattr(self, 'console_text'):
            self.console_text.clear()
            self.log_console("Console cleared", "info")

    # =============================================================================
    # METRIC NOTATION FORMATTING
    # =============================================================================
    @staticmethod
    def get_unit_for_function(func_code):
        """Return the unit for a given measurement function."""
        # Create reverse mapping from ADC_FUNCS
        voltage_funcs = ["DCV-Ach", "DCV-Bch", "ACV-Ach", "ACV+DC-Ach", "DIODE-Ach"]
        current_funcs = ["DCI-Ach", "DCI-Bch", "ACI-Ach", "ACI+DC-Ach", "ACI-Bch", "ACI+DC-Bch"]
        resistance_funcs = ["2WΩ-Ach", "LP-2WΩ-Ach", "CONT-Ach"]
        temp_funcs = ["TEMP"]
        freq_funcs = ["FREQ-Ach"]
        
        if func_code in voltage_funcs:
            return "V"
        elif func_code in current_funcs:
            return "A"
        elif func_code in resistance_funcs:
            return "Ω"
        elif func_code in temp_funcs:
            return "°C"
        elif func_code in freq_funcs:
            return "Hz"
        return ""

    @staticmethod
    def format_with_metric_prefix(value, unit="", precision=3):
        """Format a number with metric prefixes (n, u, m, k, M, G).
        
        Args:
            value: The numeric value to format
            unit: The unit string (e.g., "V", "A", "Ω")
            precision: Number of significant figures after decimal point
        
        Returns:
            A formatted string like "1.23 mV" or "456 nA"
        """
        if value is None or not isinstance(value, (int, float)):
            return "N/A"
        
        # Handle zero and very small values
        if abs(value) == 0:
            return f"0 {unit}".strip()
        
        abs_val = abs(value)
        sign = "-" if value < 0 else ""
        
        # Define metric prefixes from largest to smallest
        prefixes = [
            (1e9, "G"),
            (1e6, "M"),
            (1e3, "k"),
            (1, ""),
            (1e-3, "m"),
            (1e-6, "u"),   # micro (u instead of μ for display compatibility)
            (1e-9, "n"),
            (1e-12, "p"),
        ]
        
        # Find the appropriate prefix
        for scale, prefix in prefixes:
            if abs_val >= scale:
                scaled_value = abs_val / scale
                # Format with appropriate precision
                if scaled_value >= 100:
                    formatted = f"{scaled_value:.0f}"
                elif scaled_value >= 10:
                    formatted = f"{scaled_value:.1f}"
                else:
                    formatted = f"{scaled_value:.{precision-1}f}"
                
                result = f"{sign}{formatted} {prefix}{unit}".strip()
                return result
        
        # Fallback for extremely small values
        formatted = f"{abs_val:.{precision}e}"
        return f"{sign}{formatted} {unit}".strip()

    # =============================================================================
    # VISA & COMMAND LOGIC
    # =============================================================================
    def toggle_connection(self):
        if self.inst:
            self.poll_timer.stop()
            self.inst.close()
            self.inst = None
            self.btn_connect.setText("Connect")
            self._update_status(False)
            self.log_console("Disconnected.", "info")
            return

        try:
            if self.use_mock:
                self.inst = MockDMMDevice()
                self.btn_connect.setText("Disconnect")
                self._update_status(True)
                self.log_console("Connected to Mock Device", "ok")
            else:
                rm = pyvisa.ResourceManager()
                self.inst = rm.open_resource(self.res_input.text())
                self.inst.timeout = 2000
                self.inst.read_termination = '\r\n'
                self.inst.write_termination = '\r\n'
                
                # Initialize ADC Mode & Display
                self.send_cmd("H0")      # Disable headers for easier parsing
                self.send_cmd("DE0")     # Disable dual display
                self.send_cmd("DSP!,F1") # Default DCV-Ach
                self.send_cmd(f"{DIGITS_CMD[self.default_digits]}")
                self.send_cmd(f"PR4") # Slow sampling rate
                self.btn_connect.setText("Disconnect")
                self._update_status(True)
                self.log_console(f"Connected to {self.res_input.text()}", "ok")
                
            self.apply_settings()
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            self.inst = None
            self._update_status(False)

    def _update_status(self, connected):
        """Update the connection status indicators."""
        if connected:
            self.status_label.setText("CONNECTED")
            self.status_label.setStyleSheet("color: #3fb950; font-weight: bold;")
            self.status_dot.setStyleSheet("color: #3fb950; font-size: 14px;")
        else:
            self.status_label.setText("DISCONNECTED")
            self.status_label.setStyleSheet("color: #f85149; font-weight: bold;")
            self.status_dot.setStyleSheet("color: #f85149; font-size: 14px;")

    def send_cmd(self, cmd):
        if not self.inst: return
        try:
            self.inst.write(cmd)
            self.log_console(f"Sent: {cmd}", "ok")
        except Exception as e:
            self.log_console(f"Cmd Error: {e}", "err")

    def apply_settings(self):
        if not self.inst: return
        # Map GUI selections to ADC commands
        if self.chk_enable_A.isChecked():
            func_a = self.cb_func_A.currentText()
            self.send_cmd(f"DSP1,{ADC_FUNCS[func_a]}")
            self.send_cmd(f"DSP1,{ADC_RANGES[self.cb_rng_A.currentText()]}")
            self.send_cmd(f"DSP1,{ADC_RATES[self.cb_rate_A.currentText()]}")
            self.send_cmd(f"DSP1,{ADC_TRIGS[self.cb_trig_A.currentText()]}")
            self.send_cmd(f"DSP1,{DIGITS_CMD[self.cb_digits.currentIndex()]}")
        
        if self.chk_enable_B.isChecked():
            func_b = self.cb_func_B.currentText()
            self.send_cmd(f"DSP2,{ADC_FUNCS[func_b]}")
            self.send_cmd(f"DSP2,{ADC_RANGES[self.cb_rng_B.currentText()]}")
            self.send_cmd(f"DSP2,{ADC_RATES[self.cb_rate_B.currentText()]}")
            self.send_cmd(f"DSP2,{ADC_TRIGS[self.cb_trig_B.currentText()]}")
            self.send_cmd(f"DSP2,{DIGITS_CMD[self.cb_digits.currentIndex()]}")
        else: 
            self.send_cmd("DP0")  # Disable second display if Channel B is not enabled
        
        self.log_console("Settings applied.", "ok")

    def toggle_continuous(self, state):
        self.is_continuous = (state == 2)  # Qt.CheckState.Checked
        if self.is_continuous and self.inst:
            self.poll_timer.start(500) # 500ms polling
        else:
            self.poll_timer.stop()

    def poll_readings(self):
        if not self.inst: return
        try:
            self.gl_plot.set_channel_enabled("A", self.chk_enable_A.isChecked())
            self.gl_plot.set_channel_enabled("B", self.chk_enable_B.isChecked())
            
            resp_a = self.inst.query("DSP1,MD?").strip()
            resp_b = self.inst.query("DSP2,MD?").strip()
            
            fk_a = _cur_fkey(self.cb_func_A.currentText())
            fk_b = _cur_fkey(self.cb_func_B.currentText())
            val_a, main_h_a, sub_h_a, is_ol_a, disp_a, desc_a = parse_adc_response(resp_a, fk_a)
            val_b, main_h_b, sub_h_b, is_ol_b, disp_b, desc_b = parse_adc_response(resp_b, fk_b)
            
            if self.chk_enable_A.isChecked():
                self.lbl_a.setText(disp_a)
            else:
                self.lbl_a.setText("--")
            
            if self.chk_enable_B.isChecked():
                self.lbl_b.setText(disp_b)
            else:
                self.lbl_b.setText("--")
            
            self.gl_plot.update_readings(val_a if not is_ol_a else OVERLOAD_THRESHOLD * 1.1,
                                         val_b if not is_ol_b else OVERLOAD_THRESHOLD * 1.1)
            self.update_statistics()
                
        except Exception as e:
            self.log_console(f"Read Error: {e}", "err")
            self.poll_timer.stop()
            self.chk_cont.setChecked(False)

# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ADCMT7352GUI()
    window.show()
    sys.exit(app.exec_())