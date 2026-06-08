#!/usr/bin/env python3
"""
Real-device integration test for ADCMT 7352A.

Tests all command flows used by the GUI application against a physical instrument:
  - VISA connection & identification
  - ADC-mode initialization sequence
  - Per-channel function, range, rate, digits, auto-zero (with DSP1/DSP2 prefixes)
  - Calculation settings (NULL, smoothing, scaling, dB, max/min, comparator)
  - Statistics queries (MAX?, MIN?, AVE?, SCNT?, SMAX?, SMIN?, SAVE?, SSIG?, SPTP?)
  - Single-channel and dual-channel reads (SD1, SD2, SD0, read_channel)
  - Worker acquisition sequences (DE + SD combos)
  - Continuous free-run acquisition with interval timing
  - Error queue, status registers, cleanup

Usage:
    python -m gui.tests.test_real_device
    python -m gui.tests.test_real_device --resource USB0::4916::520::999991006::0::INSTR

Requires: Physical ADCMT 7352A connected via USB with PyVISA backend.
"""

import sys
import time
import argparse
import logging
import math

sys.path.insert(0, '.')
from gui.instruments.adcmt7352a_adc import ADCMT7352A
from gui.commands.parser import parse_adc_response, parse_dual_response
from gui.commands.adc_commands import (
    FUNCTIONS, FUNCTION_KEYS_A, FUNCTION_KEYS_B,
    SRATE_CMD, SRATE_DISP, DIGITS_CMD, DIGITS_DISP,
    OVERLOAD_THRESHOLD,
)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
)
log = logging.getLogger(__name__)

_PASS = 0
_FAIL = 0
_TOTAL = 0


def _section(name):
    global _TOTAL
    _TOTAL += 1
    log.info("")
    log.info("=" * 60)
    log.info(f"[TEST {_TOTAL}] {name}")
    log.info("=" * 60)


def _cmd(instr, cmd, expect_ok=True):
    """Write a command, log it, and check ERR? if expect_ok is True."""
    log.info(f"  CMD: {cmd}")
    instr.write(cmd)
    time.sleep(0.05)
    if expect_ok:
        err = instr.query("ERR?")
        log.info(f"  ERR: {err}")
        if err is None:
            log.warning(f"  ⚠ ERR? returned None")
        elif not err.startswith("+0"):
            log.warning(f"  ⚠ ERR? = {err}")
        return err
    return None


def _query(instr, cmd, label=None):
    """Send a query, log it and its response, return response."""
    log.info(f"  CMD: {cmd}")
    resp = instr.query(cmd)
    log.info(f"  RSP: {resp}")
    if label:
        log.info(f"  → {label}")
    return resp


def _read(instr):
    """Read raw data from the instrument, log it, return it."""
    raw = instr.read()
    log.info(f"  RSP: {raw}")
    return raw


def _result(passed, msg=""):
    global _PASS, _FAIL
    if passed:
        _PASS += 1
        log.info(f"  ✓ PASS {msg}")
    else:
        _FAIL += 1
        log.warning(f"  ✗ FAIL {msg}")
    return passed


def _check(condition, msg=""):
    return _result(condition, msg)


def _fk_eq(resp, expected):
    """Compare function keys ignoring zero-padding (F1 == F01)."""
    if resp is None:
        return False
    r = resp.lstrip('F').lstrip('0')
    e = expected.lstrip('F').lstrip('0')
    return r == e


# ─── Test 1: Connection & IDN ─────────────────────────────────────────────

def test_connection(instr):
    _section("Connection & IDN")

    ok = instr.connect()
    _check(ok, "connect() returned True")

    if ok:
        idn = instr.get_idn()
        log.info(f"  CMD: *IDN?")
        log.info(f"  RSP: {idn}")
        _check(idn is not None and len(idn.strip()) > 0, "valid *IDN? response")
        if idn:
            _check("ADC" in idn or "7352" in idn, "*IDN? contains 'ADC' or '7352'")
    return ok


# ─── Test 2: Init Sequence ────────────────────────────────────────────────

def test_init_sequence(instr):
    _section("Init Sequence")

    _cmd(instr, "*RST")
    _cmd(instr, "H1")
    _cmd(instr, "DE0")
    _cmd(instr, "SD1")
    _cmd(instr, "TRS0")
    _cmd(instr, "INIC1")

    qu = _query(instr, "H?")
    _check(qu == "H1", f"header is H1, got {qu}")
    qu = _query(instr, "DE?")
    _check(qu == "DE0", f"second display is DE0, got {qu}")
    qu = _query(instr, "SD?")
    _check(qu == "SD1", f"output mode is SD1, got {qu}")
    qu = _query(instr, "TRS?")
    _check(qu == "TRS0", f"trigger source is TRS0, got {qu}")
    qu = _query(instr, "INIC?")
    _check(qu == "INIC1", f"continuous is INIC1, got {qu}")


# ─── Test 3: Baseline Queries ─────────────────────────────────────────────

def test_baseline_queries(instr):
    _section("Baseline Queries")

    _query(instr, "*IDN?")

    for q in ("F?", "R?", "PR?", "RE?", "AZ?", "H?", "DE?", "SD?", "DS?"):
        resp = _query(instr, q)
        _check(resp is not None, f"{q} returned response")

    h = _query(instr, "H?")
    _check(h == "H1", "header ON after init")


# ─── Test 4: Ch A Functions (subset) ──────────────────────────────────────

CH_A_SUBSET = ["F1", "F2", "F3", "F5", "F50"]

def test_ch_a_functions(instr):
    _section("Ch A Functions (subset: F1, F2, F3, F5, F50)")

    for fk in CH_A_SUBSET:
        label = FUNCTIONS.get(fk, (fk,))[0]
        _cmd(instr, f"DSP1,{fk}")
        resp = _query(instr, "DSP1,F?")
        _check(_fk_eq(resp, fk), f"DSP1,F? = {resp}, expected {fk} ({label})")


# ─── Test 5: Ch A Ranges for DCV (F1) ────────────────────────────────────

def test_ch_a_ranges(instr):
    _section("Ch A Ranges (F1 = DCV)")

    _cmd(instr, "DSP1,F1")
    for rng in ("R3", "R4", "R5", "R6", "R7"):
        _cmd(instr, f"DSP1,{rng}")
        resp = _query(instr, "DSP1,R?")
        _check(resp == rng, f"DSP1,R? = {resp}, expected {rng}")


# ─── Test 6: Ch A Full Apply via DSP1 Prefix (GUI _apply_ch_a) ────────────

def test_ch_a_full_apply_via_dsp1(instr):
    _section("Ch A Full Apply via DSP1 (GUI _apply_ch_a flow)")

    _cmd(instr, "DSP1,F1")
    _cmd(instr, "DSP1,R5")     # 20 V range
    _cmd(instr, "DSP1,PR2")    # MED rate
    _cmd(instr, "DSP1,RE5")    # 5½ digits
    _cmd(instr, "DSP1,AZ1")    # auto-zero ON

    resp = _query(instr, "DSP1,F?")
    _check(_fk_eq(resp, "F1"), f"F? = {resp}")
    resp = _query(instr, "DSP1,R?")
    _check(resp == "R5", f"R? = {resp}")
    resp = _query(instr, "PR?")
    _check(resp == "PR2", f"PR? = {resp}")
    resp = _query(instr, "RE?")
    _check(resp == "RE5", f"RE? = {resp}")
    resp = _query(instr, "AZ?")
    _check(resp == "AZ1", f"AZ? = {resp}")

    # Toggle auto-zero OFF
    _cmd(instr, "DSP1,AZ0")
    resp = _query(instr, "AZ?")
    _check(resp == "AZ0", f"AZ? = {resp} after AZ0")


# ─── Test 7: Ch A Rate / Digits / Auto-Zero (no DSP prefix) ───────────────

def test_ch_a_rate_digits_az(instr):
    _section("Ch A Rate / Digits / Auto-Zero (no DSP prefix)")

    for idx, cmd in enumerate(SRATE_CMD):
        _cmd(instr, cmd)
        resp = _query(instr, "PR?")
        _check(resp == cmd, f"PR? = {resp}, expected {cmd} ({SRATE_DISP[idx]})")

    for idx, cmd in enumerate(DIGITS_CMD):
        _cmd(instr, cmd)
        resp = _query(instr, "RE?")
        _check(resp == cmd, f"RE? = {resp}, expected {cmd} ({DIGITS_DISP[idx]})")

    for az_cmd in ("AZ0", "AZ1", "AZ2"):
        _cmd(instr, az_cmd)
        resp = _query(instr, "AZ?")
        if az_cmd == "AZ2":
            _check(resp in ("AZ0", "AZ1"), f"AZ? = {resp} after AZ2 (transient)")
        else:
            _check(resp == az_cmd, f"AZ? = {resp}, expected {az_cmd}")


# ─── Test 8: Ch B Functions (all) ─────────────────────────────────────────

def test_ch_b_functions(instr):
    _section("Ch B Enable + Functions (F12, F35, F36, F37)")

    _cmd(instr, "DE1")
    resp = _query(instr, "DE?")
    _check(resp == "DE1", f"DE? = {resp}, expected DE1")

    for fk in FUNCTION_KEYS_B:
        label = FUNCTIONS.get(fk, (fk,))[0]
        _cmd(instr, f"DSP2,{fk}")
        resp = _query(instr, "DSP2,F?")
        _check(resp == fk, f"DSP2,F? = {resp}, expected {fk} ({label})")


# ─── Test 9: Ch B Full Apply via DSP2 Prefix (GUI _apply_ch_b) ────────────

def test_ch_b_full_apply_via_dsp2(instr):
    _section("Ch B Full Apply via DSP2 (GUI _apply_ch_b flow)")

    _cmd(instr, "DSP2,F12")     # DCV Bch
    _cmd(instr, "DSP2,R5")      # 20 V
    _cmd(instr, "DSP2,PR2")     # MED
    _cmd(instr, "DSP2,RE4")     # 4½ digits
    _cmd(instr, "DSP2,AZ1")     # auto-zero ON

    resp = _query(instr, "DSP2,F?")
    _check(resp == "F12", f"DSP2,F? = {resp}")
    resp = _query(instr, "PR?")
    _check(resp == "PR2", f"PR? = {resp}")
    resp = _query(instr, "DSP2,RE?")
    _check(resp == "RE4", f"DSP2,RE? = {resp}")
    resp = _query(instr, "AZ?")
    _check(resp == "AZ1", f"AZ? = {resp}")


    # Now test Bch 10 A current function via DSP2 prefix
    _cmd(instr, "DSP2,F35")     # DCI Bch
    _cmd(instr, "DSP2,R8")      # 10 A
    _cmd(instr, "DSP2,PR1")     # FAST
    _cmd(instr, "DSP2,RE5")     # 5½ digits
    _cmd(instr, "DSP2,AZ1")

    resp = _query(instr, "DSP2,F?")
    _check(resp == "F35", f"DSP2,F? = {resp} (DCI Bch)")
    resp = _query(instr, "PR?")
    _check(resp == "PR1", f"PR? = {resp}")


# ─── Test 10: Ch B Rate / Digits / Auto-Zero ──────────────────────────────

def test_ch_b_rate_digits_az(instr):
    _section("Ch B Rate / Digits / Auto-Zero (via DSP2)")

    _cmd(instr, "DSP2,F12")

    for idx, cmd in enumerate(SRATE_CMD):
        _cmd(instr, f"DSP2,{cmd}")
        instr.write("DSP2"); time.sleep(0.02)
        resp = _query(instr, "PR?")
        _check(resp == cmd, f"DSP2,PR? = {resp}, expected {cmd} ({SRATE_DISP[idx]})")

    _cmd(instr, "DSP2,RE5")
    _cmd(instr, "DSP2,AZ1")


# ─── Test 11: Single Read Ch A (SD1) ──────────────────────────────────────

def test_single_read_a(instr):
    _section("Single Read Ch A (SD1)")

    _cmd(instr, "DSP1,F1")
    _cmd(instr, "SD1")
    _cmd(instr, "INIC1")
    time.sleep(0.3)

    raw = _read(instr)
    _check(raw is not None, "read() returned data")

    if raw:
        parsed = parse_adc_response(raw, "F1")
        val, main_h, sub_h, is_ol, disp, desc = parsed
        log.info(f"  PARSED: val={val}, hdr={main_h}, sub={sub_h}, OL={is_ol}, disp={disp}, desc={desc}")
        _check(isinstance(val, (int, float)), f"value is numeric: {val}")
        _check(not is_ol, "not overload")
        if main_h:
            _check(len(main_h) == 3, f"header '{main_h}' is 3 chars")


# ─── Test 12: Single Read Ch B (SD2) ──────────────────────────────────────

def test_single_read_b(instr):
    _section("Single Read Ch B (SD2)")

    _cmd(instr, "SD2")
    time.sleep(0.3)

    raw = _read(instr)
    _check(raw is not None, "read() returned data")

    if raw:
        parsed = parse_adc_response(raw, "F12")
        val, main_h, sub_h, is_ol, disp, desc = parsed
        log.info(f"  PARSED: val={val}, hdr={main_h}, sub={sub_h}, OL={is_ol}, disp={disp}, desc={desc}")
        _check(isinstance(val, (int, float)), f"value is numeric: {val}")


# ─── Test 13: Ch B Only Read Path (SD2) ───────────────────────────────────

def test_ch_b_only_read_path(instr):
    _section("Ch B Only Read Path (SD2)")

    _cmd(instr, "DE0")
    _cmd(instr, "SD2")
    _cmd(instr, "DSP2,F12")
    _cmd(instr, "INIC1")
    time.sleep(0.3)

    raw = instr.read()
    log.info(f"  CMD: read()")
    log.info(f"  RSP: {raw}")
    _check(raw is not None, "read() returned data")

    if raw:
        parsed = parse_adc_response(raw, "F12")
        val, main_h, sub_h, is_ol, disp, desc = parsed
        log.info(f"  PARSED: val={val}, hdr={main_h}, sub={sub_h}, OL={is_ol}, disp={disp}, desc={desc}")
        _check(isinstance(val, (int, float)), f"value is numeric: {val}")
        _check(main_h != "DCV", f"expected Bch header, got '{main_h}'")


# ─── Test 14: Dual Read (SD0) ─────────────────────────────────────────────

def test_dual_read(instr):
    _section("Dual Read (SD0)")

    _cmd(instr, "DE1")
    _cmd(instr, "DSP1,F1")
    _cmd(instr, "DSP2,F12")
    _cmd(instr, "SD0")
    _cmd(instr, "INIC1")
    time.sleep(0.3)

    raw = _read(instr)
    _check(raw is not None, "dual read() returned data")

    if raw and ',' in raw:
        parsed = parse_dual_response(raw, "F1", "F12")
        data_a, data_b = parsed
        log.info(f"  PARSED A: {data_a}")
        log.info(f"  PARSED B: {data_b}")
        _check(data_a is not None and data_b is not None, "both channels parsed")
        if data_a:
            _check(isinstance(data_a[0], (int, float)), "Ch A value is numeric")
        if data_b:
            _check(isinstance(data_b[0], (int, float)), "Ch B value is numeric")
    elif raw:
        parsed = parse_adc_response(raw, "F1")
        log.info(f"  PARSED (single): {parsed}")


# ─── Test 15: Worker Acquisition Sequences (DE + SD combos) ───────────────

def test_worker_acquisition_sequences(instr):
    _section("Worker Acquisition Sequences")

    _cmd(instr, "*RST")
    _cmd(instr, "H1")
    _cmd(instr, "INIC1")

    # Sequence 1: Ch A only → DE0 + SD1
    log.info("  --- Sequence 1: Ch A only (DE0 + SD1) ---")
    _cmd(instr, "DE0")
    _cmd(instr, "SD1")
    _cmd(instr, "DSP1,F1")
    time.sleep(0.2)
    raw = _read(instr)
    _check(raw is not None, "Seq1 (Ch A only): read() returned data")
    if raw:
        parsed = parse_adc_response(raw, "F1")
        _check(isinstance(parsed[0], (int, float)), "Seq1: value is numeric")

    # Sequence 2: Ch B only → DE0 + SD2
    log.info("  --- Sequence 2: Ch B only (DE0 + SD2 + read) ---")
    _cmd(instr, "DSP2,F12")
    _cmd(instr, "SD2")
    time.sleep(0.2)
    raw = _read(instr)
    _check(raw is not None, "Seq2 (Ch B only): read() returned data")
    if raw:
        parsed = parse_adc_response(raw, "F12")
        _check(isinstance(parsed[0], (int, float)), "Seq2: value is numeric")

    # Sequence 3: Both → DE1 + SD0
    log.info("  --- Sequence 3: Both channels (DE1 + SD0) ---")
    _cmd(instr, "DSP1,F1")
    _cmd(instr, "DE1")
    _cmd(instr, "SD0")
    time.sleep(0.2)
    raw = _read(instr)
    _check(raw is not None, "Seq3 (both): read() returned data")
    if raw and ',' in raw:
        data_a, data_b = parse_dual_response(raw, "F1", "F12")
        _check(data_a is not None, "Seq3: Ch A parsed")
        _check(data_b is not None, "Seq3: Ch B parsed")


# ─── Test 16: Continuous Free-Run Readings ─────────────────────────────────

def test_continuous_read(instr):
    _section("Continuous Free-Run (10 reads)")

    _cmd(instr, "SD0")
    _cmd(instr, "INIC1")
    time.sleep(0.2)

    reads = []
    for i in range(10):
        raw = instr.read()
        log.info(f"  READ[{i}]: {raw}")
        _check(raw is not None, f"read[{i}] returned data")
        if raw:
            reads.append(raw)
        time.sleep(0.1)

    _check(len(reads) >= 8, f"got {len(reads)}/10 readings (≥8 pass)")

    if len(reads) >= 3:
        has_comma = [',' in r for r in reads[:5]]
        all_same_format = all(has_comma) or not any(has_comma)
        _check(all_same_format, "format consistent (all SD0 or all single)")


# ─── Test 17: Interval Timing Validation ──────────────────────────────────

def test_interval_timing(instr):
    _section("Interval Timing (5 reads at 200ms)")

    _cmd(instr, "SD1")
    _cmd(instr, "DSP1,F1")
    _cmd(instr, "INIC1")
    time.sleep(0.3)

    target_ms = 200
    timestamps = []
    for i in range(5):
        t0 = time.monotonic()
        raw = instr.read()
        _check(raw is not None, f"timed read[{i}] returned data")
        timestamps.append(time.monotonic())
        time.sleep(target_ms / 1000.0)

    intervals = []
    for i in range(1, len(timestamps)):
        delta = (timestamps[i] - timestamps[i - 1]) * 1000
        intervals.append(delta)

    if intervals:
        avg_interval = sum(intervals) / len(intervals)
        min_interval = min(intervals)
        max_interval = max(intervals)
        log.info(f"  Intervals (ms): avg={avg_interval:.1f}, min={min_interval:.1f}, max={max_interval:.1f}")
        tolerance = 0.5
        lower = target_ms * (1 - tolerance)
        upper = target_ms * (1 + tolerance)
        within_tolerance = all(lower <= iv <= upper for iv in intervals)
        _check(within_tolerance,
               f"intervals within [{lower:.0f}, {upper:.0f}] ms: {[f'{iv:.0f}' for iv in intervals]}")


# ─── Test 18: Calculations Apply (GUI _apply_calc) ─────────────────────────

def test_calculations_apply(instr):
    _section("Calculations Apply (GUI _apply_calc flow)")

    _cmd(instr, "*RST")
    _cmd(instr, "H1")
    _cmd(instr, "DSP1,F1")
    _cmd(instr, "INIC1")

    # NULL calculation
    log.info("  --- NULL Calculation (NL0/NL1) ---")
    _cmd(instr, "NL1")
    resp = _query(instr, "NL?")
    _check(resp == "NL1", f"NL? = {resp}, expected NL1")
    _cmd(instr, "NL0")
    resp = _query(instr, "NL?")
    _check(resp == "NL0", f"NL? = {resp}, expected NL0")

    # Smoothing calculation
    log.info("  --- Smoothing (SM0/SM1 + TI) ---")
    _cmd(instr, "SM1")
    _cmd(instr, "TI25")
    resp = _query(instr, "SM?")
    _check(resp == "SM1", f"SM? = {resp}, expected SM1")
    resp = _query(instr, "TI?")
    _check(resp == "TI025", f"TI? = {resp}, expected TI025")
    _cmd(instr, "SM0")
    resp = _query(instr, "SM?")
    _check(resp == "SM0", f"SM? = {resp}, expected SM0")

    # Scaling calculation
    log.info("  --- Scaling (SC0/SC1) ---")
    _cmd(instr, "SC1")
    resp = _query(instr, "SC?")
    _check(resp == "SC1", f"SC? = {resp}, expected SC1")
    _cmd(instr, "SC0")
    resp = _query(instr, "SC?")
    _check(resp == "SC0", f"SC? = {resp}, expected SC0")

    # dB/dBm calculation
    log.info("  --- dB/dBm (DB0/DB1/DB2) ---")
    _cmd(instr, "DB1")
    resp = _query(instr, "DB?")
    _check(resp == "DB1", f"DB? = {resp}, expected DB1")
    _cmd(instr, "DB0")
    resp = _query(instr, "DB?")
    _check(resp == "DB0", f"DB? = {resp}, expected DB0")

    # MAX/MIN calculation
    log.info("  --- MAX/MIN (MN0/MN1 + queries) ---")
    _cmd(instr, "MN0")
    resp = _query(instr, "MN?")
    _check(resp == "MN0", f"MN? = {resp}, expected MN0 (OFF)")
    _cmd(instr, "MN1")
    resp = _query(instr, "MN?")
    _check(resp == "MN1", f"MN? = {resp}, expected MN1 (ON)")

    time.sleep(0.5)
    max_r = _query(instr, "MAX?")
    _check(max_r is not None, "MAX? returned response")
    min_r = _query(instr, "MIN?")
    _check(min_r is not None, "MIN? returned response")
    ave_r = _query(instr, "AVE?")
    _check(ave_r is not None, "AVE? returned response")
    avn_r = _query(instr, "AVN?")
    _check(avn_r is not None, "AVN? returned response")

    # Comparator calculation
    log.info("  --- Comparator (CO0/CO1 + HI/LO) ---")
    _cmd(instr, "CO0")
    resp = _query(instr, "CO?")
    _check(resp == "CO0", f"CO? = {resp}, expected CO0 (OFF)")
    _cmd(instr, "CO1")
    _cmd(instr, "HI+1.00000E+00")
    _cmd(instr, "LO-1.00000E+00")
    resp = _query(instr, "CO?")
    _check(resp == "CO1", f"CO? = {resp}, expected CO1 (ON)")
    hi_r = _query(instr, "HI?")
    lo_r = _query(instr, "LO?")

    _cmd(instr, "CO0")
    _cmd(instr, "MN0")


# ─── Test 19: Read Stats (GUI _read_stats) ────────────────────────────────

def test_read_stats(instr):
    _section("Read Stats (GUI _read_stats flow)")

    _cmd(instr, "*RST")
    _cmd(instr, "H1")
    _cmd(instr, "DSP1,F1")
    _cmd(instr, "MN1")
    _cmd(instr, "SD1")
    _cmd(instr, "INIC1")
    time.sleep(1.0)

    log.info("  --- Querying all stats (MAX?..SPTP?) ---")
    stat_queries = [
        "MAX?", "MIN?", "AVE?", "AVN?",
        "SCNT?", "SMAX?", "SMIN?", "SAVE?", "SSIG?", "SPTP?",
    ]
    results = {}
    for q in stat_queries:
        resp = _query(instr, q)
        _check(resp is not None, f"{q} returned response")
        if resp:
            results[q] = resp.strip()

    _check(len(results) >= 8,
           f"got {len(results)}/{len(stat_queries)} stat responses (≥8 pass)")

    # AVN? should show a non-zero count after 1s of acquisition
    avn = results.get("AVN?", "")
    if avn:
        try:
            count = float(avn.replace("AVN", "").strip())
            _check(count > 0, f"AVN? = {count} (expected > 0 after acquisition)")
        except (ValueError, IndexError):
            _check(False, f"AVN? = {avn}, could not parse count")


# ─── Test 20: Error Queue ─────────────────────────────────────────────────

def test_error_queue(instr):
    _section("Error Queue")

    _cmd(instr, "INIC1")

    _cmd(instr, "XYZ", expect_ok=False)
    time.sleep(0.05)

    err = _query(instr, "ERR?")
    _check(err is not None, "ERR? returned response")
    _check(err is None or not err.startswith("+0"),
           f"ERR? = {err} (expected non-zero error after invalid command)")


# ─── Test 21: Status Registers ────────────────────────────────────────────

def test_status_registers(instr):
    _section("Status Registers")

    for q in ("*STB?", "*ESR?", "MSR?"):
        resp = _query(instr, q)
        _check(resp is not None, f"{q} returned response")
        if resp:
            _check(resp.strip().lstrip('-').isdigit(), f"{q} = {resp} (numeric)")


# ─── Test 22: Cleanup ─────────────────────────────────────────────────────

def test_cleanup(instr):
    _section("Cleanup")

    _cmd(instr, "ABO", expect_ok=False)
    _cmd(instr, "INIC0")
    _cmd(instr, "DE0")
    _cmd(instr, "SD1")
    _cmd(instr, "H1")
    _cmd(instr, "TRS3")

    _cmd(instr, "*CLS", expect_ok=False)
    time.sleep(0.1)
    _query(instr, "ERR?")
    _cmd(instr, "DS1")

    instr.disconnect()
    _check(not instr.connected, "disconnected")
    log.info("  Disconnect OK")


# ─── Main Runner ──────────────────────────────────────────────────────────

def main():
    global _PASS, _FAIL, _TOTAL
    _PASS = 0
    _FAIL = 0
    _TOTAL = 0

    parser = argparse.ArgumentParser(description="ADCMT 7352A real-device test")
    parser.add_argument("--resource", default=None,
                        help="VISA resource string (default: from ADCMT7352A)")
    args = parser.parse_args()

    instr = ADCMT7352A(use_mock=False, resource_string=args.resource)
    log.info(f"VISA resource: {instr._resource_string}")

    if not instr.connect():
        log.error("Failed to connect to instrument")
        sys.exit(1)

    try:
        tests = [
            (test_connection, instr),
            (test_init_sequence, instr),
            (test_baseline_queries, instr),
            (test_ch_a_functions, instr),
            (test_ch_a_ranges, instr),
            (test_ch_a_full_apply_via_dsp1, instr),
            (test_ch_a_rate_digits_az, instr),
            (test_ch_b_functions, instr),
            (test_ch_b_full_apply_via_dsp2, instr),
            (test_ch_b_rate_digits_az, instr),
            (test_single_read_a, instr),
            (test_single_read_b, instr),
            (test_ch_b_only_read_path, instr),
            (test_dual_read, instr),
            (test_worker_acquisition_sequences, instr),
            (test_continuous_read, instr),
            (test_interval_timing, instr),
            (test_calculations_apply, instr),
            (test_read_stats, instr),
            (test_error_queue, instr),
            (test_status_registers, instr),
            (test_cleanup, instr),
        ]

        for fn, arg in tests:
            try:
                fn(arg)
            except Exception as e:
                _result(False, f"exception: {e}")
                import traceback
                log.warning(traceback.format_exc())

        log.info("")
        log.info("=" * 60)
        log.info(f"SUMMARY: {_PASS}/{_TOTAL} passed, {_FAIL} failed")
        log.info("=" * 60)

        sys.exit(0 if _FAIL == 0 else 1)

    finally:
        if instr.connected:
            instr.write("ABO")
            instr.write("INIC0")
            instr.disconnect()
            log.info("Clean disconnect in finally")


if __name__ == "__main__":
    main()
