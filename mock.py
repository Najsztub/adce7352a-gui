import numpy as np
import random
import time


FUNCTION_RANGES = {
    "F1":  {"R0": (0, 1000), "R3": (0, 0.2), "R4": (0, 2), "R5": (0, 20), "R6": (0, 200), "R7": (0, 1000)},
    "F2":  {"R0": (0, 700), "R3": (0, 0.2), "R4": (0, 2), "R5": (0, 20), "R6": (0, 200), "R7": (0, 700)},
    "F3":  {"R0": (0, 200e6), "R3": (0, 200), "R4": (0, 2e3), "R5": (0, 20e3), "R6": (0, 200e3), "R7": (0, 2e6), "R8": (0, 20e6), "R9": (0, 200e6)},
    "F5":  {"R0": (0, 2), "R1": (0, 2e-6), "R2": (0, 20e-6), "R3": (0, 200e-6), "R4": (0, 2e-3), "R5": (0, 20e-3), "R6": (0, 200e-3), "R7": (0, 2)},
    "F6":  {"R0": (0, 2), "R3": (0, 200e-6), "R4": (0, 2e-3), "R5": (0, 20e-3), "R6": (0, 200e-3), "R7": (0, 2)},
    "F7":  {"R0": (0, 700), "R3": (0, 0.2), "R4": (0, 2), "R5": (0, 20), "R6": (0, 200), "R7": (0, 700)},
    "F8":  {"R0": (0, 2), "R3": (0, 200e-6), "R4": (0, 2e-3), "R5": (0, 20e-3), "R6": (0, 200e-3), "R7": (0, 2)},
    "F12": {"R0": (0, 200), "R3": (0, 0.2), "R4": (0, 2), "R5": (0, 20), "R6": (0, 200)},
    "F13": {"R0": (0, 10)},
    "F20": {"R0": (0, 20e6), "R3": (0, 200), "R4": (0, 2e3), "R5": (0, 20e3), "R6": (0, 200e3), "R7": (0, 2e6), "R8": (0, 20e6)},
    "F22": {"R0": (0, 1000)},
    "F35": {"R8": (0, 10)},
    "F36": {"R8": (0, 10)},
    "F37": {"R8": (0, 10)},
    "F40": {"R0": (-40, 100)},
    "F50": {"R0": (0, 1e6)},
}


class MockDMMDevice:
    def __init__(self):
        self.timeout = 2000
        self._error_queue = []
        self._init_state()

    def _init_state(self):
        self.ch_a = {
            "enabled": True,
            "func": "F1",
            "range": "R0",
            "rate": "PR4",
            "trig": "TRS0",
            "digits": "RE4",
            "value": 5.0,
            "base_noise_std": 0.001,
            "noise_std": 0.001,
        }
        self.ch_b = {
            "enabled": False,
            "func": "F12",
            "range": "R0",
            "rate": "PR4",
            "trig": "TRS0",
            "digits": "RE4",
            "value": 3.3,
            "base_noise_std": 0.001,
            "noise_std": 0.001,
        }
        self._header_mode = False
        self._display_enabled = True
        self._last_trigger_time = 0

    def query(self, cmd):
        cmd = cmd.strip()
        
        if cmd.endswith("?"):
            return self._handle_query(cmd)
        else:
            self.write(cmd)
            return None

    def _handle_query(self, cmd):
        if "MD?" in cmd:
            return self._handle_measurement(cmd)
        elif "ERR?" in cmd:
            return self._handle_error()
        elif "ID?" in cmd:
            return "ADCMT7352A"
        elif "STAT?" in cmd:
            return "+0000"
        elif "DSP?" in cmd:
            return self._handle_dsp_query(cmd)
        return "+0.00000E+00,"

    def _handle_measurement(self, cmd):
        if "DSP1" in cmd:
            ch = self.ch_a
        elif "DSP2" in cmd:
            ch = self.ch_b
        else:
            return "+0.00000E+00,"

        if not ch["enabled"]:
            return "+0.00000E+00,"

        val = self._generate_value(ch)
        exp = f"{val:.5e}".replace('e', 'E')
        
        if self._header_mode:
            prefix = self._get_header_prefix(ch)
            return f"{prefix} {exp},"
        return f"{exp},"

    def _generate_value(self, ch):
        func = ch["func"]
        rng = ch["range"]
        base = ch["value"]
        std = ch["noise_std"]
        
        if func not in FUNCTION_RANGES:
            func = "F1"
        
        ranges = FUNCTION_RANGES.get(func, {"R0": (0, 10)})
        
        if rng == "R0":
            resolved_range = self._resolve_auto_range(func, base)
        else:
            resolved_range = rng
        
        min_val, max_val = ranges.get(resolved_range, (0, 10))
        
        noise = np.random.normal(0, std * abs(base) if base != 0 else std)
        val = base + noise
        
        if func == "F1" or func == "F12":
            drift = np.random.normal(0, std * 0.1)
            ch["value"] = np.clip(ch["value"] + drift, min_val * 0.9, max_val * 0.9)
        
        val = np.clip(val, min_val, max_val)
        
        if val >= max_val and max_val > 0:
            return 9.9e+9
        
        return val

    def _resolve_auto_range(self, func, value):
        ranges = FUNCTION_RANGES.get(func, {"R0": (0, 10)})
        
        if func == "F1":
            if value < 0.2: return "R3"
            elif value < 2: return "R4"
            elif value < 20: return "R5"
            elif value < 200: return "R6"
            else: return "R7"
        elif func == "F3":
            if value < 200: return "R3"
            elif value < 2e3: return "R4"
            elif value < 20e3: return "R5"
            elif value < 200e3: return "R6"
            elif value < 2e6: return "R7"
            elif value < 20e6: return "R8"
            else: return "R9"
        
        return "R1"

    def _get_header_prefix(self, ch):
        func = ch["func"]
        func_headers = {
            "F1": "DCV", "F2": "ACV", "F3": "R2W", "F5": "DCI", "F6": "ACI",
            "F7": "ADV", "F8": "ADI", "F12": "BDV", "F13": "DOD", "F20": "R2L",
            "F22": "RCT", "F35": "BDI", "F36": "BAI", "F37": "BCI", "F40": "TC_",
            "F50": "FRQ",
        }
        return func_headers.get(func, "DCV")

    def _handle_error(self):
        if self._error_queue:
            err = self._error_queue.pop(0)
            return f"+{err:04d}"
        return "+0000"

    def _handle_dsp_query(self, cmd):
        if "DSP1" in cmd:
            ch = self.ch_a
        elif "DSP2" in cmd:
            ch = self.ch_b
        else:
            return "0"
        
        if "F" in cmd:
            return ch["func"]
        elif "R" in cmd:
            return ch["range"]
        return "0"

    def write(self, cmd):
        cmd = cmd.strip()
        parts = cmd.split(",")
        
        if len(parts) >= 2:
            target = parts[0]
            
            if target in ("DSP1", "DSP2"):
                self._handle_dsp_command(target, parts[1:])
            elif target == "DP":
                self._handle_display_command(parts[1])
            elif target == "H":
                self._header_mode = (parts[1] == "1")
            elif target == "DE":
                pass
            elif target in ("INI", "ABO"):
                self._handle_special_command(target)
            elif target in ("RE3", "RE4", "RE5"):
                self._handle_digits_command(target)
            elif target in ("PR1", "PR2", "PR3", "PR4"):
                self._handle_rate_command(target)
            elif target in ("TRS0", "TRS1", "TRS2", "TRS3"):
                self._handle_trigger_command(target)

    def _handle_dsp_command(self, target, params):
        ch = self.ch_a if target == "DSP1" else self.ch_b
        
        for p in params:
            if p.startswith("F") and p in FUNCTION_RANGES:
                ch["func"] = p
                self._update_noise_for_function(ch)
            elif p.startswith("R") and len(p) <= 2:
                if p == "R0":
                    ch["range"] = "R0"
                elif p in ("R1", "R2", "R3", "R4", "R5", "R6", "R7", "R8", "R9"):
                    ch["range"] = p
            elif p.startswith("PR"):
                ch["rate"] = p
            elif p.startswith("TRS"):
                ch["trig"] = p

    def _update_noise_for_function(self, ch):
        func = ch["func"]
        
        if func in ("F1", "F12"):
            ch["noise_std"] = 0.001
        elif func in ("F2", "F7"):
            ch["noise_std"] = 0.01
        elif func in ("F3", "F20"):
            ch["noise_std"] = 0.005
        elif func in ("F5", "F6", "F8", "F35", "F36", "F37"):
            ch["noise_std"] = 0.002
        elif func == "F50":
            ch["noise_std"] = 1.0
        elif func == "F40":
            ch["noise_std"] = 0.1
        else:
            ch["noise_std"] = 0.001

    def _handle_display_command(self, param):
        if param == "0":
            self.ch_b["enabled"] = False
        elif param == "1":
            self.ch_b["enabled"] = True

    def _handle_special_command(self, cmd):
        if cmd == "INI":
            self._init_state()
        elif cmd == "ABO":
            self._last_trigger_time = time.time()

    def _handle_digits_command(self, cmd):
        for ch in (self.ch_a, self.ch_b):
            ch["digits"] = cmd

    def _handle_rate_command(self, cmd):
        rate_noise = {"PR1": 0.01, "PR2": 0.005, "PR3": 0.002, "PR4": 0.001}
        noise = rate_noise.get(cmd, 0.001)
        for ch in (self.ch_a, self.ch_b):
            base_std = ch.get("base_noise_std", 0.001)
            ch["noise_std"] = base_std * (noise / 0.001)

    def _handle_trigger_command(self, cmd):
        for ch in (self.ch_a, self.ch_b):
            ch["trig"] = cmd

    def close(self):
        pass

    def read(self):
        """Simulate bare read - return a measurement for DSP1."""
        return self._handle_measurement("DSP1?")
