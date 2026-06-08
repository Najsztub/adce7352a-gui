"""
Mock/Simulation Backend for ADCMT 7352A

Simulates ADC-mode responses for testing without hardware.
Supports dual-channel simulation (SD0, DE1, DSP1/DSP2).
"""

import math
import time
import logging
from .visa_backend import InstrumentBackend

log = logging.getLogger(__name__)


class MockBackend(InstrumentBackend):
    def __init__(self):
        self._func_a = "F1"
        self._func_b = "F12"
        self._range_a = "R0"
        self._range_b = "R0"
        self._srate = "PR2"
        self._digits = "RE5"
        self._az = "AZ1"
        self._hdr = "H1"
        self._nl = False
        self._sm = False
        self._sm_pts = 10
        self._sc = False
        self._db = False
        self._co = False
        self._hi = 10.0
        self._lo = -10.0
        self._mn = False
        self._de = False
        self._sd = 1
        self._dsp = "DSP1"
        self._ds = True
        self._t0 = time.time()
        self._count = 0
        self._error_queue = []
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._t0 = time.time()
        self._count = 0
        self._connected = True
        log.info("Mock backend connected")
        return True

    def disconnect(self):
        self._connected = False
        log.info("Mock backend disconnected")

    def get_idn(self) -> str | None:
        return "ADC Corp.,7352A,999991006,FW2.4.1"

    def _true_val_ch(self, fn, t=None):
        if t is None:
            t = time.time() - self._t0
        if fn in ("F1", "F2", "F7"):
            return 3.2986 + 0.002 * math.sin(t * 0.7) + 3e-4 * math.sin(t * 13.1)
        if fn == "F12":
            return -1.5021 + 0.005 * math.cos(t * 0.5) + 1e-3 * math.sin(t * 7.3)
        if fn in ("F5", "F35"):
            return 0.1024 + 5e-4 * math.cos(t * 1.1)
        if fn in ("F6", "F8", "F36", "F37"):
            return 0.0981 + 4e-4 * math.cos(t * 1.3)
        if fn in ("F3", "F20"):
            return 9876.5 + 0.8 * math.sin(t * 0.3)
        if fn == "F50":
            return 50.001 + 1e-3 * math.sin(t * 0.1)
        if fn == "F40":
            return 23.45 + 0.05 * math.sin(t * 0.05)
        if fn == "F13":
            return 0.6234 + 2e-4 * math.sin(t * 0.8)
        if fn == "F22":
            return 4.7 + 0.01 * math.sin(t * 1.5)
        return 0.0

    def _true_val(self):
        return self._true_val_ch(self._func_a)

    def _hdr3(self, fn=None):
        from ..commands.adc_commands import FUNCTIONS
        return FUNCTIONS.get(fn or self._func_a, ("", "", "", "DCV"))[3]

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

    def _single_read(self, fn):
        val = self._true_val_ch(fn)
        s = self._sub(val)
        if self._hdr == "H1":
            return f"{self._hdr3(fn)}{s}  {self._fmt_val(val)}"
        return self._fmt_val(val)

    def read(self) -> str | None:
        self._count += 1
        if self._de and self._sd == 0:
            val_a = self._true_val_ch(self._func_a)
            val_b = self._true_val_ch(self._func_b)
            s_a = self._sub(val_a)
            s_b = self._sub(val_b)
            if self._hdr == "H1":
                return f"{self._hdr3(self._func_a)}{s_a}  {self._fmt_val(val_a)}, {self._hdr3(self._func_b)}{s_b}  {self._fmt_val(val_b)}"
            return f"{self._fmt_val(val_a)}, {self._fmt_val(val_b)}"
        fn = self._func_b if self._dsp == "DSP2" else self._func_a
        return self._single_read(fn)

    def write(self, cmd):
        from ..commands.adc_commands import FUNCTIONS
        cmd = cmd.strip().upper()
        dsp_prefix = None
        if cmd.startswith("DSP1,"):
            dsp_prefix = "DSP1"
            cmd = cmd[5:]
        elif cmd.startswith("DSP2,"):
            dsp_prefix = "DSP2"
            cmd = cmd[5:]

        if cmd == "DSP1":
            self._dsp = "DSP1"
            return
        if cmd == "DSP2":
            self._dsp = "DSP2"
            return
        if cmd == "DE1":
            self._de = True
            return
        if cmd == "DE0":
            self._de = False
            return
        if cmd == "SD0":
            self._sd = 0
            return
        if cmd == "SD1":
            self._sd = 1
            return
        if cmd == "SD2":
            self._sd = 2
            return

        target = self._func_a if dsp_prefix != "DSP2" else self._func_b
        for fk in FUNCTIONS:
            if cmd == fk:
                if dsp_prefix == "DSP2":
                    self._func_b = fk
                else:
                    self._func_a = fk
                return
        if cmd in ("R0", "R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9", "RX"):
            if dsp_prefix == "DSP2":
                self._range_b = cmd
            else:
                self._range_a = cmd
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
            self._nl = True; return
        if cmd == "NL0":
            self._nl = False; return
        if cmd == "SM1":
            self._sm = True; return
        if cmd == "SM0":
            self._sm = False; return
        if cmd.startswith("TI"):
            try: self._sm_pts = int(cmd[2:])
            except ValueError: pass
            return
        if cmd == "SC1":
            self._sc = True; return
        if cmd == "SC0":
            self._sc = False; return
        if cmd == "DB1":
            self._db = True; return
        if cmd == "DB0":
            self._db = False; return
        if cmd == "CO1":
            self._co = True; return
        if cmd == "CO0":
            self._co = False; return
        if cmd.startswith("HI"):
            try: self._hi = float(cmd[2:])
            except ValueError: pass
            return
        if cmd.startswith("LO"):
            try: self._lo = float(cmd[2:])
            except ValueError: pass
            return
        if cmd == "MN1":
            self._mn = True; return
        if cmd == "MN0":
            self._mn = False; return
        if cmd == "DE1":
            self._de = True; return
        if cmd == "DE0":
            self._de = False; return
        if cmd in ("SD0", "SD1", "SD2"):
            self._sd = int(cmd[2]); return
        if cmd == "DS1":
            self._ds = True; return
        if cmd == "DS0":
            self._ds = False; return

    def query(self, cmd) -> str | None:
        from ..commands.adc_commands import FUNCTIONS
        cmd = cmd.strip().upper()
        if cmd == "*IDN?":
            return "ADC Corp.,7352A,999991006,FW2.4.1"
        if cmd == "F?":
            return self._func_a
        if cmd == "DSP1,F?":
            return self._func_a
        if cmd == "DSP2,F?":
            return self._func_b
        if cmd == "R?":
            return self._range_a
        if cmd == "PR?":
            return self._srate
        if cmd == "RE?":
            return self._digits
        if cmd == "AZ?":
            return self._az
        if cmd == "H?":
            return self._hdr
        if cmd == "ERR?":
            if self._error_queue:
                return self._error_queue.pop(0)
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
        if cmd == "DE?":
            return "DE1" if self._de else "DE0"
        if cmd == "SD?":
            return f"SD{self._sd}"
        if cmd == "DS?":
            return "DS1" if self._ds else "DS0"
        if cmd == "DSP?":
            return self._dsp
        return "+000"

    def write_with_err_check(self, cmd: str) -> bool:
        self.write(cmd)
        err = self.query("ERR?")
        if err and not err.startswith("+0"):
            return False
        return True
