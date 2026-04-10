"""
ADCE 7352A Instrument Control GUI
PyVISA Resource: USB0::4916::520::999991006::0::INSTR
"""

import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont
import threading
import time
import collections
import math

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
    from matplotlib.animation import FuncAnimation
    import matplotlib.ticker as ticker
    MATPLOTLIB_AVAILABLE = True
except ImportError:
    MATPLOTLIB_AVAILABLE = False

# ── Colour palette (industrial dark theme) ────────────────────────────────────
BG       = "#0f1117"
PANEL    = "#181c27"
CARD     = "#1e2435"
BORDER   = "#2a3050"
ACCENT   = "#00d4ff"
ACCENT2  = "#ff6b35"
SUCCESS  = "#00e676"
WARNING  = "#ffd600"
DANGER   = "#ff1744"
TEXT     = "#e8eaf6"
MUTED    = "#7986cb"
PLOT_BG  = "#0d1118"

RESOURCE_ID = "USB0::4916::520::999991006::0::INSTR"
MAX_POINTS   = 500   # rolling buffer length


# ── Simulated instrument (used when PyVISA / hardware not available) ──────────
class SimulatedInstrument:
    def __init__(self):
        self._voltage_set  = 5.0
        self._current_set  = 1.0
        self._output_on    = False
        self._t0           = time.time()

    def query(self, cmd):
        cmd = cmd.strip()
        if not cmd:
            if not self._output_on:
                return "0.0000,0.0000,0.0000"
            noise_v = 0.01 * math.sin(time.time() * 3.7) + 0.005 * (hash(time.time()) % 100) / 100
            noise_i = 0.002 * math.cos(time.time() * 2.1) + 0.001 * (hash(time.time() * 1.3) % 100) / 100
            v = self._voltage_set + noise_v
            i = self._current_set * 0.95 + noise_i
            p = v * i
            return f"{v:.4f},{i:.4f},{p:.4f}"
        if cmd == "*IDN?":
            return "ADCE,7352A,999991006,FW2.4.1"
        if cmd == "MEAS:VOLT?":
            if not self._output_on:
                return "0.0000"
            noise = 0.01 * math.sin(time.time() * 3.7) + 0.005 * (hash(time.time()) % 100) / 100
            return f"{self._voltage_set + noise:.4f}"
        if cmd == "MEAS:CURR?":
            if not self._output_on:
                return "0.0000"
            noise = 0.002 * math.cos(time.time() * 2.1) + 0.001 * (hash(time.time() * 1.3) % 100) / 100
            return f"{self._current_set * 0.95 + noise:.4f}"
        if cmd == "MEAS:POW?":
            if not self._output_on:
                return "0.0000"
            v = self._voltage_set + 0.01 * math.sin(time.time() * 3.7)
            i = self._current_set * 0.95 + 0.002 * math.cos(time.time() * 2.1)
            return f"{v * i:.4f}"
        if cmd == "OUTP?":
            return "1" if self._output_on else "0"
        if cmd == "VOLT?":
            return f"{self._voltage_set:.4f}"
        if cmd == "CURR?":
            return f"{self._current_set:.4f}"
        if cmd == "SOUR:RANG?":
            return "HIGH"
        return "0"

    def write(self, cmd):
        cmd = cmd.strip()
        if cmd.startswith("VOLT "):
            try:
                self._voltage_set = float(cmd.split()[1])
            except ValueError:
                pass
        elif cmd.startswith("CURR "):
            try:
                self._current_set = float(cmd.split()[1])
            except ValueError:
                pass
        elif cmd == "OUTP ON" or cmd == "OUTP 1":
            self._output_on = True
        elif cmd == "OUTP OFF" or cmd == "OUTP 0":
            self._output_on = False

    def close(self):
        pass


# ── Main application ──────────────────────────────────────────────────────────
class ADCE7352AGUI:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title("ADCE 7352A  ·  Instrument Controller")
        self.root.configure(bg=BG)
        self.root.geometry("1280x820")
        self.root.minsize(1000, 700)

        self.instrument   = None
        self.connected    = False
        self.reading      = False
        self.read_thread  = None
        self.read_interval_ms = 500

        # rolling data buffers
        self.times     = collections.deque(maxlen=MAX_POINTS)
        self.voltages  = collections.deque(maxlen=MAX_POINTS)
        self.currents  = collections.deque(maxlen=MAX_POINTS)
        self.powers    = collections.deque(maxlen=MAX_POINTS)
        self.t_start   = None

        self._build_styles()
        self._build_ui()

    # ── Styles ─────────────────────────────────────────────────────────────────
    def _build_styles(self):
        style = ttk.Style()
        style.theme_use("clam")
        style.configure("TFrame",       background=BG)
        style.configure("Card.TFrame",  background=CARD)
        style.configure("Panel.TFrame", background=PANEL)

        style.configure("TLabel",
                        background=BG, foreground=TEXT,
                        font=("Consolas", 10))
        style.configure("Card.TLabel",
                        background=CARD, foreground=TEXT,
                        font=("Consolas", 10))
        style.configure("Header.TLabel",
                        background=BG, foreground=ACCENT,
                        font=("Consolas", 11, "bold"))
        style.configure("Muted.TLabel",
                        background=CARD, foreground=MUTED,
                        font=("Consolas", 9))

        style.configure("TEntry",
                        fieldbackground=PANEL, foreground=TEXT,
                        insertcolor=ACCENT, bordercolor=BORDER,
                        font=("Consolas", 10))
        style.configure("TCombobox",
                        fieldbackground=PANEL, foreground=TEXT,
                        selectbackground=PANEL, selectforeground=ACCENT,
                        arrowcolor=ACCENT, bordercolor=BORDER,
                        font=("Consolas", 10))
        style.map("TCombobox",
                  fieldbackground=[("readonly", PANEL)],
                  foreground=[("readonly", TEXT)])

        style.configure("TNotebook",       background=BG, borderwidth=0)
        style.configure("TNotebook.Tab",
                        background=PANEL, foreground=MUTED,
                        padding=[12, 6],
                        font=("Consolas", 10))
        style.map("TNotebook.Tab",
                  background=[("selected", CARD)],
                  foreground=[("selected", ACCENT)])

        style.configure("Horizontal.TSeparator", background=BORDER)

    # ── UI skeleton ────────────────────────────────────────────────────────────
    def _build_ui(self):
        # Title bar
        title_bar = tk.Frame(self.root, bg=PANEL, height=52)
        title_bar.pack(fill="x", side="top")
        title_bar.pack_propagate(False)

        tk.Label(title_bar, text="⬡", bg=PANEL, fg=ACCENT,
                 font=("Consolas", 22)).pack(side="left", padx=(16, 4), pady=8)
        tk.Label(title_bar, text="ADCE 7352A", bg=PANEL, fg=TEXT,
                 font=("Consolas", 15, "bold")).pack(side="left", pady=8)
        tk.Label(title_bar, text="  Instrument Controller", bg=PANEL, fg=MUTED,
                 font=("Consolas", 11)).pack(side="left", pady=8)

        self.status_dot = tk.Label(title_bar, text="●", bg=PANEL, fg=DANGER,
                                   font=("Consolas", 14))
        self.status_dot.pack(side="right", padx=(0, 8))
        self.status_label = tk.Label(title_bar, text="DISCONNECTED", bg=PANEL,
                                     fg=DANGER, font=("Consolas", 10, "bold"))
        self.status_label.pack(side="right", padx=(0, 4))

        # Main body
        body = tk.Frame(self.root, bg=BG)
        body.pack(fill="both", expand=True, padx=12, pady=8)

        # Left sidebar
        sidebar = tk.Frame(body, bg=BG, width=300)
        sidebar.pack(side="left", fill="y", padx=(0, 10))
        sidebar.pack_propagate(False)

        self._build_connection_card(sidebar)
        self._build_settings_card(sidebar)
        self._build_output_card(sidebar)
        self._build_readback_card(sidebar)

        # Right: notebook (plot + console)
        right = tk.Frame(body, bg=BG)
        right.pack(side="left", fill="both", expand=True)

        nb = ttk.Notebook(right)
        nb.pack(fill="both", expand=True)

        plot_frame   = tk.Frame(nb, bg=PLOT_BG)
        console_frame = tk.Frame(nb, bg=PANEL)
        nb.add(plot_frame,   text="  📈  Live Plot  ")
        nb.add(console_frame, text="  🖥  Console  ")

        self._build_plot(plot_frame)
        self._build_console(console_frame)

    # ── Sidebar cards ──────────────────────────────────────────────────────────
    def _card(self, parent, title):
        wrap = tk.Frame(parent, bg=CARD, bd=0, highlightthickness=1,
                        highlightbackground=BORDER)
        wrap.pack(fill="x", pady=(0, 8))
        hdr = tk.Frame(wrap, bg=BORDER, height=1)
        hdr.pack(fill="x")
        tk.Label(wrap, text=title, bg=CARD, fg=ACCENT,
                 font=("Consolas", 10, "bold"),
                 anchor="w").pack(fill="x", padx=10, pady=(8, 4))
        inner = tk.Frame(wrap, bg=CARD)
        inner.pack(fill="x", padx=10, pady=(0, 10))
        return inner

    def _btn(self, parent, text, cmd, fg=ACCENT, **kw):
        b = tk.Button(parent, text=text, command=cmd,
                      bg=PANEL, fg=fg, activebackground=BORDER,
                      activeforeground=fg, relief="flat",
                      font=("Consolas", 10, "bold"),
                      cursor="hand2", bd=0,
                      highlightthickness=1, highlightbackground=BORDER,
                      padx=8, pady=4, **kw)
        return b

    def _row(self, parent, label, widget_factory):
        f = tk.Frame(parent, bg=CARD)
        f.pack(fill="x", pady=2)
        tk.Label(f, text=label, bg=CARD, fg=MUTED,
                 font=("Consolas", 9), width=14, anchor="w").pack(side="left")
        w = widget_factory(f)
        w.pack(side="left", fill="x", expand=True)
        return w

    def _entry(self, parent, default="", width=10):
        e = tk.Entry(parent, bg=PANEL, fg=TEXT, insertbackground=ACCENT,
                     relief="flat", font=("Consolas", 10), bd=2,
                     highlightthickness=1, highlightbackground=BORDER, width=width)
        e.insert(0, default)
        return e

    # ── Connection card ────────────────────────────────────────────────────────
    def _build_connection_card(self, parent):
        inner = self._card(parent, "CONNECTION")

        tk.Label(inner, text="Resource", bg=CARD, fg=MUTED,
                 font=("Consolas", 9)).pack(anchor="w")
        self.resource_var = tk.StringVar(value=RESOURCE_ID)
        re = tk.Entry(inner, textvariable=self.resource_var,
                      bg=PANEL, fg=ACCENT, insertbackground=ACCENT,
                      relief="flat", font=("Consolas", 9), bd=2,
                      highlightthickness=1, highlightbackground=BORDER)
        re.pack(fill="x", pady=(2, 6))

        btn_row = tk.Frame(inner, bg=CARD)
        btn_row.pack(fill="x")
        self.connect_btn = self._btn(btn_row, "CONNECT", self._connect, fg=SUCCESS)
        self.connect_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self._btn(btn_row, "IDN?", self._query_idn, fg=MUTED).pack(side="left")

        tk.Label(inner, text="", bg=CARD).pack()  # spacer
        self.idn_label = tk.Label(inner, text="—", bg=CARD, fg=MUTED,
                                  font=("Consolas", 8), wraplength=260, justify="left")
        self.idn_label.pack(anchor="w")

        # Simulate checkbox
        self.sim_var = tk.BooleanVar(value=not PYVISA_AVAILABLE)
        tk.Checkbutton(inner, text="Simulate (no hardware)",
                       variable=self.sim_var,
                       bg=CARD, fg=MUTED, activebackground=CARD,
                       selectcolor=PANEL, font=("Consolas", 9)).pack(anchor="w", pady=(4, 0))

    # ── Settings card ──────────────────────────────────────────────────────────
    def _build_settings_card(self, parent):
        inner = self._card(parent, "DEVICE SETTINGS")

        self.volt_entry = self._row(inner, "Voltage (V)", lambda p: self._entry(p, "5.000"))
        self.curr_entry = self._row(inner, "Current (A)", lambda p: self._entry(p, "1.000"))

        tk.Label(inner, text="Range", bg=CARD, fg=MUTED,
                 font=("Consolas", 9)).pack(anchor="w", pady=(4, 0))
        self.range_var = tk.StringVar(value="HIGH")
        cb = ttk.Combobox(inner, textvariable=self.range_var,
                          values=["HIGH", "LOW", "AUTO"],
                          state="readonly", font=("Consolas", 10))
        cb.pack(fill="x", pady=(2, 6))

        tk.Label(inner, text="OVP Limit (V)", bg=CARD, fg=MUTED,
                 font=("Consolas", 9)).pack(anchor="w")
        self.ovp_entry = self._entry(inner, "35.00")
        self.ovp_entry.pack(fill="x", pady=(2, 6))

        self._btn(inner, "APPLY SETTINGS", self._apply_settings,
                  fg=ACCENT).pack(fill="x")

    # ── Output card ───────────────────────────────────────────────────────────
    def _build_output_card(self, parent):
        inner = self._card(parent, "OUTPUT CONTROL")

        btn_row = tk.Frame(inner, bg=CARD)
        btn_row.pack(fill="x", pady=(0, 6))
        self.out_on_btn  = self._btn(btn_row, "OUTPUT ON",  self._output_on,  fg=SUCCESS)
        self.out_off_btn = self._btn(btn_row, "OUTPUT OFF", self._output_off, fg=DANGER)
        self.out_on_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.out_off_btn.pack(side="left", fill="x", expand=True)

        sep = tk.Frame(inner, bg=BORDER, height=1)
        sep.pack(fill="x", pady=4)

        tk.Label(inner, text="Acquisition", bg=CARD, fg=MUTED,
                 font=("Consolas", 9)).pack(anchor="w")

        iv_row = tk.Frame(inner, bg=CARD)
        iv_row.pack(fill="x", pady=2)
        tk.Label(iv_row, text="Interval (ms)", bg=CARD, fg=MUTED,
                 font=("Consolas", 9), width=14, anchor="w").pack(side="left")
        self.interval_entry = self._entry(iv_row, "500")
        self.interval_entry.pack(side="left")

        acq_row = tk.Frame(inner, bg=CARD)
        acq_row.pack(fill="x", pady=(6, 0))
        self.start_btn = self._btn(acq_row, "▶  START", self._start_reading, fg=SUCCESS)
        self.stop_btn  = self._btn(acq_row, "■  STOP",  self._stop_reading,  fg=WARNING)
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 4))
        self.stop_btn.pack(side="left", fill="x", expand=True)

        clr_btn = self._btn(inner, "CLEAR BUFFERS", self._clear_buffers, fg=MUTED)
        clr_btn.pack(fill="x", pady=(6, 0))

    # ── Readback card ──────────────────────────────────────────────────────────
    def _build_readback_card(self, parent):
        inner = self._card(parent, "LIVE READBACK")

        def metric(label, color):
            f = tk.Frame(inner, bg=CARD)
            f.pack(fill="x", pady=2)
            tk.Label(f, text=label, bg=CARD, fg=MUTED,
                     font=("Consolas", 9), width=10, anchor="w").pack(side="left")
            val = tk.Label(f, text="— —", bg=CARD, fg=color,
                           font=("Consolas", 14, "bold"))
            val.pack(side="left")
            return val

        self.v_display = metric("Voltage", ACCENT)
        self.i_display = metric("Current", ACCENT2)
        self.p_display = metric("Power  ", SUCCESS)

    # ── Plot ───────────────────────────────────────────────────────────────────
    def _build_plot(self, parent):
        if not MATPLOTLIB_AVAILABLE:
            tk.Label(parent, text="matplotlib not installed.\npip install matplotlib",
                     bg=PLOT_BG, fg=DANGER, font=("Consolas", 12)).pack(expand=True)
            return

        ctrl = tk.Frame(parent, bg=PLOT_BG)
        ctrl.pack(fill="x", padx=10, pady=(6, 0))

        tk.Label(ctrl, text="Channels:", bg=PLOT_BG, fg=MUTED,
                 font=("Consolas", 9)).pack(side="left")
        self.show_volt_var = tk.BooleanVar(value=True)
        self.show_curr_var = tk.BooleanVar(value=True)
        self.show_pow_var  = tk.BooleanVar(value=False)

        def chk(parent, text, var, color):
            return tk.Checkbutton(parent, text=text, variable=var,
                                  bg=PLOT_BG, fg=color, activebackground=PLOT_BG,
                                  selectcolor=PANEL, font=("Consolas", 9),
                                  command=self._redraw_plot)

        chk(ctrl, " Voltage", self.show_volt_var, ACCENT).pack(side="left", padx=6)
        chk(ctrl, " Current", self.show_curr_var, ACCENT2).pack(side="left", padx=6)
        chk(ctrl, " Power",   self.show_pow_var,  SUCCESS).pack(side="left", padx=6)

        fig = Figure(figsize=(8, 5), dpi=100, facecolor=PLOT_BG)
        self.ax = fig.add_subplot(111)
        self._style_axes(self.ax)
        fig.tight_layout(pad=1.5)

        self.canvas = FigureCanvasTkAgg(fig, master=parent)
        self.canvas.get_tk_widget().pack(fill="both", expand=True, padx=6, pady=6)
        self.fig = fig

        # secondary Y axis for current
        self.ax2 = self.ax.twinx()
        self._style_axes(self.ax2)
        self.ax2.tick_params(colors=ACCENT2, labelcolor=ACCENT2)
        self.ax2.yaxis.label.set_color(ACCENT2)

        self.line_v = None
        self.line_i = None
        self.line_p = None

    def _style_axes(self, ax):
        ax.set_facecolor(PLOT_BG)
        ax.tick_params(colors=MUTED, labelcolor=MUTED, labelsize=8)
        ax.spines["bottom"].set_color(BORDER)
        ax.spines["top"].set_color(BORDER)
        ax.spines["left"].set_color(BORDER)
        ax.spines["right"].set_color(BORDER)
        ax.grid(color=BORDER, linestyle="--", linewidth=0.5, alpha=0.5)

    def _redraw_plot(self):
        if not MATPLOTLIB_AVAILABLE or not hasattr(self, "ax"):
            return
        ts = list(self.times)
        vs = list(self.voltages)
        cs = list(self.currents)
        ps = list(self.powers)
        if not ts:
            return

        self.ax.cla()
        self.ax2.cla()
        self._style_axes(self.ax)
        self._style_axes(self.ax2)
        self.ax2.tick_params(colors=ACCENT2, labelcolor=ACCENT2)

        plotted = 0
        if self.show_volt_var.get() and vs:
            self.ax.plot(ts, vs, color=ACCENT,  linewidth=1.5, label="Voltage (V)")
            self.ax.set_ylabel("Voltage (V)", color=ACCENT, fontsize=9)
            plotted += 1
        if self.show_curr_var.get() and cs:
            self.ax2.plot(ts, cs, color=ACCENT2, linewidth=1.5, label="Current (A)", linestyle="--")
            self.ax2.set_ylabel("Current (A)", color=ACCENT2, fontsize=9)
            plotted += 1
        if self.show_pow_var.get() and ps:
            self.ax.plot(ts, ps, color=SUCCESS,  linewidth=1.5, label="Power (W)", linestyle=":")
            plotted += 1

        self.ax.set_xlabel("Time (s)", color=MUTED, fontsize=9)
        self.ax.tick_params(colors=MUTED, labelcolor=MUTED, labelsize=8)
        self.ax2.tick_params(colors=ACCENT2, labelcolor=ACCENT2, labelsize=8)

        # combined legend
        lines1, labels1 = self.ax.get_legend_handles_labels()
        lines2, labels2 = self.ax2.get_legend_handles_labels()
        if lines1 or lines2:
            self.ax.legend(lines1 + lines2, labels1 + labels2,
                           loc="upper left", fontsize=8,
                           facecolor=CARD, edgecolor=BORDER, labelcolor=TEXT)

        self._style_axes(self.ax)
        for sp in self.ax2.spines.values():
            sp.set_color(BORDER)
        self.canvas.draw_idle()

    # ── Console ────────────────────────────────────────────────────────────────
    def _build_console(self, parent):
        top = tk.Frame(parent, bg=PANEL)
        top.pack(fill="x", padx=8, pady=6)

        tk.Label(top, text="SCPI Command:", bg=PANEL, fg=MUTED,
                 font=("Consolas", 9)).pack(side="left")
        self.cmd_entry = tk.Entry(top, bg=BG, fg=ACCENT, insertbackground=ACCENT,
                                  relief="flat", font=("Consolas", 10), bd=2,
                                  highlightthickness=1, highlightbackground=BORDER,
                                  width=40)
        self.cmd_entry.pack(side="left", padx=6)
        self.cmd_entry.bind("<Return>", lambda e: self._send_console_cmd())
        self._btn(top, "SEND", self._send_console_cmd, fg=ACCENT).pack(side="left")
        self._btn(top, "READ", self._read_instrument, fg=SUCCESS).pack(side="left", padx=(4, 0))
        self._btn(top, "CLEAR", self._clear_console, fg=MUTED).pack(side="left", padx=(4, 0))

        self.console = tk.Text(parent, bg=BG, fg=TEXT,
                               font=("Consolas", 10),
                               relief="flat", bd=0, padx=8, pady=8,
                               insertbackground=ACCENT, wrap="word",
                               state="disabled")
        self.console.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        # color tags
        self.console.tag_config("cmd",     foreground=ACCENT)
        self.console.tag_config("resp",    foreground=TEXT)
        self.console.tag_config("err",     foreground=DANGER)
        self.console.tag_config("info",    foreground=MUTED)
        self.console.tag_config("success", foreground=SUCCESS)

        self._log("ADCE 7352A Controller ready.", "info")
        if not PYVISA_AVAILABLE:
            self._log("PyVISA not found — simulation mode available.", "err")
        if not MATPLOTLIB_AVAILABLE:
            self._log("matplotlib not found — plotting disabled.", "err")

    def _log(self, text, tag="resp"):
        self.console.configure(state="normal")
        ts = time.strftime("%H:%M:%S")
        self.console.insert("end", f"[{ts}] {text}\n", tag)
        self.console.see("end")
        self.console.configure(state="disabled")

    def _clear_console(self):
        self.console.configure(state="normal")
        self.console.delete("1.0", "end")
        self.console.configure(state="disabled")

    # ── Instrument communication ───────────────────────────────────────────────
    def _connect(self):
        if self.connected:
            self._disconnect()
            return

        if self.sim_var.get():
            self.instrument = SimulatedInstrument()
            self.connected = True
            self._set_status(True)
            self._log("Connected (simulation mode)", "success")
            self.connect_btn.config(text="DISCONNECT", fg=DANGER)
            self._query_idn()
            return

        if not PYVISA_AVAILABLE:
            messagebox.showerror("PyVISA Missing",
                                 "pyvisa is not installed.\n\npip install pyvisa pyvisa-py")
            return
        try:
            rm = pyvisa.ResourceManager()
            self.instrument = rm.open_resource(self.resource_var.get())
            self.instrument.timeout = 5000
            self.instrument.read_termination = '\r\n'
            self.instrument.write_termination = '\r\n'
            self.connected = True
            self._set_status(True)
            self._log(f"Connected: {self.resource_var.get()}", "success")
            self.connect_btn.config(text="DISCONNECT", fg=DANGER)
            self._query_idn()
        except Exception as exc:
            self._log(f"Connection error: {exc}", "err")
            messagebox.showerror("Connection Error", str(exc))

    def _disconnect(self):
        self._stop_reading()
        if self.instrument:
            try:
                self.instrument.close()
            except Exception:
                pass
        self.instrument = None
        self.connected = False
        self._set_status(False)
        self.connect_btn.config(text="CONNECT", fg=SUCCESS)
        self._log("Disconnected.", "info")

    def _set_status(self, ok: bool):
        color = SUCCESS if ok else DANGER
        label = "CONNECTED" if ok else "DISCONNECTED"
        self.status_dot.config(fg=color)
        self.status_label.config(fg=color, text=label)

    def _safe_write(self, cmd):
        if not self.connected or self.instrument is None:
            self._log("Not connected.", "err")
            return False
        try:
            self.instrument.write(cmd)
            self._log(f">> {cmd}", "cmd")
            return True
        except Exception as exc:
            self._log(f"Write error: {exc}", "err")
            return False

    def _safe_query(self, cmd):
        if not self.connected or self.instrument is None:
            self._log("Not connected.", "err")
            return None
        try:
            resp = self.instrument.query(cmd).strip()
            self._log(f">> {cmd}", "cmd")
            self._log(f"<< {resp}", "resp")
            return resp
        except Exception as exc:
            self._log(f"Query error: {exc}", "err")
            return None

    # ── Actions ────────────────────────────────────────────────────────────────
    def _query_idn(self):
        resp = self._safe_query("*IDN?")
        if resp:
            self.idn_label.config(text=resp)

    def _apply_settings(self):
        try:
            v  = float(self.volt_entry.get())
            i  = float(self.curr_entry.get())
            ov = float(self.ovp_entry.get())
            rng = self.range_var.get()
        except ValueError:
            messagebox.showerror("Input Error", "Invalid numeric value.")
            return
        self._safe_write(f"VOLT {v:.4f}")
        self._safe_write(f"CURR {i:.4f}")
        self._safe_write(f"VOLT:PROT {ov:.4f}")
        self._safe_write(f"SOUR:RANG {rng}")

    def _output_on(self):
        self._safe_write("OUTP ON")

    def _output_off(self):
        self._safe_write("OUTP OFF")

    def _clear_buffers(self):
        self.times.clear()
        self.voltages.clear()
        self.currents.clear()
        self.powers.clear()
        if MATPLOTLIB_AVAILABLE and hasattr(self, "ax"):
            self.ax.cla()
            self.ax2.cla()
            self._style_axes(self.ax)
            self._style_axes(self.ax2)
            self.canvas.draw_idle()
        self._log("Buffers cleared.", "info")

    # ── Acquisition loop ───────────────────────────────────────────────────────
    def _start_reading(self):
        if self.reading:
            return
        if not self.connected:
            self._log("Connect to instrument first.", "err")
            return
        try:
            self.read_interval_ms = max(100, int(self.interval_entry.get()))
        except ValueError:
            self.read_interval_ms = 500

        self.t_start = time.time()
        self.reading = True
        self.read_thread = threading.Thread(target=self._read_loop, daemon=True)
        self.read_thread.start()
        self._log(f"Acquisition started  (interval={self.read_interval_ms} ms)", "success")

    def _stop_reading(self):
        self.reading = False
        self._log("Acquisition stopped.", "info")

    def _read_loop(self):
        plot_counter = 0
        while self.reading:
            t0 = time.time()
            try:
                resp = self.instrument.query("").strip()
                parts = resp.split(",")
                if not parts:
                    continue
                v = float(parts[0].split("_")[-1].strip())
                i = 0.0
                p = 0.0

                elapsed = time.time() - self.t_start
                self.times.append(elapsed)
                self.voltages.append(v)
                self.currents.append(i)
                self.powers.append(p)

                # update readback labels
                self.root.after(0, self._update_displays, v, i, p)

                plot_counter += 1
                if plot_counter >= 2:   # redraw every 2nd sample
                    plot_counter = 0
                    self.root.after(0, self._redraw_plot)

            except Exception as exc:
                self.root.after(0, self._log, f"Read error: {exc}", "err")

            elapsed_ms = (time.time() - t0) * 1000
            sleep_ms = max(10, self.read_interval_ms - elapsed_ms)
            time.sleep(sleep_ms / 1000)

    def _update_displays(self, v, i, p):
        self.v_display.config(text=f"{v:+.4f} V")
        self.i_display.config(text=f"{i:+.4f} A")
        self.p_display.config(text=f"{p:+.4f} W")

    # ── SCPI console ───────────────────────────────────────────────────────────
    def _send_console_cmd(self):
        cmd = self.cmd_entry.get().strip()
        if not cmd:
            return
        if cmd.endswith("?"):
            self._safe_query(cmd)
        else:
            self._safe_write(cmd)
        self.cmd_entry.delete(0, "end")

    def _read_instrument(self):
        if not self.connected or self.instrument is None:
            self._log("Not connected.", "err")
            return
        try:
            resp = self.instrument.query("").strip()
            self._log(f"<< {resp}", "resp")
        except Exception as exc:
            self._log(f"Read error: {exc}", "err")

    # ── Cleanup ────────────────────────────────────────────────────────────────
    def on_close(self):
        self._disconnect()
        self.root.destroy()


# ── Entry point ───────────────────────────────────────────────────────────────
def main():
    root = tk.Tk()
    app  = ADCE7352AGUI(root)
    root.protocol("WM_DELETE_WINDOW", app.on_close)
    root.mainloop()


if __name__ == "__main__":
    main()
