import sys
import re
import csv
import time
import pyvisa
import numpy as np
from datetime import datetime

from PyQt5.QtCore import QTimer, Qt, QPoint, QPointF
from PyQt5.QtGui import (QPainter, QColor, QFont, QFontMetrics, QPen,
                          QBrush, QLinearGradient, QPolygonF)
from PyQt5.QtWidgets import (
    QApplication, QMainWindow, QVBoxLayout, QHBoxLayout,
    QWidget, QPushButton, QComboBox, QLabel, QGroupBox,
    QLineEdit, QStatusBar, QFormLayout, QCheckBox, QMessageBox,
    QOpenGLWidget, QTabWidget, QSpinBox, QDoubleSpinBox, QListWidget,
    QListWidgetItem, QTextEdit, QFileDialog, QSizePolicy, QFrame,
    QScrollArea, QSplitter
)
from OpenGL.GL import *

from mock import MockDMMDevice

# =============================================================================
# COLLAPSIBLE GROUP BOX WIDGET
# =============================================================================
class CollapsibleSection(QGroupBox):
    """Collapsible group box with built-in toggle from title click."""
    
    def __init__(self, title="", parent=None):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(True)
        self._toggle_style()
        self.toggled.connect(self._toggle_style)
        
    def _toggle_style(self):
        """Update title with collapse/expand indicator."""
        state = "▼" if self.isChecked() else "▶"
        orig_title = self.title().rstrip(" ▼▶ ")
        self.setTitle(f"{orig_title} {state}")

# =============================================================================

ADC_FUNCS = {
    "DCV-Ach": "F1", "ACV-Ach": "F2", "2WΩ-Ach": "F3", "DCI-Ach": "F5",
    "ACI-Ach": "F6", "ACV+DC-Ach": "F7", "ACI+DC-Ach": "F8",
    "DCV-Bch": "F12", "DIODE-Ach": "F13", "LP-2WΩ-Ach": "F20",
    "CONT-Ach": "F22", "DCI-Bch": "F35", "ACI-Bch": "F36",
    "ACI+DC-Bch": "F37", "TEMP": "F40", "FREQ-Ach": "F50"
}

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
ADC_RATES  = {"FAST": "PR1", "MED": "PR2", "SLOW1": "PR3", "SLOW2": "PR4"}
ADC_TRIGS  = {"IMM": "TRS0", "MAN": "TRS1", "EXT": "TRS2", "BUS": "TRS3"}

DIGITS_CMD  = ["RE3", "RE4", "RE5"]
DIGITS_DISP = ["3½", "4½", "5½"]

OVERLOAD_THRESHOLD = 9.9e+9

SUB_LABELS = {
    "_": "", "O": " [OL]", "H": " [HI]", "P": " [PASS]",
    "L": " [LO]", "N": " [NULL]", "S": " [SCALE]", "B": " [dB]",
    "W": " [dBm]", "E": " [Err]", "M": " [MAX]", "I": " [MIN]",
    "A": " [AVG]", "D": " [CALC2]",
}

HDR_LABELS = {
    "DCV": "DC Volt", "ACV": "AC Volt", "ADV": "AC+DC Volt",
    "R2W": "2W Res",  "R2L": "LP-2W",  "DCI": "DC Curr",
    "ACI": "AC Curr", "ADI": "AC+DC Curr", "FRQ": "Freq",
    "DOD": "Diode",   "RCT": "Cont",   "TC_": "Temp",
    "BDV": "DC Volt B", "BDI": "DC Curr B", "BAI": "AC Curr B", "BCI": "AC+DC Curr B",
}

FUNCTIONS = {
    "F1":  ("DCV  Ach",          "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),("20 V","R5"),("200 V","R6"),("1000 V","R7")], "DCV"),
    "F2":  ("ACV  Ach",          "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),("20 V","R5"),("200 V","R6"),("700 V","R7")], "ACV"),
    "F7":  ("ACV AC+DC  Ach",    "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),("20 V","R5"),("200 V","R6"),("700 V","R7")], "ADV"),
    "F3":  ("2W Ω  Ach",         "Ω",
            [("Auto","R0"),("200 Ω","R3"),("2 kΩ","R4"),("20 kΩ","R5"),
             ("200 kΩ","R6"),("2 MΩ","R7"),("20 MΩ","R8"),("200 MΩ","R9")], "R2W"),
    "F20": ("LP-2W Ω  Ach",      "Ω",
            [("Auto","R0"),("200 Ω","R3"),("2 kΩ","R4"),("20 kΩ","R5"),
             ("200 kΩ","R6"),("2 MΩ","R7"),("20 MΩ","R8")], "R2L"),
    "F5":  ("DCI  Ach",          "A",
            [("Auto","R0"),("2000 nA","R1"),("20 µA","R2"),("200 µA","R3"),
             ("2 mA","R4"),("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "DCI"),
    "F6":  ("ACI  Ach",          "A",
            [("Auto","R0"),("200 µA","R3"),("2 mA","R4"),
             ("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "ACI"),
    "F8":  ("ACI AC+DC  Ach",    "A",
            [("Auto","R0"),("200 µA","R3"),("2 mA","R4"),
             ("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "ADI"),
    "F50": ("FREQ  Ach",         "Hz", [("Auto","R0")], "FRQ"),
    "F13": ("DIODE  Ach",        "V",  [("—","")],      "DOD"),
    "F22": ("CONT  Ach",         "Ω",  [("—","")],      "RCT"),
    "F40": ("TEMP",              "°C", [("—","")],      "TC_"),
    "F12": ("DCV  Bch",          "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),("20 V","R5"),("200 V","R6")], "BDV"),
    "F35": ("DCI  Bch",          "A",  [("10 A","R8")], "BDI"),
    "F36": ("ACI  Bch",          "A",  [("10 A","R8")], "BAI"),
    "F37": ("ACI AC+DC  Bch",    "A",  [("10 A","R8")], "BCI"),
}

# =============================================================================
# RESPONSE PARSER  (§6.6.2)
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
        main_h, sub_h, num_s = m.group(1), m.group(2), m.group(3)
    else:
        nm = _NUM_RE.match(raw)
        num_s = nm.group(1) if nm else raw
    try:
        val = float(num_s)
    except ValueError:
        return 0.0, main_h, sub_h, False, raw, raw
    is_ol = val >= OVERLOAD_THRESHOLD
    unit  = FUNCTIONS.get(func_key, ("","V","","DCV"))[1]
    disp  = "OVERLOAD" if is_ol else _si_fmt(val, unit)
    desc  = HDR_LABELS.get(main_h, main_h) + SUB_LABELS.get(sub_h, f" [{sub_h}]")
    return val, main_h, sub_h, is_ol, disp, desc


# =============================================================================
# COLOUR PALETTE  (GitHub-dark inspired)
# =============================================================================
CLR_BG      = (0.06, 0.07, 0.10)
CLR_GRID    = (0.14, 0.15, 0.20)
CLR_ZERO    = (0.22, 0.24, 0.30)
CLR_CH_A    = (0.00, 1.00, 0.50)   # green
CLR_CH_B    = (0.00, 0.85, 1.00)   # cyan
CLR_M1      = (1.00, 0.75, 0.00)   # gold   – Marker 1
CLR_M2      = (1.00, 0.35, 0.20)   # orange – Marker 2
CLR_CROSSH  = (0.45, 0.55, 0.65)   # dim steel


# =============================================================================
# OPENGL LIVE PLOT WIDGET
# =============================================================================
class DMMGLPlot(QOpenGLWidget):
    """
    Live rolling-buffer plot.

    Interactions
    ─────────────
    • Scroll wheel       → Y-zoom toward cursor
    • Ctrl + Scroll      → X-zoom (sample window width)
    • Left-click         → place Marker 1
    • Right-click        → place Marker 2
    • Middle-click drag  → pan
    • Double-click       → reset zoom / pan
    """

    def __init__(self, parent=None):
        super().__init__(parent)

        # ── data buffers ──────────────────────────────────────────────
        self.buf_size = 200
        self.data_a   = np.full(self.buf_size, np.nan)
        self.data_b   = np.full(self.buf_size, np.nan)
        self.times: list[float] = []   # elapsed seconds from start
        self._t0: float | None = None  # capture start time

        # ── view limits ───────────────────────────────────────────────
        self.y_min = -1.0
        self.y_max =  1.0
        self._y_min_auto = -1.0
        self._y_max_auto =  1.0
        
        # X-axis (time-based)
        self.x_min = 0.0
        self.x_max = 10.0
        self._x_min_auto = 0.0
        self._x_max_auto = 10.0
        self._x_auto_scale = True  # auto-extend X as new data arrives
        self.x_visible_width = None  # if set, limit visible window

        # ── zoom / pan ────────────────────────────────────────────────
        self.zoom_y   = 1.0    # Y zoom factor (>1 = zoomed in)
        self.pan_y    = 0.0    # Y pan offset in data units
        self.zoom_x   = 1.0    # X zoom factor
        self._pan_origin: QPoint | None = None
        self._pan_x0    = 0.0
        self._pan_y0    = 0.0

        # ── channel visibility ────────────────────────────────────────
        self.enable_a = True
        self.enable_b = False

        # ── display options ───────────────────────────────────────────
        self.show_fill      = False   # fill area under curve
        self.show_crosshair = True
        self.show_grid      = True
        self.line_width     = 2.0

        # ── crosshair ────────────────────────────────────────────────
        self._mouse_pos: QPoint | None = None

        # ── markers ──────────────────────────────────────────────────
        self.marker1: tuple[float, float] | None = None   # (sample_idx, value)
        self.marker2: tuple[float, float] | None = None
        self.marker_callback = None    # called when markers change

        # ── annotations ──────────────────────────────────────────────
        self.annotations: list[tuple] = []   # (x, y, text, rgb)
        self.enable_annotations = False

        # ── misc ──────────────────────────────────────────────────────
        self.x_label = "Samples"
        self.y_label = "Value"
        self.y_unit  = ""

        self.setMinimumHeight(200)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)

    # ------------------------------------------------------------------ #
    #  margins / coordinate helpers
    # ------------------------------------------------------------------ #
    ML, MR, MT, MB = 60, 12, 12, 30   # left / right / top / bottom margin px

    def _plot_rect(self):
        """Return (px, py, pw, ph) of the inner plot area in screen pixels."""
        w, h = self.width(), self.height()
        return self.ML, self.MT, w - self.ML - self.MR, h - self.MT - self.MB

    def _screen_to_data(self, sx, sy):
        """Convert screen pixel → (time_sec_float, data_value_float)."""
        px, py, pw, ph = self._plot_rect()
        x_range = self.x_max - self.x_min
        xi = self.x_min + ((sx - px) / pw) * x_range if x_range > 0 else self.x_min
        yv = self.y_min + (1.0 - (sy - py) / ph) * (self.y_max - self.y_min)
        return xi, yv

    def _data_to_screen(self, xi, yv):
        """Convert (time_sec, data_value) → screen pixel (sx, sy)."""
        px, py, pw, ph = self._plot_rect()
        x_range = self.x_max - self.x_min
        sx = px + ((xi - self.x_min) / x_range) * pw if x_range > 0 else px
        sy = py + ph * (1.0 - (yv - self.y_min) / (self.y_max - self.y_min))
        return sx, sy

    def _visible_time_range(self):
        """Visible time range in seconds."""
        w = (self.x_max - self.x_min) / self.zoom_x if self.zoom_x > 0 else (self.x_max - self.x_min)
        return max(0.1, w)

    # ------------------------------------------------------------------ #
    #  public API
    # ------------------------------------------------------------------ #
    def set_buffer_size(self, n: int):
        n = max(10, n)
        self.data_a = np.full(n, np.nan)
        self.data_b = np.full(n, np.nan)
        self.buf_size = n
        self.times.clear()
        self._t0 = None
        self._x_min_auto = 0.0
        self._x_max_auto = 10.0
        self.x_min, self.x_max = 0.0, 10.0
        self.update()

    def set_channel_enabled(self, channel, enabled):
        if channel == "A": self.enable_a = enabled
        else:              self.enable_b = enabled
        self.update()

    def update_readings(self, val_a, val_b, timestamp: float | None = None):
        """Update with new readings. timestamp is elapsed seconds from capture start."""
        if self._t0 is None:
            self._t0 = time.time()
        if timestamp is None:
            timestamp = time.time() - self._t0
        
        # Shift existing data to make room for new point (rolling window)
        self.data_a = np.roll(self.data_a, -1)
        self.data_b = np.roll(self.data_b, -1)
        self.data_a[-1] = val_a
        self.data_b[-1] = val_b
        
        # Track times for X axis
        self.times.append(timestamp)
        if len(self.times) > self.buf_size:
            self.times = self.times[-self.buf_size:]
        
        # Auto-scale X axis: extend to show all data left-to-right
        if self._x_auto_scale and self.times:
            self._x_min_auto = self.times[0]
            self._x_max_auto = self.times[-1]
            # Apply zoom to visible window
            if self.x_visible_width:
                self.x_max = self.x_min + self.x_visible_width
            else:
                self.x_max = self._x_max_auto + 1  # small margin
            self.x_min = self._x_min_auto
        
        self._recalc_auto_range()
        self._apply_zoom_pan()
        self.update()

    def reset_zoom(self):
        self.zoom_y = 1.0
        self.zoom_x = 1.0
        self.pan_y  = 0.0
        self.x_visible_width = None
        if self._x_auto_scale and self.times:
            self.x_min = self._x_min_auto
            self.x_max = self._x_max_auto
        self._apply_zoom_pan()
        self.update()

    def set_auto_scale_x(self, enabled: bool):
        """Enable/disable X-axis auto-scaling."""
        self._x_auto_scale = enabled
        if enabled:
            self.reset_zoom()

    def set_visible_time_window(self, seconds: float | None):
        """Set visible time window width in seconds. None = show all."""
        self.x_visible_width = seconds
        if self._x_auto_scale and self.times:
            if seconds:
                self.x_max = self.x_min + seconds
            else:
                self.x_max = self._x_max_auto
        self.update()

    def clear_data(self):
        self.data_a[:] = np.nan
        self.data_b[:] = np.nan
        self.times.clear()
        self._t0 = None
        self._x_min_auto = 0.0
        self._x_max_auto = 10.0
        self.x_min, self.x_max = 0.0, 10.0
        self.marker1 = None
        self.marker2 = None
        if self.marker_callback: self.marker_callback()
        self.update()

    def add_annotation(self, x, y, text, color=(1.0, 1.0, 1.0)):
        self.annotations.append((x, y, text, color))
        self.update()

    def clear_annotations(self):
        self.annotations.clear()
        self.update()

    # ------------------------------------------------------------------ #
    #  internal range helpers
    # ------------------------------------------------------------------ #
    def _recalc_auto_range(self):
        vals = []
        if self.enable_a: vals.append(self.data_a)
        if self.enable_b: vals.append(self.data_b)
        if not vals:
            self._y_min_auto, self._y_max_auto = -1.0, 1.0
            return
        all_v = np.concatenate(vals)
        valid = all_v[np.isfinite(all_v)]
        if len(valid) == 0:
            self._y_min_auto, self._y_max_auto = -1.0, 1.0
            return
        mn, mx = float(np.min(valid)), float(np.max(valid))
        mg = (mx - mn) * 0.12 if mx != mn else abs(mn) * 0.1 + 0.5
        self._y_min_auto = mn - mg
        self._y_max_auto = mx + mg

    def _apply_zoom_pan(self):
        # Y axis
        cy = (self._y_min_auto + self._y_max_auto) / 2
        hy = (self._y_max_auto - self._y_min_auto) / 2 / self.zoom_y
        self.y_min = cy - hy + self.pan_y
        self.y_max = cy + hy + self.pan_y
        
        # X axis - apply zoom centered on auto-scaled range
        if self.times:
            x_span = self._x_max_auto - self._x_min_auto
            if x_span > 0:
                # Calculate visible width based on zoom
                vis_w = x_span / self.zoom_x
                # Center on the auto-scaled range
                cx = (self._x_min_auto + self._x_max_auto) / 2
                self.x_min = cx - vis_w / 2
                self.x_max = cx + vis_w / 2

    # ------------------------------------------------------------------ #
    #  GL  initialisation / resize
    # ------------------------------------------------------------------ #
    def initializeGL(self):
        r, g, b = CLR_BG
        glClearColor(r, g, b, 1.0)
        glEnable(GL_LINE_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)

    # ------------------------------------------------------------------ #
    #  main paint
    # ------------------------------------------------------------------ #
    def paintGL(self):
        glClear(GL_COLOR_BUFFER_BIT)
        w, h = self.width(), self.height()
        px, py, pw, ph = self._plot_rect()
        
        # Use visible time range for X axis
        x_min, x_max = self.x_min, self.x_max
        if x_max <= x_min:
            x_min, x_max = 0.0, 10.0
        
        # Ortho projection mapped to inner plot rect (time-based X)
        glMatrixMode(GL_PROJECTION)
        glLoadIdentity()
        glOrtho(x_min, x_max, self.y_min, self.y_max, -1, 1)
        # Apply viewport clip to inner rect only
        glViewport(px, h - py - ph, pw, ph)
        glMatrixMode(GL_MODELVIEW)
        glLoadIdentity()

        if self.show_grid:
            self._draw_grid(x_min, x_max)
        self._draw_zero_line(x_min, x_max)
        if self.enable_a: self._draw_channel(self.data_a, CLR_CH_A, x_min, x_max)
        if self.enable_b: self._draw_channel(self.data_b, CLR_CH_B, x_min, x_max)
        if self.enable_annotations: self._draw_annotation_lines(x_min, x_max)
        self._draw_markers(x_min, x_max)

        # Restore full viewport for QPainter overlay
        glViewport(0, 0, w, h)
        self._draw_overlay_painter()

    def _draw_grid(self, x_min, x_max):
        r, g, b = CLR_GRID
        glColor4f(r, g, b, 1.0)
        glLineWidth(1.0)
        glBegin(GL_LINES)
        # Vertical grid lines (time in seconds)
        span = x_max - x_min
        step_x = span / 10 if span else 1
        x = x_min
        while x <= x_max + step_x * 0.01:
            glVertex2f(x, self.y_min)
            glVertex2f(x, self.y_max)
            x += step_x
        # Horizontal grid lines (5 divisions)
        span_y = self.y_max - self.y_min
        step_y = span_y / 5 if span_y else 1
        y = self.y_min
        while y <= self.y_max + step_y * 0.01:
            glVertex2f(x_min, y)
            glVertex2f(x_max, y)
            y += step_y
        glEnd()

    def _draw_zero_line(self, x_min, x_max):
        if self.y_min < 0 < self.y_max:
            r, g, b = CLR_ZERO
            glColor4f(r, g, b, 1.0)
            glLineWidth(1.5)
            glBegin(GL_LINES)
            glVertex2f(x_min, 0); glVertex2f(x_max, 0)
            glEnd()

    def _draw_channel(self, data, color, x_min, x_max):
        r, g, b = color
        n = len(self.times) if self.times else 0
        if n == 0:
            return
        
        # times list contains the last n timestamps, corresponding to the last n elements of data
        # Data is rolled so newest value is at data[-1], oldest at data[-n]
        
        # Fill under curve
        if self.show_fill:
            glColor4f(r, g, b, 0.10)
            glBegin(GL_TRIANGLE_STRIP)
            # Iterate backwards - newest data is at end
            for j in range(n):
                i = len(data) - n + j  # data index
                val = data[i]
                t = self.times[j]
                v = val if np.isfinite(val) else self.y_min
                glVertex2f(t, self.y_min)
                glVertex2f(t, v)
            glEnd()
        
        # Line
        glColor4f(r, g, b, 1.0)
        glLineWidth(self.line_width)
        glBegin(GL_LINE_STRIP)
        for j in range(n):
            i = len(data) - n + j
            val = data[i]
            if np.isfinite(val):
                t = self.times[j]
                glVertex2f(t, val)
            else:
                glEnd(); glBegin(GL_LINE_STRIP)   # break on NaN
        glEnd()

    def _draw_annotation_lines(self, x_min, x_max):
        n = len(self.times) if self.times else len(self.data_a)
        if n == 0:
            return
        time_vals = self.times if self.times else list(range(n))
        glLineWidth(1.0)
        for x, y, text, color in self.annotations:
            glColor4f(*color, 0.8)
            if x < len(time_vals):
                xi = time_vals[int(x)]
                glBegin(GL_LINES)
                glVertex2f(xi, self.y_min); glVertex2f(xi, self.y_max)
                glEnd()
                glPointSize(7.0)
                glBegin(GL_POINTS)
                glVertex2f(xi, y)
                glEnd()

    def _draw_markers(self, x_min, x_max):
        n = len(self.times) if self.times else len(self.data_a)
        if n == 0:
            return
        time_vals = self.times if self.times else list(range(n))
        for marker, color in [(self.marker1, CLR_M1), (self.marker2, CLR_M2)]:
            if marker is None: continue
            mx, my = marker  # now stores time, not index
            r, g, b = color
            glColor4f(r, g, b, 0.9)
            glLineWidth(1.5)
            glEnable(0x0B10)  # GL_LINE_STIPPLE – skip if unsupported
            glBegin(GL_LINES)
            glVertex2f(mx, self.y_min); glVertex2f(mx, self.y_max)
            glEnd()
            glPointSize(10.0)
            glBegin(GL_POINTS)
            glVertex2f(mx, my)
            glEnd()

    # ------------------------------------------------------------------ #
    #  QPainter overlay (axis labels, crosshair, marker readouts, annots)
    # ------------------------------------------------------------------ #
    def _draw_overlay_painter(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)

        px, py, pw, ph = self._plot_rect()
        x_span = self.x_max - self.x_min if self.x_max != self.x_min else 1.0
        y_span = self.y_max - self.y_min if self.y_max != self.y_min else 1.0

        # ── border rect ──────────────────────────────────────────────
        painter.setPen(QPen(QColor(48, 54, 61), 1))
        painter.drawRect(px, py, pw, ph)

        # ── Y-axis tick labels ────────────────────────────────────────
        tick_font = QFont("Consolas", 8)
        painter.setFont(tick_font)
        fm = QFontMetrics(tick_font)
        painter.setPen(QColor(130, 140, 160))
        for i in range(6):
            yv  = self.y_min + i * y_span / 5
            sy  = py + ph * (1.0 - i / 5.0)
            lbl = _si_fmt(yv, self.y_unit) if self.y_unit else f"{yv:.4g}"
            tw  = fm.horizontalAdvance(lbl)
            painter.drawText(px - tw - 4, int(sy) + fm.ascent() // 2, lbl)

        # ── X-axis tick labels (time in seconds) ────────────────────────
        n_ticks = min(10, int(x_span))
        step    = x_span / n_ticks if n_ticks else 1
        painter.setPen(QColor(100, 110, 125))
        t = self.x_min
        while t <= self.x_max + step * 0.01:
            sx = px + int((t - self.x_min) / x_span * pw)
            lbl = f"{t:.2f}s"
            tw = fm.horizontalAdvance(lbl)
            painter.drawText(sx - tw // 2, py + ph + 16, lbl)
            t += step

        # ── axis titles ───────────────────────────────────────────────
        ax_font = QFont("Consolas", 9, QFont.Bold)
        painter.setFont(ax_font)
        painter.setPen(QColor(170, 180, 195))
        painter.drawText(px + pw // 2 - 30, py + ph + 28, "Time (s)")
        painter.save()
        painter.translate(12, py + ph // 2)
        painter.rotate(-90)
        painter.drawText(-30, 0, self.y_label)
        painter.restore()

        # ── channel legend ────────────────────────────────────────────
        leg_y = py + 6
        leg_x = px + pw - 130
        if self.enable_a:
            painter.setPen(QColor(0, 255, 128))
            painter.drawText(leg_x, leg_y + 12, "── Ch A")
        if self.enable_b:
            painter.setPen(QColor(0, 218, 255))
            painter.drawText(leg_x, leg_y + 26, "── Ch B")

        # ── annotations text labels ───────────────────────────────────
        if self.enable_annotations:
            abox_font = QFont("Consolas", 8)
            painter.setFont(abox_font)
            afm = QFontMetrics(abox_font)
            time_vals = self.times if self.times else list(range(len(self.data_a)))
            for xi_idx, yv, text, color in self.annotations:
                if xi_idx < len(time_vals):
                    r, g, b = color
                    t_val = time_vals[int(xi_idx)]
                    sx, sy = self._data_to_screen(t_val, yv)
                    if not (px <= sx <= px + pw and py <= sy <= py + ph): continue
                    lbl = f"{text}: {_si_fmt(yv, self.y_unit)}"
                    tw, th = afm.horizontalAdvance(lbl), afm.height()
                    bx, by = int(sx) + 6, int(sy) - th - 4
                    bx = min(bx, px + pw - tw - 6)
                    painter.fillRect(bx - 2, by - 1, tw + 4, th + 2,
                                     QColor(20, 22, 28, 200))
                    painter.setPen(QColor(int(r*255), int(g*255), int(b*255)))
                    painter.drawText(bx, by + afm.ascent(), lbl)

        # ── marker readouts ───────────────────────────────────────────
        self._draw_marker_overlay(painter, px, py, pw, ph)

        # ── crosshair ─────────────────────────────────────────────────
        if self.show_crosshair and self._mouse_pos is not None:
            mx, my = self._mouse_pos.x(), self._mouse_pos.y()
            if px <= mx <= px + pw and py <= my <= py + ph:
                pen = QPen(QColor(100, 130, 160, 160), 1, Qt.DashLine)
                painter.setPen(pen)
                painter.drawLine(px, my, px + pw, my)
                painter.drawLine(mx, py, mx, py + ph)

                xi, yv = self._screen_to_data(mx, my)
                lbl = f"  {xi:.0f}  {_si_fmt(yv, self.y_unit) if self.y_unit else f'{yv:.5g}'}"
                crs_font = QFont("Consolas", 8)
                painter.setFont(crs_font)
                cfm = QFontMetrics(crs_font)
                tw = cfm.horizontalAdvance(lbl)
                bx = mx + 5 if mx + tw + 10 < px + pw else mx - tw - 10
                painter.fillRect(bx - 2, my - cfm.height() - 2, tw + 4, cfm.height() + 2,
                                 QColor(15, 18, 25, 190))
                painter.setPen(QColor(190, 210, 230))
                painter.drawText(bx, my - 4, lbl)

        painter.end()

    def _draw_marker_overlay(self, painter, px, py, pw, ph):
        n = len(self.times) if self.times else len(self.data_a)
        time_vals = self.times if self.times else list(range(n))
        mfont = QFont("Consolas", 8, QFont.Bold)
        painter.setFont(mfont)
        mfm = QFontMetrics(mfont)

        def draw_one(marker, label, bg_color: QColor, text_color: QColor, stack=0):
            if marker is None: return
            mx_time, mv = marker  # now stores time in seconds, not index
            sx, sy = self._data_to_screen(mx_time, mv)
            # vertical dashed line
            pen = QPen(text_color, 1, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(sx), py, int(sx), py + ph)
            # circle at value
            painter.setPen(QPen(text_color, 2))
            painter.setBrush(QBrush(bg_color))
            painter.drawEllipse(QPointF(sx, sy), 5, 5)
            # label box
            lbl = f"{label}: {_si_fmt(mv, self.y_unit) if self.y_unit else f'{mv:.5g}'}"
            tw, th = mfm.horizontalAdvance(lbl), mfm.height()
            bx = int(sx) + 8
            by = py + 6 + stack * (th + 6)
            if bx + tw + 6 > px + pw: bx = int(sx) - tw - 10
            painter.fillRect(bx - 2, by - 1, tw + 6, th + 2, bg_color)
            painter.setPen(text_color)
            painter.drawText(bx + 2, by + mfm.ascent(), lbl)

        draw_one(self.marker1, "M1", QColor(60, 48, 0, 200),  QColor(255, 200, 0),  0)
        draw_one(self.marker2, "M2", QColor(60, 22, 10, 200), QColor(255, 110, 60), 1)

        # delta between markers (show time diff in seconds)
        if self.marker1 and self.marker2:
            delta = self.marker2[1] - self.marker1[1]
            dt    = self.marker2[0] - self.marker1[0]
            lbl   = f"Δ = {_si_fmt(delta, self.y_unit) if self.y_unit else f'{delta:.5g}'}  (Δt={dt:.2f}s)"
            dfont = QFont("Consolas", 8)
            painter.setFont(dfont)
            dfm = QFontMetrics(dfont)
            tw, th = dfm.horizontalAdvance(lbl), dfm.height()
            bx = px + pw // 2 - tw // 2
            by = py + ph - th - 6
            painter.fillRect(bx - 4, by - 2, tw + 8, th + 4, QColor(20, 25, 35, 215))
            painter.setPen(QColor(200, 220, 255))
            painter.drawText(bx, by + dfm.ascent(), lbl)

    # ------------------------------------------------------------------ #
    #  mouse / keyboard
    # ------------------------------------------------------------------ #
    def mouseMoveEvent(self, event):
        self._mouse_pos = event.pos()
        if self._pan_origin is not None and (event.buttons() & Qt.MiddleButton):
            dy_px = event.pos().y() - self._pan_origin.y()
            dx_px = event.pos().x() - self._pan_origin.x()
            px, py, pw, ph = self._plot_rect()
            # Y pan
            span_y = self.y_max - self.y_min
            self.pan_y = self._pan_y0 - dy_px / ph * span_y
            # X pan (in time units)
            span_x = self.x_max - self.x_min
            self.x_min = self._pan_x0 - dx_px / pw * span_x
            self.x_max = self.x_min + span_x
            self._apply_zoom_pan()
        self.update()

    def mousePressEvent(self, event):
        px, py, pw, ph = self._plot_rect()
        if not (px <= event.x() <= px + pw and py <= event.y() <= py + ph):
            return
        xi, yv = self._screen_to_data(event.x(), event.y())  # xi is time in seconds
        # Find actual value at this time from our data
        actual_y = yv
        if self.times:
            # Find closest time index
            idx = 0
            min_dist = float('inf')
            for i, t in enumerate(self.times):
                dist = abs(t - xi)
                if dist < min_dist:
                    min_dist = dist
                    idx = i
            if self.enable_a and np.isfinite(self.data_a[idx]):
                actual_y = float(self.data_a[idx])
            elif self.enable_b and np.isfinite(self.data_b[idx]):
                actual_y = float(self.data_b[idx])

        if event.button() == Qt.LeftButton:
            self.marker1 = (xi, actual_y)  # store time, not index
        elif event.button() == Qt.RightButton:
            self.marker2 = (xi, actual_y)  # store time, not index
        elif event.button() == Qt.MiddleButton:
            self._pan_origin = event.pos()
            self._pan_x0 = self.x_min
            self._pan_y0 = self.pan_y

        if self.marker_callback:
            self.marker_callback()
        self.update()

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MiddleButton:
            self._pan_origin = None

    def mouseDoubleClickEvent(self, event):
        self.reset_zoom()

    def wheelEvent(self, event):
        px, py, pw, ph = self._plot_rect()
        factor = 1.15 if event.angleDelta().y() > 0 else 1.0 / 1.15
        ctrl   = event.modifiers() & Qt.ControlModifier

        if ctrl:
            # X-zoom (sample window)
            self.zoom_x = np.clip(self.zoom_x * factor, 0.1, 10.0)
        else:
            # Y-zoom toward cursor
            if py <= event.y() <= py + ph:
                xi, yv = self._screen_to_data(event.x(), event.y())
                self.zoom_y = np.clip(self.zoom_y * factor, 0.05, 200.0)
                # Adjust pan so the point under cursor stays fixed
                cy  = (self._y_min_auto + self._y_max_auto) / 2
                hy  = (self._y_max_auto - self._y_min_auto) / 2 / self.zoom_y
                # New range without pan
                new_min = cy - hy
                # Solve for pan_y so yv stays at same screen fraction
                span = self.y_max - self.y_min
                frac = (yv - self.y_min) / span if span else 0.5
                new_span = hy * 2
                new_ymin_want = yv - frac * new_span
                self.pan_y = new_ymin_want - new_min
            else:
                self.zoom_y = np.clip(self.zoom_y * factor, 0.05, 200.0)
            self._apply_zoom_pan()
        self.update()
        event.accept()


# =============================================================================
# MAIN APPLICATION WINDOW
# =============================================================================
class ADCMT7352GUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADCMT 7352A/E  –  Controller  (ADC Language)")
        self.resize(1200, 750)

        self.inst = None
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_readings)
        self.is_continuous  = False
        self.use_mock       = False
        self.default_digits = 2          # 4½  (RE4)
        self._rec_data_a: list[tuple] = []   # (timestamp, value)
        self._rec_data_b: list[tuple] = []
        self._capture_start_time: float | None = None

        self.init_ui()
        self.statusBar().showMessage("Ready.  Select device and click Connect.")

    # ================================================================== #
    #  UI construction
    # ================================================================== #
    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setSpacing(0)
        root.setContentsMargins(0, 0, 0, 0)

        # ── left settings panel (scrollable) ──────────────────────────
        left_widget = self._build_left_panel()
        left_scroll = QScrollArea()
        left_scroll.setWidget(left_widget)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setMinimumWidth(280)
        left_scroll.setMaximumWidth(420)
        left_scroll.setStyleSheet("QScrollArea { border: none; background-color: #090c12; }")

        # ── right content ─────────────────────────────────────────────
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(6, 6, 6, 6)
        rl.setSpacing(4)

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_plot_tab(),         " Live Plot")
        self.tabs.addTab(self._build_measurements_tab(), " Statistics")
        self.tabs.addTab(self._build_export_tab(),       " Export")
        self.tabs.addTab(self._build_console_tab(),      " ADC Console")
        rl.addWidget(self.tabs)

        # ── splitter for resizable panels ─────────────────────────────
        splitter = QSplitter(Qt.Horizontal)
        splitter.addWidget(left_scroll)
        splitter.addWidget(right)
        splitter.setCollapsible(0, False)
        splitter.setCollapsible(1, False)
        splitter.setSizes([300, 900])
        
        root.addWidget(splitter, 1)

    # ── STYLE HELPERS ─────────────────────────────────────────────────
    _GRP = """
        QGroupBox {
            border: 1px solid #30363d; border-radius: 5px;
            margin-top: 10px; padding-top: 8px;
            background-color: #0d1117; font-size: 10px;
        }
        QGroupBox::title {
            subcontrol-origin: margin; left: 10px;
            padding: 0 5px; color: #58a6ff; font-weight: bold; font-size: 10px;
        }
        QGroupBox::indicator {
            width: 13px; height: 13px;
        }
        QGroupBox::indicator:unchecked {
            image: none;
        }
        QGroupBox::indicator:checked {
            image: none;
        }
    """

    def _grp(self, title):
        g = CollapsibleSection(title)
        g.setStyleSheet(self._GRP)
        return g

    # ================================================================== #
    #  LEFT  PANEL
    # ================================================================== #
    def _build_left_panel(self):
        panel = QWidget()
        panel.setStyleSheet("background-color: #090c12;")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(5)

        # Title
        t = QLabel("ADCMT 7352A")
        t.setStyleSheet("font-size: 15px; font-weight: bold; color: #c9d1d9; padding-top: 4px;")
        layout.addWidget(t)
        s = QLabel("Digital Multimeter  [ADC mode]")
        s.setStyleSheet("color: #6e7681; font-size: 10px;")
        layout.addWidget(s)

        # Status
        self.status_label = QLabel("DISCONNECTED")
        self.status_label.setStyleSheet("color: #f85149; font-weight: bold;")
        self.status_dot   = QLabel("●")
        self.status_dot.setStyleSheet("color: #f85149; font-size: 13px;")
        sb = QWidget(); sbl = QHBoxLayout(sb); sbl.setContentsMargins(0,0,0,0)
        sbl.addWidget(self.status_dot); sbl.addWidget(self.status_label); sbl.addStretch()
        layout.addWidget(sb)

        # ── Collapsible sections ──────────────────────────────────────
        layout.addWidget(self._build_connection_card())
        layout.addWidget(self._build_channel_card("Channel A  (DSP1)", "A"))
        layout.addWidget(self._build_digits_card())
        layout.addWidget(self._build_channel_card("Channel B  (DSP2)", "B"))
        layout.addWidget(self._build_display_card())
        layout.addWidget(self._build_control_card())
        
        layout.addStretch()
        return panel

    def _build_connection_card(self):
        g = self._grp("CONNECTION")
        lay = QVBoxLayout(g); lay.setContentsMargins(8,12,8,8)

        rl = QHBoxLayout(); rl.addWidget(QLabel("Device:"))
        self.cb_device = QComboBox()
        self.cb_device.addItems(["Real Device (VISA)", "Mock Device (Testing)"])
        self.cb_device.currentIndexChanged.connect(self.on_device_changed)
        rl.addWidget(self.cb_device); lay.addLayout(rl)

        xl = QHBoxLayout(); xl.addWidget(QLabel("Resource:"))
        self.res_input = QLineEdit("TCPIP0::10.1.1.138::5025::SOCKET")
        self.res_input.setPlaceholderText("VISA Resource String")
        xl.addWidget(self.res_input, 1); lay.addLayout(xl)

        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.toggle_connection)
        lay.addWidget(self.btn_connect)
        return g

    def _build_channel_card(self, title, ch):
        g = self._grp(title)
        lay = QVBoxLayout(g); lay.setContentsMargins(8,12,8,8)

        cb_enable = QCheckBox("Enable Channel")
        cb_enable.setChecked(ch == "A")
        setattr(self, f"chk_enable_{ch}", cb_enable)
        lay.addWidget(cb_enable)

        for lbl_txt, attr, items, default_idx in [
            ("Function:", f"cb_func_{ch}", list(ADC_FUNCS.keys()), 0),
            ("Range:",    f"cb_rng_{ch}",  list(ADC_RANGES.keys()), 0),
            ("Rate:",     f"cb_rate_{ch}", list(ADC_RATES.keys()),  2),
            ("Trigger:",  f"cb_trig_{ch}", list(ADC_TRIGS.keys()),  0),
        ]:
            row = QHBoxLayout(); row.addWidget(QLabel(lbl_txt))
            cb = QComboBox(); cb.addItems(items); cb.setCurrentIndex(default_idx)
            setattr(self, attr, cb)
            row.addWidget(cb); lay.addLayout(row)

        # function description label
        lbl_f = QLabel(); lbl_f.setStyleSheet("color: #6e7681; font-size: 9px;")
        setattr(self, f"lbl_func_{ch}", lbl_f)
        lay.addWidget(lbl_f)
        getattr(self, f"cb_func_{ch}").currentTextChanged.connect(
            lambda t, c=ch: self._update_func_label(c, t))
        self._update_func_label(ch, getattr(self, f"cb_func_{ch}").currentText())

        return g

    def _build_digits_card(self):
        g = self._grp("DIGITS"); lay = QHBoxLayout(g); lay.setContentsMargins(8,12,8,8)
        lay.addWidget(QLabel("Digits:"))
        self.cb_digits = QComboBox(); self.cb_digits.addItems(DIGITS_DISP)
        self.cb_digits.setCurrentIndex(self.default_digits)
        lay.addWidget(self.cb_digits)
        return g

    def _build_display_card(self):
        g = self._grp("LIVE READINGS"); lay = QVBoxLayout(g); lay.setContentsMargins(8,12,8,8)
        for ch, color in [("A","#00ff80"),("B","#00d9ff")]:
            lay.addWidget(QLabel(f"Channel {ch}:"))
            lbl = QLabel("--")
            lbl.setStyleSheet(f"font-family:monospace;font-size:15px;color:{color};"
                              f"padding:6px;background:#060809;border:1px solid #30363d;border-radius:3px;")
            lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            lbl.setMinimumHeight(44)
            setattr(self, f"lbl_{ch.lower()}", lbl)
            lay.addWidget(lbl)
        return g

    def _build_control_card(self):
        g = self._grp("CONTROLS"); lay = QVBoxLayout(g); lay.setContentsMargins(8,12,8,8)
        self.btn_apply = QPushButton("Apply Settings")
        self.btn_apply.clicked.connect(self.apply_settings)
        lay.addWidget(self.btn_apply)
        row = QHBoxLayout()
        b1 = QPushButton("INI"); b1.clicked.connect(lambda: self.send_cmd("INI"))
        b2 = QPushButton("ABO"); b2.clicked.connect(lambda: self.send_cmd("ABO"))
        row.addWidget(b1); row.addWidget(b2); lay.addLayout(row)
        self.chk_cont = QCheckBox("Continuous Read")
        self.chk_cont.stateChanged.connect(self.toggle_continuous)
        lay.addWidget(self.chk_cont)
        return g

    # ================================================================== #
    #  PLOT TAB
    # ================================================================== #
    def _build_plot_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(4,4,4,4); lay.setSpacing(4)

        # ── toolbar ───────────────────────────────────────────────────
        tb = QWidget(); tbl = QHBoxLayout(tb); tbl.setContentsMargins(0,0,0,0)

        self.btn_auto_zoom = QPushButton("⤢ Auto Zoom")
        self.btn_auto_zoom.clicked.connect(self._do_reset_zoom)
        tbl.addWidget(self.btn_auto_zoom)

        self.btn_clear_data = QPushButton("✕ Clear Data")
        self.btn_clear_data.clicked.connect(self._do_clear_data)
        tbl.addWidget(self.btn_clear_data)

        self.btn_clr_markers = QPushButton("✕ Clear Markers")
        self.btn_clr_markers.clicked.connect(self._do_clear_markers)
        tbl.addWidget(self.btn_clr_markers)

        tbl.addWidget(self._sep())

        self.chk_fill = QCheckBox("Fill")
        self.chk_fill.stateChanged.connect(lambda s: setattr(self.gl_plot, 'show_fill', bool(s)) or self.gl_plot.update())
        tbl.addWidget(self.chk_fill)

        self.chk_crosshair = QCheckBox("Crosshair")
        self.chk_crosshair.setChecked(True)
        self.chk_crosshair.stateChanged.connect(lambda s: setattr(self.gl_plot, 'show_crosshair', bool(s)) or self.gl_plot.update())
        tbl.addWidget(self.chk_crosshair)

        tbl.addWidget(self._sep())
        tbl.addWidget(QLabel("Buffer:"))
        self.spn_buf = QSpinBox(); self.spn_buf.setRange(20, 5000)
        self.spn_buf.setValue(200); self.spn_buf.setSingleStep(50)
        self.spn_buf.editingFinished.connect(
            lambda: self.gl_plot.set_buffer_size(self.spn_buf.value()))
        tbl.addWidget(self.spn_buf)

        tbl.addWidget(self._sep())
        tbl.addWidget(QLabel("Line:"))
        self.spn_lw = QDoubleSpinBox(); self.spn_lw.setRange(0.5, 6.0)
        self.spn_lw.setSingleStep(0.5); self.spn_lw.setValue(2.0)
        self.spn_lw.valueChanged.connect(lambda v: setattr(self.gl_plot, 'line_width', v) or self.gl_plot.update())
        tbl.addWidget(self.spn_lw)

        tbl.addStretch()

        # zoom-mode hint
        hint = QLabel("Scroll=Y-zoom  |  Ctrl+Scroll=X-zoom  |  LClick=M1  |  RClick=M2  |  MClick-drag=Pan  |  DblClick=Reset")
        hint.setStyleSheet("color:#808a88;font-size:9px;")
        tbl.addWidget(hint)

        lay.addWidget(tb)

        # ── GL plot ───────────────────────────────────────────────────
        self.gl_plot = DMMGLPlot()
        self.gl_plot.marker_callback = self._update_marker_display
        lay.addWidget(self.gl_plot, 1)

        # ── marker readout strip ──────────────────────────────────────
        ms = QWidget(); msl = QHBoxLayout(ms); msl.setContentsMargins(4,2,4,2)
        self.lbl_m1  = QLabel("M1: –");  self.lbl_m1.setStyleSheet("color:#ffc000;font-family:monospace;font-size:10px;")
        self.lbl_m2  = QLabel("M2: –");  self.lbl_m2.setStyleSheet("color:#ff6e3c;font-family:monospace;font-size:10px;")
        self.lbl_mdl = QLabel("Δ: –");   self.lbl_mdl.setStyleSheet("color:#a0b8d0;font-family:monospace;font-size:10px;")
        msl.addWidget(self.lbl_m1); msl.addWidget(self._sep())
        msl.addWidget(self.lbl_m2); msl.addWidget(self._sep())
        msl.addWidget(self.lbl_mdl); msl.addStretch()
        lay.addWidget(ms)
        return w

    def _sep(self):
        f = QFrame(); f.setFrameShape(QFrame.VLine)
        f.setStyleSheet("color:#30363d;"); return f

    # ================================================================== #
    #  STATISTICS TAB
    # ================================================================== #
    def _build_measurements_tab(self):
        w = QWidget(); lay = QVBoxLayout(w)

        # ── per-channel stats ─────────────────────────────────────────
        for ch, color in [("A","#00ff80"),("B","#00d9ff")]:
            g = self._grp(f"Channel {ch}  Statistics")
            fl = QFormLayout(g); fl.setContentsMargins(10,14,10,8)
            stat_dict = {}
            for key, lbl in [("min","Minimum"),("max","Maximum"),("avg","Average"),
                              ("med","Median"),("std","Std Dev"),
                              ("p10","10th %ile"),("p90","90th %ile"),
                              ("n","Samples"),("last","Last")]:
                lb = QLabel("N/A")
                lb.setStyleSheet(f"font-family:monospace;color:{color};")
                fl.addRow(f"{lbl}:", lb)
                stat_dict[key] = lb
            setattr(self, f"_stats_{ch}", stat_dict)
            lay.addWidget(g)

        # ── annotations ───────────────────────────────────────────────
        g2 = self._grp("Annotations"); fl2 = QFormLayout(g2); fl2.setContentsMargins(10,14,10,8)
        self.chk_annot_enable = QCheckBox("Show annotations on plot")
        self.chk_annot_enable.stateChanged.connect(self._toggle_annotations)
        fl2.addRow(self.chk_annot_enable)
        self.chk_annot_min = QCheckBox("Mark Minimum")
        self.chk_annot_max = QCheckBox("Mark Maximum")
        self.chk_annot_avg = QCheckBox("Mark Average")
        for c in [self.chk_annot_min, self.chk_annot_max, self.chk_annot_avg]:
            fl2.addRow(c)
        lay.addWidget(g2)
        lay.addStretch()
        return w

    # ================================================================== #
    #  EXPORT TAB
    # ================================================================== #
    def _build_export_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(10,10,10,10)

        g = self._grp("Save Recorded Data"); fl = QVBoxLayout(g); fl.setContentsMargins(10,14,10,8)
        self.lbl_rec_count = QLabel("Recorded:  0 samples")
        self.lbl_rec_count.setStyleSheet("color:#8b949e;")
        fl.addWidget(self.lbl_rec_count)

        rl = QHBoxLayout()
        b_csv = QPushButton("💾 Export CSV")
        b_csv.clicked.connect(lambda: self._export("csv"))
        b_txt = QPushButton("📄 Export TXT")
        b_txt.clicked.connect(lambda: self._export("txt"))
        rl.addWidget(b_csv); rl.addWidget(b_txt)
        fl.addLayout(rl)

        self.chk_rec_timestamps = QCheckBox("Include timestamps")
        self.chk_rec_timestamps.setChecked(True)
        fl.addWidget(self.chk_rec_timestamps)

        b_clr = QPushButton("✕ Clear Record Buffer")
        b_clr.clicked.connect(self._clear_rec_buffer)
        fl.addWidget(b_clr)
        lay.addWidget(g)

        # preview
        g2 = self._grp("Preview  (last 20 rows)"); pl = QVBoxLayout(g2); pl.setContentsMargins(8,12,8,8)
        self.txt_preview = QTextEdit()
        self.txt_preview.setReadOnly(True)
        self.txt_preview.setStyleSheet("background:#060809;color:#8b949e;font-family:Consolas,monospace;font-size:9px;")
        self.txt_preview.setMaximumHeight(200)
        pl.addWidget(self.txt_preview)
        lay.addWidget(g2)
        lay.addStretch()
        return w

    # ================================================================== #
    #  CONSOLE TAB
    # ================================================================== #
    def _build_console_tab(self):
        w = QWidget(); lay = QVBoxLayout(w); lay.setContentsMargins(6,6,6,6)

        row = QHBoxLayout()
        row.addWidget(QLabel("CMD:"))
        self.cmd_edit = QLineEdit()
        self.cmd_edit.setPlaceholderText("Enter ADC command (e.g.  F1  or  DSP1,MD?)")
        self.cmd_edit.returnPressed.connect(self.send_console_cmd)
        row.addWidget(self.cmd_edit, 1)
        for label, slot, style in [
            ("SEND",  self.send_console_cmd,         ""),
            ("CLEAR", self.clear_console,             ""),
            ("*RST",  lambda: self.send_cmd("*RST"),  "color:#f85149;"),
            ("*CLS",  lambda: self.send_cmd("*CLS"),  "color:#d29922;"),
        ]:
            b = QPushButton(label)
            if style: b.setStyleSheet(style)
            b.clicked.connect(slot)
            row.addWidget(b)
        lay.addLayout(row)

        self.console_text = QTextEdit()
        self.console_text.setReadOnly(True)
        self.console_text.setStyleSheet(
            "QTextEdit{background:#060809;color:#c9d1d9;"
            "font-family:Consolas,monospace;font-size:10px;border:none;}")
        lay.addWidget(self.console_text)

        self.log_console("ADCMT 7352A  [ADC mode,  \\r\\n termination]", "info")
        self.log_console("LClick on plot = Marker1 | RClick = Marker2 | Scroll = zoom | Ctrl+Scroll = X-zoom", "info")
        return w

    # ================================================================== #
    #  HELPER ACTIONS
    # ================================================================== #
    def _do_reset_zoom(self):
        self.gl_plot.reset_zoom()

    def _do_clear_data(self):
        self.gl_plot.clear_data()
        self._rec_data_a.clear(); self._rec_data_b.clear()
        self._update_export_preview()

    def _do_clear_markers(self):
        self.gl_plot.marker1 = None
        self.gl_plot.marker2 = None
        self._update_marker_display()
        self.gl_plot.update()

    def _update_marker_display(self):
        def fmt(m, label):
            if m is None: return f"{label}: –"
            return f"{label}: idx={int(m[0])}  val={_si_fmt(m[1], self.gl_plot.y_unit) if self.gl_plot.y_unit else f'{m[1]:.6g}'}"
        self.lbl_m1.setText(fmt(self.gl_plot.marker1, "M1"))
        self.lbl_m2.setText(fmt(self.gl_plot.marker2, "M2"))
        if self.gl_plot.marker1 and self.gl_plot.marker2:
            d = self.gl_plot.marker2[1] - self.gl_plot.marker1[1]
            self.lbl_mdl.setText(f"Δ = {_si_fmt(d, self.gl_plot.y_unit) if self.gl_plot.y_unit else f'{d:.6g}'}")
        else:
            self.lbl_mdl.setText("Δ: –")

    def _toggle_annotations(self, state):
        self.gl_plot.enable_annotations = bool(state)
        if not state: self.gl_plot.clear_annotations()
        self.gl_plot.update()

    def _update_func_label(self, ch, func_code):
        lw = getattr(self, f"lbl_func_{ch}", None)
        if lw and func_code in FUNC_LABELS:
            lw.setText(FUNC_LABELS[func_code])

    def _sep(self):
        f = QFrame(); f.setFrameShape(QFrame.VLine)
        f.setStyleSheet("color:#30363d;"); return f

    # ================================================================== #
    #  STATISTICS
    # ================================================================== #
    def update_statistics(self):
        """Compute and display stats for both channels; update annotations."""
        for ch, data in [("A", self.gl_plot.data_a), ("B", self.gl_plot.data_b)]:
            d  = getattr(self, f"_stats_{ch}")
            vd = data[np.isfinite(data)]
            unit = self.gl_plot.y_unit
            def f(v): return _si_fmt(v, unit) if unit else f"{v:.6g}"
            if len(vd):
                d["min"].setText(f(float(np.min(vd))))
                d["max"].setText(f(float(np.max(vd))))
                d["avg"].setText(f(float(np.mean(vd))))
                d["med"].setText(f(float(np.median(vd))))
                d["std"].setText(f(float(np.std(vd))))
                d["p10"].setText(f(float(np.percentile(vd, 10))))
                d["p90"].setText(f(float(np.percentile(vd, 90))))
                d["n"].setText(str(len(vd)))
                d["last"].setText(f(float(vd[-1])))
            else:
                for k in d: d[k].setText("N/A")

        # annotations on channel A
        if self.gl_plot.enable_annotations:
            vd_a = self.gl_plot.data_a; vd_a = vd_a[np.isfinite(vd_a)]
            self.gl_plot.clear_annotations()
            if len(vd_a):
                if self.chk_annot_min.isChecked():
                    idx = int(np.argmin(vd_a))
                    self.gl_plot.add_annotation(idx, float(vd_a[idx]), "Min", (1.0,0.2,0.2))
                if self.chk_annot_max.isChecked():
                    idx = int(np.argmax(vd_a))
                    self.gl_plot.add_annotation(idx, float(vd_a[idx]), "Max", (0.2,1.0,0.4))
                if self.chk_annot_avg.isChecked():
                    avg = float(np.mean(vd_a))
                    self.gl_plot.add_annotation(len(vd_a)//2, avg, "Avg", (1.0,1.0,0.2))

    # ================================================================== #
    #  EXPORT
    # ================================================================== #
    def _clear_rec_buffer(self):
        self._rec_data_a.clear(); self._rec_data_b.clear()
        self._update_export_preview()

    def _update_export_preview(self):
        n = len(self._rec_data_a)
        self.lbl_rec_count.setText(f"Recorded:  {n} samples")
        rows = self._rec_data_a[-20:]
        lines = ["timestamp,ch_a,ch_b"]
        for i, (ts, va) in enumerate(rows):
            vb = self._rec_data_b[i][1] if i < len(self._rec_data_b) else "N/A"
            lines.append(f"{ts.strftime('%H:%M:%S.%f')[:-3]},{va},{vb}")
        self.txt_preview.setPlainText("\n".join(lines))

    def _export(self, fmt):
        if not self._rec_data_a:
            QMessageBox.warning(self, "No data", "No recorded data to export.")
            return
        ext = "CSV files (*.csv)" if fmt == "csv" else "Text files (*.txt)"
        path, _ = QFileDialog.getSaveFileName(self, "Save data", "", ext)
        if not path: return
        inc_ts = self.chk_rec_timestamps.isChecked()
        try:
            with open(path, "w", newline="") as fh:
                if fmt == "csv":
                    wr = csv.writer(fh)
                    hdr = (["timestamp"] if inc_ts else []) + ["ch_a", "ch_b"]
                    wr.writerow(hdr)
                    for i, (ts, va) in enumerate(self._rec_data_a):
                        vb = self._rec_data_b[i][1] if i < len(self._rec_data_b) else ""
                        row = ([ts.isoformat()] if inc_ts else []) + [va, vb]
                        wr.writerow(row)
                else:
                    for i, (ts, va) in enumerate(self._rec_data_a):
                        vb = self._rec_data_b[i][1] if i < len(self._rec_data_b) else ""
                        line = (f"{ts.isoformat()}  " if inc_ts else "") + f"{va}\t{vb}\n"
                        fh.write(line)
            self.log_console(f"Exported {len(self._rec_data_a)} rows → {path}", "ok")
        except Exception as e:
            QMessageBox.critical(self, "Export error", str(e))

    # ================================================================== #
    #  VISA / COMMAND LOGIC
    # ================================================================== #
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
                self.inst.read_termination  = '\r\n'
                self.inst.write_termination = '\r\n'
                self._init_instrument()
                self.btn_connect.setText("Disconnect")
                self._update_status(True)
                self.log_console(f"Connected to {self.res_input.text()}", "ok")
            self.apply_settings()
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            self.inst = None
            self._update_status(False)

    def _update_status(self, connected):
        c = "#3fb950" if connected else "#f85149"
        t = "CONNECTED" if connected else "DISCONNECTED"
        self.status_label.setText(t)
        self.status_label.setStyleSheet(f"color:{c};font-weight:bold;")
        self.status_dot.setStyleSheet(f"color:{c};font-size:13px;")

    def _send_cmd(self, cmd):
        """Send command with ERR? check (matching adce7352a_gui2.py)."""
        if not self.inst: return False
        try:
            self.log_console(f"Sent: {cmd}", "cmd")
            self.inst.write(cmd)
            time.sleep(0.025)  # USB settling time per manual
            err = self.inst.query("ERR?")
            if err and not err.startswith("+000"):
                self.log_console(f"   ERR? → {err}", "err")
                return False
            return True
        except Exception as e:
            self.log_console(f"Cmd Error: {e}", "err")
            return False

    def _init_instrument(self):
        """Initialize instrument with proper sequence from adce7352a_gui2.py."""
        self._send_cmd("*RST")
        time.sleep(0.1)
        self._send_cmd("H1")   # header ON
        self._send_cmd("DE0")  # 2nd display OFF
        self._send_cmd("SD1")  # remote output: 1st display only
        self._send_cmd("TRS0") # trigger source: IMMEDIATE
        self._send_cmd("INIC1")# continuous measurement ON
        # Get IDN
        try:
            idn = self.inst.query("*IDN?")
            self.log_console(f"IDN: {idn}", "ok")
        except:
            pass
        self.log_console("Instrument initialized.", "ok")

    def send_cmd(self, cmd):
        """Legacy wrapper for backward compatibility."""
        self._send_cmd(cmd)

    def apply_settings(self):
        if not self.inst: return
        for ch, dsp in [("A","DSP1"),("B","DSP2")]:
            if getattr(self, f"chk_enable_{ch}").isChecked():
                self.send_cmd(f"{dsp},{ADC_FUNCS[getattr(self, f'cb_func_{ch}').currentText()]}")
                self.send_cmd(f"{dsp},{ADC_RANGES[getattr(self, f'cb_rng_{ch}').currentText()]}")
                self.send_cmd(f"{dsp},{ADC_RATES[getattr(self, f'cb_rate_{ch}').currentText()]}")
                self.send_cmd(f"{dsp},{ADC_TRIGS[getattr(self, f'cb_trig_{ch}').currentText()]}")
                self.send_cmd(f"{dsp},{DIGITS_CMD[self.cb_digits.currentIndex()]}")
        if not self.chk_enable_B.isChecked():
            self.send_cmd("DP0")
        # update y-label / unit from selected function
        fk = _cur_fkey(self.cb_func_A.currentText())
        info = FUNCTIONS.get(fk, ("","V","",""))
        self.gl_plot.y_unit  = info[1]
        self.gl_plot.y_label = info[1]
        self.log_console("Settings applied.", "ok")

    def toggle_continuous(self, state):
        self.is_continuous = bool(state)
        if self.is_continuous and self.inst:
            self._capture_start_time = time.time()
            # Reset plot time base
            self.gl_plot._t0 = self._capture_start_time
            self.gl_plot.times.clear()
            self.gl_plot.x_min = 0.0
            self.gl_plot.x_max = 10.0
            self.gl_plot._x_min_auto = 0.0
            self.gl_plot._x_max_auto = 10.0
            self.poll_timer.start(500)
        else:
            self.poll_timer.stop()

    def on_device_changed(self, index):
        self.use_mock = (index == 1)
        self.res_input.setEnabled(index == 0)

    def poll_readings(self):
        if not self.inst: return
        try:
            ch_a_enabled = self.chk_enable_A.isChecked()
            ch_b_enabled = self.chk_enable_B.isChecked()
            
            self.gl_plot.set_channel_enabled("A", ch_a_enabled)
            self.gl_plot.set_channel_enabled("B", ch_b_enabled)

            # Read only enabled channels using bare read (no query command)
            resp_a = ""
            resp_b = ""
            fk_a   = _cur_fkey(self.cb_func_A.currentText()) if ch_a_enabled else "F1"
            fk_b   = _cur_fkey(self.cb_func_B.currentText()) if ch_b_enabled else "F1"

            if ch_a_enabled:
                if ch_b_enabled: self.inst.write("DSP1")  # select DSP1
                resp_a = self.inst.read().strip()
            
            if ch_b_enabled:
                self.inst.write("DSP2")  # select DSP2
                resp_b = self.inst.read().strip()

            # Parse responses
            val_a, _, _, is_ol_a, disp_a, _ = parse_adc_response(resp_a, fk_a) if ch_a_enabled else (0.0, "", "_", False, "--", "")
            val_b, _, _, is_ol_b, disp_b, _ = parse_adc_response(resp_b, fk_b) if ch_b_enabled else (0.0, "", "_", False, "--", "")

            self.lbl_a.setText(disp_a)
            self.lbl_b.setText(disp_b)

            push_a = val_a if (ch_a_enabled and not is_ol_a) else np.nan
            push_b = val_b if (ch_b_enabled and not is_ol_b) else np.nan
            self.gl_plot.update_readings(push_a, push_b)

            # record only when enabled
            ts = datetime.now()
            if ch_a_enabled:
                self._rec_data_a.append((ts, push_a))
            if ch_b_enabled:
                self._rec_data_b.append((ts, push_b))
            self._update_export_preview()
            self.update_statistics()

        except Exception as e:
            self.log_console(f"Read Error: {e}", "err")
            self.poll_timer.stop()
            self.chk_cont.setChecked(False)

    # ================================================================== #
    #  CONSOLE
    # ================================================================== #
    def log_console(self, text, tag="info"):
        if not hasattr(self, "console_text") or not self.console_text: return
        colors = {"info":"#8b949e","cmd":"#58a6ff","resp":"#c9d1d9","err":"#f85149","ok":"#3fb950"}
        color  = colors.get(tag, "#c9d1d9")
        ts     = datetime.now().strftime("%H:%M:%S")
        # Use HTML so each message is colour-coded
        html = (f'<span style="color:#505a68;">[{ts}]</span> '
                f'<span style="color:{color};">{text}</span>')
        self.console_text.append(html)
        sb = self.console_text.verticalScrollBar()
        sb.setValue(sb.maximum())

    def send_console_cmd(self):
        cmd = self.cmd_edit.text().strip()
        if not cmd: return
        if not self.inst:
            self.log_console("Not connected", "err"); return
        self.log_console(f"&gt;&gt; {cmd}", "cmd")
        try:
            if cmd.endswith("?"):
                resp = self.inst.query(cmd)
                self.log_console(f"&lt;&lt; {resp or '(empty)'}", "resp" if resp else "err")
            else:
                self.inst.write(cmd)
                err = self.inst.query("ERR?")
                if err and not err.startswith("+000"):
                    self.log_console(f"   ERR? → {err}", "err")
                else:
                    self.log_console(f"OK: {cmd}", "ok")
        except Exception as e:
            self.log_console(f"Error: {e}", "err")
        self.cmd_edit.clear()

    def clear_console(self):
        if hasattr(self, "console_text"):
            self.console_text.clear()
            self.log_console("Console cleared.", "info")


# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    # Dark-palette polish
    from PyQt5.QtGui import QPalette
    pal = QPalette()
    pal.setColor(QPalette.Window,          QColor(33, 38, 45))   # Rozjaśnione z (13, 17, 23)
    pal.setColor(QPalette.WindowText,      QColor(240, 246, 252)) # Prawie biały
    pal.setColor(QPalette.Base,            QColor(22, 27, 34))    # Rozjaśnione z (9, 12, 18)
    pal.setColor(QPalette.AlternateBase,   QColor(48, 54, 61))    # Wyraźniejszy kontrast
    pal.setColor(QPalette.Text,            QColor(240, 246, 252))
    pal.setColor(QPalette.Button,          QColor(48, 54, 61))    # Jaśniejsze przyciski
    pal.setColor(QPalette.ButtonText,      QColor(255, 255, 255))
    pal.setColor(QPalette.Highlight,       QColor(88, 166, 255))  # Żywszy błękit
    pal.setColor(QPalette.HighlightedText, QColor(255, 255, 255))

    app.setPalette(pal)
    window = ADCMT7352GUI()
    window.show()
    sys.exit(app.exec_())