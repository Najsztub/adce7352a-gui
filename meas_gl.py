import sys
import re
import pyvisa
import numpy as np

from PyQt5.QtCore import QTimer, Qt
# Add QOpenGLWidget to your existing QtWidgets import
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QComboBox, QLabel, QGroupBox, 
                             QLCDNumber, QLineEdit, QStatusBar, QFormLayout, QCheckBox, QMessageBox,
                             QOpenGLWidget) 
from OpenGL.GL import *

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
ADC_RANGES = {"AUTO": "R0", "R1": "R1", "R2": "R2", "R3": "R3", 
              "R4": "R4", "R5": "R5", "R6": "R6", "R7": "R7", "R8": "R8", "R9": "R9"}
ADC_RATES = {"FAST": "PR1", "MED": "PR2", "SLOW1": "PR3", "SLOW2": "PR4"}
ADC_TRIGS = {"IMM": "TRS0", "MAN": "TRS1", "EXT": "TRS2", "BUS": "TRS3"}

# =============================================================================
# OPENGL LIVE PLOT WIDGET
# =============================================================================
class DMMGLPlot(QOpenGLWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.data_a = np.zeros(200)
        self.data_b = np.zeros(200)
        self.min_val, self.max_val = -1.0, 1.0
        self.setMinimumHeight(150)

    def update_readings(self, val_a, val_b):
        # Shift buffer and insert new value
        self.data_a = np.roll(self.data_a, -1)
        self.data_b = np.roll(self.data_b, -1)
        self.data_a[-1] = val_a
        self.data_b[-1] = val_b
        
        # Update auto-scale bounds
        all_vals = np.concatenate([self.data_a, self.data_b])
        valid = all_vals[np.isfinite(all_vals)]
        if len(valid) > 0:
            self.min_val = np.min(valid) * 1.1
            self.max_val = np.max(valid) * 1.1
            if self.max_val == self.min_val:
                self.max_val += 1.0
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

        # Plot Channel A (Green)
        glColor3f(0.0, 1.0, 0.5)
        glLineWidth(2.0)
        glBegin(GL_LINE_STRIP)
        for i, val in enumerate(self.data_a):
            if np.isfinite(val): glVertex2f(i, val)
        glEnd()

        # Plot Channel B (Cyan)
        glColor3f(0.0, 0.85, 1.0)
        glBegin(GL_LINE_STRIP)
        for i, val in enumerate(self.data_b):
            if np.isfinite(val): glVertex2f(i, val)
        glEnd()

# =============================================================================
# MAIN APPLICATION WINDOW
# =============================================================================
class ADCMT7352GUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADCMT 7352A/E Controller (ADC Lang)")
        self.resize(850, 600)
        self.inst = None
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_readings)
        self.is_continuous = False

        self.init_ui()
        self.statusBar().showMessage("Ready. Enter VISA resource and click Connect.")

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # --- Connection Bar ---
        conn_layout = QHBoxLayout()
        self.res_input = QLineEdit("USB0::0x0B21::0x0001::12345678::INSTR")
        self.res_input.setPlaceholderText("VISA Resource String (e.g., USB0::..., GPIB0::1::INSTR)")
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(QLabel("Resource:"))
        conn_layout.addWidget(self.res_input, 1)
        conn_layout.addWidget(self.btn_connect)
        main_layout.addLayout(conn_layout)

        # --- Controls Grid ---
        controls_layout = QHBoxLayout()
        
        # Channel A Group
        grp_a = QGroupBox("Channel A (DSP1)")
        f_a = QFormLayout()
        self.cb_func_a = QComboBox(); self.cb_func_a.addItems(ADC_FUNCS.keys())
        self.cb_rng_a = QComboBox(); self.cb_rng_a.addItems(ADC_RANGES.keys())
        self.cb_rate_a = QComboBox(); self.cb_rate_a.addItems(ADC_RATES.keys())
        self.cb_trig_a = QComboBox(); self.cb_trig_a.addItems(ADC_TRIGS.keys())
        f_a.addRow("Function", self.cb_func_a)
        f_a.addRow("Range", self.cb_rng_a)
        f_a.addRow("Rate", self.cb_rate_a)
        f_a.addRow("Trigger", self.cb_trig_a)
        grp_a.setLayout(f_a)

        # Channel B Group
        grp_b = QGroupBox("Channel B (DSP2)")
        f_b = QFormLayout()
        self.cb_func_b = QComboBox(); self.cb_func_b.addItems(ADC_FUNCS.keys())
        self.cb_rng_b = QComboBox(); self.cb_rng_b.addItems(ADC_RANGES.keys())
        self.cb_rate_b = QComboBox(); self.cb_rate_b.addItems(ADC_RATES.keys())
        self.cb_trig_b = QComboBox(); self.cb_trig_b.addItems(ADC_TRIGS.keys())
        f_b.addRow("Function", self.cb_func_b)
        f_b.addRow("Range", self.cb_rng_b)
        f_b.addRow("Rate", self.cb_rate_b)
        f_b.addRow("Trigger", self.cb_trig_b)
        grp_b.setLayout(f_b)

        # Global Actions
        grp_glob = QGroupBox("System / Actions")
        f_g = QFormLayout()
        self.btn_apply = QPushButton("Apply Settings")
        self.btn_init = QPushButton("Initiate (INI)")
        self.btn_abort = QPushButton("Abort (ABO)")
        self.chk_cont = QCheckBox("Continuous Read")
        self.chk_cont.stateChanged.connect(self.toggle_continuous)
        f_g.addRow(self.btn_apply)
        f_g.addRow(self.btn_init)
        f_g.addRow(self.btn_abort)
        f_g.addRow(self.chk_cont)
        grp_glob.setLayout(f_g)

        controls_layout.addWidget(grp_a)
        controls_layout.addWidget(grp_b)
        controls_layout.addWidget(grp_glob)
        main_layout.addLayout(controls_layout)

        # --- Displays ---
        disp_layout = QHBoxLayout()
        self.lcd_a = QLCDNumber(); self.lcd_a.setSegmentStyle(QLCDNumber.Flat); self.lcd_a.setMinimumHeight(60)
        self.lcd_b = QLCDNumber(); self.lcd_b.setSegmentStyle(QLCDNumber.Flat); self.lcd_b.setMinimumHeight(60)
        disp_layout.addWidget(QLabel("DSP1 Value:")); disp_layout.addWidget(self.lcd_a, 1)
        disp_layout.addWidget(QLabel("DSP2 Value:")); disp_layout.addWidget(self.lcd_b, 1)
        main_layout.addLayout(disp_layout)

        # --- OpenGL Plot ---
        self.gl_plot = DMMGLPlot()
        main_layout.addWidget(self.gl_plot, 1)

        # --- Signal Connections ---
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_init.clicked.connect(lambda: self.send_cmd("INI"))
        self.btn_abort.clicked.connect(lambda: self.send_cmd("ABO"))

    # =============================================================================
    # VISA & COMMAND LOGIC
    # =============================================================================
    def toggle_connection(self):
        if self.inst:
            self.poll_timer.stop()
            self.inst.close()
            self.inst = None
            self.btn_connect.setText("Connect")
            self.statusBar().showMessage("Disconnected.")
            return

        try:
            rm = pyvisa.ResourceManager()
            self.inst = rm.open_resource(self.res_input.text())
            self.inst.timeout = 2000
            self.inst.read_termination = '\r\n'
            self.inst.write_termination = '\r\n'
            
            # Initialize ADC Mode & Display
            self.send_cmd("H0")      # Disable headers for easier parsing
            self.send_cmd("DE1")     # Enable dual display
            self.send_cmd("DSP1,F1") # Default DCV-Ach
            self.send_cmd("DSP2,F12")# Default DCV-Bch
            
            self.btn_connect.setText("Disconnect")
            self.statusBar().showMessage(f"Connected to {self.res_input.text()}")
            self.apply_settings()
        except Exception as e:
            QMessageBox.critical(self, "Connection Error", str(e))
            self.inst = None

    def send_cmd(self, cmd):
        if not self.inst: return
        try:
            self.inst.write(cmd)
        except Exception as e:
            self.statusBar().showMessage(f"Cmd Error: {e}")

    def apply_settings(self):
        if not self.inst: return
        # Map GUI selections to ADC commands
        self.send_cmd(f"DSP1,{ADC_FUNCS[self.cb_func_a.currentText()]}")
        self.send_cmd(f"DSP2,{ADC_FUNCS[self.cb_func_b.currentText()]}")
        self.send_cmd(f"DSP1,{ADC_RANGES[self.cb_rng_a.currentText()]}")
        self.send_cmd(f"DSP2,{ADC_RANGES[self.cb_rng_b.currentText()]}")
        self.send_cmd(f"DSP1,{ADC_RATES[self.cb_rate_a.currentText()]}")
        self.send_cmd(f"DSP2,{ADC_RATES[self.cb_rate_b.currentText()]}")
        self.send_cmd(f"DSP1,{ADC_TRIGS[self.cb_trig_a.currentText()]}")
        self.send_cmd(f"DSP2,{ADC_TRIGS[self.cb_trig_b.currentText()]}")
        self.statusBar().showMessage("Settings applied.")

    def toggle_continuous(self, state):
        self.is_continuous = (state == Qt.Checked)
        if self.is_continuous and self.inst:
            self.poll_timer.start(500) # 500ms polling
        else:
            self.poll_timer.stop()

    def poll_readings(self):
        if not self.inst: return
        try:
            # Query both displays. ADC format: S±DD...DDE±DD,
            resp_a = self.inst.query("DSP1,MD?").strip()
            resp_b = self.inst.query("DSP2,MD?").strip()
            
            val_a = self.parse_adc_response(resp_a)
            val_b = self.parse_adc_response(resp_b)
            
            self.lcd_a.display(val_a if val_a is not None else "OL")
            self.lcd_b.display(val_b if val_b is not None else "OL")
            
            if val_a is not None and val_b is not None:
                self.gl_plot.update_readings(float(val_a), float(val_b))
                
        except Exception as e:
            self.statusBar().showMessage(f"Read Error: {e}")
            self.poll_timer.stop()
            self.chk_cont.setChecked(False)

    @staticmethod
    def parse_adc_response(resp):
        # Extract scientific notation floats: e.g., S+1.23456E+00,
        matches = re.findall(r'[-+]?\d*\.\d+[eE][-+]?\d+', resp)
        return matches[0] if matches else None

# =============================================================================
# ENTRY POINT
# =============================================================================
if __name__ == "__main__":
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    window = ADCMT7352GUI()
    window.show()
    sys.exit(app.exec_())