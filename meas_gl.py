import sys
import re
import pyvisa
import numpy as np

from PyQt5.QtCore import QTimer, Qt
# Add QOpenGLWidget to your existing QtWidgets import
from PyQt5.QtWidgets import (QApplication, QMainWindow, QVBoxLayout, QHBoxLayout, 
                             QWidget, QPushButton, QComboBox, QLabel, QGroupBox, 
                             QLCDNumber, QLineEdit, QStatusBar, QFormLayout, QCheckBox, QMessageBox,
                             QOpenGLWidget, QTabWidget, QSpinBox, QDoubleSpinBox, QListWidget, 
                             QListWidgetItem, QTextEdit) 
from OpenGL.GL import *
from OpenGL.GL import GL_TEXTURE_2D

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

# User-readable function labels
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
ADC_RATES = {"FAST": "PR1", "MED": "PR2", "SLOW1": "PR3", "SLOW2": "PR4"}
ADC_TRIGS = {"IMM": "TRS0", "MAN": "TRS1", "EXT": "TRS2", "BUS": "TRS3"}

# =============================================================================
# MOCK DEVICE CLASS FOR TESTING
# =============================================================================
class MockDMMDevice:
    """Simulates ADCMT 7352A responses for GUI testing without hardware."""
    def __init__(self):
        self.current_func_a = "F1"
        self.current_func_b = "F12"
        self.value_a = 0.5
        self.value_b = 0.3
        self.timeout = 2000
    
    def query(self, cmd):
        """Simulate device query responses."""
        import random
        # Add realistic variation to readings
        noise_a = random.gauss(0, 0.02)
        noise_b = random.gauss(0, 0.01)
        self.value_a = np.clip(self.value_a + noise_a, -10, 10)
        self.value_b = np.clip(self.value_b + noise_b, -5, 5)
        
        if "DSP1,MD?" in cmd:
            exp_a = f"{self.value_a:.5e}".replace('e', 'E')
            return f"S{exp_a},"
        elif "DSP2,MD?" in cmd:
            exp_b = f"{self.value_b:.5e}".replace('e', 'E')
            return f"S{exp_b},"
        return "S+0.00000E+00,"
    
    def write(self, cmd):
        """Simulate device command execution."""
        if "DSP1" in cmd and "F" in cmd:
            self.current_func_a = cmd.split(",")[1]
        elif "DSP2" in cmd and "F" in cmd:
            self.current_func_b = cmd.split(",")[1]
    
    def close(self):
        """Simulate device close."""
        pass

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
        
        # Annotation support
        self.annotations = []  # List of (x, y, text, color) tuples
        self.enable_annotations = False
        self.stats_display = {}  # Dict for statistics display

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
    
    def add_annotation(self, x, y, text, color=(1.0, 1.0, 1.0)):
        """Add an annotation to the plot."""
        self.annotations.append((x, y, text, color))
        self.update()
    
    def clear_annotations(self):
        """Clear all annotations."""
        self.annotations.clear()
        self.update()
    
    def set_statistics(self, stats_dict):
        """Update statistics for display."""
        self.stats_display = stats_dict
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
        
        # Draw Annotations
        if self.enable_annotations:
            glLineWidth(1.0)
            for x, y, text, color in self.annotations:
                # Draw vertical line at annotation point
                glColor3f(*color)
                glBegin(GL_LINES)
                glVertex2f(x, self.min_val)
                glVertex2f(x, self.max_val)
                glEnd()
                # Draw marker point
                glPointSize(8.0)
                glBegin(GL_POINTS)
                glVertex2f(x, y)
                glEnd()

# =============================================================================
# MAIN APPLICATION WINDOW
# =============================================================================
class ADCMT7352GUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("ADCMT 7352A/E Controller (ADC Lang)")
        self.resize(1000, 700)
        self.inst = None
        self.poll_timer = QTimer()
        self.poll_timer.timeout.connect(self.poll_readings)
        self.is_continuous = False
        self.use_mock = False

        self.init_ui()
        self.statusBar().showMessage("Ready. Select device and click Connect.")

    def init_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        main_layout = QVBoxLayout(central)

        # --- Device & Connection Bar ---
        conn_layout = QHBoxLayout()
        conn_layout.addWidget(QLabel("Device:"))
        self.cb_device = QComboBox()
        self.cb_device.addItems(["Real Device (VISA)", "Mock Device (Testing)"])
        self.cb_device.currentIndexChanged.connect(self.on_device_changed)
        conn_layout.addWidget(self.cb_device)
        
        self.res_input = QLineEdit("USB0::0x0B21::0x0001::12345678::INSTR")
        self.res_input.setPlaceholderText("VISA Resource String (e.g., USB0::..., GPIB0::1::INSTR)")
        conn_layout.addWidget(QLabel("Resource:"))
        conn_layout.addWidget(self.res_input, 1)
        
        self.btn_connect = QPushButton("Connect")
        self.btn_connect.clicked.connect(self.toggle_connection)
        conn_layout.addWidget(self.btn_connect)
        main_layout.addLayout(conn_layout)

        # --- Tabbed Interface ---
        self.tabs = QTabWidget()
        
        # Tab 1: Channel A Configuration
        self.tab_a = self.create_channel_tab("Channel A (DSP1)", "A")
        self.tabs.addTab(self.tab_a, "Channel A")
        
        # Tab 2: Channel B Configuration
        self.tab_b = self.create_channel_tab("Channel B (DSP2)", "B")
        self.tabs.addTab(self.tab_b, "Channel B")
        
        # Tab 3: Measurements & Statistics
        self.tab_meas = self.create_measurements_tab()
        self.tabs.addTab(self.tab_meas, "Measurements")
        
        main_layout.addWidget(self.tabs)

        # --- LCD Displays ---
        disp_layout = QHBoxLayout()
        self.lcd_a = QLCDNumber()
        self.lcd_a.setSegmentStyle(QLCDNumber.Flat)
        self.lcd_a.setMinimumHeight(60)
        self.lcd_b = QLCDNumber()
        self.lcd_b.setSegmentStyle(QLCDNumber.Flat)
        self.lcd_b.setMinimumHeight(60)
        disp_layout.addWidget(QLabel("Channel A Value:"))
        disp_layout.addWidget(self.lcd_a, 1)
        disp_layout.addWidget(QLabel("Channel B Value:"))
        disp_layout.addWidget(self.lcd_b, 1)
        main_layout.addLayout(disp_layout)

        # --- OpenGL Plot ---
        self.gl_plot = DMMGLPlot()
        main_layout.addWidget(self.gl_plot, 1)

        # --- Control Buttons ---
        btn_layout = QHBoxLayout()
        self.btn_apply = QPushButton("Apply Settings")
        self.btn_apply.clicked.connect(self.apply_settings)
        self.btn_init = QPushButton("Initiate (INI)")
        self.btn_init.clicked.connect(lambda: self.send_cmd("INI"))
        self.btn_abort = QPushButton("Abort (ABO)")
        self.btn_abort.clicked.connect(lambda: self.send_cmd("ABO"))
        self.chk_cont = QCheckBox("Continuous Read")
        self.chk_cont.stateChanged.connect(self.toggle_continuous)
        
        btn_layout.addWidget(self.btn_apply)
        btn_layout.addWidget(self.btn_init)
        btn_layout.addWidget(self.btn_abort)
        btn_layout.addWidget(self.chk_cont)
        btn_layout.addStretch()
        main_layout.addLayout(btn_layout)

    def create_channel_tab(self, title, channel):
        """Create a configuration tab for a channel."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        grp = QGroupBox(title)
        form = QFormLayout()
        
        # Enable/Disable checkbox
        cb_enable = QCheckBox("Enable Channel")
        cb_enable.setChecked(channel == "A")
        setattr(self, f"chk_enable_{channel}", cb_enable)
        form.addRow("Enabled:", cb_enable)
        
        # Function selection
        cb_func = QComboBox()
        cb_func.addItems(ADC_FUNCS.keys())
        # Set meaningful display text
        cb_func.setMaxVisibleItems(10)
        setattr(self, f"cb_func_{channel}", cb_func)
        form.addRow("Function:", cb_func)
        
        # Add user-readable label display
        label_display = QLabel()
        label_display.setStyleSheet("color: #888;")
        setattr(self, f"lbl_func_{channel}", label_display)
        form.addRow("Description:", label_display)
        cb_func.currentTextChanged.connect(
            lambda text: self.update_function_label(channel, text))
        self.update_function_label(channel, cb_func.currentText())
        
        # Range selection
        cb_range = QComboBox()
        cb_range.addItems(ADC_RANGES.keys())
        setattr(self, f"cb_rng_{channel}", cb_range)
        form.addRow("Range:", cb_range)
        
        # Rate selection
        cb_rate = QComboBox()
        cb_rate.addItems(ADC_RATES.keys())
        setattr(self, f"cb_rate_{channel}", cb_rate)
        form.addRow("Rate:", cb_rate)
        
        # Trigger selection
        cb_trig = QComboBox()
        cb_trig.addItems(ADC_TRIGS.keys())
        setattr(self, f"cb_trig_{channel}", cb_trig)
        form.addRow("Trigger:", cb_trig)
        
        grp.setLayout(form)
        layout.addWidget(grp)
        layout.addStretch()
        
        return widget
    
    def update_function_label(self, channel, func_code):
        """Update the user-readable function label."""
        label_widget = getattr(self, f"lbl_func_{channel}", None)
        if label_widget and func_code in FUNC_LABELS:
            label_widget.setText(FUNC_LABELS[func_code])
    
    def create_measurements_tab(self):
        """Create the measurements and statistics tab."""
        widget = QWidget()
        layout = QVBoxLayout(widget)
        
        # Statistics display
        stats_grp = QGroupBox("Data Statistics")
        stats_layout = QFormLayout()
        
        self.lbl_stat_min = QLabel("N/A")
        self.lbl_stat_max = QLabel("N/A")
        self.lbl_stat_avg = QLabel("N/A")
        self.lbl_stat_med = QLabel("N/A")
        self.lbl_stat_std = QLabel("N/A")
        self.lbl_stat_p10 = QLabel("N/A")
        self.lbl_stat_p90 = QLabel("N/A")
        
        stats_layout.addRow("Minimum:", self.lbl_stat_min)
        stats_layout.addRow("Maximum:", self.lbl_stat_max)
        stats_layout.addRow("Average:", self.lbl_stat_avg)
        stats_layout.addRow("Median:", self.lbl_stat_med)
        stats_layout.addRow("Std Dev:", self.lbl_stat_std)
        stats_layout.addRow("10th %ile:", self.lbl_stat_p10)
        stats_layout.addRow("90th %ile:", self.lbl_stat_p90)
        
        stats_grp.setLayout(stats_layout)
        layout.addWidget(stats_grp)
        
        # Annotation options
        annot_grp = QGroupBox("Graph Annotations")
        annot_layout = QFormLayout()
        
        self.chk_annot_enable = QCheckBox("Enable Annotations")
        self.chk_annot_enable.stateChanged.connect(self.toggle_annotations)
        annot_layout.addRow(self.chk_annot_enable)
        
        annot_grp.setLayout(annot_layout)
        layout.addWidget(annot_grp)
        
        # Statistics checkboxes for annotation
        annot_select_grp = QGroupBox("Annotation Sources")
        annot_select_layout = QFormLayout()
        
        self.chk_annot_min = QCheckBox("Mark Minimum")
        self.chk_annot_max = QCheckBox("Mark Maximum")
        self.chk_annot_avg = QCheckBox("Mark Average")
        
        annot_select_layout.addRow(self.chk_annot_min)
        annot_select_layout.addRow(self.chk_annot_max)
        annot_select_layout.addRow(self.chk_annot_avg)
        
        annot_select_grp.setLayout(annot_select_layout)
        layout.addWidget(annot_select_grp)
        
        layout.addStretch()
        return widget
    
    def on_device_changed(self, index):
        """Handle device selection change."""
        self.use_mock = (index == 1)
        self.res_input.setEnabled(index == 0)
    
    def toggle_annotations(self, state):
        """Enable/disable annotations on the plot."""
        self.gl_plot.enable_annotations = (state == Qt.Checked)
        if not self.gl_plot.enable_annotations:
            self.gl_plot.clear_annotations()
        self.gl_plot.update()
    
    def update_statistics(self):
        """Calculate and display statistics."""
        data_a = self.gl_plot.data_a[self.gl_plot.data_a != 0]
        data_b = self.gl_plot.data_b[self.gl_plot.data_b != 0]
        
        # Use channel A for now
        valid_data = data_a[np.isfinite(data_a)]
        
        if len(valid_data) > 0:
            self.lbl_stat_min.setText(f"{np.min(valid_data):.6f}")
            self.lbl_stat_max.setText(f"{np.max(valid_data):.6f}")
            self.lbl_stat_avg.setText(f"{np.mean(valid_data):.6f}")
            self.lbl_stat_med.setText(f"{np.median(valid_data):.6f}")
            self.lbl_stat_std.setText(f"{np.std(valid_data):.6f}")
            self.lbl_stat_p10.setText(f"{np.percentile(valid_data, 10):.6f}")
            self.lbl_stat_p90.setText(f"{np.percentile(valid_data, 90):.6f}")
            
            # Add annotations if enabled
            if self.gl_plot.enable_annotations:
                self.gl_plot.clear_annotations()
                if self.chk_annot_min.isChecked():
                    min_idx = np.argmin(valid_data)
                    self.gl_plot.add_annotation(min_idx, np.min(valid_data), 
                                               "Min", (1.0, 0.0, 0.0))
                if self.chk_annot_max.isChecked():
                    max_idx = np.argmax(valid_data)
                    self.gl_plot.add_annotation(max_idx, np.max(valid_data), 
                                               "Max", (0.0, 1.0, 0.0))
                if self.chk_annot_avg.isChecked():
                    avg_val = np.mean(valid_data)
                    self.gl_plot.add_annotation(100, avg_val, "Avg", (1.0, 1.0, 0.0))

    # =============================================================================
    # METRIC NOTATION FORMATTING
    # =============================================================================
    @staticmethod
    def get_unit_for_function(func_code):
        """Return the unit for a given measurement function."""
        # Create reverse mapping from ADC_FUNCS
        voltage_funcs = ["DCV-Ach", "DCV-Bch", "ACV-Ach", "ACV+DC-Ach", "DIODE-Ach"]
        current_funcs = ["DCI-Ach", "DCI-Bch", "ACI-Ach", "ACI+DC-Ach", "ACI-Bch", "ACI+DC-Bch"]
        resistance_funcs = ["2WΩ-Ach", "LP-2WΩ-Ach", "CONT-Ach"]
        temp_funcs = ["TEMP"]
        freq_funcs = ["FREQ-Ach"]
        
        if func_code in voltage_funcs:
            return "V"
        elif func_code in current_funcs:
            return "A"
        elif func_code in resistance_funcs:
            return "Ω"
        elif func_code in temp_funcs:
            return "°C"
        elif func_code in freq_funcs:
            return "Hz"
        return ""

    @staticmethod
    def format_with_metric_prefix(value, unit="", precision=3):
        """Format a number with metric prefixes (n, u, m, k, M, G).
        
        Args:
            value: The numeric value to format
            unit: The unit string (e.g., "V", "A", "Ω")
            precision: Number of significant figures after decimal point
        
        Returns:
            A formatted string like "1.23 mV" or "456 nA"
        """
        if value is None or not isinstance(value, (int, float)):
            return "N/A"
        
        # Handle zero and very small values
        if abs(value) == 0:
            return f"0 {unit}".strip()
        
        abs_val = abs(value)
        sign = "-" if value < 0 else ""
        
        # Define metric prefixes from largest to smallest
        prefixes = [
            (1e9, "G"),
            (1e6, "M"),
            (1e3, "k"),
            (1, ""),
            (1e-3, "m"),
            (1e-6, "u"),   # micro (u instead of μ for display compatibility)
            (1e-9, "n"),
            (1e-12, "p"),
        ]
        
        # Find the appropriate prefix
        for scale, prefix in prefixes:
            if abs_val >= scale:
                scaled_value = abs_val / scale
                # Format with appropriate precision
                if scaled_value >= 100:
                    formatted = f"{scaled_value:.0f}"
                elif scaled_value >= 10:
                    formatted = f"{scaled_value:.1f}"
                else:
                    formatted = f"{scaled_value:.{precision-1}f}"
                
                result = f"{sign}{formatted} {prefix}{unit}".strip()
                return result
        
        # Fallback for extremely small values
        formatted = f"{abs_val:.{precision}e}"
        return f"{sign}{formatted} {unit}".strip()

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
            if self.use_mock:
                self.inst = MockDMMDevice()
                self.btn_connect.setText("Disconnect")
                self.statusBar().showMessage("Connected to Mock Device")
            else:
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
        if self.chk_enable_A.isChecked():
            func_a = self.cb_func_A.currentText()
            self.send_cmd(f"DSP1,{ADC_FUNCS[func_a]}")
            self.send_cmd(f"DSP1,{ADC_RANGES[self.cb_rng_A.currentText()]}")
            self.send_cmd(f"DSP1,{ADC_RATES[self.cb_rate_A.currentText()]}")
            self.send_cmd(f"DSP1,{ADC_TRIGS[self.cb_trig_A.currentText()]}")
        
        if self.chk_enable_B.isChecked():
            func_b = self.cb_func_B.currentText()
            self.send_cmd(f"DSP2,{ADC_FUNCS[func_b]}")
            self.send_cmd(f"DSP2,{ADC_RANGES[self.cb_rng_B.currentText()]}")
            self.send_cmd(f"DSP2,{ADC_RATES[self.cb_rate_B.currentText()]}")
            self.send_cmd(f"DSP2,{ADC_TRIGS[self.cb_trig_B.currentText()]}")
        
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
            
            # Format values with metric notation
            if val_a is not None:
                func_a = self.cb_func_A.currentText()
                unit_a = self.get_unit_for_function(func_a)
                display_a = self.format_with_metric_prefix(float(val_a), unit_a)
            else:
                display_a = "OL"
            
            if val_b is not None:
                func_b = self.cb_func_B.currentText()
                unit_b = self.get_unit_for_function(func_b)
                display_b = self.format_with_metric_prefix(float(val_b), unit_b)
            else:
                display_b = "OL"
            
            self.lcd_a.display(display_a)
            self.lcd_b.display(display_b)
            
            if val_a is not None and val_b is not None:
                self.gl_plot.update_readings(float(val_a), float(val_b))
                self.update_statistics()
                
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