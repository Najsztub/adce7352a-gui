"""
ADCMT 7352A Digital Multimeter Controller — Entry Point

Usage:
    python main.py                   # Mock backend (default)
    python main.py --real            # Real VISA hardware
    python main.py --mock            # Explicit mock
"""

import sys
import os
import argparse

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt


def main():
    parser = argparse.ArgumentParser(description="ADCMT 7352A Controller")
    parser.add_argument("--mock", action="store_true", default=False,
                        help="Use mock backend (no hardware required)")
    parser.add_argument("--real", action="store_true", default=False,
                        help="Use real VISA hardware")
    args = parser.parse_args()

    use_mock = args.mock or not args.real

    app = QApplication(sys.argv)
    app.setApplicationName("ADCMT 7352A Controller")
    app.setOrganizationName("Elektro")
    app.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    stylesheet_path = os.path.join(os.path.dirname(__file__), "gui", "resources", "styles.qss")
    if os.path.exists(stylesheet_path):
        with open(stylesheet_path, "r") as f:
            app.setStyleSheet(f.read())

    # Late import so Qt is initialized first
    from gui.ui.main_window import MainWindow
    from gui.instruments.adcmt7352a_adc import ADCMT7352A

    resource = None if use_mock else "USB0::4916::520::999991006::0::INSTR"
    instrument = ADCMT7352A(use_mock=use_mock, resource_string=resource)

    win = MainWindow(app)
    win.setup_instrument(instrument)

    if use_mock:
        win.setWindowTitle(win.windowTitle() + "  [MOCK MODE]")

    win.show()

    if resource:
        instrument.connect()
        win.update_status(True)
        win._query_idn()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
