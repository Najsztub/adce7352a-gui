"""
Threaded acquisition worker for ADCMT 7352A

Runs a free-run acquisition loop in a QThread:
- Supports dual-channel (SD0) and single-channel modes
- Emits signals for live data, plot, errors
"""

import time
from PyQt5.QtCore import QThread, pyqtSignal
from ..commands.parser import parse_adc_response, parse_dual_response
from ..commands.adc_commands import OVERLOAD_THRESHOLD


class AcquisitionWorker(QThread):
    data_received = pyqtSignal(object)
    data_plot = pyqtSignal(list, list, list, list)
    error_occurred = pyqtSignal(str)
    status_message = pyqtSignal(str, str)

    def __init__(self, instrument, parent=None):
        super().__init__(parent)
        self._instrument = instrument
        self._running = False
        self._interval_ms = 500
        self._func_key_a = "F1"
        self._func_key_b = "F12"
        self._ch_a_enabled = True
        self._ch_b_enabled = False
        self._t0 = None
        self._ts_a = []
        self._vals_a = []
        self._ts_b = []
        self._vals_b = []
        self._max_pts = 600

    def set_interval(self, ms):
        self._interval_ms = max(50, ms)

    def set_function(self, func_key):
        self._func_key_a = func_key

    def set_ch_a_enabled(self, enabled: bool):
        self._ch_a_enabled = enabled

    def set_ch_b_enabled(self, enabled: bool):
        self._ch_b_enabled = enabled

    def set_func_key_a(self, key):
        self._func_key_a = key

    def set_func_key_b(self, key):
        self._func_key_b = key

    def set_buffer_size(self, n):
        self._max_pts = n

    def stop(self):
        self._running = False

    @property
    def is_running(self):
        return self._running

    def run(self):
        if not self._instrument or not self._instrument.connected:
            self.error_occurred.emit("No instrument connected")
            return

        self._running = True
        self._t0 = time.time()
        self._ts_a.clear()
        self._vals_a.clear()
        self._ts_b.clear()
        self._vals_b.clear()

        both = self._ch_a_enabled and self._ch_b_enabled
        if both:
            self._instrument.enable_dual_display(True)
            self._instrument.set_output_mode("BOTH")
        elif self._ch_a_enabled:
            self._instrument.enable_dual_display(False)
            self._instrument.set_output_mode("FIRST")
        elif self._ch_b_enabled:
            self._instrument.enable_dual_display(False)
            self._instrument.set_output_mode("SECOND")

        self.status_message.emit("Acquisition started", "ok")

        while self._running:
            t_start = time.time()
            try:
                elapsed = time.time() - self._t0
                if both:
                    raw_a, raw_b = self._instrument.read_dual()
                    data_a = parse_adc_response(raw_a, self._func_key_a) if raw_a else None
                    data_b = parse_adc_response(raw_b, self._func_key_b) if raw_b else None
                elif self._ch_a_enabled:
                    raw = self._instrument.read()
                    data_a = parse_adc_response(raw, self._func_key_a) if raw else None
                    data_b = None
                elif self._ch_b_enabled:
                    raw = self._instrument.read()
                    data_b = parse_adc_response(raw, self._func_key_b) if raw else None
                    data_a = None
                else:
                    time.sleep(self._interval_ms / 1000.0)
                    continue

                result = {}
                if data_a:
                    va, mh_a, sh_a, ol_a, disp_a, desc_a = data_a
                    plot_va = OVERLOAD_THRESHOLD * 1.1 if ol_a else va
                    self._ts_a.append(elapsed)
                    self._vals_a.append(plot_va)
                    if len(self._ts_a) > self._max_pts:
                        self._ts_a.pop(0)
                        self._vals_a.pop(0)
                    result['A'] = data_a

                if data_b:
                    vb, mh_b, sh_b, ol_b, disp_b, desc_b = data_b
                    plot_vb = OVERLOAD_THRESHOLD * 1.1 if ol_b else vb
                    self._ts_b.append(elapsed)
                    self._vals_b.append(plot_vb)
                    if len(self._ts_b) > self._max_pts:
                        self._ts_b.pop(0)
                        self._vals_b.pop(0)
                    result['B'] = data_b

                self.data_received.emit(result)

                self.data_plot.emit(
                    list(self._ts_a), list(self._vals_a),
                    list(self._ts_b), list(self._vals_b))

            except Exception as e:
                self.error_occurred.emit(f"Read error: {e}")
                time.sleep(0.5)

            elapsed_ms = (time.time() - t_start) * 1000
            sleep_ms = max(0.0, self._interval_ms - elapsed_ms) / 1000.0
            time.sleep(sleep_ms)

        self.status_message.emit("Acquisition stopped", "info")
