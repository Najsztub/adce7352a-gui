"""
ADC Command Registry - ADCMT 7352A (§6.6.3)

All ADC-mode commands, ranges, and metadata from the official manual.
"""

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

FUNCTION_KEYS = list(FUNCTIONS.keys())
FUNCTION_KEYS.sort(key=lambda k: int(k[1:]) if k[1:].isdigit() else 999)

SRATE_CMD = ["PR1", "PR2", "PR3", "PR4"]
SRATE_DISP = ["FAST", "MED", "SLOW1", "SLOW2"]

DIGITS_CMD = ["RE3", "RE4", "RE5"]
DIGITS_DISP = ["3½", "4½", "5½"]

TRIG_SOURCES = {
    "IMM": "TRS0",
    "MAN": "TRS1",
    "EXT": "TRS2",
    "BUS": "TRS3",
}

DSP_CMD = ["DSP1", "DSP2"]
DE_MODES = {"OFF": "DE0", "ON": "DE1"}
SD_MODES = {"BOTH": "SD0", "FIRST": "SD1", "SECOND": "SD2"}

FUNCTION_KEYS_A = ["F1", "F2", "F7", "F3", "F20", "F5", "F6", "F8", "F50", "F13", "F22", "F40"]
FUNCTION_KEYS_B = ["F12", "F35", "F36", "F37"]

OVERLOAD_THRESHOLD = 9.9e+36
OVERLOAD_DISPLAY = "9.99999E+37"

SUB_LABELS = {
    "_": "",     "O": " [OL]",   "H": " [HI]",   "P": " [PASS]",
    "L": " [LO]", "N": " [NULL]", "S": " [SCALE]", "B": " [dB]",
    "W": " [dBm]", "E": " [Err]", "M": " [MAX]",   "I": " [MIN]",
    "A": " [AVG]", "D": " [CALC2]",
}

HDR_LABELS = {
    "DCV": "DC Volt", "ACV": "AC Volt", "ADV": "AC+DC Volt",
    "R2W": "2W Res",  "R2L": "LP-2W",  "DCI": "DC Curr",
    "ACI": "AC Curr", "ADI": "AC+DC Curr", "FRQ": "Freq",
    "DOD": "Diode",   "RCT": "Cont",   "TC_": "Temp",
    "BDV": "Bch DCV", "BDI": "Bch DCI", "BAI": "Bch ACI", "BCI": "Bch ACI+DC",
}

AZ_MODES = {"ON": "AZ1", "OFF": "AZ0", "ONCE": "AZ2"}
HDR_MODES = {"ON": "H1", "OFF": "H0"}

COMMAND_CATEGORIES = {
    "Function": [k for k in FUNCTIONS],
    "Range": ["R0","R1","R2","R3","R4","R5","R6","R7","R8","R9","RX"],
    "Rate": list(SRATE_CMD),
    "Digits": list(DIGITS_CMD),
    "AutoZero": ["AZ0","AZ1","AZ2"],
    "Trigger": list(TRIG_SOURCES.values()) + ["TRN","SPN","TDE0","TDE1"],
    "Header": ["H0","H1"],
    "Display": ["DSP1","DSP2","DE0","DE1","SD0","SD1","SD2","DS0","DS1"],
    "Output": ["ODE0","ODE1","ODE2"],
    "Delimiter": ["DL0","DL1","DL2"],
    "SRQ": ["S0","S1"],
    "NULL": ["NL0","NL1","KNL"],
    "Smooth": ["SM0","SM1","TI"],
    "Scaling": ["SC0","SC1","KA","KB","KC","KAM","KBM","KCM"],
    "dB/dBm": ["DB0","DB1","DB2","KD","KDM"],
    "MaxMin": ["MN0","MN1","MAX?","MIN?","AVE?","AVN?"],
    "Comparator": ["CO0","CO1","HI","LO","HIM","LOM","LOP0","LOP1","MIP0","MIP1","HIP0","HIP1"],
    "Statistics": ["SIRD","SCNT?","SMAX?","SMIN?","SAVE?","SSIG?","SPTP?"],
    "DualMath": ["MCL0","MCL1","MCL2","MCL3","MCL4"],
    "System": ["*RST","*CLS","*IDN?","*OPC","*OPC?","*WAI","*STB?","*SRE","*ESR?","*ESE",
               "MSR?","MSE","QSR?","QSE","OSR?","OSE","*PSC","*OPT?","*TST?"],
    "SaveRecall": ["*SAV0","*SAV1","*SAV2","*SAV3","*RCL0","*RCL1","*RCL2","*RCL3","SINI","RINI"],
    "Calibration": ["CAL0","CAL1","CAL?","XOUT","PC","XDT","CMNT"],
    "Error": ["ERR?"],
    "Init": ["INIC0","INIC1","ABO"],
    "Buzzer": ["BZ0","BZ1","BZ2","BZ3","BZ4","BP0","BP1","BP2"],
    "Continuity": ["KOM"],
    "Temperature": ["TCR0","TCR1"],
    "PowerFreq": ["LF?"],
}

def get_func_by_key(fkey):
    return FUNCTIONS.get(fkey, ("Unknown","V",[],""))

def get_function_label(fkey):
    info = FUNCTIONS.get(fkey)
    return info[0] if info else fkey

def cur_fkey(func_label):
    for k, v in FUNCTIONS.items():
        if v[0] == func_label:
            return k
    return "F1"

def lookup_range_cmd(fkey, range_label):
    info = FUNCTIONS.get(fkey)
    if not info:
        return "R0"
    for lbl, cmd in info[2]:
        if lbl == range_label:
            return cmd
    return "R0"

def lookup_range_label(fkey, range_cmd):
    info = FUNCTIONS.get(fkey)
    if not info:
        return "Auto"
    for lbl, cmd in info[2]:
        if cmd == range_cmd:
            return lbl
    return "Auto"
