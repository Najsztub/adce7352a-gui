"""
ADCMT 7352A Main Application Window

NI InstrumentStudio-style 3-pane layout:
  Left:   Collapsible control panels (scrollable)
  Center: Tabbed content (plot, statistics, export, console, status)
  
Supports dual-channel measurement via SD0 mode.
"""

import time
import logging
from collections import deque

from PyQt5.QtCore import Qt
from PyQt5.QtWidgets import (QMainWindow, QWidget, QVBoxLayout,
    QHBoxLayout, QSplitter, QScrollArea, QLabel, QMessageBox,
    QTabWidget, QPushButton, QGroupBox, QComboBox, QCheckBox, QLineEdit,
    QStatusBar, QMenuBar, QMenu, QAction, QFrame)
from ..core.config import AppConfig
from ..core.theme import ThemeColors

log = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, app):
        super().__init__()
        self._app = app
        self._instrument = None
        self._worker = None
        self._gl_plot = None
        self._ts_a = deque(maxlen=600)
        self._vals_a = deque(maxlen=600)
        self._ts_b = deque(maxlen=600)
        self._vals_b = deque(maxlen=600)
        self._t0 = None

        self._config = AppConfig()
        self._theme = ThemeColors(True)
        self._config_restore = True

        self.setWindowTitle("ADCMT 7352A  —  Digital Multimeter Controller  [ADC mode]")
        self.setMinimumSize(1100, 750)

        geo = self._config.restore_window_geometry()
        if geo:
            self.restoreGeometry(geo)
        else:
            self.resize(1400, 880)
        state = self._config.restore_window_state()
        if state:
            self.restoreState(state)

        self._load_themes()
        self._build_menu()
        self._build_central()
        self._build_status_bar()

        self._restore_ui_state()

    def setup_instrument(self, instrument):
        self._instrument = instrument

    def _load_themes(self):
        import os
        base = os.path.join(os.path.dirname(__file__), "..", "resources")
        dark_path = os.path.join(base, "styles.qss")
        light_path = os.path.join(base, "light.qss")
        self._dark_qss = ""
        self._light_qss = ""
        try:
            with open(dark_path) as f:
                self._dark_qss = f.read()
            with open(light_path) as f:
                self._light_qss = f.read()
        except OSError as e:
            log.warning("Could not load theme files: %s", e)

    def _toggle_theme(self, use_dark):
        self._theme = ThemeColors(use_dark)
        app = self._app
        if use_dark:
            app.setStyleSheet(self._dark_qss)
        else:
            app.setStyleSheet(self._light_qss)
        if self._gl_plot:
            self._gl_plot.set_theme(use_dark)
        if self._instrument and self._instrument.connected:
            self.update_status(True)
        else:
            self.update_status(False)
        self._sb.showMessage("Dark theme" if use_dark else "Light theme")

    def _build_menu(self):
        mb = self.menuBar()
        file_menu = mb.addMenu("&File")
        exit_action = QAction("Exit", self)
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = mb.addMenu("&View")
        self._action_dark = QAction("Dark Theme", self, checkable=True)
        self._action_dark.setChecked(True)
        self._action_dark.triggered.connect(self._toggle_theme)
        view_menu.addAction(self._action_dark)

        help_menu = mb.addMenu("&Help")
        about_action = QAction("About", self)
        about_action.triggered.connect(self._show_about)
        help_menu.addAction(about_action)

    def _build_central(self):
        central = QWidget()
        self.setCentralWidget(central)
        root_layout = QHBoxLayout(central)
        root_layout.setSpacing(0)
        root_layout.setContentsMargins(0, 0, 0, 0)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        left_scroll.setMinimumWidth(260)
        left_scroll.setMaximumWidth(400)

        left_panel = self._build_left_panel()
        left_scroll.setWidget(left_panel)

        right_panel = self._build_right_panel()

        self._splitter = QSplitter(Qt.Horizontal)
        self._splitter.addWidget(left_scroll)
        self._splitter.addWidget(right_panel)
        self._splitter.setCollapsible(0, False)
        self._splitter.setCollapsible(1, False)
        self._splitter.setSizes([300, 1100])
        root_layout.addWidget(self._splitter, 1)

    def _build_left_panel(self):
        panel = QWidget()
        panel.setObjectName("leftPanel")
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(4)

        title = QLabel("ADCMT 7352A")
        title.setObjectName("titleLabel")
        layout.addWidget(title)
        subtitle = QLabel("Digital Multimeter  [ADC mode]")
        subtitle.setObjectName("subtitleLabel")
        layout.addWidget(subtitle)

        self._status_bar_widget = QWidget()
        sb_layout = QHBoxLayout(self._status_bar_widget)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        self._status_dot = QLabel("●")
        self._status_dot.setStyleSheet("color: #f85149; font-size: 14px;")
        self._status_label = QLabel("DISCONNECTED")
        self._status_label.setStyleSheet("color: #f85149; font-weight: bold; font-size: 10px;")
        sb_layout.addWidget(self._status_dot)
        sb_layout.addWidget(self._status_label)
        sb_layout.addStretch()
        layout.addWidget(self._status_bar_widget)

        layout.addWidget(self._build_connection_section())
        layout.addWidget(self._build_channels_section())
        layout.addWidget(self._build_acquisition_section())
        layout.addWidget(self._build_calculation_section())

        layout.addStretch()
        return panel

    def _btn(self, text, callback, color=None):
        btn = QPushButton(text)
        btn.clicked.connect(callback)
        return btn

    def _grp(self, title):
        g = QGroupBox(title)
        return g

    def _build_connection_section(self):
        g = self._grp("CONNECTION")
        layout = QVBoxLayout(g)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(4)

        self._mode_combo = QComboBox()
        self._mode_combo.addItems(["Mock Device (Testing)", "Real Device (VISA)"])
        self._mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        layout.addWidget(QLabel("Backend:"))
        layout.addWidget(self._mode_combo)

        self._resource_edit = QLineEdit("USB0::4916::520::999991006::0::INSTR")
        self._resource_edit.setEnabled(False)
        layout.addWidget(QLabel("Resource:"))
        layout.addWidget(self._resource_edit)

        btn_row = QHBoxLayout()
        self._connect_btn = self._btn("CONNECT", self._toggle_connection, "#3fb950")
        btn_row.addWidget(self._connect_btn)
        idn_btn = self._btn("IDN?", self._query_idn, "#8b949e")
        btn_row.addWidget(idn_btn)
        layout.addLayout(btn_row)

        self._idn_label = QLabel("—")
        self._idn_label.setObjectName("idnLabel")
        self._idn_label.setWordWrap(True)
        layout.addWidget(self._idn_label)

        return g

    def _build_channels_section(self):
        from ..commands.adc_commands import (FUNCTIONS, FUNCTION_KEYS_A,
            FUNCTION_KEYS_B, SRATE_DISP, DIGITS_DISP)

        g = self._grp("CHANNELS")
        layout = QVBoxLayout(g)
        layout.setContentsMargins(4, 10, 4, 4)
        layout.setSpacing(2)

        self._ch_tabs = QTabWidget()
        self._ch_tabs.setObjectName("chTabs")
        self._ch_tabs.setDocumentMode(True)

        def build_tab(prefix, func_keys, color):
            tab = QWidget()
            tl = QVBoxLayout(tab)
            tl.setContentsMargins(4, 6, 4, 4)
            tl.setSpacing(3)

            cb = QCheckBox("Enable Channel")
            cb.setChecked(prefix == "A")
            setattr(self, f"_chk_{prefix}", cb)
            tl.addWidget(cb)

            tl.addWidget(QLabel("Function:"))
            fc = QComboBox()
            fc.addItems([FUNCTIONS[k][0] for k in func_keys])
            setattr(self, f"_func_combo_{prefix}", fc)
            tl.addWidget(fc)

            tl.addWidget(QLabel("Range:"))
            rc = QComboBox()
            setattr(self, f"_range_combo_{prefix}", rc)
            tl.addWidget(rc)
            self._refresh_ranges(prefix, func_keys)
            fc.currentTextChanged.connect(lambda _, p=prefix, fk=func_keys: self._refresh_ranges(p, fk))

            rate_row = QHBoxLayout()
            rate_row.addWidget(QLabel("Rate:"))
            rc2 = QComboBox()
            rc2.addItems(SRATE_DISP)
            rc2.setCurrentText("MED")
            setattr(self, f"_rate_combo_{prefix}", rc2)
            rate_row.addWidget(rc2)
            tl.addLayout(rate_row)

            digits_row = QHBoxLayout()
            digits_row.addWidget(QLabel("Digits:"))
            dc = QComboBox()
            dc.addItems(DIGITS_DISP)
            dc.setCurrentText("5½")
            setattr(self, f"_digits_combo_{prefix}", dc)
            digits_row.addWidget(dc)
            tl.addLayout(digits_row)

            az = QCheckBox("Auto-Zero ON")
            az.setChecked(True)
            setattr(self, f"_az_check_{prefix}", az)
            tl.addWidget(az)

            apply_btn = QPushButton("APPLY")
            apply_btn.setObjectName("applyBtn" + prefix)
            if prefix == "A":
                apply_btn.clicked.connect(self._apply_ch_a)
            else:
                apply_btn.clicked.connect(self._apply_ch_b)
            tl.addWidget(apply_btn)

            return tab

        tab_a = build_tab("A", FUNCTION_KEYS_A, "#58a6ff")
        tab_b = build_tab("B", FUNCTION_KEYS_B, "#bc8cff")
        self._ch_tabs.addTab(tab_a, "  Ch A  ")
        self._ch_tabs.addTab(tab_b, "  Ch B  ")

        layout.addWidget(self._ch_tabs)
        return g

    def _refresh_ranges(self, prefix, func_keys):
        from ..commands.adc_commands import FUNCTIONS
        combo = getattr(self, f"_range_combo_{prefix}")
        fk = getattr(self, f"_func_combo_{prefix}").currentText()
        for k in func_keys:
            if FUNCTIONS[k][0] == fk:
                combo.clear()
                combo.addItems([r[0] for r in FUNCTIONS[k][2]])
                return
        combo.clear()

    def _cur_fkey(self, prefix):
        from ..commands.adc_commands import FUNCTIONS
        combo = getattr(self, f"_func_combo_{prefix}")
        label = combo.currentText()
        for k, v in FUNCTIONS.items():
            if v[0] == label:
                return k
        return "F1" if prefix == "A" else "F12"

    def _build_acquisition_section(self):
        g = self._grp("ACQUISITION")
        layout = QVBoxLayout(g)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(4)

        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Interval (ms):"))
        self._interval_edit = QLineEdit("500")
        self._interval_edit.setMaximumWidth(70)
        interval_row.addWidget(self._interval_edit)
        interval_row.addStretch()
        layout.addLayout(interval_row)

        btn_row = QHBoxLayout()
        self._start_btn = self._btn("▶ START", self._start_acq, "#3fb950")
        self._stop_btn = self._btn("■ STOP", self._stop_acq, "#d29922")
        self._stop_btn.setEnabled(False)
        btn_row.addWidget(self._start_btn)
        btn_row.addWidget(self._stop_btn)
        layout.addLayout(btn_row)

        clear_btn = self._btn("CLEAR DATA", self._clear_data, "#8b949e")
        layout.addWidget(clear_btn)

        return g

    def _build_calculation_section(self):
        g = self._grp("CALCULATIONS")
        layout = QVBoxLayout(g)
        layout.setContentsMargins(8, 10, 8, 8)
        layout.setSpacing(3)

        self._nl_check = QCheckBox("NULL  (NL0/NL1)")
        self._sm_check = QCheckBox("Smoothing  (SM0/SM1)")
        self._co_check = QCheckBox("Comparator  (CO0/CO1)")
        self._mn_check = QCheckBox("MAX/MIN  (MN0/MN1)")

        for cb in (self._nl_check, self._sm_check, self._co_check, self._mn_check):
            layout.addWidget(cb)

        hi_row = QHBoxLayout()
        hi_row.addWidget(QLabel("HI:"))
        self._hi_edit = QLineEdit("10.0")
        self._hi_edit.setMaximumWidth(80)
        hi_row.addWidget(self._hi_edit)
        hi_row.addWidget(QLabel("LO:"))
        self._lo_edit = QLineEdit("-10.0")
        self._lo_edit.setMaximumWidth(80)
        hi_row.addWidget(self._lo_edit)
        hi_row.addStretch()
        layout.addLayout(hi_row)

        apply_calc = self._btn("APPLY CALCULATIONS", self._apply_calc, "#bc8cff")
        layout.addWidget(apply_calc)
        read_stats = self._btn("READ STATS", self._read_stats, "#8b949e")
        layout.addWidget(read_stats)

        return g

    def _build_right_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.setContentsMargins(6, 6, 6, 6)
        layout.setSpacing(4)

        live_bar = QFrame()
        live_bar.setObjectName("liveBar")
        live_layout = QHBoxLayout(live_bar)
        live_layout.setContentsMargins(10, 6, 10, 6)

        live_layout.addWidget(self._live_label("A:"))
        self._live_val_a = self._live_label("— — — — — —", "26px")
        self._live_val_a.setObjectName("liveValA")
        live_layout.addWidget(self._live_val_a)
        self._live_unit_a = self._live_label("", "12px")
        self._live_unit_a.setObjectName("liveUnitA")
        live_layout.addWidget(self._live_unit_a)

        sep = QLabel("  |  ")
        sep.setObjectName("liveSep")
        live_layout.addWidget(sep)

        live_layout.addWidget(self._live_label("B:"))
        self._live_val_b = self._live_label("— — — — — —", "26px")
        self._live_val_b.setObjectName("liveValB")
        live_layout.addWidget(self._live_val_b)
        self._live_unit_b = self._live_label("", "12px")
        self._live_unit_b.setObjectName("liveUnitB")
        live_layout.addWidget(self._live_unit_b)

        live_layout.addStretch()
        self._live_subheader = self._live_label("", "10px")
        self._live_subheader.setObjectName("liveSubheader")
        live_layout.addWidget(self._live_subheader)
        layout.addWidget(live_bar)

        self._tabs = QTabWidget()
        self._tabs.setDocumentMode(True)

        self._plot_tab = self._build_plot_tab()
        self._tabs.addTab(self._plot_tab, "  Live Plot  ")

        from .tabs.stats_tab import StatisticsTab
        from .tabs.export_tab import ExportTab
        from .tabs.console_tab import ConsoleTab

        self._stats_tab = StatisticsTab()
        self._tabs.addTab(self._stats_tab, "  Statistics  ")

        self._export_tab = ExportTab()
        self._tabs.addTab(self._export_tab, "  Export  ")

        self._console_tab = ConsoleTab()
        self._tabs.addTab(self._console_tab, "  Console  ")

        layout.addWidget(self._tabs, 1)
        return widget

    def _live_label(self, text, size="14px"):
        lbl = QLabel(text)
        lbl.setStyleSheet(f"font-size: {size}; font-weight: bold;")
        return lbl

    def _build_plot_tab(self):
        from ..plotting.gl_plot import EnhancedGLPlot
        self._gl_plot = EnhancedGLPlot(self)
        return self._gl_plot

    def _build_status_bar(self):
        self._sb = QStatusBar()
        self.setStatusBar(self._sb)
        self._sb.showMessage("Ready  |  ADC mode  |  Disconnected")

    def _show_about(self):
        QMessageBox.about(self, "About ADCMT 7352A Controller",
            "ADCMT 7352A Digital Multimeter Controller\n"
            "ADC Command Mode\n"
            "Version 1.0.0\n\n"
            "Based on the official ADCMT 7352A Operation Manual\n"
            "FOE-8440254B00")

    def update_status(self, connected):
        t = self._theme
        if connected:
            self._status_dot.setStyleSheet(f"color: {t.conn_ok}; font-size: 14px;")
            self._status_label.setText("CONNECTED")
            self._status_label.setStyleSheet(f"color: {t.conn_ok}; font-weight: bold; font-size: 10px;")
            self._connect_btn.setText("DISCONNECT")
            self._connect_btn.setStyleSheet(f"color: {t.conn_err}; font-weight: bold;")
            self._sb.showMessage("Connected  |  ADC mode  |  USB0::4916::520::999991006::0::INSTR")
        else:
            self._status_dot.setStyleSheet(f"color: {t.conn_err}; font-size: 14px;")
            self._status_label.setText("DISCONNECTED")
            self._status_label.setStyleSheet(f"color: {t.conn_err}; font-weight: bold; font-size: 10px;")
            self._connect_btn.setText("CONNECT")
            self._connect_btn.setStyleSheet(f"color: {t.conn_ok}; font-weight: bold;")
            self._sb.showMessage("Disconnected  |  ADC mode")

    def _on_mode_changed(self, idx):
        self._resource_edit.setEnabled(idx == 1)

    def _toggle_connection(self):
        if self._instrument and self._instrument.connected:
            self._disconnect()
        else:
            self._connect()

    def _connect(self):
        from ..instruments.adcmt7352a_adc import ADCMT7352A
        use_mock = self._mode_combo.currentIndex() == 0
        resource = self._resource_edit.text() if not use_mock else None
        self._instrument = ADCMT7352A(use_mock=use_mock, resource_string=resource)
        if self._instrument.connect():
            self._console_tab.set_instrument(self._instrument)
            self.update_status(True)
            self._query_idn()
        else:
            QMessageBox.critical(self, "Connection Error", "Failed to connect to instrument")

    def _disconnect(self):
        if self._worker and self._worker.isRunning():
            self._stop_acq()
        if self._instrument:
            self._instrument.disconnect()
        self.update_status(False)

    def _query_idn(self):
        if self._instrument and self._instrument.connected:
            idn = self._instrument.get_idn()
            if idn:
                self._idn_label.setText(idn)

    def _apply_ch_a(self):
        if not self._instrument or not self._instrument.connected:
            QMessageBox.warning(self, "Not Connected", "Connect to instrument first")
            return
        from ..commands.adc_commands import (FUNCTIONS, SRATE_CMD, SRATE_DISP,
                                             DIGITS_CMD, DIGITS_DISP)
        fk = self._cur_fkey("A")
        rng_idx = self._range_combo_A.currentIndex()
        func_ranges = FUNCTIONS[fk][2]
        r_cmd = func_ranges[rng_idx][1] if rng_idx < len(func_ranges) else "R0"
        rate_cmd = SRATE_CMD[SRATE_DISP.index(self._rate_combo_A.currentText())]
        digits_cmd = DIGITS_CMD[DIGITS_DISP.index(self._digits_combo_A.currentText())]
        az = self._az_check_A.isChecked()
        self._instrument.apply_settings_ch_a(fk, r_cmd, rate_cmd, digits_cmd, az)
        self._sb.showMessage(f"Ch A applied: {fk}, {r_cmd}, {rate_cmd}, {digits_cmd}, AZ{'1' if az else '0'}")

    def _apply_ch_b(self):
        if not self._instrument or not self._instrument.connected:
            QMessageBox.warning(self, "Not Connected", "Connect to instrument first")
            return
        from ..commands.adc_commands import (FUNCTIONS, SRATE_CMD, SRATE_DISP,
                                             DIGITS_CMD, DIGITS_DISP)
        fk = self._cur_fkey("B")
        rng_idx = self._range_combo_B.currentIndex()
        func_ranges = FUNCTIONS[fk][2]
        r_cmd = func_ranges[rng_idx][1] if rng_idx < len(func_ranges) else "R0"
        rate_cmd = SRATE_CMD[SRATE_DISP.index(self._rate_combo_B.currentText())]
        digits_cmd = DIGITS_CMD[DIGITS_DISP.index(self._digits_combo_B.currentText())]
        az = self._az_check_B.isChecked()
        self._instrument.apply_settings_ch_b(fk, r_cmd, rate_cmd, digits_cmd, az)
        self._sb.showMessage(f"Ch B applied: {fk}, {r_cmd}, {rate_cmd}, {digits_cmd}, AZ{'1' if az else '0'}")

    def _apply_calc(self):
        if not self._instrument or not self._instrument.connected:
            return
        try:
            hi = float(self._hi_edit.text())
            lo = float(self._lo_edit.text())
        except ValueError:
            hi, lo = 10.0, -10.0
        self._instrument.apply_calc(
            nl=self._nl_check.isChecked(),
            sm=self._sm_check.isChecked(),
            co=self._co_check.isChecked(),
            mn=self._mn_check.isChecked(),
            hi=hi, lo=lo)
        self._sb.showMessage("Calculations applied")

    def _read_stats(self):
        if not self._instrument or not self._instrument.connected:
            return
        stats = self._instrument.read_stats()
        msg = "\n".join(f"{k}: {v}" for k, v in stats.items())
        QMessageBox.information(self, "Statistics", msg if msg else "(empty)")

    def _start_acq(self):
        if not self._instrument or not self._instrument.connected:
            QMessageBox.warning(self, "Not Connected", "Connect to instrument first")
            return
        from ..core.worker import AcquisitionWorker
        try:
            iv = int(self._interval_edit.text())
        except ValueError:
            iv = 500
        iv = max(50, iv)

        self._t0 = time.time()
        self._ts_a.clear()
        self._vals_a.clear()
        self._ts_b.clear()
        self._vals_b.clear()

        ch_a = self._chk_A.isChecked()
        ch_b = self._chk_B.isChecked()

        if self._gl_plot:
            if ch_a:
                self._gl_plot.set_y_label_a("Ch A")
            if ch_b:
                self._gl_plot.set_y_label_b("Ch B")

        self._worker = AcquisitionWorker(self._instrument, self)
        self._worker.set_interval(iv)
        self._worker.set_ch_a_enabled(ch_a)
        self._worker.set_ch_b_enabled(ch_b)
        self._worker.set_func_key_a(self._cur_fkey("A"))
        self._worker.set_func_key_b(self._cur_fkey("B"))
        self._worker.data_received.connect(self._on_data)
        self._worker.data_plot.connect(self._on_plot_data)
        self._worker.error_occurred.connect(self._on_worker_error)
        self._worker.start()

        self._start_btn.setEnabled(False)
        self._stop_btn.setEnabled(True)
        modes = []
        if ch_a: modes.append("A")
        if ch_b: modes.append("B")
        self._sb.showMessage(f"Acquisition started  ({'+'.join(modes)})  interval={iv}ms")

    def _stop_acq(self):
        if self._worker and self._worker.isRunning():
            self._worker.stop()
            self._worker.wait(2000)
        self._start_btn.setEnabled(True)
        self._stop_btn.setEnabled(False)
        self._sb.showMessage("Acquisition stopped")

    def _clear_data(self):
        self._ts_a.clear()
        self._vals_a.clear()
        self._ts_b.clear()
        self._vals_b.clear()
        if self._gl_plot:
            self._gl_plot.clear_data()

    def _get_unit(self, fk):
        from ..commands.adc_commands import FUNCTIONS
        return FUNCTIONS.get(fk, ("", "V", "", ""))[1]

    def _on_data(self, result):
        t = self._theme
        now = time.time()
        if self._t0:
            elapsed = now - self._t0
        else:
            elapsed = 0.0
        if 'A' in result:
            val, mh, sh, is_ol, disp, desc = result['A']
            self._ts_a.append(elapsed)
            self._vals_a.append(val)
            unit_a = self._get_unit(self._cur_fkey("A"))
            self._live_val_a.setText(disp)
            clr = t.live_ol if is_ol else (t.live_warn if sh not in ("_", "") else t.live_ok_a)
            self._live_val_a.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {clr};")
            self._live_unit_a.setText(unit_a)
            if self._gl_plot:
                self._gl_plot.set_y_unit_a(unit_a)

        if 'B' in result:
            val, mh, sh, is_ol, disp, desc = result['B']
            self._ts_b.append(elapsed)
            self._vals_b.append(val)
            unit_b = self._get_unit(self._cur_fkey("B"))
            self._live_val_b.setText(disp)
            clr = t.live_ol if is_ol else (t.live_warn if sh not in ("_", "") else t.live_ok_b)
            self._live_val_b.setStyleSheet(f"font-size: 26px; font-weight: bold; color: {clr};")
            self._live_unit_b.setText(unit_b)
            if self._gl_plot:
                self._gl_plot.set_y_unit_b(unit_b)

        self._stats_tab.update("A", self._vals_a)
        self._stats_tab.update("B", self._vals_b)
        self._export_tab.write_data(result)

    def _on_plot_data(self, ts_a, vals_a, ts_b, vals_b):
        if self._gl_plot:
            va = vals_a[-1] if vals_a else 0.0
            vb = vals_b[-1] if vals_b else 0.0
            ta = ts_a[-1] if ts_a else None
            self._gl_plot.update_readings(va, vb, ta)

    def _on_worker_error(self, msg):
        self._sb.showMessage(f"Error: {msg}")
        self._stop_acq()

    def _restore_ui_state(self):
        fka = self._config.restore_last_function_a()
        try:
            idx_a = self._func_combo_A.findText(
                __import__("gui.commands.adc_commands", fromlist=["FUNCTIONS"]).FUNCTIONS[fka][0])
            if idx_a >= 0:
                self._func_combo_A.setCurrentIndex(idx_a)
        except Exception:
            pass
        fkb = self._config.restore_last_function_b()
        try:
            idx_b = self._func_combo_B.findText(
                __import__("gui.commands.adc_commands", fromlist=["FUNCTIONS"]).FUNCTIONS[fkb][0])
            if idx_b >= 0:
                self._func_combo_B.setCurrentIndex(idx_b)
        except Exception:
            pass
        cha = self._config.restore_ch_a_enabled()
        self._chk_A.setChecked(cha)
        chb = self._config.restore_ch_b_enabled()
        self._chk_B.setChecked(chb)
        iv = self._config.restore_read_interval()
        self._interval_edit.setText(str(iv))
        is_dark = self._config.restore_dark_theme()
        self._action_dark.setChecked(is_dark)
        self._toggle_theme(is_dark)

    def closeEvent(self, event):
        self._stop_acq()
        self._export_tab.close()
        if self._instrument:
            self._instrument.disconnect()
        self._config.save_window_geometry(self.saveGeometry())
        self._config.save_window_state(self.saveState())
        self._config.save_ch_a_enabled(self._chk_A.isChecked())
        self._config.save_ch_b_enabled(self._chk_B.isChecked())
        self._config.save_read_interval(int(self._interval_edit.text()))
        self._config.save_dark_theme(self._action_dark.isChecked())
        self._config.sync()
        super().closeEvent(event)
