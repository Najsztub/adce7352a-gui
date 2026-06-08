"""
ADCMT 7352A Instrument Driver - ADC Command Mode

Unified interface over VISA or Mock backends.
Handles instrument initialization, commands, and acquisition setup.
Supports dual-channel (DSP1/DSP2) with SD0 output mode.
"""

import time
import logging
from .visa_backend import VISABackend, InstrumentBackend
from .mock_backend import MockBackend

log = logging.getLogger(__name__)


class ADCMT7352A:
    def __init__(self, use_mock=False, resource_string=None):
        self._use_mock = use_mock
        self._resource_string = resource_string or VISABackend.RESOURCE_DEFAULT
        self._backend: InstrumentBackend = None

    @property
    def backend(self):
        return self._backend

    @property
    def connected(self) -> bool:
        return self._backend is not None and self._backend.connected

    def connect(self) -> bool:
        if self.connected:
            return True
        if self._use_mock:
            self._backend = MockBackend()
        else:
            self._backend = VISABackend(self._resource_string)
        if self._backend.connect():
            if not self._use_mock:
                self._init_sequence()
            return True
        self._backend = None
        return False

    def disconnect(self):
        if self._backend:
            self._backend.disconnect()
        self._backend = None

    def _init_sequence(self):
        time.sleep(0.25)
        self.query("ERR?")
        time.sleep(0.05)

        init_cmds = ["*RST", "H1", "DE0", "SD1", "TRS0", "INIC1"]
        for cmd in init_cmds:
            self.write(cmd)
            time.sleep(0.1)
            err = self.query("ERR?")
            if err and not err.startswith("+0"):
                log.warning("init '%s' → %s", cmd, err)

    def _check_err(self, label=""):
        err = self.query("ERR?")
        if err and not err.startswith("+0"):
            log.warning("ERR after %s: %s", label, err)
        return err

    def write(self, cmd: str):
        if self._backend:
            self._backend.write(cmd)

    def write_with_err_check(self, cmd: str) -> bool:
        if self._backend:
            return self._backend.write_with_err_check(cmd)
        return False

    def query(self, cmd: str) -> str | None:
        if self._backend:
            return self._backend.query(cmd)
        return None

    def read(self) -> str | None:
        if self._backend:
            return self._backend.read()
        return None

    def get_idn(self) -> str | None:
        return self.query("*IDN?")

    def write_dsp(self, dsp: str, cmd: str):
        if self._backend:
            self._backend.write(f"{dsp},{cmd}")
            time.sleep(0.02)

    def apply_function(self, func_key: str):
        self.write(func_key)
        time.sleep(0.02)

    def apply_range(self, range_cmd: str):
        if range_cmd:
            self.write(range_cmd)
            time.sleep(0.02)

    def apply_rate(self, rate_idx: int):
        from ..commands.adc_commands import SRATE_CMD
        if 0 <= rate_idx < len(SRATE_CMD):
            self.write(SRATE_CMD[rate_idx])
            time.sleep(0.02)

    def apply_digits(self, digits_idx: int):
        from ..commands.adc_commands import DIGITS_CMD
        if 0 <= digits_idx < len(DIGITS_CMD):
            self.write(DIGITS_CMD[digits_idx])
            time.sleep(0.02)

    def apply_auto_zero(self, enabled: bool):
        self.write("AZ1" if enabled else "AZ0")
        time.sleep(0.02)

    def apply_settings(self, func_key, range_cmd, rate_idx, digits_idx, az_enabled):
        self.apply_function(func_key)
        self.apply_range(range_cmd)
        self.apply_rate(rate_idx)
        self.apply_digits(digits_idx)
        self.apply_auto_zero(az_enabled)

    def apply_settings_ch_a(self, func_key, range_cmd, rate_cmd, digits_cmd, az_enabled):
        self.write_dsp("DSP1", func_key)
        if range_cmd:
            self.write_dsp("DSP1", range_cmd)
        self.write_dsp("DSP1", rate_cmd)
        self.write_dsp("DSP1", digits_cmd)
        self.write_dsp("DSP1", "AZ1" if az_enabled else "AZ0")
        self._check_err("apply_ch_a")

    def apply_settings_ch_b(self, func_key, range_cmd, rate_cmd, digits_cmd, az_enabled):
        self.write_dsp("DSP2", func_key)
        if range_cmd:
            self.write_dsp("DSP2", range_cmd)
        self.write_dsp("DSP2", rate_cmd)
        self.write_dsp("DSP2", digits_cmd)
        self.write_dsp("DSP2", "AZ1" if az_enabled else "AZ0")
        self._check_err("apply_ch_b")

    def apply_calc(self, nl=False, sm=False, sm_pts=10, sc=False,
                   db=False, mn=False, co=False, hi=10.0, lo=-10.0):
        self.write("NL1" if nl else "NL0"); time.sleep(0.015)
        self.write("SM1" if sm else "SM0"); time.sleep(0.015)
        if sm:
            pts = max(2, min(100, sm_pts))
            self.write(f"TI{pts}"); time.sleep(0.015)
        self.write("SC1" if sc else "SC0"); time.sleep(0.015)
        self.write("DB1" if db else "DB0"); time.sleep(0.015)
        self.write("MN1" if mn else "MN0"); time.sleep(0.015)
        self.write("CO1" if co else "CO0"); time.sleep(0.015)
        if co:
            self.write(f"HI{hi:.6E}"); time.sleep(0.015)
            self.write(f"LO{lo:.6E}"); time.sleep(0.015)
        self._check_err("apply_calc")

    def read_stats(self):
        results = {}
        for cmd in ("MAX?", "MIN?", "AVE?", "AVN?",
                     "SCNT?", "SMAX?", "SMIN?", "SAVE?", "SSIG?", "SPTP?"):
            resp = self.query(cmd)
            if resp:
                results[cmd] = resp.strip()
        return results

    def start_acquisition(self):
        self.write("INIC1")
        self.write("TRS0")
        time.sleep(0.05)
        self._check_err("start_acq")

    def stop_acquisition(self):
        self.write("ABO")
        time.sleep(0.02)
        self._check_err("stop_acq")

    def enable_dual_display(self, enabled=True):
        self.write("DE1" if enabled else "DE0")
        time.sleep(0.02)
        self._check_err("DE")

    def set_output_mode(self, mode: str):
        from ..commands.adc_commands import SD_MODES
        self.write(SD_MODES.get(mode, "SD0"))
        time.sleep(0.02)

    def read_dual(self) -> tuple:
        raw = self.read()
        if raw is None:
            return None, None
        stripped = raw.strip()
        parts = stripped.split(',')
        if len(parts) >= 2:
            return parts[0].strip(), parts[1].strip()
        return stripped, None

    def read_channel(self, channel: str) -> str | None:
        dsp = {"A": "DSP1", "B": "DSP2"}[channel.upper()]
        self.write(dsp)
        time.sleep(0.02)
        return self.read()
