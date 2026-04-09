import re
import math
import time
import random
from collections import defaultdict

# =============================================================================

ADC_FUNCS = {
    "DCV-Ach": "F1", "ACV-Ach": "F2", "2WΩ-Ach": "F3", "DCI-Ach": "F5",
    "ACI-Ach": "F6", "ACV+DC-Ach": "F7", "ACI+DC-Ach": "F8",
    "DCV-Bch": "F12", "DIODE-Ach": "F13", "LP-2WΩ-Ach": "F20",
    "CONT-Ach": "F22", "DCI-Bch": "F35", "ACI-Bch": "F36",
    "ACI+DC-Bch": "F37", "TEMP": "F40", "FREQ-Ach": "F50"
}

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
ADC_RATES  = {"FAST": "PR1", "MED": "PR2", "SLOW1": "PR3", "SLOW2": "PR4"}
ADC_TRIGS  = {"IMM": "TRS0", "MAN": "TRS1", "EXT": "TRS2", "BUS": "TRS3"}

DIGITS_CMD  = ["RE3", "RE4", "RE5"]
DIGITS_DISP = ["3½", "4½", "5½"]

OVERLOAD_THRESHOLD = 9.9e+9

SUB_LABELS = {
    "_": "", "O": " [OL]", "H": " [HI]", "P": " [PASS]",
    "L": " [LO]", "N": " [NULL]", "S": " [SCALE]", "B": " [dB]",
    "W": " [dBm]", "E": " [Err]", "M": " [MAX]", "I": " [MIN]",
    "A": " [AVG]", "D": " [CALC2]",
}

HDR_LABELS = {
    "DCV": "DC Volt", "ACV": "AC Volt", "ADV": "AC+DC Volt",
    "R2W": "2W Res",  "R2L": "LP-2W",  "DCI": "DC Curr",
    "ACI": "AC Curr", "ADI": "AC+DC Curr", "FRQ": "Freq",
    "DOD": "Diode",   "RCT": "Cont",   "TC_": "Temp",
    "BDV": "DC Volt B", "BDI": "DC Curr B", "BAI": "AC Curr B", "BCI": "AC+DC Curr B",
}

FUNCTIONS = {
    "F1":  ("DCV  Ach",          "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),("20 V","R5"),("200 V","R6"),("1000 V","R7")], "DCV"),
    "F2":  ("ACV  Ach",          "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),("20 V","R5"),("200 V","R6"),("700 V","R7")], "ACV"),
    "F7":  ("ACV AC+DC  Ach",    "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),("20 V","R5"),("200 V","R6"),("700 V","R7")], "ADV"),
    "F3":  ("2W Ω  Ach",         "Ω",
            [("Auto","R0"),("200 Ω","R3"),("2 kΩ","R4"),("20 kΩ","R5"),
             ("200 kΩ","R6"),("2 MΩ","R7"),("20 MΩ","R8"),("200 MΩ","R9")], "R2W"),
    "F20": ("LP-2W Ω  Ach",      "Ω",
            [("Auto","R0"),("200 Ω","R3"),("2 kΩ","R4"),("20 kΩ","R5"),
             ("200 kΩ","R6"),("2 MΩ","R7"),("20 MΩ","R8")], "R2L"),
    "F5":  ("DCI  Ach",          "A",
            [("Auto","R0"),("2000 nA","R1"),("20 µA","R2"),("200 µA","R3"),
             ("2 mA","R4"),("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "DCI"),
    "F6":  ("ACI  Ach",          "A",
            [("Auto","R0"),("200 µA","R3"),("2 mA","R4"),
             ("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "ACI"),
    "F8":  ("ACI AC+DC  Ach",    "A",
            [("Auto","R0"),("200 µA","R3"),("2 mA","R4"),
             ("20 mA","R5"),("200 mA","R6"),("2000 mA","R7")], "ADI"),
    "F50": ("FREQ  Ach",         "Hz", [("Auto","R0")], "FRQ"),
    "F13": ("DIODE  Ach",        "V",  [("—","")],      "DOD"),
    "F22": ("CONT  Ach",         "Ω",  [("—","")],      "RCT"),
    "F40": ("TEMP",              "°C", [("—","")],      "TC_"),
    "F12": ("DCV  Bch",          "V",
            [("Auto","R0"),("200 mV","R3"),("2 V","R4"),("20 V","R5"),("200 V","R6")], "BDV"),
    "F35": ("DCI  Bch",          "A",  [("10 A","R8")], "BDI"),
    "F36": ("ACI  Bch",          "A",  [("10 A","R8")], "BAI"),
    "F37": ("ACI AC+DC  Bch",    "A",  [("10 A","R8")], "BCI"),
}

# =============================================================================
# RESPONSE PARSER  (§6.6.2)
# =============================================================================
_HDR_RE = re.compile(r'^([A-Z0-9_]{3})([A-Z_])\s+([-+]?\d[\d.]*E[+-]\d+)\s*$')
_NUM_RE = re.compile(r'^([-+]?\d[\d.]*E[+-]\d+)')

def cur_fkey(func_label):
    for k, v in FUNCTIONS.items():
        if v[0] == func_label:
            return k
    return "F1"

def si_fmt(val, unit):
    if val == 0:
        return f"0.000 {unit}"
    a = abs(val)
    for scale, pfx in [(1e12,"T"),(1e9,"G"),(1e6,"M"),(1e3,"k"),
                       (1,""),(1e-3,"m"),(1e-6,"µ"),(1e-9,"n"),(1e-12,"p")]:
        if a >= scale * 0.9999:
            return f"{val/scale:.5g} {pfx}{unit}"
    return f"{val:.5E} {unit}"

def parse_adc_response(raw, func_key="F1"):
    """Returns (value, main_hdr, sub_hdr, is_overload, display_str, desc_str)."""
    raw = raw.strip()
    main_h, sub_h = "", "_"
    m = _HDR_RE.match(raw)
    if m:
        main_h, sub_h, num_s = m.group(1), m.group(2), m.group(3)
    else:
        nm = _NUM_RE.match(raw)
        num_s = nm.group(1) if nm else raw
    try:
        val = float(num_s)
    except ValueError:
        return 0.0, main_h, sub_h, False, raw, raw
    is_ol = val >= OVERLOAD_THRESHOLD
    unit  = FUNCTIONS.get(func_key, ("","V","","DCV"))[1]
    disp  = "OVERLOAD" if is_ol else si_fmt(val, unit)
    desc  = HDR_LABELS.get(main_h, main_h) + SUB_LABELS.get(sub_h, f" [{sub_h}]")
    return val, main_h, sub_h, is_ol, disp, desc
