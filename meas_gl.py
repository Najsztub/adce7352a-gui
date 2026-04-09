import sys
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

from DMMGLPlot import DMMGLPlot

from mock import MockDMMDevice, FUNCTION_RANGES

from adceDev import *

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
        self.toggled.connect(self._on_toggled)
        
    def _toggle_style(self):
        """Update title with collapse/expand indicator."""
        state = "▼" if self.isChecked() else "▶"
        orig_title = self.title().rstrip(" ▼▶ ")
        self.setTitle(f"{orig_title} {state}")
    
    def _on_toggled(self, checked):
        self._toggle_style()
        # Show/hide all child widgets
        for w in self.children():
            if w != self.layout():  # Skip the layout itself
                w.setVisible(checked)




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
        # Refresh rate selector
        self.cb_rate = QComboBox()
        self.cb_rate.addItems(["50 ms", "100 ms", "200 ms", "500 ms", "1 s", "2 s"])
        self.cb_rate.setCurrentIndex(3)  # Default: 500 ms
        self.cb_rate.setToolTip("Refresh interval for continuous reading")
        self.cb_rate.currentIndexChanged.connect(self._on_poll_rate_changed)
        lay.addWidget(self.cb_rate)
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
            return f"{label}: idx={int(m[0])}  val={si_fmt(m[1], self.gl_plot.y_unit) if self.gl_plot.y_unit else f'{m[1]:.6g}'}"
        self.lbl_m1.setText(fmt(self.gl_plot.marker1, "M1"))
        self.lbl_m2.setText(fmt(self.gl_plot.marker2, "M2"))
        if self.gl_plot.marker1 and self.gl_plot.marker2:
            d = self.gl_plot.marker2[1] - self.gl_plot.marker1[1]
            self.lbl_mdl.setText(f"Δ = {si_fmt(d, self.gl_plot.y_unit) if self.gl_plot.y_unit else f'{d:.6g}'}")
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
            def f(v): return si_fmt(v, unit) if unit else f"{v:.6g}"
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
        fk = cur_fkey(self.cb_func_A.currentText())
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
            # Use selected poll rate
            rate_ms = [50, 100, 200, 500, 1000, 2000][self.cb_rate.currentIndex()]
            self.poll_timer.start(rate_ms)
        else:
            self.poll_timer.stop()

    def _on_poll_rate_changed(self, index):
        """Handle poll rate combo change - restart timer if running."""
        if self.is_continuous and self.poll_timer.isActive():
            rate_ms = [50, 100, 200, 500, 1000, 2000][index]
            self.poll_timer.stop()
            self.poll_timer.start(rate_ms)

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
            fk_a   = cur_fkey(self.cb_func_A.currentText()) if ch_a_enabled else "F1"
            fk_b   = cur_fkey(self.cb_func_B.currentText()) if ch_b_enabled else "F1"

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