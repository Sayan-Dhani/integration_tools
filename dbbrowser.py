#!/usr/bin/env python3
import sys
from PyQt5.QtWidgets import QApplication, QMainWindow
from db.module_db import ModuleDB


class DBMainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Module Database")

        # Create and set the module DB widget as central widget
        self.module_db = ModuleDB()
        self.setCentralWidget(self.module_db)

        # Set initial size
        self.resize(1000, 800)


def main():
    app = QApplication(sys.argv)
    window = DBMainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
