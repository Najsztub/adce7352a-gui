"""
Settings persistence via QSettings

Saves/restores window geometry, VISA resource, panel state, etc.
"""

from PyQt5.QtCore import QSettings

ORGANIZATION = "Elektro"
APPLICATION = "ADCMT7352A"


class AppConfig:
    def __init__(self):
        self._s = QSettings(ORGANIZATION, APPLICATION)

    def save_window_geometry(self, geometry):
        self._s.setValue("window/geometry", geometry)

    def restore_window_geometry(self):
        return self._s.value("window/geometry")

    def save_window_state(self, state):
        self._s.setValue("window/state", state)

    def restore_window_state(self):
        return self._s.value("window/state")

    def save_resource_string(self, resource):
        self._s.setValue("connection/resource", resource)

    def restore_resource_string(self):
        return self._s.value("connection/resource", "USB0::4916::520::999991006::0::INSTR")

    def save_use_mock(self, use_mock):
        self._s.setValue("connection/use_mock", use_mock)

    def restore_use_mock(self):
        return self._s.value("connection/use_mock", False, type=bool)

    def save_read_interval(self, ms):
        self._s.setValue("acquisition/read_interval", ms)

    def restore_read_interval(self):
        return self._s.value("acquisition/read_interval", 500, type=int)

    def save_buffer_size(self, n):
        self._s.setValue("plot/buffer_size", n)

    def restore_buffer_size(self):
        return self._s.value("plot/buffer_size", 200, type=int)

    def save_last_function_a(self, fkey):
        self._s.setValue("instrument/function_a", fkey)

    def restore_last_function_a(self):
        return self._s.value("instrument/function_a", "F1")

    def save_last_function_b(self, fkey):
        self._s.setValue("instrument/function_b", fkey)

    def restore_last_function_b(self):
        return self._s.value("instrument/function_b", "F12")

    def save_ch_a_enabled(self, enabled):
        self._s.setValue("channel/a_enabled", enabled)

    def restore_ch_a_enabled(self):
        return self._s.value("channel/a_enabled", True, type=bool)

    def save_ch_b_enabled(self, enabled):
        self._s.setValue("channel/b_enabled", enabled)

    def restore_ch_b_enabled(self):
        return self._s.value("channel/b_enabled", False, type=bool)

    def save_splitter_sizes(self, sizes):
        self._s.setValue("layout/splitter_sizes", sizes)

    def restore_splitter_sizes(self):
        return self._s.value("layout/splitter_sizes")

    def save_console_history(self, history):
        self._s.setValue("console/history", history)

    def restore_console_history(self):
        return self._s.value("console/history", [])

    def save_dark_theme(self, is_dark):
        self._s.setValue("theme/dark", is_dark)

    def restore_dark_theme(self):
        return self._s.value("theme/dark", True, type=bool)

    def sync(self):
        self._s.sync()
