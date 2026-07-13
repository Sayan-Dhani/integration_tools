import os
import sys
import logging
import pyvisa as visa
from PyQt5.QtWidgets import QApplication, QWidget, QMessageBox
from PyQt5.uic import loadUi
from PyQt5.QtCore import QTimer

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        # logging.FileHandler('power_supply.log')
    ],
)
logger = logging.getLogger(__name__)


class PowerSupplyController(QWidget):
    def __init__(self, parent=None):
        super(PowerSupplyController, self).__init__(parent)
        # Load the UI file
        ui_path = os.path.join(os.path.dirname(__file__), "power_supply.ui")
        loadUi(ui_path, self)

        # Initialize status dictionary
        self.status = {
            "voltage": 0.000,
            "current": 0.000,
            "power": "OFF",
            "set_voltage": 0.0,
            "set_current": 0.0,
        }
        self.connected = False

        # Set up timer early so closeEvent doesn't crash on connection failure
        self.timer = QTimer(self)

        # Connect to the power supply
        self.connect_to_power_supply()
        if not self.connected:
            self.timer.stop()
            return

        # Connect UI signals to slots
        self.setup_ui_connections()

        # Set up a timer to periodically update measurements
        self.timer.timeout.connect(self.update_measurements)
        self.timer.start(1000)  # Update every 1000ms (1 second)

        # Update UI with initial status
        self.update_ui()
        self.log_status("Initial Power Supply Status")
        self.setWindowTitle("Power Supply GUI")

    def log_status(self, message):
        """Log the current status with a descriptive message"""
        logger.info(f"{message}: {self.status}")

    def connect_to_power_supply(self):
        """Connect to the power supply device"""
        try:
            ip_address = "192.168.0.16"
            self.rm = visa.ResourceManager()
            self.power_supply = self.rm.open_resource(f"TCPIP0::{ip_address}::INSTR")
            self.connected = True
            print("Successfully connected to power supply")
        except Exception as e:
            logger.error(f"Failed connection: {e}")
            QMessageBox.critical(
                self, "Connection Error", f"Failed to connect to power supply: {e}"
            )

    def setup_ui_connections(self):
        """Connect UI signals to slots"""
        self.powsup_voltage_set_PB.clicked.connect(self.set_voltage)
        self.powsup_current_set_PB.clicked.connect(self.set_current)
        self.power_ON_PB.clicked.connect(self.power_on)
        self.power_OFF_PB.clicked.connect(self.power_off)

    def update_ui(self):
        """Update the UI elements with current status"""
        self.powsup_current_value_label.setText(str(self.status["current"]))
        self.powsup_voltage_value_label.setText(str(self.status["voltage"]))
        self.powsup_voltage_set_value_label.setText(str(self.status["set_voltage"]))
        self.powsup_current_set_value_label.setText(str(self.status["set_current"]))
        # Update power LED color
        if self.status["power"] == "ON":
            self.power_LED.setStyleSheet("background-color: green;")
        else:
            self.power_LED.setStyleSheet("background-color: red;")

    def update_measurements(self):
        """Periodically update the voltage and current measurements"""
        if not self.connected:
            return
        try:
            # Read actual voltage and current
            voltage = self.power_supply.query("MEAS:VOLT?\x00").strip()
            current = self.power_supply.query("MEAS:CURR?\x00").strip()

            # Update status
            self.status["voltage"] = voltage
            self.status["current"] = current

            # Update UI
            self.update_ui()
            self.log_status("Updated measurements")
        except Exception as e:
            logger.error(f"Error reading measurements: {e}")

    def set_voltage(self):
        """Set the voltage value from the line edit"""
        if not self.connected:
            return
        try:
            voltage = float(self.powsup_voltage_LE.text())
            self.power_supply.write(f"APPLY {voltage}\x00")
            self.status["set_voltage"] = voltage
            logger.info(f"Voltage set to {voltage}V")
            print(f"Voltage set to {voltage}V")
        except ValueError:
            logger.error("Invalid voltage input")
            QMessageBox.warning(
                self, "Input Error", "Please enter a valid number for voltage"
            )
        except Exception as e:
            logger.error(f"Failed to set voltage: {e}")
            QMessageBox.critical(self, "Error", f"Failed to set voltage: {e}")

    def set_current(self):
        """Set the current value from the line edit"""
        if not self.connected:
            return
        try:
            current = float(self.powsup_current_LE.text())
            self.power_supply.write(f"SOUR:CURR {current}\x00")
            self.status["set_current"] = current
            logger.info(f"Current set to {current}A")
            print(f"Current set to {current}A")
        except ValueError:
            logger.error("Invalid current input")
            QMessageBox.warning(
                self, "Input Error", "Please enter a valid number for current"
            )
        except Exception as e:
            logger.error(f"Failed to set current: {e}")
            QMessageBox.critical(self, "Error", f"Failed to set current: {e}")

    def power_on(self):
        """Turn the power supply ON"""
        if not self.connected:
            return
        try:
            self.power_supply.write("OUTP:STAT ON\x00")
            self.status["power"] = "ON"
            self.update_ui()
            self.log_status("Power Supply turned ON")
            print("Power Supply is ON")
        except Exception as e:
            print(f"Error turning power ON: {e}")
            logger.error(f"Failed to turn power ON: {e}")
            QMessageBox.critical(self, "Error", f"Failed to turn power ON: {e}")

    def power_off(self):
        """Turn the power supply OFF"""
        if not self.connected:
            return
        try:
            self.power_supply.write("OUTP:STAT OFF\x00")
            self.status["power"] = "OFF"
            self.update_ui()
            # Force a measurement update to show actual off values
            self.update_measurements()
            logger.info("Power Supply turned OFF")
            print("Power Supply is OFF")
        except Exception as e:
            logger.error(f"Failed to turn power OFF: {e}")
            QMessageBox.critical(self, "Error", f"Failed to turn power OFF: {e}")
            print(f"Error turning power OFF: {e}")

    def closeEvent(self, event):
        """Ensure proper cleanup when closing the application"""
        try:
            if hasattr(self, "timer"):
                self.timer.stop()
            if hasattr(self, "power_supply"):
                self.power_off()  # Turn off power supply when closing
                self.power_supply.close()
            if hasattr(self, "rm"):
                self.rm.close()
            logger.info("Power Supply Controller closed successfully")
        except Exception as e:
            print(f"Error during cleanup: {e}")
            logger.error(f"Error during cleanup: {e}")
        event.accept()


def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    controller = PowerSupplyController()
    window.setCentralWidget(controller)
    window.setWindowTitle("Power Supply")
    window.resize(controller.width(), controller.height())
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    from PyQt5.QtWidgets import QMainWindow

    main()
