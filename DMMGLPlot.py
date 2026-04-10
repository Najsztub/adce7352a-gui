import time
import numpy as np
from PyQt5.QtCore import Qt, QPoint, QPointF
from PyQt5.QtGui import QPainter, QColor, QPen, QBrush, QFont, QFontMetrics
from PyQt5.QtWidgets import QOpenGLWidget
from OpenGL.GL import *

from mock import MockDMMDevice, FUNCTION_RANGES
from adceDev import *

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
            lbl = si_fmt(yv, self.y_unit) if self.y_unit else f"{yv:.4g}"
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
                    lbl = f"{text}: {si_fmt(yv, self.y_unit)}"
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
                lbl = f"  {xi:.0f}  {si_fmt(yv, self.y_unit) if self.y_unit else f'{yv:.5g}'}"
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
            lbl = f"{label}: {si_fmt(mv, self.y_unit) if self.y_unit else f'{mv:.5g}'}"
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
            lbl   = f"Δ = {si_fmt(delta, self.y_unit) if self.y_unit else f'{delta:.5g}'}  (Δt={dt:.2f}s)"
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
