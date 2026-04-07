"""
ADCMT 7352A  Digital Multimeter  –  Control & Plot GUI
Resource : USB0::4916::520::999991006::0::INSTR

Command language : ADC mode  (set on instrument: MENU → I/F → LANG → ADC)
Termination      : \\r\\n  (CR+LF) for both read and write
Reading data     : instrument continuously outputs measurements in free-run
                   mode (INIC1 + TRS0).  Data is obtained by a bare
                   instr.read() — no query command is needed (manual §6.7.4
                   USB sample: ausbrd() calls ausb_read() without any prior
                   write).

All commands from ADC Command Reference  (manual §6.6.3, FOE-8440254B00)
Output data format from §6.6.2.
"""

import tkinter as tk
from tkinter import ttk, messagebox
import threading
import time
import collections
import math
import re

try:
    import pyvisa
    PYVISA_AVAILABLE = True
except ImportError:
    PYVISA_AVAILABLE = False

try:
    import matplotlib
    matplotlib.use("TkAgg")
    from matplotlib.figure import Figure
    from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
    MPLOT = True
except ImportError:
    MPLOT = False

# ══════════════════════════════════════════════════════════════════════════════
#  ADC command tables  (§6.6.3)
# ══════════════════════════════════════════════════════════════════════════════

# Function commands and metadata
# key: ADC Fn command string
# value: (display label, unit, [(range_label, Rn_cmd)], output_header_3char)
#
# Range table from manual §6.6.3:
#   R0  = AUTO
#   R1  = 2000 nA  (DCI only)
#   R2  = 20 µA    (DCI only)
#   R3  = 200 mV / 200 Ω / 200 µA
#   R4  = 2000 mV / 2 kΩ / 2 mA
#   R5  = 20 V / 20 kΩ / 20 mA
#   R6  = 200 V / 200 kΩ / 200 mA
#   R7  = 1000 V (DCV) / 700 V (ACV) / 2 MΩ / 2000 mA
#   R8  = 20 MΩ / 10 A (Bch current)
#   R9  = 200 MΩ (2W only)

FUNCTIONS = {
    "F1":  ("DCV  Ach",          "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),
             ("20 V","R5"),("200 V","R6"),("1000 V","R7")], "DCV"),
    "F2":  ("ACV  Ach",           "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),
             ("20 V","R5"),("200 V","R6"),("700 V","R7")], "ACV"),
    "F7":  ("ACV AC+DC  Ach",     "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),
             ("20 V","R5"),("200 V","R6"),("700 V","R7")], "ADV"),
    "F3":  ("2W Ω  Ach",          "Ω",
            [("Auto","R0"),("200 Ω","R3"),("2 kΩ","R4"),("20 kΩ","R5"),
             ("200 kΩ","R6"),("2 MΩ","R7"),("20 MΩ","R8"),("200 MΩ","R9")], "R2W"),
    "F20": ("LP-2W Ω  Ach",       "Ω",
            [("Auto","R0"),("200 Ω","R3"),("2 kΩ","R4"),("20 kΩ","R5"),
             ("200 kΩ","R6"),("2 MΩ","R7"),("20 MΩ","R8")], "R2L"),
    "F5":  ("DCI  Ach",           "A",
            [("Auto","R0"),("2000 nA","R1"),("20 µA","R2"),("200 µA","R3"),
             ("2 mA","R4"),("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "DCI"),
    "F6":  ("ACI  Ach",           "A",
            [("Auto","R0"),("200 µA","R3"),("2 mA","R4"),
             ("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "ACI"),
    "F8":  ("ACI AC+DC  Ach",     "A",
            [("Auto","R0"),("200 µA","R3"),("2 mA","R4"),
             ("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "ADI"),
    "F50": ("FREQ  Ach",          "Hz", [("Auto","R0")], "FRQ"),
    "F13": ("DIODE  Ach",         "V",  [("—","")],      "DOD"),
    "F22": ("CONT  Ach",          "Ω",  [("—","")],      "RCT"),
    "F40": ("TEMP",               "°C", [("—","")],      "TC_"),
    "F12": ("DCV  Bch",           "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),
             ("20 V","R5"),("200 V","R6")], "BDV"),
    "F35": ("DCI  Bch",           "A",  [("10 A","R8")], "BDI"),
    "F36": ("ACI  Bch",           "A",  [("10 A","R8")], "BAI"),
    "F37": ("ACI AC+DC  Bch",     "A",  [("10 A","R8")], "BCI"),
}

# Sampling rate  PR1..PR4  (§6.6.3)
SRATE_CMD  = ["PR1", "PR2", "PR3", "PR4"]
SRATE_DISP = ["FAST", "MED", "SLOW1", "SLOW2"]

# Digits  RE3..RE5  (§6.6.3)
DIGITS_CMD  = ["RE3", "RE4", "RE5"]
DIGITS_DISP = ["3½", "4½", "5½"]

# Output data sub-header meanings  (§6.6.2 table)
SUB_LABELS = {
    "_": "",     "O": " [OL]",    "H": " [HI]",  "P": " [PASS]",
    "L": " [LO]","N": " [NULL]",  "S": " [SCALE]","B": " [dB]",
    "W": " [dBm]","E": " [Err]",  "M": " [MAX]",  "I": " [MIN]",
    "A": " [AVG]","D": " [CALC2]",
}

# Header → description  (§6.6.2 table 4)
HDR_LABELS = {
    "DCV":"DC Volt","ACV":"AC Volt","ADV":"AC+DC Volt",
    "R2W":"2W Res", "R2L":"LP-2W", "DCI":"DC Curr",
    "ACI":"AC Curr","ADI":"AC+DC Curr","FRQ":"Freq",
    "DOD":"Diode",  "RCT":"Cont",  "TC_":"Temp",
    "BDV":"Bch DCV","BDI":"Bch DCI","BAI":"Bch ACI","BCI":"Bch ACI+DC",
}

OVERLOAD_THRESHOLD = 9.9e+36   # §6.6.2: 9.99999E+37 = overload

# ══════════════════════════════════════════════════════════════════════════════
#  Simulator  (mimics ADC-mode responses)
# ══════════════════════════════════════════════════════════════════════════════
class Sim7352A:
    """Simulates the 7352A in ADC command mode with CR+LF termination."""

    def __init__(self):
        self._func   = "F1"
        self._range  = "R0"
        self._srate  = "PR2"
        self._digits = "RE5"
        self._az     = "AZ1"
        self._hdr    = "H1"       # header ON by default after H1 command
        self._nl     = False      # NULL calc
        self._sm     = False      # smoothing
        self._sm_pts = 10
        self._co     = False      # comparator
        self._hi     = 10.0
        self._lo     = -10.0
        self._mn     = False      # MAX/MIN
        self._t0     = time.time()
        self._count  = 0

    def _true_val(self):
        t  = time.time() - self._t0
        fn = self._func
        if fn in ("F1","F2","F7","F12"):
            return 3.2986 + 0.002*math.sin(t*0.7) + 3e-4*math.sin(t*13.1)
        if fn in ("F5","F35"):
            return 0.1024 + 5e-4*math.cos(t*1.1)
        if fn in ("F6","F8","F36","F37"):
            return 0.0981 + 4e-4*math.cos(t*1.3)
        if fn in ("F3","F20"):
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
        return FUNCTIONS.get(self._func, ("","","","DCV"))[3]

    def _sub(self, val):
        if self._co:
            if val > self._hi: return "H"
            if val < self._lo: return "L"
            return "P"
        if self._nl: return "N"
        return "_"

    def _fmt_val(self, val):
        sign = "+" if val >= 0 else "-"
        return f"{sign}{abs(val):.5E}"

    def read(self):
        """Bare read — instrument outputs next measurement."""
        self._count += 1
        val = self._true_val()
        s   = self._sub(val)
        if self._hdr == "H1":
            return f"{self._hdr3()}{s}  {self._fmt_val(val)}"
        return self._fmt_val(val)

    def write(self, cmd):
        cmd = cmd.strip().upper()
        # strip DSP1, prefix
        if cmd.startswith("DSP1,"):
            cmd = cmd[5:]
        # function
        for fk in FUNCTIONS:
            if cmd == fk:
                self._func = fk; return
        if cmd in ("R0","R1","R2","R3","R4","R5","R6","R7","R8","R9"):
            self._range = cmd; return
        if cmd in ("PR1","PR2","PR3","PR4"):
            self._srate = cmd; return
        if cmd in ("RE3","RE4","RE5"):
            self._digits = cmd; return
        if cmd in ("AZ0","AZ1","AZ2"):
            self._az = cmd; return
        if cmd in ("H0","H1"):
            self._hdr = cmd; return
        if cmd == "NL1":  self._nl = True;  return
        if cmd == "NL0":  self._nl = False; return
        if cmd == "SM1":  self._sm = True;  return
        if cmd == "SM0":  self._sm = False; return
        if cmd.startswith("TI"):
            try: self._sm_pts = int(cmd[2:])
            except: pass
            return
        if cmd == "CO1":  self._co = True;  return
        if cmd == "CO0":  self._co = False; return
        if cmd.startswith("HI"):
            try: self._hi = float(cmd[2:])
            except: pass
            return
        if cmd.startswith("LO"):
            try: self._lo = float(cmd[2:])
            except: pass
            return
        if cmd == "MN1":  self._mn = True;  return
        if cmd == "MN0":  self._mn = False; return
        # everything else (INIC1, TRS0, DE0, SD1, *RST, *CLS …) silently accepted

    def query(self, cmd):
        cmd = cmd.strip().upper()
        # ADC query responses
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
        if cmd in ("SCNT?","SMAX?","SMIN?","SAVE?","SSIG?","SPTP?"):
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

# ══════════════════════════════════════════════════════════════════════════════
#  Colours
# ══════════════════════════════════════════════════════════════════════════════
BG     = "#0d1117"
PANEL  = "#161b22"
CARD   = "#1c2128"
BORDER = "#30363d"
ACCENT = "#58a6ff"
GREEN  = "#3fb950"
YELLOW = "#d29922"
RED    = "#f85149"
ORANGE = "#e3b341"
PURPLE = "#bc8cff"
TEXT   = "#c9d1d9"
MUTED  = "#8b949e"
MAX_PTS = 600

# ══════════════════════════════════════════════════════════════════════════════
#  GUI
# ══════════════════════════════════════════════════════════════════════════════
class DMM7352A:
    def __init__(self, root: tk.Tk):
        self.root      = root
        self.instr     = None
        self.connected = False
        self.reading   = False
        self._rlock    = threading.Lock()
        self.ts        = collections.deque(maxlen=MAX_PTS)
        self.vals      = collections.deque(maxlen=MAX_PTS)
        self.t0        = None

        root.title("ADCMT 7352A  Digital Multimeter  [ADC mode]")
        root.configure(bg=BG)
        root.geometry("1360x860")
        root.minsize(1060, 720)

        self._styles()
        self._build_ui()

    # ── styles ────────────────────────────────────────────────────────────────
    def _styles(self):
        s = ttk.Style(); s.theme_use("clam")
        s.configure("TFrame",       background=BG, foreground=TEXT, font=("Consolas",10))
        s.configure("TLabel",       background=BG, foreground=TEXT, font=("Consolas",10))
        s.configure("TNotebook",    background=BG, borderwidth=0)
        s.configure("TNotebook.Tab",background=PANEL, foreground=MUTED,
                    padding=[12,5], font=("Consolas",10))
        s.map("TNotebook.Tab",
              background=[("selected",CARD)], foreground=[("selected",ACCENT)])
        s.configure("TCombobox",
                    fieldbackground=PANEL, foreground=TEXT,
                    selectbackground=PANEL, selectforeground=ACCENT,
                    arrowcolor=ACCENT, bordercolor=BORDER, font=("Consolas",10))
        s.map("TCombobox", fieldbackground=[("readonly",PANEL)],
              foreground=[("readonly",TEXT)])

    # ── widget helpers ────────────────────────────────────────────────────────
    def _card(self, parent, title, pady_top=0):
        o = tk.Frame(parent, bg=CARD, highlightthickness=1, highlightbackground=BORDER)
        o.pack(fill="x", pady=(pady_top,6))
        tk.Label(o, text=title, bg=CARD, fg=ACCENT,
                 font=("Consolas",10,"bold"), anchor="w").pack(fill="x", padx=10, pady=(7,3))
        tk.Frame(o, bg=BORDER, height=1).pack(fill="x")
        inn = tk.Frame(o, bg=CARD)
        inn.pack(fill="x", padx=10, pady=(6,8))
        return inn

    def _btn(self, parent, text, cmd, fg=ACCENT, **kw):
        return tk.Button(parent, text=text, command=cmd,
                         bg=PANEL, fg=fg, activebackground=BORDER, activeforeground=fg,
                         relief="flat", font=("Consolas",10,"bold"), cursor="hand2",
                         bd=0, highlightthickness=1, highlightbackground=BORDER,
                         padx=8, pady=4, **kw)

    def _entry(self, parent, default="", width=10):
        e = tk.Entry(parent, bg=PANEL, fg=TEXT, insertbackground=ACCENT,
                     relief="flat", font=("Consolas",10), bd=2,
                     highlightthickness=1, highlightbackground=BORDER, width=width)
        e.insert(0, default)
        return e

    # ── full UI ───────────────────────────────────────────────────────────────
    def _build_ui(self):
        # title bar
        tb = tk.Frame(self.root, bg=PANEL, height=50)
        tb.pack(fill="x"); tb.pack_propagate(False)
        tk.Label(tb, text="◈  ADCMT 7352A", bg=PANEL, fg=TEXT,
                 font=("Consolas",15,"bold")).pack(side="left", padx=14)
        tk.Label(tb, text="Digital Multimeter  [ADC mode]", bg=PANEL, fg=MUTED,
                 font=("Consolas",11)).pack(side="left")
        self._sdot = tk.Label(tb, text="●", bg=PANEL, fg=RED, font=("Consolas",14))
        self._sdot.pack(side="right", padx=(0,10))
        self._slbl = tk.Label(tb, text="DISCONNECTED", bg=PANEL, fg=RED,
                              font=("Consolas",10,"bold"))
        self._slbl.pack(side="right", padx=(0,4))

        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=10, pady=8)

        sb = tk.Frame(body, bg=BG, width=300)
        sb.pack(side="left", fill="y", padx=(0,8))
        sb.pack_propagate(False)
        self._build_conn_card(sb)
        self._build_func_card(sb)
        self._build_acq_card(sb)
        self._build_calc_card(sb)
        self._build_live_card(sb)

        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)
        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)
        pf = tk.Frame(nb, bg=BG); cf = tk.Frame(nb, bg=PANEL)
        nb.add(pf, text="  📈  Live Plot  ")
        nb.add(cf, text="  🖥  ADC Console  ")
        self._build_plot(pf)
        self._build_console(cf)

    # ── connection card ───────────────────────────────────────────────────────
    def _build_conn_card(self, sb):
        c = self._card(sb, "CONNECTION")
        tk.Label(c, text="Resource string", bg=CARD, fg=MUTED,
                 font=("Consolas",8)).pack(anchor="w")
        self._res_var = tk.StringVar(value="USB0::4916::520::999991006::0::INSTR")
        tk.Entry(c, textvariable=self._res_var,
                 bg=PANEL, fg=ACCENT, insertbackground=ACCENT,
                 relief="flat", font=("Consolas",8), bd=2,
                 highlightthickness=1, highlightbackground=BORDER
                 ).pack(fill="x", pady=(2,6))

        r = tk.Frame(c, bg=CARD); r.pack(fill="x")
        self._cbtn = self._btn(r, "CONNECT", self._connect, fg=GREEN)
        self._cbtn.pack(side="left", fill="x", expand=True, padx=(0,3))
        self._btn(r, "IDN?", self._do_idn, fg=MUTED).pack(side="left")

        self._sim_var = tk.BooleanVar(value=not PYVISA_AVAILABLE)
        tk.Checkbutton(c, text="Simulate (no hardware)", variable=self._sim_var,
                       bg=CARD, fg=MUTED, activebackground=CARD,
                       selectcolor=PANEL, font=("Consolas",9)).pack(anchor="w", pady=(5,0))
        self._idn_lbl = tk.Label(c, text="—", bg=CARD, fg=MUTED,
                                 font=("Consolas",8), wraplength=268, justify="left")
        self._idn_lbl.pack(anchor="w", pady=(3,0))

    # ── function / range card ─────────────────────────────────────────────────
    def _build_func_card(self, sb):
        c = self._card(sb, "FUNCTION & RANGE  (F1..F50, R0..R9)")

        tk.Label(c, text="Function", bg=CARD, fg=MUTED,
                 font=("Consolas",9)).pack(anchor="w")
        self._fkeys  = list(FUNCTIONS.keys())
        self._flabels = [v[0] for v in FUNCTIONS.values()]
        self._func_var = tk.StringVar(value=self._flabels[0])
        self._func_cb  = ttk.Combobox(c, textvariable=self._func_var,
                                      values=self._flabels, state="readonly",
                                      font=("Consolas",10))
        self._func_cb.pack(fill="x", pady=(2,6))
        self._func_cb.bind("<<ComboboxSelected>>", lambda _: self._refresh_ranges())

        tk.Label(c, text="Range  (Rn)", bg=CARD, fg=MUTED,
                 font=("Consolas",9)).pack(anchor="w")
        self._range_var = tk.StringVar(value="Auto")
        self._range_cb  = ttk.Combobox(c, textvariable=self._range_var,
                                       state="readonly", font=("Consolas",10))
        self._range_cb.pack(fill="x", pady=(2,6))
        self._refresh_ranges()

        # sampling rate  PR1..PR4
        sr = tk.Frame(c, bg=CARD); sr.pack(fill="x", pady=2)
        tk.Label(sr, text="Sampling  (PRn)", bg=CARD, fg=MUTED,
                 font=("Consolas",9), width=17, anchor="w").pack(side="left")
        self._srate_var = tk.StringVar(value="MED")
        ttk.Combobox(sr, textvariable=self._srate_var, values=SRATE_DISP,
                     state="readonly", font=("Consolas",10), width=7).pack(side="left")

        # digits  RE3..RE5
        dr = tk.Frame(c, bg=CARD); dr.pack(fill="x", pady=2)
        tk.Label(dr, text="Digits  (REn)", bg=CARD, fg=MUTED,
                 font=("Consolas",9), width=17, anchor="w").pack(side="left")
        self._digits_var = tk.StringVar(value="5½")
        ttk.Combobox(dr, textvariable=self._digits_var, values=DIGITS_DISP,
                     state="readonly", font=("Consolas",10), width=7).pack(side="left")

        # auto-zero  AZ0/AZ1
        self._az_var = tk.BooleanVar(value=True)
        tk.Checkbutton(c, text="Auto-Zero ON  (AZ1)", variable=self._az_var,
                       bg=CARD, fg=MUTED, activebackground=CARD,
                       selectcolor=PANEL, font=("Consolas",9)).pack(anchor="w", pady=(4,0))

        self._btn(c, "APPLY  FUNCTION & SETTINGS",
                  self._apply_func, fg=ACCENT).pack(fill="x", pady=(8,0))

    def _cur_fkey(self):
        lbl = self._func_var.get()
        for k, v in FUNCTIONS.items():
            if v[0] == lbl: return k
        return "F1"

    def _refresh_ranges(self):
        fk   = self._cur_fkey()
        rngs = FUNCTIONS[fk][2]
        lbls = [r[0] for r in rngs]
        self._range_cb["values"] = lbls
        self._range_var.set(lbls[0])
        self._cur_ranges = rngs

    # ── acquisition card ──────────────────────────────────────────────────────
    def _build_acq_card(self, sb):
        c = self._card(sb, "ACQUISITION  (bare read)")
        ir = tk.Frame(c, bg=CARD); ir.pack(fill="x", pady=2)
        tk.Label(ir, text="Read interval (ms)", bg=CARD, fg=MUTED,
                 font=("Consolas",9), width=18, anchor="w").pack(side="left")
        self._iv_e = self._entry(ir, "500", width=6); self._iv_e.pack(side="left")

        br = tk.Frame(c, bg=CARD); br.pack(fill="x", pady=(6,0))
        self._start_btn = self._btn(br, "▶  START", self._start_acq, fg=GREEN)
        self._stop_btn  = self._btn(br, "■  STOP",  self._stop_acq,  fg=YELLOW)
        self._start_btn.pack(side="left", fill="x", expand=True, padx=(0,3))
        self._stop_btn.pack(side="left",  fill="x", expand=True)
        self._btn(c, "CLEAR DATA", self._clear_data, fg=MUTED).pack(fill="x", pady=(4,0))

    # ── calculations card ─────────────────────────────────────────────────────
    def _build_calc_card(self, sb):
        c = self._card(sb, "CALCULATIONS  (§6.6.3)")

        def chk(text, var):
            tk.Checkbutton(c, text=text, variable=var,
                           bg=CARD, fg=MUTED, activebackground=CARD,
                           selectcolor=PANEL, font=("Consolas",9)).pack(anchor="w")

        self._nl_var = tk.BooleanVar()
        self._sm_var = tk.BooleanVar()
        self._co_var = tk.BooleanVar()
        self._mn_var = tk.BooleanVar()

        chk("NULL calc  (NL0/NL1)",          self._nl_var)
        chk("Smoothing  (SM0/SM1)",           self._sm_var)

        sp = tk.Frame(c, bg=CARD); sp.pack(fill="x", pady=(0,2))
        tk.Label(sp, text="  Smooth count  TIn (2-100)", bg=CARD, fg=MUTED,
                 font=("Consolas",8), anchor="w").pack(side="left")
        self._spts_e = self._entry(sp, "10", width=4); self._spts_e.pack(side="left")

        chk("Comparator  (CO0/CO1)",          self._co_var)

        def lrow(lbl, default):
            r = tk.Frame(c, bg=CARD); r.pack(fill="x", pady=1)
            tk.Label(r, text=f"  {lbl}", bg=CARD, fg=MUTED,
                     font=("Consolas",8), width=9, anchor="w").pack(side="left")
            e = self._entry(r, default, width=10); e.pack(side="left"); return e

        self._hi_e = lrow("HI  (HIn)", "10.0")
        self._lo_e = lrow("LO  (LOn)", "-10.0")

        chk("MAX/MIN/AVE  (MN0/MN1)",         self._mn_var)

        self._btn(c, "APPLY CALCULATIONS",
                  self._apply_calc, fg=PURPLE).pack(fill="x", pady=(6,0))
        self._btn(c, "READ MAX/MIN/AVE/STATS",
                  self._read_stats, fg=MUTED).pack(fill="x",  pady=(3,0))

    # ── live readback card ────────────────────────────────────────────────────
    def _build_live_card(self, sb):
        c = self._card(sb, "LIVE READING")
        self._val_lbl  = tk.Label(c, text="— — — — —", bg=CARD, fg=ACCENT,
                                  font=("Consolas",21,"bold"))
        self._val_lbl.pack(anchor="w")
        self._unit_lbl = tk.Label(c, text="", bg=CARD, fg=MUTED,
                                  font=("Consolas",11))
        self._unit_lbl.pack(anchor="w")
        self._sub_lbl  = tk.Label(c, text="", bg=CARD, fg=YELLOW,
                                  font=("Consolas",9))
        self._sub_lbl.pack(anchor="w")

    # ── plot ──────────────────────────────────────────────────────────────────
    def _build_plot(self, parent):
        if not MPLOT:
            tk.Label(parent, text="matplotlib not installed\npip install matplotlib",
                     bg=BG, fg=RED, font=("Consolas",12)).pack(expand=True)
            return
        ctrl = tk.Frame(parent, bg=BG); ctrl.pack(fill="x", padx=8, pady=(5,0))
        tk.Label(ctrl, text="Y-axis:", bg=BG, fg=MUTED,
                 font=("Consolas",9)).pack(side="left")
        self._autoy = tk.BooleanVar(value=True)
        tk.Checkbutton(ctrl, text="Auto-scale", variable=self._autoy,
                       bg=BG, fg=MUTED, activebackground=BG,
                       selectcolor=PANEL, font=("Consolas",9),
                       command=self._redraw).pack(side="left", padx=8)
        tk.Label(ctrl, text="pts:", bg=BG, fg=MUTED,
                 font=("Consolas",9)).pack(side="left")
        self._npts_var = tk.StringVar(value="200")
        ttk.Combobox(ctrl, textvariable=self._npts_var,
                     values=["50","100","200","300","500","all"],
                     state="readonly", font=("Consolas",9), width=5
                     ).pack(side="left", padx=4)

        fig = Figure(figsize=(8,5), dpi=96, facecolor=BG)
        self._ax = fig.add_subplot(111)
        self._sax(self._ax)
        fig.tight_layout(pad=1.8)
        self._fig    = fig
        self._canvas = FigureCanvasTkAgg(fig, master=parent)
        self._canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)

    def _sax(self, ax):
        ax.set_facecolor(BG)
        ax.tick_params(colors=MUTED, labelcolor=MUTED, labelsize=8)
        for sp in ax.spines.values(): sp.set_color(BORDER)
        ax.grid(color=BORDER, linestyle="--", linewidth=0.4, alpha=0.6)

    def _redraw(self):
        if not MPLOT or not hasattr(self,"_ax"): return
        n   = self._npts_var.get() if hasattr(self,"_npts_var") else "200"
        if n == "all":
            ts = list(self.ts); vs = list(self.vals)
        else:
            ts = list(self.ts)[-int(n):]; vs = list(self.vals)[-int(n):]
        if not ts: return
        ax = self._ax; ax.cla(); self._sax(ax)
        fk   = self._cur_fkey()
        unit = FUNCTIONS[fk][1]
        ok_ts = [t for t,v in zip(ts,vs) if v < OVERLOAD_THRESHOLD]
        ok_vs = [v for v in vs            if v < OVERLOAD_THRESHOLD]
        ol_ts = [t for t,v in zip(ts,vs) if v >= OVERLOAD_THRESHOLD]
        if ok_ts:
            ax.plot(ok_ts, ok_vs, color=ACCENT, linewidth=1.3,
                    marker=".", markersize=2.5, label=f"Measurement ({unit})")
        for t in ol_ts:
            ax.axvline(t, color=RED, linewidth=0.7, linestyle=":", alpha=0.6)
        if ol_ts:
            ax.axvline(ol_ts[-1], color=RED, linewidth=0.7, linestyle=":", label="OVERLOAD")
        if ok_vs and self._autoy.get():
            mn,mx = min(ok_vs), max(ok_vs)
            pad   = (mx-mn)*0.15 if mx!=mn else abs(mn)*0.05+1e-9
            ax.set_ylim(mn-pad, mx+pad)
        ax.set_xlabel("Time (s)", color=MUTED, fontsize=9)
        ax.set_ylabel(unit,       color=ACCENT, fontsize=9)
        ax.tick_params(axis="y",  colors=ACCENT, labelcolor=ACCENT)
        if ok_ts or ol_ts:
            ax.legend(fontsize=8, facecolor=CARD, edgecolor=BORDER,
                      labelcolor=TEXT, loc="upper left")
        self._canvas.draw_idle()

    # ── ADC console ───────────────────────────────────────────────────────────
    def _build_console(self, parent):
        top = tk.Frame(parent, bg=PANEL); top.pack(fill="x", padx=8, pady=6)
        tk.Label(top, text="CMD:", bg=PANEL, fg=MUTED,
                 font=("Consolas",9)).pack(side="left")
        self._cmd_e = tk.Entry(top, bg=BG, fg=ACCENT, insertbackground=ACCENT,
                               relief="flat", font=("Consolas",10), bd=2,
                               highlightthickness=1, highlightbackground=BORDER,
                               width=40)
        self._cmd_e.pack(side="left", padx=6)
        self._cmd_e.bind("<Return>", lambda _: self._send_cmd())
        self._btn(top, "SEND",  self._send_cmd,             fg=ACCENT).pack(side="left")
        self._btn(top, "CLEAR", self._clr_console,          fg=MUTED ).pack(side="left", padx=(3,0))
        self._btn(top, "*RST",  lambda: self._adc_write("*RST"), fg=RED   ).pack(side="left", padx=(8,0))
        self._btn(top, "*CLS",  lambda: self._adc_write("*CLS"), fg=YELLOW).pack(side="left", padx=(3,0))

        self._cons = tk.Text(parent, bg=BG, fg=TEXT,
                             font=("Consolas",9), relief="flat", bd=0,
                             padx=8, pady=6, insertbackground=ACCENT,
                             wrap="word", state="disabled")
        self._cons.pack(fill="both", expand=True, padx=8, pady=(0,8))
        for tag, fg in [("cmd",ACCENT),("resp",TEXT),("err",RED),
                        ("info",MUTED),("ok",GREEN),("ol",ORANGE)]:
            self._cons.tag_config(tag, foreground=fg)
        self._log("ADCMT 7352A  [ADC mode, \\r\\n termination]","info")
        self._log("Free-run: instrument streams data → bare read() used for acquisition.","info")
        if not PYVISA_AVAILABLE:
            self._log("pyvisa not installed — simulation mode active.","err")

    def _log(self, text, tag="resp"):
        self._cons.configure(state="normal")
        self._cons.insert("end", f"[{time.strftime('%H:%M:%S')}]  {text}\n", tag)
        self._cons.see("end"); self._cons.configure(state="disabled")

    def _clr_console(self):
        self._cons.configure(state="normal"); self._cons.delete("1.0","end")
        self._cons.configure(state="disabled")

    # ══════════════════════════════════════════════════════════════════════════
    #  Transport helpers
    #  Termination: \r\n on both write and read  (manual §6.3.3)
    #  USB caution: 20 ms wait after each write  (manual §6.6.3 CAUTION)
    # ══════════════════════════════════════════════════════════════════════════
    def _chk(self):
        if not self.connected or self.instr is None:
            self._log("Not connected.","err"); return False
        return True

    def _adc_write(self, cmd):
        """Write an ADC command.  Checks ERR? afterwards."""
        if not self._chk(): return
        try:
            self._log(f">> {cmd}", "cmd")
            self.instr.write(cmd)
            time.sleep(0.025)                    # 20 ms USB settling
            err = self.instr.query("ERR?").strip()
            if not err.startswith("+000"):
                self._log(f"   ⚠ ERR? → {err}", "err")
        except Exception as exc:
            self._log(f"Write error: {exc}", "err")

    def _adc_query(self, cmd):
        """Write a query command and return the stripped response."""
        if not self._chk(): return None
        try:
            self._log(f">> {cmd}", "cmd")
            time.sleep(0.025)
            resp = self.instr.query(cmd).strip()
            self._log(f"<< {resp}", "resp")
            return resp
        except Exception as exc:
            self._log(f"Query error: {exc}", "err"); return None

    def _adc_read(self):
        """Bare read — no command sent.  Returns latest measurement string."""
        return self.instr.read().strip()

    # ══════════════════════════════════════════════════════════════════════════
    #  Response parser  (§6.6.2)
    #  Header ON (H1):  "DCV_  +3.29860E+00"   or  "DCV_  -0.00123E+00"
    #  Header OFF (H0): "+3.29860E+00"
    #  Overload:        9.99999E+37
    # ══════════════════════════════════════════════════════════════════════════
    _HDR_RE = re.compile(r'^([A-Z0-9_]{3})([A-Z_])\s+([-+]?\d[\d.]*E[+-]\d+)\s*$')
    _NUM_RE = re.compile(r'^([-+]?\d[\d.]*E[+-]\d+)')

    def _parse(self, raw):
        """Returns (value, main_hdr, sub_hdr, is_overload, display_str, desc_str)."""
        raw = raw.strip()
        main_h, sub_h = "", "_"
        m = self._HDR_RE.match(raw)
        if m:
            main_h = m.group(1)
            sub_h  = m.group(2)
            num_s  = m.group(3)
        else:
            nm = self._NUM_RE.match(raw)
            num_s = nm.group(1) if nm else raw
        try:
            val = float(num_s)
        except ValueError:
            return 0.0, main_h, sub_h, False, raw, raw
        is_ol = val >= OVERLOAD_THRESHOLD
        unit  = FUNCTIONS[self._cur_fkey()][1]
        disp  = "OVERLOAD" if is_ol else self._si_fmt(val, unit)
        desc  = HDR_LABELS.get(main_h, main_h) + SUB_LABELS.get(sub_h, f" [{sub_h}]")
        return val, main_h, sub_h, is_ol, disp, desc

    @staticmethod
    def _si_fmt(val, unit):
        if val == 0: return f"0.000 {unit}"
        a = abs(val)
        for scale, pfx in [(1e12,"T"),(1e9,"G"),(1e6,"M"),(1e3,"k"),
                           (1,""),(1e-3,"m"),(1e-6,"µ"),(1e-9,"n"),(1e-12,"p")]:
            if a >= scale * 0.9999:
                return f"{val/scale:.5g} {pfx}{unit}"
        return f"{val:.5E} {unit}"

    # ══════════════════════════════════════════════════════════════════════════
    #  Actions
    # ══════════════════════════════════════════════════════════════════════════
    def _connect(self):
        if self.connected: self._disconnect(); return
        if self._sim_var.get():
            self.instr = Sim7352A()
            self.connected = True
            self._set_st(True)
            self._cbtn.config(text="DISCONNECT", fg=RED)
            self._log("Connected (simulation mode)","ok")
            self._init_instrument()
            return
        if not PYVISA_AVAILABLE:
            messagebox.showerror("PyVISA","pip install pyvisa pyvisa-py"); return
        try:
            rm   = pyvisa.ResourceManager()
            inst = rm.open_resource(self._res_var.get())
            inst.timeout          = 10000
            inst.write_termination = "\r\n"   # CR+LF  (§6.3.3)
            inst.read_termination  = "\r\n"
            self.instr = inst
            self.connected = True
            self._set_st(True)
            self._cbtn.config(text="DISCONNECT", fg=RED)
            self._log(f"Connected: {self._res_var.get()}  [\\r\\n termination]","ok")
            self._init_instrument()
        except Exception as exc:
            self._log(f"Connection error: {exc}","err")
            messagebox.showerror("Connection error", str(exc))

    def _disconnect(self):
        self._stop_acq()
        if self.instr:
            try: self.instr.close()
            except: pass
        self.instr = None; self.connected = False
        self._set_st(False); self._cbtn.config(text="CONNECT", fg=GREEN)
        self._log("Disconnected.","info")

    def _set_st(self, ok):
        c, t = (GREEN,"CONNECTED") if ok else (RED,"DISCONNECTED")
        self._sdot.config(fg=c); self._slbl.config(fg=c, text=t)

    def _init_instrument(self):
        """Initial setup sequence matching the USB sample program (§6.7.4)."""
        self._adc_write("*RST")         # parameter initialisation
        time.sleep(0.1)
        self._adc_write("H1")           # header ON  → "DCV_  +x.xxxxxExx"
        self._adc_write("DE0")          # 2nd display OFF
        self._adc_write("SD1")          # remote output: 1st display only
        self._adc_write("TRS0")         # trigger source: IMMEDIATE
        self._adc_write("INIC1")        # continuous measurement ON
        self._do_idn()

    def _do_idn(self):
        r = self._adc_query("*IDN?")
        if r: self._idn_lbl.config(text=r)

    # Apply function + range + rate + digits + auto-zero  (§6.6.3)
    def _apply_func(self):
        if not self._chk(): return
        fk    = self._cur_fkey()
        rlbl  = self._range_var.get()
        rngs  = FUNCTIONS[fk][2]
        r_cmd = next((rc for lbl,rc in rngs if lbl == rlbl), "R0")

        si    = SRATE_DISP.index(self._srate_var.get()) if self._srate_var.get() in SRATE_DISP else 1
        pr    = SRATE_CMD[si]
        di    = DIGITS_DISP.index(self._digits_var.get()) if self._digits_var.get() in DIGITS_DISP else 2
        re    = DIGITS_CMD[di]
        az    = "AZ1" if self._az_var.get() else "AZ0"

        # Function:  Fn  (or DSP1,Fn for 1st display — same thing)
        self._adc_write(fk)
        # Range:     Rn  (skip if no range cmd, e.g. DIODE/CONT/TEMP)
        if r_cmd:
            self._adc_write(r_cmd)
        # Sampling rate:  PR1..PR4
        self._adc_write(pr)
        # Display digits: RE3..RE5
        self._adc_write(re)
        # Auto-zero:      AZ0 / AZ1
        self._adc_write(az)
        # Confirm
        self._adc_query("F?")
        self._adc_query("R?")

    # Apply calculation settings  (§6.6.3)
    def _apply_calc(self):
        if not self._chk(): return
        # NULL  NL0/NL1
        self._adc_write("NL1" if self._nl_var.get() else "NL0")
        # Smoothing  SM0/SM1  +  TIn
        self._adc_write("SM1" if self._sm_var.get() else "SM0")
        if self._sm_var.get():
            try: pts = max(2, min(100, int(self._spts_e.get())))
            except: pts = 10
            self._adc_write(f"TI{pts}")
        # Comparator  CO0/CO1  +  HIn / LOn
        self._adc_write("CO1" if self._co_var.get() else "CO0")
        if self._co_var.get():
            try: hi, lo = float(self._hi_e.get()), float(self._lo_e.get())
            except: hi, lo = 10.0, -10.0
            self._adc_write(f"HI{hi:.6E}")
            self._adc_write(f"LO{lo:.6E}")
        # MAX/MIN  MN0/MN1
        self._adc_write("MN1" if self._mn_var.get() else "MN0")
        self._adc_query("*OPC?")

    def _read_stats(self):
        """Read MAX/MIN/AVE from MAX/MIN/AVE rolling calc and stats memory."""
        if not self._chk(): return
        for cmd, lbl in [
            ("MAX?",  "MAX"),
            ("MIN?",  "MIN"),
            ("AVE?",  "AVE"),
            ("AVN?",  "AVE N"),
            ("SCNT?", "STAT N"),
            ("SMAX?", "STAT MAX"),
            ("SMIN?", "STAT MIN"),
            ("SAVE?", "STAT AVG"),
            ("SSIG?", "STAT σ"),
            ("SPTP?", "MAX−MIN"),
        ]:
            r = self._adc_query(cmd)
            if r: self._log(f"  {lbl:12s}: {r}", "ok")

    # ── acquisition loop ──────────────────────────────────────────────────────
    def _start_acq(self):
        if self.reading: return
        if not self._chk(): return
        try: iv = max(50, int(self._iv_e.get()))
        except: iv = 500
        self._iv_ms = iv; self.t0 = time.time(); self.reading = True
        threading.Thread(target=self._loop, daemon=True).start()
        self._log(f"Acquisition started  (interval={iv} ms, bare read())","ok")

    def _stop_acq(self):
        if self.reading:
            self.reading = False
            self._log("Acquisition stopped.","info")

    def _clear_data(self):
        self.ts.clear(); self.vals.clear()
        if MPLOT and hasattr(self,"_ax"):
            self._ax.cla(); self._sax(self._ax); self._canvas.draw_idle()
        self._log("Data cleared.","info")

    def _loop(self):
        """
        Instrument is in free-run / continuous mode (INIC1 + TRS0).
        Data is read with a bare instr.read() — no write command needed.
        (mirrors §6.7.4 USB sample: ausbrd() → ausb_read() without prior write)
        """
        ticker = 0
        while self.reading:
            t0 = time.time()
            try:
                with self._rlock:
                    raw = self._adc_read()          # bare read — no command
                val, mh, sh, is_ol, disp, desc = self._parse(raw)
                elapsed = time.time() - self.t0
                self.ts.append(elapsed)
                self.vals.append(OVERLOAD_THRESHOLD * 1.1 if is_ol else val)
                self.root.after(0, self._upd_live, disp,
                                FUNCTIONS[self._cur_fkey()][1], desc, is_ol, sh)
                ticker += 1
                if ticker >= 3:
                    ticker = 0
                    self.root.after(0, self._redraw)
            except Exception as exc:
                self.root.after(0, self._log, f"Read error: {exc}", "err")
                time.sleep(0.5)

            elapsed_ms = (time.time()-t0)*1000
            time.sleep(max(0.0, (self._iv_ms - elapsed_ms)/1000))

    def _upd_live(self, disp, unit, desc, is_ol, sub_h):
        colour = RED if is_ol else (ORANGE if sub_h not in ("_","") else ACCENT)
        self._val_lbl.config(text=disp,  fg=colour)
        self._unit_lbl.config(text=unit)
        self._sub_lbl.config(text=desc if (is_ol or sub_h not in ("_","")) else "")

    # ── ADC console send ──────────────────────────────────────────────────────
    def _send_cmd(self):
        cmd = self._cmd_e.get().strip()
        if not cmd: return
        (self._adc_query if cmd.endswith("?") else self._adc_write)(cmd)
        self._cmd_e.delete(0,"end")

    # ── cleanup ───────────────────────────────────────────────────────────────
    def on_close(self):
        self._disconnect(); self.root.destroy()


# ══════════════════════════════════════════════════════════════════════════════
def main():
    root = tk.Tk()
    app  = DMM7352A(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()

if __name__ == "__main__":
    main()
