"""
Enhanced OpenGL live plot widget with dual Y-axis support.

Channel A → left Y-axis (green)
Channel B → right Y-axis (cyan)
Shared X-axis (time, seconds)
"""

import numpy as np
from PyQt5.QtCore import Qt, QPoint, QPointF, pyqtSignal
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics
from PyQt5.QtWidgets import QOpenGLWidget, QVBoxLayout, QWidget, QHBoxLayout, QPushButton, QLabel
from OpenGL.GL import *

CLR_BG      = (0.06, 0.07, 0.10)
CLR_GRID    = (0.14, 0.15, 0.20)
CLR_ZERO    = (0.22, 0.24, 0.30)
CLR_CH_A    = (0.00, 1.00, 0.50)
CLR_CH_B    = (0.00, 0.85, 1.00)
CLR_M1      = (1.00, 0.75, 0.00)
CLR_M2      = (1.00, 0.35, 0.20)
CLR_CROSSH  = (0.45, 0.55, 0.65)

# Light theme colors
CLR_BG_L      = (0.97, 0.98, 0.99)
CLR_GRID_L    = (0.85, 0.87, 0.90)
CLR_ZERO_L    = (0.75, 0.77, 0.80)
CLR_CROSSH_L  = (0.55, 0.60, 0.65)

_PLOT_THEMES = {
    True:  {"bg": CLR_BG, "grid": CLR_GRID, "zero": CLR_ZERO,
            "crosshair": CLR_CROSSH, "m1": CLR_M1, "m2": CLR_M2},
    False: {"bg": CLR_BG_L, "grid": CLR_GRID_L, "zero": CLR_ZERO_L,
            "crosshair": CLR_CROSSH_L, "m1": CLR_M1, "m2": CLR_M2},
}

# Overlay painter color palettes (dark / light)
_OL_DARK = {
    "border": (48, 54, 61),
    "bg_rect": (15, 18, 25, 190),
    "bg_tooltip": (20, 25, 35, 215),
    "text_label": (170, 180, 195),
    "text_dim": (100, 110, 125),
    "text_bright": (190, 210, 230),
    "text_tooltip": (200, 220, 255),
}
_OL_LIGHT = {
    "border": (180, 190, 200),
    "bg_rect": (240, 242, 245, 200),
    "bg_tooltip": (235, 237, 240, 220),
    "text_label": (60, 70, 80),
    "text_dim": (100, 110, 120),
    "text_bright": (30, 35, 40),
    "text_tooltip": (30, 35, 40),
}


def si_fmt(val, unit=""):
    if not np.isfinite(val):
        return "OVLD" if abs(val) > 1e36 else "------"
    a = abs(val)
    if a == 0:
        return f"0 {unit}".strip()
    prefixes = [(1e9, "G"), (1e6, "M"), (1e3, "k"),
                (1e0, ""), (1e-3, "m"), (1e-6, "µ"),
                (1e-9, "n"), (1e-12, "p")]
    for div, pfx in prefixes:
        if a >= div / 10 or div == 1:
            v = val / div
            if abs(v) < 0.01 and div > 1: continue
            s = f"{v:.5g}"
            return f"{s} {pfx}{unit}".strip()
    return f"{val:.4g} {unit}".strip()


class _GLPlotWidget(QOpenGLWidget):
    data_updated = pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.buf_size = 600
        self.data_a = np.full(self.buf_size, np.nan)
        self.data_b = np.full(self.buf_size, np.nan)
        self.times = []
        self._t0 = None

        # Channel A Y range (left axis)
        self.y_min_a = -1.0
        self.y_max_a = 1.0
        self._y_min_auto_a = -1.0
        self._y_max_auto_a = 1.0

        # Channel A zoom/pan
        self.zoom_y_a = 1.0
        self.pan_y_a = 0.0

        # Channel B Y range (right axis)
        self.y_min_b = -1.0
        self.y_max_b = 1.0
        self._y_min_auto_b = -1.0
        self._y_max_auto_b = 1.0

        # Channel B zoom/pan
        self.zoom_y_b = 1.0
        self.pan_y_b = 0.0

        # X range (shared)
        self.x_min = 0.0
        self.x_max = 10.0
        self._x_min_auto = 0.0
        self._x_max_auto = 10.0
        self.zoom_x = 1.0

        # Pan state
        self._pan_origin = None
        self._pan_x0 = 0.0
        self._pan_y0_a = 0.0
        self._pan_y0_b = 0.0

        self.enable_a = True
        self.enable_b = False
        self.show_fill = False
        self.show_crosshair = True
        self.show_grid = True
        self.line_width = 2.0
        self._mouse_pos = None
        self.marker1 = None
        self.marker2 = None
        self.marker_callback = None
        self.annotations = []
        self.enable_annotations = False
        self.x_label = "Time (s)"
        self.y_label_a = "Ch A"
        self.y_unit_a = "V"
        self.y_label_b = "Ch B"
        self.y_unit_b = "A"

        self.setMinimumHeight(200)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMouseTracking(True)
        self._theme = _PLOT_THEMES[True]
        self._ol = _OL_DARK
        self._theme_dirty = True

    ML, MR, MT, MB = 60, 60, 12, 30

    def set_theme(self, is_dark):
        self._theme = _PLOT_THEMES[is_dark]
        self._ol = _OL_DARK if is_dark else _OL_LIGHT
        self._theme_dirty = True
        self.update()

    def _plot_rect(self):
        w, h = self.width(), self.height()
        pw = max(1, w - self.ML - self.MR)
        ph = max(1, h - self.MT - self.MB)
        return self.ML, self.MT, pw, ph

    def _screen_to_data_a(self, sx, sy):
        px, py, pw, ph = self._plot_rect()
        x_range = self.x_max - self.x_min
        xi = self.x_min + ((sx - px) / pw) * x_range if x_range > 0 else self.x_min
        yv = self.y_min_a + (1.0 - (sy - py) / ph) * (self.y_max_a - self.y_min_a)
        return xi, yv

    def _screen_to_data_b(self, sx, sy):
        px, py, pw, ph = self._plot_rect()
        x_range = self.x_max - self.x_min
        xi = self.x_min + ((sx - px) / pw) * x_range if x_range > 0 else self.x_min
        yv = self.y_min_b + (1.0 - (sy - py) / ph) * (self.y_max_b - self.y_min_b)
        return xi, yv

    def _data_to_screen_a(self, xi, yv):
        px, py, pw, ph = self._plot_rect()
        x_range = self.x_max - self.x_min
        sx = px + ((xi - self.x_min) / x_range) * pw if x_range > 0 else px
        sy = py + ph * (1.0 - (yv - self.y_min_a) / (self.y_max_a - self.y_min_a))
        return sx, sy

    def _data_to_screen_b(self, xi, yv):
        px, py, pw, ph = self._plot_rect()
        x_range = self.x_max - self.x_min
        sx = px + ((xi - self.x_min) / x_range) * pw if x_range > 0 else px
        sy = py + ph * (1.0 - (yv - self.y_min_b) / (self.y_max_b - self.y_min_b))
        return sx, sy

    def set_buffer_size(self, n):
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
        else: self.enable_b = enabled
        self.update()

    def update_readings(self, val_a, val_b, timestamp=None):
        if self._t0 is None:
            self._t0 = __import__("time").time()
        if timestamp is None:
            timestamp = __import__("time").time() - self._t0

        self.data_a = np.roll(self.data_a, -1)
        self.data_b = np.roll(self.data_b, -1)
        self.data_a[-1] = val_a
        self.data_b[-1] = val_b

        self.times.append(timestamp)
        if len(self.times) > self.buf_size:
            self.times = self.times[-self.buf_size:]

        if self.times:
            self._x_min_auto = self.times[0]
            self._x_max_auto = self.times[-1]
            self.x_max = self._x_max_auto + 1
            self.x_min = self._x_min_auto

        self._recalc_auto_range()
        self._apply_zoom_pan()
        self.update()
        self.data_updated.emit(timestamp, val_a, val_b)

    def reset_zoom(self):
        self.zoom_y_a = 1.0
        self.zoom_y_b = 1.0
        self.zoom_x = 1.0
        self.pan_y_a = 0.0
        self.pan_y_b = 0.0
        if self.times:
            self.x_min = self._x_min_auto
            self.x_max = self._x_max_auto
        self._apply_zoom_pan()
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
        if self.marker_callback:
            self.marker_callback()
        self.update()

    def _recalc_auto_range(self):
        v_a = self.data_a[np.isfinite(self.data_a)]
        if len(v_a):
            mn, mx = float(np.min(v_a)), float(np.max(v_a))
            mg = (mx - mn) * 0.12 if mx != mn else abs(mn) * 0.1 + 0.5
            self._y_min_auto_a = mn - mg
            self._y_max_auto_a = mx + mg
        else:
            self._y_min_auto_a, self._y_max_auto_a = -1.0, 1.0

        v_b = self.data_b[np.isfinite(self.data_b)]
        if len(v_b):
            mn, mx = float(np.min(v_b)), float(np.max(v_b))
            mg = (mx - mn) * 0.12 if mx != mn else abs(mn) * 0.1 + 0.5
            self._y_min_auto_b = mn - mg
            self._y_max_auto_b = mx + mg
        else:
            self._y_min_auto_b, self._y_max_auto_b = -1.0, 1.0

    def _apply_zoom_pan(self):
        cy = (self._y_min_auto_a + self._y_max_auto_a) / 2
        hy = (self._y_max_auto_a - self._y_min_auto_a) / 2 / max(self.zoom_y_a, 0.001)
        self.y_min_a = cy - hy + self.pan_y_a
        self.y_max_a = cy + hy + self.pan_y_a

        cy = (self._y_min_auto_b + self._y_max_auto_b) / 2
        hy = (self._y_max_auto_b - self._y_min_auto_b) / 2 / max(self.zoom_y_b, 0.001)
        self.y_min_b = cy - hy + self.pan_y_b
        self.y_max_b = cy + hy + self.pan_y_b

        if self.times:
            x_span = self._x_max_auto - self._x_min_auto
            if x_span > 0:
                vis_w = x_span / max(self.zoom_x, 0.001)
                cx = (self._x_min_auto + self._x_max_auto) / 2
                self.x_min = cx - vis_w / 2
                self.x_max = cx + vis_w / 2

    def initializeGL(self):
        r, g, b = self._theme["bg"]
        glClearColor(r, g, b, 1.0)
        glEnable(GL_LINE_SMOOTH)
        glHint(GL_LINE_SMOOTH_HINT, GL_NICEST)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

    def resizeGL(self, w, h):
        glViewport(0, 0, w, h)

    def paintGL(self):
        if self._theme_dirty:
            self._theme_dirty = False
            r, g, b = self._theme["bg"]
            glClearColor(r, g, b, 1.0)
        glClear(GL_COLOR_BUFFER_BIT)
        w, h = self.width(), self.height()
        px, py, pw, ph = self._plot_rect()
        x_min, x_max = self.x_min, self.x_max
        if x_max <= x_min:
            x_min, x_max = 0.0, 10.0

        # Pass 1: Channel A (left Y axis)
        if self.enable_a:
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glOrtho(x_min, x_max, self.y_min_a, self.y_max_a, -1, 1)
            glViewport(px, h - py - ph, pw, ph)
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()

            if self.show_grid:
                self._draw_grid(x_min, x_max, self.y_min_a, self.y_max_a)
            self._draw_zero_line(x_min, x_max, self.y_min_a, self.y_max_a)
            self._draw_channel(self.data_a, CLR_CH_A, x_min, x_max, self.y_min_a, self.y_max_a)

        # Pass 2: Channel B (right Y axis)
        if self.enable_b:
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glOrtho(x_min, x_max, self.y_min_b, self.y_max_b, -1, 1)
            glViewport(px, h - py - ph, pw, ph)
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()

            self._draw_channel(self.data_b, CLR_CH_B, x_min, x_max, self.y_min_b, self.y_max_b)

        if self.enable_annotations:
            glMatrixMode(GL_PROJECTION)
            glLoadIdentity()
            glOrtho(x_min, x_max, self.y_min_a, self.y_max_a, -1, 1)
            glViewport(px, h - py - ph, pw, ph)
            glMatrixMode(GL_MODELVIEW)
            glLoadIdentity()
            self._draw_annotation_lines(x_min, x_max, self.y_min_a, self.y_max_a)

        glViewport(0, 0, w, h)
        self._draw_overlay_painter()

    def _draw_grid(self, x_min, x_max, y_min, y_max):
        r, g, b = self._theme["grid"]
        glColor4f(r, g, b, 1.0)
        glLineWidth(1.0)
        glBegin(GL_LINES)
        span = x_max - x_min
        step_x = span / 10 if span else 1
        x = x_min
        while x <= x_max + step_x * 0.01:
            glVertex2f(x, y_min)
            glVertex2f(x, y_max)
            x += step_x
        span_y = y_max - y_min
        step_y = span_y / 5 if span_y else 1
        y = y_min
        while y <= y_max + step_y * 0.01:
            glVertex2f(x_min, y)
            glVertex2f(x_max, y)
            y += step_y
        glEnd()

    def _draw_zero_line(self, x_min, x_max, y_min, y_max):
        if y_min < 0 < y_max:
            r, g, b = self._theme["zero"]
            glColor4f(r, g, b, 1.0)
            glLineWidth(1.5)
            glBegin(GL_LINES)
            glVertex2f(x_min, 0); glVertex2f(x_max, 0)
            glEnd()

    def _draw_channel(self, data, color, x_min, x_max, y_min, y_max):
        r, g, b = color
        n = len(self.times) if self.times else 0
        if n == 0: return
        if self.show_fill:
            glColor4f(r, g, b, 0.10)
            glBegin(GL_TRIANGLE_STRIP)
            for j in range(n):
                i = len(data) - n + j
                val = data[i]
                t = self.times[j]
                v = val if np.isfinite(val) else y_min
                glVertex2f(t, y_min)
                glVertex2f(t, v)
            glEnd()
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
                glEnd(); glBegin(GL_LINE_STRIP)
        glEnd()

    def _draw_annotation_lines(self, x_min, x_max, y_min, y_max):
        n = len(self.times) if self.times else len(self.data_a)
        if n == 0: return
        time_vals = self.times if self.times else list(range(n))
        glLineWidth(1.0)
        for x, y, text, color in self.annotations:
            glColor4f(*color, 0.8)
            if x < len(time_vals):
                xi = time_vals[int(x)]
                glBegin(GL_LINES)
                glVertex2f(xi, y_min); glVertex2f(xi, y_max)
                glEnd()
                glPointSize(7.0)
                glBegin(GL_POINTS)
                glVertex2f(xi, y)
                glEnd()

    def _draw_overlay_painter(self):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setRenderHint(QPainter.TextAntialiasing)
        px, py, pw, ph = self._plot_rect()
        x_span = self.x_max - self.x_min if self.x_max != self.x_min else 1.0
        y_span_a = self.y_max_a - self.y_min_a if self.y_max_a != self.y_min_a else 1.0
        y_span_b = self.y_max_b - self.y_min_b if self.y_max_b != self.y_min_b else 1.0

        painter.setPen(QPen(QColor(*self._ol["border"]), 1))
        painter.drawRect(px, py, pw, ph)

        tick_font = QFont("Consolas", 8)
        painter.setFont(tick_font)
        fm = QFontMetrics(tick_font)

        # Left Y-axis labels (Ch A)
        painter.setPen(QColor(0, 200, 100))
        for i in range(6):
            yv = self.y_min_a + i * y_span_a / 5
            sy = py + ph * (1.0 - i / 5.0)
            lbl = si_fmt(yv, self.y_unit_a) if self.y_unit_a else f"{yv:.4g}"
            tw = fm.horizontalAdvance(lbl)
            painter.drawText(px - tw - 4, int(sy) + fm.ascent() // 2, lbl)

        # Right Y-axis labels (Ch B)
        if self.enable_b:
            painter.setPen(QColor(0, 218, 255))
            for i in range(6):
                yv = self.y_min_b + i * y_span_b / 5
                sy = py + ph * (1.0 - i / 5.0)
                lbl = si_fmt(yv, self.y_unit_b) if self.y_unit_b else f"{yv:.4g}"
                tw = fm.horizontalAdvance(lbl)
                painter.drawText(px + pw + 4, int(sy) + fm.ascent() // 2, lbl)

        # X-axis tick labels
        n_ticks = min(10, int(x_span))
        step = x_span / n_ticks if n_ticks else 1
        painter.setPen(QColor(*self._ol["text_dim"]))
        t = self.x_min
        while t <= self.x_max + step * 0.01:
            sx = px + int((t - self.x_min) / x_span * pw)
            lbl = f"{t:.2f}s"
            tw = fm.horizontalAdvance(lbl)
            painter.drawText(sx - tw // 2, py + ph + 16, lbl)
            t += step

        # Axis titles
        ax_font = QFont("Consolas", 9, QFont.Bold)
        painter.setFont(ax_font)
        painter.setPen(QColor(*self._ol["text_label"]))
        painter.drawText(px + pw // 2 - 30, py + ph + 28, "Time (s)")

        # Left Y axis title
        painter.save()
        painter.translate(12, py + ph // 2)
        painter.rotate(-90)
        painter.setPen(QColor(0, 255, 128))
        painter.drawText(-30, 0, self.y_label_a if self.enable_a else "")
        painter.restore()

        # Right Y axis title
        if self.enable_b:
            painter.save()
            painter.translate(px + pw + 30, py + ph // 2)
            painter.rotate(-90)
            painter.setPen(QColor(0, 218, 255))
            painter.drawText(-30, 0, self.y_label_b)
            painter.restore()

        # Channel legend (top-right corner)
        leg_y = py + 6
        leg_x = px + pw - 100
        if self.enable_a:
            painter.setPen(QColor(0, 255, 128))
            unit_a = f" [{self.y_unit_a}]" if self.y_unit_a else ""
            painter.drawText(leg_x, leg_y + 12, f"─ Ch A{unit_a}")
            leg_y += 14
        if self.enable_b:
            painter.setPen(QColor(0, 218, 255))
            unit_b = f" [{self.y_unit_b}]" if self.y_unit_b else ""
            painter.drawText(leg_x, leg_y + 12, f"─ Ch B{unit_b}")

        # Crosshair
        if self.show_crosshair and self._mouse_pos is not None:
            mx, my = self._mouse_pos.x(), self._mouse_pos.y()
            if px <= mx <= px + pw and py <= my <= py + ph:
                pen = QPen(QColor(100, 130, 160, 160), 1, Qt.DashLine)
                painter.setPen(pen)
                painter.drawLine(px, my, px + pw, my)
                painter.drawLine(mx, py, mx, py + ph)

                xi_a, yv_a = self._screen_to_data_a(mx, my)
                xi_b, yv_b = self._screen_to_data_b(mx, my)
                lbl_a = si_fmt(yv_a, self.y_unit_a) if self.y_unit_a else f"{yv_a:.5g}"
                lbl_b = si_fmt(yv_b, self.y_unit_b) if self.y_unit_b else f"{yv_b:.5g}"
                lbl = f"  A:{lbl_a}  B:{lbl_b}  t={xi_a:.1f}s"
                crs_font = QFont("Consolas", 8)
                painter.setFont(crs_font)
                cfm = QFontMetrics(crs_font)
                tw = cfm.horizontalAdvance(lbl)
                bx = mx + 5 if mx + tw + 10 < px + pw else mx - tw - 10
                painter.fillRect(bx - 2, my - cfm.height() - 2, tw + 4, cfm.height() + 2, QColor(*self._ol["bg_rect"]))
                painter.setPen(QColor(*self._ol["text_bright"]))
                painter.drawText(bx, my - 4, lbl)

        # Markers
        mfont = QFont("Consolas", 8, QFont.Bold)
        painter.setFont(mfont)
        mfm = QFontMetrics(mfont)

        def draw_one(marker, label, bg_color, text_color, stack=0, use_b=False):
            if marker is None: return
            mx_time, mv = marker
            sx, sy = self._data_to_screen_b(mx_time, mv) if use_b else self._data_to_screen_a(mx_time, mv)
            pen = QPen(text_color, 1, Qt.DashLine)
            painter.setPen(pen)
            painter.drawLine(int(sx), py, int(sx), py + ph)
            painter.setPen(QPen(text_color, 2))
            painter.setBrush(QBrush(bg_color))
            painter.drawEllipse(QPointF(sx, sy), 5, 5)
            unit = self.y_unit_b if use_b else self.y_unit_a
            lbl = f"{label}: {si_fmt(mv, unit) if unit else f'{mv:.5g}'}"
            tw, th = mfm.horizontalAdvance(lbl), mfm.height()
            bx = int(sx) + 8
            by = py + 6 + stack * (th + 6)
            if bx + tw + 6 > px + pw: bx = int(sx) - tw - 10
            painter.fillRect(bx - 2, by - 1, tw + 6, th + 2, bg_color)
            painter.setPen(text_color)
            painter.drawText(bx + 2, by + mfm.ascent(), lbl)

        draw_one(self.marker1, "M1-A", QColor(60, 48, 0, 200), QColor(255, 200, 0), 0)
        draw_one(self.marker2, "M2-B", QColor(60, 22, 10, 200), QColor(255, 110, 60), 1, use_b=True)

        if self.marker1 and self.marker2:
            delta = self.marker2[1] - self.marker1[1]
            dt = self.marker2[0] - self.marker1[0]
            lbl = f"{'Δ'}={delta:.5g}  Δt={dt:.2f}s"
            dfont = QFont("Consolas", 8)
            painter.setFont(dfont)
            dfm = QFontMetrics(dfont)
            tw, th = dfm.horizontalAdvance(lbl), dfm.height()
            bx = px + pw // 2 - tw // 2
            by = py + ph - th - 6
            painter.fillRect(bx - 4, by - 2, tw + 8, th + 4, QColor(*self._ol["bg_tooltip"]))
            painter.setPen(QColor(*self._ol["text_tooltip"]))
            painter.drawText(bx, by + dfm.ascent(), lbl)

        painter.end()

    def mouseMoveEvent(self, event):
        self._mouse_pos = event.pos()
        if self._pan_origin is not None and (event.buttons() & Qt.MiddleButton):
            dy_px = event.pos().y() - self._pan_origin.y()
            dx_px = event.pos().x() - self._pan_origin.x()
            px, py, pw, ph = self._plot_rect()
            span_y_a = self.y_max_a - self.y_min_a
            self.pan_y_a = self._pan_y0_a - dy_px / ph * span_y_a
            span_y_b = self.y_max_b - self.y_min_b
            self.pan_y_b = self._pan_y0_b - dy_px / ph * span_y_b
            span_x = self.x_max - self.x_min
            self.x_min = self._pan_x0 - dx_px / pw * span_x
            self.x_max = self.x_min + span_x
            self._apply_zoom_pan()
        self.update()

    def mousePressEvent(self, event):
        px, py, pw, ph = self._plot_rect()
        if not (px <= event.x() <= px + pw and py <= event.y() <= py + ph):
            return
        xi, yv_a = self._screen_to_data_a(event.x(), event.y())
        _, yv_b = self._screen_to_data_b(event.x(), event.y())
        actual_y_a = yv_a
        actual_y_b = yv_b
        if self.times:
            idx = min(range(len(self.times)), key=lambda i: abs(self.times[i] - xi))
            if self.enable_a and np.isfinite(self.data_a[idx]):
                actual_y_a = float(self.data_a[idx])
            if self.enable_b and np.isfinite(self.data_b[idx]):
                actual_y_b = float(self.data_b[idx])

        if event.button() == Qt.LeftButton:
            self.marker1 = (xi, actual_y_a)
        elif event.button() == Qt.RightButton:
            self.marker2 = (xi, actual_y_b)
        elif event.button() == Qt.MiddleButton:
            self._pan_origin = event.pos()
            self._pan_x0 = self.x_min
            self._pan_y0_a = self.pan_y_a
            self._pan_y0_b = self.pan_y_b
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
        ctrl = event.modifiers() & Qt.ControlModifier
        if ctrl:
            self.zoom_x = np.clip(self.zoom_x * factor, 0.1, 10.0)
        else:
            mx = event.x()
            if py <= event.y() <= py + ph:
                # Left third → Ch A Y zoom, right third → Ch B Y zoom
                third = pw / 3
                if mx < px + third:
                    chan = 'A'
                elif mx > px + pw - third:
                    chan = 'B'
                else:
                    chan = 'A'

                if chan == 'A':
                    _, yv = self._screen_to_data_a(event.x(), event.y())
                    self.zoom_y_a = np.clip(self.zoom_y_a * factor, 0.05, 200.0)
                    cy = (self._y_min_auto_a + self._y_max_auto_a) / 2
                    hy = (self._y_max_auto_a - self._y_min_auto_a) / 2 / max(self.zoom_y_a, 0.001)
                    new_min = cy - hy
                    span = self.y_max_a - self.y_min_a
                    frac = (yv - self.y_min_a) / span if span else 0.5
                    new_span = hy * 2
                    self.pan_y_a = (yv - frac * new_span) - new_min
                else:
                    _, yv = self._screen_to_data_b(event.x(), event.y())
                    self.zoom_y_b = np.clip(self.zoom_y_b * factor, 0.05, 200.0)
                    cy = (self._y_min_auto_b + self._y_max_auto_b) / 2
                    hy = (self._y_max_auto_b - self._y_min_auto_b) / 2 / max(self.zoom_y_b, 0.001)
                    new_min = cy - hy
                    span = self.y_max_b - self.y_min_b
                    frac = (yv - self.y_min_b) / span if span else 0.5
                    new_span = hy * 2
                    self.pan_y_b = (yv - frac * new_span) - new_min
            else:
                self.zoom_y_a = np.clip(self.zoom_y_a * factor, 0.05, 200.0)
                self.zoom_y_b = np.clip(self.zoom_y_b * factor, 0.05, 200.0)
            self._apply_zoom_pan()
        self.update()
        event.accept()


class EnhancedGLPlot(QWidget):
    """Container widget with toolbar and embedded _GLPlotWidget."""

    data_updated = pyqtSignal(float, float, float)

    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.plot = _GLPlotWidget(self)
        layout.addWidget(self.plot, 1)

        toolbar = QHBoxLayout()
        toolbar.setSpacing(4)
        self._auto_btn = QPushButton("Auto Zoom")
        self._auto_btn.clicked.connect(self.plot.reset_zoom)
        self._clear_btn = QPushButton("Clear")
        self._clear_btn.clicked.connect(self.plot.clear_data)
        self._fill_btn = QPushButton("Fill")
        self._fill_btn.setCheckable(True)
        self._fill_btn.toggled.connect(lambda c: setattr(self.plot, 'show_fill', c) or self.plot.update())

        self._ch_b_btn = QPushButton("Ch B")
        self._ch_b_btn.setCheckable(True)
        self._ch_b_btn.toggled.connect(lambda c: self.plot.set_channel_enabled("B", c))

        toolbar.addWidget(self._auto_btn)
        toolbar.addWidget(self._clear_btn)
        toolbar.addStretch()
        toolbar.addWidget(self._fill_btn)
        toolbar.addWidget(self._ch_b_btn)
        layout.addLayout(toolbar)

        self.plot.data_updated.connect(self.data_updated)

    def update_readings(self, val_a, val_b, timestamp=None):
        self.plot.update_readings(val_a, val_b, timestamp)

    def set_y_unit(self, unit):
        self.plot.y_unit_a = unit
        self.plot.y_unit_b = unit

    def set_y_unit_a(self, unit):
        self.plot.y_unit_a = unit

    def set_y_unit_b(self, unit):
        self.plot.y_unit_b = unit

    def set_y_label_a(self, label):
        self.plot.y_label_a = label

    def set_y_label_b(self, label):
        self.plot.y_label_b = label

    def clear_data(self):
        self.plot.clear_data()

    def set_theme(self, is_dark):
        self.plot.set_theme(is_dark)

    def set_buffer_size(self, n):
        self.plot.set_buffer_size(n)
