"""
ADC Response Parser - ADCMT 7352A (§6.6.2)

Parses instrument output in ADC mode:
  Header ON  (H1):  "DCV_  +3.29860E+00"
  Header OFF (H0):  "+3.29860E+00"
  Overload:         9.99999E+37
"""

import re
from .adc_commands import (
    OVERLOAD_THRESHOLD, SUB_LABELS, HDR_LABELS, FUNCTIONS
)

_HDR_RE = re.compile(r'^([A-Z0-9_]{3})([A-Z_])\s+([-+]?\d[\d.]*E[+-]\d+)\s*$')
_NUM_RE = re.compile(r'^([-+]?\d[\d.]*E[+-]\d+)')


def si_fmt(val, unit):
    if val == 0:
        return f"0.000 {unit}"
    a = abs(val)
    for scale, pfx in [(1e12, "T"), (1e9, "G"), (1e6, "M"), (1e3, "k"),
                       (1, ""), (1e-3, "m"), (1e-6, "µ"), (1e-9, "n"), (1e-12, "p")]:
        if a >= scale * 0.9999:
            return f"{val/scale:.5g} {pfx}{unit}"
    return f"{val:.5E} {unit}"


def parse_adc_response(raw, func_key="F1"):
    raw = raw.strip()
    main_h, sub_h = "", "_"
    m = _HDR_RE.match(raw)
    if m:
        main_h = m.group(1)
        sub_h = m.group(2)
        num_s = m.group(3)
    else:
        nm = _NUM_RE.match(raw)
        num_s = nm.group(1) if nm else raw
    try:
        val = float(num_s)
    except ValueError:
        return 0.0, main_h, sub_h, False, raw, raw
    is_ol = val >= OVERLOAD_THRESHOLD
    unit = FUNCTIONS.get(func_key, ("", "V", "", "DCV"))[1]
    disp = "OVERLOAD" if is_ol else si_fmt(val, unit)
    desc = HDR_LABELS.get(main_h, main_h) + SUB_LABELS.get(sub_h, f" [{sub_h}]")
    return val, main_h, sub_h, is_ol, disp, desc


_DUAL_RE = re.compile(
    r'^([A-Z0-9_]{3})([A-Z_])\s+([-+]?\d[\d.]*E[+-]\d+)\s*,\s*'
    r'([A-Z0-9_]{3})([A-Z_])\s+([-+]?\d[\d.]*E[+-]\d+)\s*$'
)


def parse_dual_response(raw, func_key_a="F1", func_key_b="F12"):
    raw = raw.strip()
    m = _DUAL_RE.match(raw)
    if m:
        a = parse_adc_response(m.group(1) + m.group(2) + "  " + m.group(3), func_key_a)
        b = parse_adc_response(m.group(4) + m.group(5) + "  " + m.group(6), func_key_b)
        return a, b
    a = parse_adc_response(raw, func_key_a)
    return a, None


def parse_query_response(cmd, response):
    if response is None:
        return None
    resp = response.strip()
    return resp


def build_apply_settings_commands(func_key, range_cmd, rate_idx, digits_idx, az_cmd, dsp="DSP1"):
    cmds = []
    cmds.append(f"{dsp},{func_key}")
    if range_cmd:
        cmds.append(f"{dsp},{range_cmd}")
    cmds.append(f"{dsp},{rate_idx}")
    cmds.append(f"{dsp},{digits_idx}")
    cmds.append(az_cmd)
    return cmds


def build_calc_settings_commands(nl, sm, sm_pts, sc, db, mn, co, hi, lo):
    cmds = []
    cmds.append("NL1" if nl else "NL0")
    cmds.append("SM1" if sm else "SM0")
    if sm:
        pts = max(2, min(100, sm_pts))
        cmds.append(f"TI{pts}")
    cmds.append("SC1" if sc else "SC0")
    cmds.append("DB1" if db else "DB0")
    cmds.append("MN1" if mn else "MN0")
    cmds.append("CO1" if co else "CO0")
    if co:
        cmds.append(f"HI{hi:.6E}")
        cmds.append(f"LO{lo:.6E}")
    return cmds
