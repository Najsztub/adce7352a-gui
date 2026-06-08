"""
VISA Communication Backend for ADCMT 7352A

Provides low-level PyVISA communication with proper settings:
- Termination: CR+LF (\r\n) both read/write (§6.3.3)
- USB settling time: 20ms after write (§6.6.3 CAUTION)
- Error checking: ERR? after every write
"""

import time
import logging
from threading import Lock
from abc import ABC, abstractmethod

log = logging.getLogger(__name__)


class InstrumentBackend(ABC):
    @abstractmethod
    def connect(self) -> bool:
        ...

    @abstractmethod
    def disconnect(self):
        ...

    @property
    @abstractmethod
    def connected(self) -> bool:
        ...

    @abstractmethod
    def write(self, cmd: str):
        ...

    @abstractmethod
    def query(self, cmd: str) -> str | None:
        ...

    @abstractmethod
    def read(self) -> str | None:
        ...

    @abstractmethod
    def get_idn(self) -> str | None:
        ...


class VISABackend(InstrumentBackend):
    USB_SETTLE_MS = 25

    RESOURCE_DEFAULT = "USB0::4916::520::999991006::0::INSTR"

    def __init__(self, resource_string: str = RESOURCE_DEFAULT):
        self._resource_string = resource_string
        self._instr = None
        self._rlock = Lock()
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        if self._connected:
            return True
        try:
            import pyvisa
            rm = pyvisa.ResourceManager()
            self._instr = rm.open_resource(self._resource_string)
            self._instr.timeout = 10000
            self._instr.write_termination = "\r\n"
            self._instr.read_termination = "\r\n"
            self._connected = True
            log.info(f"VISA connected: {self._resource_string}")
            return True
        except ImportError:
            log.error("PyVISA not installed. pip install pyvisa pyvisa-py")
            return False
        except Exception as e:
            log.error(f"VISA connect error: {e}")
            return False

    def disconnect(self):
        if self._instr:
            try:
                self._instr.close()
            except Exception:
                pass
        self._instr = None
        self._connected = False
        log.info("VISA disconnected")

    def write(self, cmd: str):
        if not self._check():
            return
        with self._rlock:
            try:
                self._instr.write(cmd)
                time.sleep(self.USB_SETTLE_MS / 1000.0)
            except Exception as e:
                log.error(f"VISA write error: {e}")

    def query(self, cmd: str) -> str | None:
        if not self._check():
            return None
        with self._rlock:
            try:
                time.sleep(self.USB_SETTLE_MS / 1000.0)
                resp = self._instr.query(cmd)
                return resp.strip()
            except Exception as e:
                log.error(f"VISA query error: {e}")
                return None

    def read(self) -> str | None:
        if not self._check():
            return None
        with self._rlock:
            try:
                return self._instr.read().strip()
            except Exception as e:
                log.error(f"VISA read error: {e}")
                return None

    def get_idn(self) -> str | None:
        return self.query("*IDN?")

    def write_with_err_check(self, cmd: str) -> bool:
        self.write(cmd)
        err = self.query("ERR?")
        if err and not err.startswith("+0"):
            log.warning(f"ERR? after '{cmd}': {err}")
            return False
        return True

    def _check(self) -> bool:
        if not self._connected or self._instr is None:
            log.warning("Not connected")
            return False
        return True
