import math
from PyQt5.QtWidgets import (QWidget, QVBoxLayout, QHBoxLayout, QLabel,
                             QPushButton, QGroupBox, QGridLayout)
from PyQt5.QtCore import Qt


class StatisticsTab(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._skip_A = False
        self._skip_B = False
        self._stat_names = ["Min", "Max", "Avg", "StdDev", "Pk-Pk", "Count"]
        self._stat_keys = ["min", "max", "avg", "stddev", "pkpk", "count"]
        layout = QVBoxLayout(self)
        layout.setSpacing(6)

        self._build_channel_box("A", layout)
        self._build_channel_box("B", layout)

        reset_row = QHBoxLayout()
        self._reset_a_btn = QPushButton("Reset Ch A")
        self._reset_a_btn.clicked.connect(lambda: self._skip("A"))
        self._reset_b_btn = QPushButton("Reset Ch B")
        self._reset_b_btn.clicked.connect(lambda: self._skip("B"))
        reset_row.addWidget(self._reset_a_btn)
        reset_row.addWidget(self._reset_b_btn)
        reset_row.addStretch()
        layout.addLayout(reset_row)
        layout.addStretch()

    def _build_channel_box(self, prefix, layout):
        g = QGroupBox(f"Channel {prefix}")
        grid = QGridLayout(g)
        grid.setSpacing(3)

        for i, (name, key) in enumerate(zip(self._stat_names, self._stat_keys)):
            lbl_name = QLabel(f"{name}:")
            lbl_val = QLabel("—")
            lbl_val.setProperty("statChannel", prefix.lower())
            setattr(self, f"_{prefix}_{key}", lbl_val)
            grid.addWidget(lbl_name, i, 0, Qt.AlignLeft)
            grid.addWidget(lbl_val, i, 1, Qt.AlignLeft)

        layout.addWidget(g)

    def update(self, prefix, vals):
        p = prefix.upper()
        skip = getattr(self, f"_skip_{p}", False)
        if skip:
            setattr(self, f"_skip_{p}", False)
            getattr(self, f"_{p}_count").setText("0")
            return

        safe = [v for v in vals if isinstance(v, (int, float)) and math.isfinite(v)]
        if not safe:
            return

        mn = min(safe)
        mx = max(safe)
        n = len(safe)
        avg = sum(safe) / n
        var = sum((x - avg) ** 2 for x in safe) / n
        std = math.sqrt(var)
        pp = mx - mn

        getattr(self, f"_{p}_min").setText(f"{mn:.6g}")
        getattr(self, f"_{p}_max").setText(f"{mx:.6g}")
        getattr(self, f"_{p}_avg").setText(f"{avg:.6g}")
        getattr(self, f"_{p}_stddev").setText(f"{std:.6g}")
        getattr(self, f"_{p}_pkpk").setText(f"{pp:.6g}")
        getattr(self, f"_{p}_count").setText(str(n))

    def _skip(self, prefix):
        p = prefix.upper()
        setattr(self, f"_skip_{p}", True)
        placeholders = {"_min": "—", "_max": "—", "_avg": "—",
                        "_stddev": "—", "_pkpk": "—", "_count": "0"}
        for suffix, val in placeholders.items():
            getattr(self, f"_{p}{suffix}").setText(val)
