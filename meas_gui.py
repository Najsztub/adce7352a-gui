"""
ADCMT 7352A  Digital Multimeter  –  Control & Plot GUI (PyMeasure version)
Resource : USB0::4916::520::999991006::0::INSTR

Command language : ADC mode  (set on instrument: MENU → I/F → LANG → ADC)
Termination      : \r\n  (CR+LF) for both read and write
Reading data     : instrument continuously outputs measurements in free-run
                   mode (INIC1 + TRS0).  Data is obtained by a bare
                   instr.read() — no query command is needed.

Forked from adce7352a_gui2.py, recreated using pyMeasure Plotter.
"""

import threading
from pymeasure.display.Qt import QtWidgets, QtCore, QtGui
from pymeasure.experiment import IntegerParameter, FloatParameter, BooleanParameter, ListParameter
from pymeasure.experiment import Procedure, Results, Worker
from pymeasure.display import Plotter
import sys
import logging
import re
import math
import time
import collections
from threading import Lock

log = logging.getLogger(__name__)
log.addHandler(logging.NullHandler())

import pyvisa


BG = "#0d1117"
PANEL = "#161b22"
CARD = "#1c2128"
BORDER = "#30363d"
ACCENT = "#58a6ff"
GREEN = "#3fb950"
YELLOW = "#d29922"
RED = "#f85149"
ORANGE = "#e3b341"
PURPLE = "#bc8cff"
TEXT = "#c9d1d9"
MUTED = "#8b949e"
MAX_PTS = 600
OVERLOAD_THRESHOLD = 9.9e+36

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

SRATE_CMD = ["PR1", "PR2", "PR3", "PR4"]
SRATE_DISP = ["FAST", "MED", "SLOW1", "SLOW2"]

DIGITS_CMD = ["RE3", "RE4", "RE5"]
DIGITS_DISP = ["3½", "4½", "5½"]

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
    "BDV": "Bch DCV", "BDI": "Bch DCI", "BAI": "Bch ACI", "BCI": "Bch ACI+DC",
}


class Sim7352A:
    def __init__(self):
        self._func = "F1"
        self._range = "R0"
        self._srate = "PR2"
        self._digits = "RE5"
        self._az = "AZ1"
        self._hdr = "H1"
        self._nl = False
        self._sm = False
        self._sm_pts = 10
        self._co = False
        self._hi = 10.0
        self._lo = -10.0
        self._mn = False
        self._t0 = time.time()
        self._count = 0

    def _true_val(self):
        t = time.time() - self._t0
        fn = self._func
        if fn in ("F1", "F2", "F7", "F12"):
            return 3.2986 + 0.002*math.sin(t*0.7) + 3e-4*math.sin(t*13.1)
        if fn in ("F5", "F35"):
            return 0.1024 + 5e-4*math.cos(t*1.1)
        if fn in ("F6", "F8", "F36", "F37"):
            return 0.0981 + 4e-4*math.cos(t*1.3)
        if fn in ("F3", "F20"):
            return 9876.5 + 0.8*math.sin(t*0.3)
        if fn == "F50":
            return 50.001 + 1e-3*math.sin(t*0.1)
        if fn == "F40":
            return 23.45 + 0.05*math.sin(t*0.05)
        if fn == "F13":
            return 0.6234 + 2e-4*math.sin(t*0.8)
        if fn == "F22":
            return 4.7 + 0.01*math.sin(t*1.5)
        return 0.0

    def _hdr3(self):
        return FUNCTIONS.get(self._func, ("", "", "", "DCV"))[3]

    def _sub(self, val):
        if self._co:
            if val > self._hi:
                return "H"
            if val < self._lo:
                return "L"
            return "P"
        if self._nl:
            return "N"
        return "_"

    def _fmt_val(self, val):
        sign = "+" if val >= 0 else "-"
        return f"{sign}{abs(val):.5E}"

    def read(self):
        self._count += 1
        val = self._true_val()
        s = self._sub(val)
        if self._hdr == "H1":
            return f"{self._hdr3()}{s}  {self._fmt_val(val)}"
        return self._fmt_val(val)

    def write(self, cmd):
        cmd = cmd.strip().upper()
        if cmd.startswith("DSP1,"):
            cmd = cmd[5:]
        for fk in FUNCTIONS:
            if cmd == fk:
                self._func = fk
                return
        if cmd in ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"):
            self._range = cmd
            return
        if cmd in ("PR1", "PR2", "PR3", "PR4"):
            self._srate = cmd
            return
        if cmd in ("RE3", "RE4", "RE5"):
            self._digits = cmd
            return
        if cmd in ("AZ0", "AZ1", "AZ2"):
            self._az = cmd
            return
        if cmd in ("H0", "H1"):
            self._hdr = cmd
            return
        if cmd == "NL1":
            self._nl = True
            return
        if cmd == "NL0":
            self._nl = False
            return
        if cmd == "SM1":
            self._sm = True
            return
        if cmd == "SM0":
            self._sm = False
            return
        if cmd.startswith("TI"):
            try:
                self._sm_pts = int(cmd[2:])
            except:
                pass
            return
        if cmd == "CO1":
            self._co = True
            return
        if cmd == "CO0":
            self._co = False
            return
        if cmd.startswith("HI"):
            try:
                self._hi = float(cmd[2:])
            except:
                pass
            return
        if cmd.startswith("LO"):
            try:
                self._lo = float(cmd[2:])
            except:
                pass
            return
        if cmd == "MN1":
            self._mn = True
            return
        if cmd == "MN0":
            self._mn = False
            return

    def query(self, cmd):
        cmd = cmd.strip().upper()
        if cmd == "*IDN?":
            return "ADC Corp.,7352A,999991006,FW2.4.1"
        if cmd == "F?":
            return self._func
        if cmd == "R?":
            return self._range
        if cmd == "PR?":
            return self._srate
        if cmd == "RE?":
            return self._digits
        if cmd == "AZ?":
            return self._az
        if cmd == "H?":
            return self._hdr
        if cmd == "ERR?":
            return '+000,"No error"'
        if cmd == "NL?":
            return "NL1" if self._nl else "NL0"
        if cmd == "SM?":
            return "SM1" if self._sm else "SM0"
        if cmd == "TI?":
            return f"TI{self._sm_pts:03d}"
        if cmd == "CO?":
            return "CO1" if self._co else "CO0"
        if cmd == "HI?":
            return f"HI{self._hi:+.5E}"
        if cmd == "LO?":
            return f"LO{self._lo:+.5E}"
        if cmd == "MN?":
            return "MN1" if self._mn else "MN0"
        if cmd == "MAX?":
            v = self._true_val()
            return f"M {self._fmt_val(v * 1.005)}"
        if cmd == "MIN?":
            v = self._true_val()
            return f"I {self._fmt_val(v * 0.995)}"
        if cmd == "AVE?":
            return f"A {self._fmt_val(self._true_val())}"
        if cmd == "AVN?":
            return f"AVN{self._count:.5E}"
        if cmd in ("SCNT?", "SMAX?", "SMIN?", "SAVE?", "SSIG?", "SPTP?"):
            v = self._true_val()
            pfx = cmd[:4]
            return f"{pfx}{self._fmt_val(v)}"
        if cmd == "*OPC?":
            return "1"
        if cmd == "*STB?":
            return "16"
        if cmd == "INIC?":
            return "INIC1"
        if cmd == "TRS?":
            return "TRS0"
        return "+000"

    def close(self): pass


_HDR_RE = re.compile(r'^([A-Z0-9_]{3})([A-Z_])\s+([-+]?\d[\d.]*E[+-]\d+)\s*$')
_NUM_RE = re.compile(r'^([-+]?\d[\d.]*E[+-]\d+)')


def parse_adc_response(raw, func_key="F1"):
    main_h, sub_h = "", "_"
    m = _HDR_RE.match(raw)
    if m:
        main_h = m.group(1)
        sub_h = m.group(2)
        num_s = m.group(3)
    else:
        nm = _NUM_RE.match(raw)
        num_s = nm.group(1) if nm else raw
    try:
        val = float(num_s)
    except ValueError:
        return 0.0, main_h, sub_h, False, raw, raw
    is_ol = val >= OVERLOAD_THRESHOLD
    unit = FUNCTIONS.get(func_key, ("", "V", "", "DCV"))[1]
    disp = "OVERLOAD" if is_ol else si_fmt(val, unit)
    desc = HDR_LABELS.get(main_h, main_h) + \
        SUB_LABELS.get(sub_h, f" [{sub_h}]")
    return val, main_h, sub_h, is_ol, disp, desc


def si_fmt(val, unit):
    if val == 0:
        return f"0.000 {unit}"
    a = abs(val)
    for scale, pfx in [(1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"),
                       (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")]:
        if a >= scale * 0.9999:
            return f"{val/scale:.5g} {pfx}{unit}"
    return f"{val:.5E} {unit}"


class ADCInstrument:
    def __init__(self, resource_string=None, simulate=False):
        self.resource_string = resource_string
        self.simulate = simulate
        self.instr = None
        self.connected = False
        self._rlock = Lock()
        self._func_key = "F1"

    def connect(self):
        if self.simulate:
            self.instr = Sim7352A()
            self.connected = True
            log.info("Connected (simulation mode)")
            return True
        try:
            rm = pyvisa.ResourceManager()
            self.instr = rm.open_resource(self.resource_string)
            self.instr.timeout = 10000
            self.instr.write_termination = "\r\n"
            self.instr.read_termination = "\r\n"
            self.connected = True
            log.info(f"Connected: {self.resource_string}")
            return True
        except Exception as e:
            log.error(f"Connection error: {e}")
            return False

    def disconnect(self):
        if self.instr:
            try:
                self.instr.close()
            except:
                pass
        self.instr = None
        self.connected = False

    def write(self, cmd):
        if not self.connected:
            return
        with self._rlock:
            log.debug(f">> {cmd}")
            self.instr.write(cmd)
            time.sleep(0.025)

    def query(self, cmd):
        if not self.connected:
            return None
        with self._rlock:
            log.debug(f">> {cmd}")
            time.sleep(0.025)
            resp = self.instr.query(cmd).strip()
            log.debug(f"<< {resp}")
            return resp

    def read(self):
        if not self.connected:
            return None
        with self._rlock:
            return self.instr.read().strip()

    def get_idn(self):
        return self.query("*IDN?")

    def init_instrument(self):
        self.write("*RST")
        time.sleep(0.1)
        self.write("H1")
        self.write("DE0")
        self.write("SD1")
        self.write("TRS0")
        self.write("INIC1")


class ADCProcedure(Procedure):
    resource_string = "USB0::4916::520::999991006::0::INSTR"
    simulate = BooleanParameter('Simulate', default=True)

    read_interval = IntegerParameter('Read Interval (ms)', default=500)

    DATA_COLUMNS = ['Time (s)', 'Value', 'Status']

    def __init__(self):
        super().__init__()
        self.instrument = None
        self.running = False
        self._stop_flag = False

    def startup(self):
        log.info("Starting ADC procedure")
        self.instrument = ADCInstrument(
            resource_string=self.resource_string,
            simulate=self.simulate
        )
        if not self.instrument.connect():
            raise Exception("Failed to connect to instrument")

        self.instrument.init_instrument()
        self._apply_settings()

    def _apply_settings(self):
        if not self.instrument:
            return

        self.instrument.write(self.function)

        if not self.range_auto and self.range_value:
            self.instrument.write(self.range_value)

        si = SRATE_DISP.index(
            self.sampling_rate) if self.sampling_rate in SRATE_DISP else 1
        self.instrument.write(SRATE_CMD[si])

        di = DIGITS_DISP.index(
            self.digits) if self.digits in DIGITS_DISP else 2
        self.instrument.write(DIGITS_CMD[di])

        az = "AZ1" if self.auto_zero else "AZ0"
        self.instrument.write(az)

    def execute(self):
        self.running = True
        self._stop_flag = False
        t0 = time.time()
        ticker = 0

        log.info(f"Starting acquisition: interval={self.read_interval}ms")

        while not self._stop_flag:
            try:
                raw = self.instrument.read()
                if raw is None:
                    continue

                val, mh, sh, is_ol, disp, desc = parse_adc_response(
                    raw, self.function)
                elapsed = time.time() - t0

                status = "OK"
                if is_ol:
                    val = OVERLOAD_THRESHOLD * 1.1
                    status = "OVERLOAD"
                elif sh not in ("_", ""):
                    status = sh

                data = {
                    'Time (s)': elapsed,
                    'Value': val,
                    'Status': status
                }
                self.emit('results', data)

                if ticker >= 3:
                    ticker = 0
                else:
                    ticker += 1

            except Exception as e:
                log.error(f"Read error: {e}")
                time.sleep(0.5)
                continue

            elapsed_ms = (time.time() - t0) * 1000
            time.sleep(max(0.0, (self.read_interval - elapsed_ms) / 1000))

            if self.should_stop():
                log.warning("Caught stop flag")
                break

        self.running = False
        log.info("Acquisition stopped")

    def shutdown(self):
        if self.instrument:
            self.instrument.disconnect()
        log.info("Procedure shutdown")


class CustomPlotter(Plotter):
    def setup_plot(self, plot):
        plot.setBackground('k')
        plot.setLabel('bottom', 'Time', units='s')
        plot.setLabel('left', 'Value', units='')
        plot.showGrid(x=True, y=True, alpha=0.3)
        plot.setXRange(0, 10)
        plot.autoRange()


def make_style():
    return """
    QWidget { background-color: #0d1117; color: #c9d1d9; font-family: Consolas, monospace; }
    QLabel { color: #c9d1d9; }
    QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 8px; padding-top: 8px; }
    QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; }
    QPushButton { background-color: #161b22; color: #58a6ff; border: 1px solid #30363d; 
                  padding: 6px 12px; border-radius: 4px; }
    QPushButton:hover { background-color: #1c2128; border-color: #58a6ff; }
    QPushButton:pressed { background-color: #0d1117; }
    QLineEdit { background-color: #161b22; color: #58a6ff; border: 1px solid #30363d; 
                padding: 4px; border-radius: 2px; }
    QComboBox { background-color: #161b22; color: #c9d1d9; border: 1px solid #30363d; 
               padding: 4px; border-radius: 2px; }
    QComboBox::drop-down { border: none; }
    QComboBox::down-arrow { image: none; border-left: 3px solid transparent; border-right: 3px solid transparent; border-top: 5px solid #58a6ff; }
    QTabWidget::pane { border: 1px solid #30363d; background-color: #0d1117; }
    QTabBar::tab { background-color: #161b22; color: #8b949e; padding: 8px 16px; border: 1px solid #30363d; border-bottom: none; }
    QTabBar::tab:selected { background-color: #1c2128; color: #58a6ff; }
    QCheckBox { color: #c9d1d9; }
    QCheckBox::indicator { width: 16px; height: 16px; border: 1px solid #30363d; border-radius: 3px; background-color: #161b22; }
    QCheckBox::indicator:checked { background-color: #58a6ff; border-color: #58a6ff; }
    """


class ADCWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADCMT 7352A Digital Multimeter [PyMeasure]")
        self.setMinimumSize(1000, 700)
        self.setStyleSheet(make_style())

        self.procedure = None
        self.results = None
        self.worker = None
        self.plotter = None

        self.ts = collections.deque(maxlen=MAX_PTS)
        self.vals = collections.deque(maxlen=MAX_PTS)
        self.t0 = None

        self._setup_ui()

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        self.setCentralWidget(central)
        main_layout = QtWidgets.QHBoxLayout(central)
        main_layout.setSpacing(0)
        main_layout.setContentsMargins(0, 0, 0, 0)

        left_panel = self._build_left_panel()
        left_panel.setFixedWidth(220)
        main_layout.addWidget(left_panel)

        right_panel = QtWidgets.QWidget()
        right_panel.setObjectName("rightPanel")
        right_layout = QtWidgets.QVBoxLayout(right_panel)
        right_layout.setContentsMargins(8, 8, 8, 8)

        self.tabs = QtWidgets.QTabWidget()
        self.tabs.setDocumentMode(True)

        self.plot_tab = QtWidgets.QWidget()
        self.plot_layout = QtWidgets.QVBoxLayout(self.plot_tab)

        self.console_tab = self._build_console_tab()

        self.tabs.addTab(self.plot_tab, " Live Plot ")
        self.tabs.addTab(self.console_tab, " ADC Console ")

        right_layout.addWidget(self.tabs)

        main_layout.addWidget(right_panel, 1)

        self._setup_plot_display()

    def _build_left_panel(self):
        panel = QtWidgets.QWidget()
        panel.setObjectName("leftPanel")
        panel.setStyleSheet("#leftPanel { background-color: #0d1117; }")
        layout = QtWidgets.QVBoxLayout(panel)
        layout.setContentsMargins(10, 10, 10, 10)
        layout.setSpacing(6)

        title = QtWidgets.QLabel("◈ ADCMT 7352A")
        title.setStyleSheet(
            "font-size: 16px; font-weight: bold; color: #c9d1d9;")
        layout.addWidget(title)

        subtitle = QtWidgets.QLabel("Digital Multimeter [ADC mode]")
        subtitle.setStyleSheet("color: #8b949e; font-size: 11px;")
        layout.addWidget(subtitle)

        self.status_label = QtWidgets.QLabel("DISCONNECTED")
        self.status_label.setStyleSheet("color: #f85149; font-weight: bold;")
        self.status_dot = QtWidgets.QLabel("●")
        self.status_dot.setStyleSheet("color: #f85149; font-size: 14px;")

        status_bar = QtWidgets.QFrame()
        status_bar.setFrameShape(QtWidgets.QFrame.NoFrame)
        sb_layout = QtWidgets.QHBoxLayout(status_bar)
        sb_layout.addWidget(self.status_dot)
        sb_layout.addWidget(self.status_label)
        sb_layout.addStretch()
        layout.addWidget(status_bar)

        layout.addWidget(self._create_card(
            "CONNECTION", self._build_conn_card()))
        layout.addWidget(self._create_card(
            "FUNCTION & RANGE", self._build_func_card()))
        layout.addWidget(self._build_acq_card())
        layout.addWidget(self._build_live_card())

        layout.addStretch()

        return panel

    def _create_card(self, title, content_widget):
        group = QtWidgets.QGroupBox(title)
        group.setStyleSheet("""
            QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 12px; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; font-weight: bold; }
        """)
        layout = QtWidgets.QVBoxLayout(group)
        layout.setContentsMargins(10, 12, 10, 10)
        layout.addWidget(content_widget)
        return group

    def _build_conn_card(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        lbl = QtWidgets.QLabel("Resource string")
        lbl.setStyleSheet("color: #8b949e; font-size: 8px;")
        layout.addWidget(lbl)

        self.resource_edit = QtWidgets.QLineEdit(
            "USB0::4916::520::999991006::0::INSTR")
        self.resource_edit.setStyleSheet("color: #58a6ff; font-size: 9px;")
        layout.addWidget(self.resource_edit)

        btn_layout = QtWidgets.QHBoxLayout()
        self.connect_btn = QtWidgets.QPushButton("CONNECT")
        self.connect_btn.setStyleSheet("""
            QPushButton { background-color: #161b22; color: #3fb950; border: 1px solid #30363d; 
                          padding: 6px; border-radius: 4px; font-weight: bold; }
            QPushButton:hover { border-color: #3fb950; }
        """)
        self.connect_btn.clicked.connect(self._on_connect)
        btn_layout.addWidget(self.connect_btn)

        self.idn_btn = QtWidgets.QPushButton("IDN?")
        self.idn_btn.setStyleSheet("color: #8b949e;")
        self.idn_btn.clicked.connect(self._do_idn)
        btn_layout.addWidget(self.idn_btn)
        layout.addLayout(btn_layout)

        self.sim_chk = QtWidgets.QCheckBox("Simulate (no hardware)")
        self.sim_chk.setStyleSheet("color: #8b949e;")
        self.sim_chk.setChecked(True)
        layout.addWidget(self.sim_chk)

        self.idn_label = QtWidgets.QLabel("—")
        self.idn_label.setStyleSheet("color: #8b949e; font-size: 8px;")
        self.idn_label.setWordWrap(True)
        layout.addWidget(self.idn_label)

        return widget

    def _build_func_card(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(4)

        lbl = QtWidgets.QLabel("Function")
        lbl.setStyleSheet("color: #8b949e; font-size: 9px;")
        layout.addWidget(lbl)

        self.func_combo = QtWidgets.QComboBox()
        self.func_combo.addItems([v[0] for v in FUNCTIONS.values()])
        self.func_combo.setCurrentIndex(0)
        self.func_combo.currentIndexChanged.connect(self._refresh_ranges)
        layout.addWidget(self.func_combo)

        lbl = QtWidgets.QLabel("Range")
        lbl.setStyleSheet("color: #8b949e; font-size: 9px;")
        layout.addWidget(lbl)

        self.range_combo = QtWidgets.QComboBox()
        self._refresh_ranges()
        layout.addWidget(self.range_combo)

        rate_layout = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel("Sampling")
        lbl.setStyleSheet("color: #8b949e; font-size: 9px;")
        rate_layout.addWidget(lbl)
        self.srate_combo = QtWidgets.QComboBox()
        self.srate_combo.addItems(SRATE_DISP)
        self.srate_combo.setCurrentText("MED")
        rate_layout.addWidget(self.srate_combo)
        layout.addLayout(rate_layout)

        digits_layout = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel("Digits")
        lbl.setStyleSheet("color: #8b949e; font-size: 9px;")
        digits_layout.addWidget(lbl)
        self.digits_combo = QtWidgets.QComboBox()
        self.digits_combo.addItems(DIGITS_DISP)
        self.digits_combo.setCurrentText("5½")
        digits_layout.addWidget(self.digits_combo)
        layout.addLayout(digits_layout)

        self.az_chk = QtWidgets.QCheckBox("Auto-Zero ON (AZ1)")
        self.az_chk.setStyleSheet("color: #8b949e;")
        self.az_chk.setChecked(True)
        layout.addWidget(self.az_chk)

        self.apply_btn = QtWidgets.QPushButton("APPLY SETTINGS")
        self.apply_btn.setStyleSheet("color: #58a6ff; font-weight: bold;")
        self.apply_btn.clicked.connect(self._apply_settings)
        layout.addWidget(self.apply_btn)

        return widget

    def _refresh_ranges(self):
        idx = self.func_combo.currentIndex()
        fkeys = list(FUNCTIONS.keys())
        fk = fkeys[idx]
        rngs = FUNCTIONS[fk][2]
        self.range_combo.clear()
        self.range_combo.addItems([r[0] for r in rngs])

    def _build_acq_card(self):
        widget = QtWidgets.QGroupBox("ACQUISITION")
        widget.setStyleSheet("""
            QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 12px; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; font-weight: bold; }
        """)
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(10, 12, 10, 10)

        interval_layout = QtWidgets.QHBoxLayout()
        lbl = QtWidgets.QLabel("Read interval (ms)")
        lbl.setStyleSheet("color: #8b949e; font-size: 9px;")
        interval_layout.addWidget(lbl)
        self.interval_edit = QtWidgets.QLineEdit("500")
        self.interval_edit.setMaximumWidth(80)
        interval_layout.addWidget(self.interval_edit)
        interval_layout.addStretch()
        layout.addLayout(interval_layout)

        btn_layout = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("▶  START")
        self.start_btn.setStyleSheet("color: #3fb950; font-weight: bold;")
        self.start_btn.clicked.connect(self._start_acq)
        btn_layout.addWidget(self.start_btn)

        self.stop_btn = QtWidgets.QPushButton("■  STOP")
        self.stop_btn.setStyleSheet("color: #d29922; font-weight: bold;")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_acq)
        btn_layout.addWidget(self.stop_btn)
        layout.addLayout(btn_layout)

        self.clear_btn = QtWidgets.QPushButton("CLEAR DATA")
        self.clear_btn.setStyleSheet("color: #8b949e;")
        self.clear_btn.clicked.connect(self._clear_data)
        layout.addWidget(self.clear_btn)

        return widget

    def _build_live_card(self):
        widget = QtWidgets.QGroupBox("LIVE READING")
        widget.setStyleSheet("""
            QGroupBox { border: 1px solid #30363d; border-radius: 4px; margin-top: 12px; padding-top: 8px; }
            QGroupBox::title { subcontrol-origin: margin; left: 10px; padding: 0 5px; color: #58a6ff; font-weight: bold; }
        """)
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(10, 12, 10, 10)

        self.val_label = QtWidgets.QLabel("— — — — —")
        self.val_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #58a6ff;")
        layout.addWidget(self.val_label)

        self.unit_label = QtWidgets.QLabel("")
        self.unit_label.setStyleSheet("font-size: 11px; color: #8b949e;")
        layout.addWidget(self.unit_label)

        self.status_label2 = QtWidgets.QLabel("")
        self.status_label2.setStyleSheet("font-size: 9px; color: #d29922;")
        layout.addWidget(self.status_label2)

        return widget

    def _setup_plot_display(self):
        try:
            import pyqtgraph as pg
            pg.setConfigOption('background', 'k')
            pg.setConfigOption('foreground', 'w')

            self.plot_widget = pg.PlotWidget()
            self.plot_widget.setBackground('#0d1117')
            self.plot_widget.setLabel('bottom', 'Time', units='s')
            self.plot_widget.setLabel('left', 'Value', units='')
            self.plot_widget.showGrid(x=True, y=True, alpha=0.3)
            self.plot_widget.setXRange(0, 10)

            self.curve = self.plot_widget.plot(
                pen=pg.mkPen(color='#58a6ff', width=1.5))

            self.plot_layout.addWidget(self.plot_widget)

        except ImportError:
            label = QtWidgets.QLabel(
                "pyqtgraph not installed\npip install pyqtgraph")
            label.setStyleSheet("color: #f85149; font-size: 12px;")
            label.setAlignment(QtCore.Qt.AlignCenter)
            self.plot_layout.addWidget(label)

    def _build_console_tab(self):
        widget = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(widget)
        layout.setContentsMargins(8, 8, 8, 8)

        top = QtWidgets.QFrame()
        top_layout = QtWidgets.QHBoxLayout(top)
        top_layout.setContentsMargins(0, 0, 0, 0)

        lbl = QtWidgets.QLabel("CMD:")
        lbl.setStyleSheet("color: #8b949e;")
        top_layout.addWidget(lbl)

        self.cmd_edit = QtWidgets.QLineEdit()
        self.cmd_edit.setPlaceholderText("Enter ADC command...")
        self.cmd_edit.returnPressed.connect(self._send_cmd)
        top_layout.addWidget(self.cmd_edit, 1)

        self.send_btn = QtWidgets.QPushButton("SEND")
        self.send_btn.setStyleSheet("color: #58a6ff;")
        self.send_btn.clicked.connect(self._send_cmd)
        top_layout.addWidget(self.send_btn)

        self.clear_console_btn = QtWidgets.QPushButton("CLEAR")
        self.clear_console_btn.setStyleSheet("color: #8b949e;")
        self.clear_console_btn.clicked.connect(self._clear_console)
        top_layout.addWidget(self.clear_console_btn)

        self.rst_btn = QtWidgets.QPushButton("*RST")
        self.rst_btn.setStyleSheet("color: #f85149;")
        self.rst_btn.clicked.connect(lambda: self._adc_write("*RST"))
        top_layout.addWidget(self.rst_btn)

        self.cls_btn = QtWidgets.QPushButton("*CLS")
        self.cls_btn.setStyleSheet("color: #d29922;")
        self.cls_btn.clicked.connect(lambda: self._adc_write("*CLS"))
        top_layout.addWidget(self.cls_btn)

        layout.addWidget(top)

        self.console_text = QtWidgets.QTextEdit()
        self.console_text.setReadOnly(True)
        self.console_text.setStyleSheet("""
            QTextEdit { background-color: #0d1117; color: #c9d1d9; 
                       font-family: Consolas, monospace; font-size: 10px; }
        """)
        layout.addWidget(self.console_text)

        self._log_console("ADCMT 7352A", "info")
        self._log_console(
            "Free-run: instrument streams data → bare read() used for acquisition.", "info")

        return widget

    def _log_console(self, text, tag="info"):
        if not hasattr(self, 'console_text') or self.console_text is None:
            return
        colors = {"info": "#8b949e", "cmd": "#58a6ff", "resp": "#c9d1d9",
                  "err": "#f85149", "ok": "#3fb950"}
        color = colors.get(tag, "#c9d1d9")

        self.console_text.setPlainText(
            self.console_text.toPlainText() + f"[{time.strftime('%H:%M:%S')}] {text}\n")
        self.console_text.verticalScrollBar().setValue(
            self.console_text.verticalScrollBar().maximum())

    def _clear_console(self):
        self.console_text.clear()

    def _on_connect(self):
        if hasattr(self, 'acq_thread') and self.acq_thread and self.acq_thread.is_alive():
            self._stop_acq()

        if hasattr(self, 'instrument') and self.instrument and self.instrument.connected:
            self.instrument.disconnect()
            self._update_status(False)
            self._log_console("Disconnected.", "info")
            return

        simulate = self.sim_chk.isChecked()
        resource = self.resource_edit.text()

        self.instrument = ADCInstrument(resource_string=resource if not simulate else None,
                                        simulate=simulate)

        if self.instrument.connect():
            self._update_status(True)
            self._log_console("Connected successfully", "ok")
            self.instrument.init_instrument()
            self._do_idn()
        else:
            self._log_console("Connection failed", "err")

    def _update_status(self, connected):
        if connected:
            self.status_label.setText("CONNECTED")
            self.status_label.setStyleSheet(
                "color: #3fb950; font-weight: bold;")
            self.status_dot.setStyleSheet("color: #3fb950; font-size: 14px;")
            self.connect_btn.setText("DISCONNECT")
            self.connect_btn.setStyleSheet("""
                QPushButton { background-color: #161b22; color: #f85149; border: 1px solid #30363d; 
                              padding: 6px; border-radius: 4px; font-weight: bold; }
                QPushButton:hover { border-color: #f85149; }
            """)
        else:
            self.status_label.setText("DISCONNECTED")
            self.status_label.setStyleSheet(
                "color: #f85149; font-weight: bold;")
            self.status_dot.setStyleSheet("color: #f85149; font-size: 14px;")
            self.connect_btn.setText("CONNECT")
            self.connect_btn.setStyleSheet("""
                QPushButton { background-color: #161b22; color: #3fb950; border: 1px solid #30363d; 
                              padding: 6px; border-radius: 4px; font-weight: bold; }
                QPushButton:hover { border-color: #3fb950; }
            """)

    def _do_idn(self):
        if hasattr(self, 'instrument') and self.instrument:
            idn = self.instrument.get_idn()
            if idn:
                self.idn_label.setText(idn)
                self._log_console(f"<< {idn}", "resp")

    def _apply_settings(self):
        if not hasattr(self, 'instrument') or not self.instrument:
            self._log_console("Not connected", "err")
            return

        idx = self.func_combo.currentIndex()
        fkeys = list(FUNCTIONS.keys())
        fk = fkeys[idx]

        self.instrument.write(fk)

        rng_idx = self.range_combo.currentIndex()
        func_ranges = FUNCTIONS[fk][2]
        if rng_idx < len(func_ranges) and func_ranges[rng_idx][1]:
            self.instrument.write(func_ranges[rng_idx][1])

        srate_idx = SRATE_DISP.index(self.srate_combo.currentText())
        self.instrument.write(SRATE_CMD[srate_idx])

        digits_idx = DIGITS_DISP.index(self.digits_combo.currentText())
        self.instrument.write(DIGITS_CMD[digits_idx])

        az = "AZ1" if self.az_chk.isChecked() else "AZ0"
        self.instrument.write(az)

        self._log_console("Settings applied", "ok")

    def _start_acq(self):
        if not hasattr(self, 'instrument') or not self.instrument:
            self._log_console("Not connected", "err")
            return

        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        self.t0 = time.time()
        self.ts.clear()
        self.vals.clear()

        self.acq_thread = threading.Thread(target=self._acq_loop, daemon=True)
        self.acq_thread.start()

        self._log_console("Acquisition started", "ok")

    def _stop_acq(self):
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self._log_console("Acquisition stopped", "info")

    def _clear_data(self):
        self.ts.clear()
        self.vals.clear()
        if hasattr(self, 'curve'):
            self.curve.setData([], [])
        self._log_console("Data cleared", "info")

    def _acq_loop(self):
        ticker = 0
        try:
            iv = int(self.interval_edit.text()
                     ) if self.interval_edit.text() else 500
        except:
            iv = 500
        iv = max(50, iv)

        while self.stop_btn.isEnabled():
            t_start = time.time()
            try:
                raw = self.instrument.read()
                if raw is None:
                    continue

                log.debug(f"READ: {raw}")

                idx = self.func_combo.currentIndex()
                fkeys = list(FUNCTIONS.keys())
                fk = fkeys[idx]

                val, mh, sh, is_ol, disp, desc = parse_adc_response(raw, fk)
                elapsed = time.time() - self.t0

                log.debug(f"RESULT: {elapsed:.3f}s, {val}, {disp}")

                self.ts.append(elapsed)
                self.vals.append(OVERLOAD_THRESHOLD * 1.1 if is_ol else val)

                QtWidgets.QApplication.instance().postEvent(
                    self, _UpdateLiveEvent(disp, FUNCTIONS[fk][1], desc, is_ol, sh))

                ticker += 1
                if ticker >= 3:
                    ticker = 0
                    QtWidgets.QApplication.instance().postEvent(
                        self, _UpdatePlotEvent(list(self.ts), list(self.vals)))

            except Exception as e:
                self._log_console(f"Read error: {e}", "err")
                time.sleep(0.5)
                continue

            elapsed_ms = (time.time() - t_start) * 1000
            time.sleep(max(0.0, (iv - elapsed_ms) / 1000))

    def _send_cmd(self):
        cmd = self.cmd_edit.text().strip()
        if not cmd:
            return

        if not hasattr(self, 'instrument') or not self.instrument:
            self._log_console("Not connected", "err")
            return

        self._log_console(f">> {cmd}", "cmd")
        QtWidgets.QApplication.processEvents()

        try:
            if cmd.endswith("?"):
                resp = self.instrument.query(cmd)
                if resp:
                    self._log_console(f"<< {resp}", "resp")
                else:
                    self._log_console(f"<< (empty)", "err")
            else:
                self.instrument.write(cmd)
                # resp = self.instrument.query(cmd)
                err = self.instrument.query("ERR?")
                if err and not err.startswith("+000"):
                    self._log_console(f"   ERR? -> {err}", "err")
                else:
                    self._log_console(f"Sent: {cmd}", "ok")
        except Exception as e:
            self._log_console(f"Error: {e}", "err")

        self.cmd_edit.clear()

    def event(self, event):
        if isinstance(event, _UpdateLiveEvent):
            self.val_label.setText(event.disp)
            self.val_label.setStyleSheet(
                f"font-size: 20px; font-weight: bold; color: {event.color};")
            self.unit_label.setText(event.unit)
            self.status_label2.setText(event.desc if event.desc else "")
            return True
        elif isinstance(event, _UpdatePlotEvent):
            if hasattr(self, 'curve'):
                self.curve.setData(event.ts, event.vals)
                if event.ts:
                    self.plot_widget.setXRange(
                        max(0, event.ts[-1] - 10), event.ts[-1])
            return True
        return super().event(event)

    def closeEvent(self, event):
        if hasattr(self, 'instrument') and self.instrument:
            self.instrument.disconnect()
        super().closeEvent(event)


class _UpdateLiveEvent(QtCore.QEvent):
    def __init__(self, disp, unit, desc, is_ol, sub_h):
        super().__init__(QtCore.QEvent.User)
        self.disp = disp
        self.unit = unit
        self.desc = desc
        self.color = "#f85149" if is_ol else (
            "#e3b341" if sub_h not in ("_", "") else "#58a6ff")


class _UpdatePlotEvent(QtCore.QEvent):
    def __init__(self, ts, vals):
        super().__init__(QtCore.QEvent.User + 1)
        self.ts = ts
        self.vals = vals


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)

    app = QtWidgets.QApplication(sys.argv)
    window = ADCWindow()
    window.show()
    sys.exit(app.exec())
