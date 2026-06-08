"""
Collapsible QGroupBox widget with toggle indicator
"""

from PyQt5.QtWidgets import QGroupBox, QVBoxLayout


class CollapsibleGroup(QGroupBox):
    def __init__(self, title="", parent=None, collapsed=False):
        super().__init__(title, parent)
        self.setCheckable(True)
        self.setChecked(not collapsed)
        self.toggled.connect(self._on_toggled)
        self._orig_title = title
        self._update_title()

    def _update_title(self):
        state = "▾" if self.isChecked() else "▸"
        self.setTitle(f"{self._orig_title}  {state}")

    def _on_toggled(self, checked):
        self._update_title()
        for w in self.findChildren(QGroupBox):
            pass

    def set_title(self, title):
        self._orig_title = title
        self._update_title()
