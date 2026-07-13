from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import QTimer, QThread, pyqtSignal
import os
import time
from datetime import datetime
from .command_worker import CommandWorker
import logging
import requests
from .module_tests import TEST_SPECS_MAP

logger = logging.getLogger(__name__)


class ModulesListTab(QtWidgets.QMainWindow):
    def __init__(self):
        super(ModulesListTab, self).__init__()
        ui_path = os.path.join(os.path.dirname(__file__), "modules_list.ui")
        uic.loadUi(ui_path, self)
        self.mounted_modules = {}
        self.caen = None  # Placeholder for CAEN object
        self.light_on = True  # Conservative approach, assume light is on
        self.marta_safe = False  # Conservative approach, assume Marta is not safe
        self.marta_log_msg = ""
        self.current_worker = None  # Placeholder for the current worker
        self.test_queue = []  # Queue for test commands
        self._show_test_results = True  # Control test result popups
        self.ring_id = ""  # Placeholder for ring ID
        self.thermal_camera = None  # Placeholder for thermal camera system
        self.module_temperature_tab = None  # Placeholder for module temperature tab
        self.test_command = None  # Current test command
        self.test_spec = None  # Current test specification\
        self.current_session = None
        self.db_url = None

        # Set column widths for better button visibility in Actions
        self.moduleList.setColumnWidth(0, 60)  # Position
        self.moduleList.setColumnWidth(1, 150)  # Module Name
        self.moduleList.setColumnWidth(2, 150)  # Module Info
        self.moduleList.setColumnWidth(3, 140)  # Channels
        self.moduleList.setColumnWidth(4, 60)  # LV V
        self.moduleList.setColumnWidth(5, 60)  # LV I
        self.moduleList.setColumnWidth(6, 60)  # HV
        self.moduleList.setColumnWidth(7, 60)  # HV I (μA)
        self.moduleList.setColumnWidth(8, 60)  # T (C)
        self.moduleList.setColumnWidth(9, 60)  # Testing
        self.moduleList.setColumnWidth(10, 430)  # Actions

        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_module_list)
        self.update_interval = 1000  # Update every second

        # Connect existing buttons
        self.select_all_button_2.clicked.connect(self.select_all_modules)
        self.turn_lv_off_all_button.clicked.connect(
            self.turn_off_lv_for_selected_modules
        )
        self.turn_lv_on_all_button.clicked.connect(self.turn_on_lv_for_selected_modules)
        self.turn_hv_off_all_button.clicked.connect(
            self.turn_off_hv_for_selected_modules
        )
        self.turn_hv_on_all_button.clicked.connect(self.turn_on_hv_for_selected_modules)
        self.refresh_button.clicked.connect(self.update_module_list)

        # Connect test control buttons
        self.start_test_all_button.clicked.connect(self.run_test_for_selected_modules)
        self.cancel_test_all_button.clicked.connect(self.stop_all_tests)
        self.start_t_monitor_button.clicked.connect(
            lambda: self.start_temperature_monitoring()  # self.module_temperature_tab)
        )
        self.stop_t_monitor_button.clicked.connect(
            lambda: self.stop_temperature_monitoring()  # self.module_temperature_tab)
        )

        # Tests Combobox
        self.set_test_command()  # Initialize test command
        self.select_test_combobox.clear()
        self.select_test_combobox.addItems(list(TEST_SPECS_MAP.keys()))
        self.select_test_combobox.currentIndexChanged.connect(self.set_test_command)

        # Message box setup (keep for HV safety warnings)
        self.message_box = QtWidgets.QMessageBox()
        self.message_box.setWindowTitle("Safety Warning")
        self.message_box.setIcon(QtWidgets.QMessageBox.Warning)
        self.message_box.setStandardButtons(QtWidgets.QMessageBox.Ok)

        # Create a message box for displaying the camera status
        self.camera_status_message_box = QtWidgets.QMessageBox()

    def get_session(self):
        if self.current_session is None:
            return self._new_session()
        if (
            self.current_session_operator != self.operator_le.text()
            or self.current_session_comments != self.comments_le.text()
        ):
            return self._new_session()
        return self.current_session

    def _make_api_request(self, endpoint, method, data=None):
        """Make API request and return result"""
        url = f"{self.db_url.rstrip('/')}/{endpoint.lstrip('/')}"
        try:
            # Simulate API response for demonstration purposes
            # result = {"sessionName": "SIMULATED_SESSION_12345"}
            response = requests.request(
                method=method.lower(), url=url, json=data if data else None
            )
            if response.status_code != 200 and response.status_code != 201:
                logger.error(f"API Error ({response.status_code}): {response.text}")
                return False, None
            result = response.json()
            return True, result
        except requests.RequestException as e:
            logger.error(f"API Error: {str(e)}")
            return False, str(e)

    def _new_session(self):
        session = {
            "operator": self.operator_le.text(),
            "description": f"INTEGRATION: {self.comments_le.text()}",
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "modulesList": list(self.mounted_modules.keys()),
            "ringId": self.ring_id,
        }
        # create new session in DB
        _, result = self._make_api_request("sessions", "POST", session)
        self.current_session = result["sessionName"]
        self.current_session_operator = self.operator_le.text()
        self.current_session_comments = self.comments_le.text()
        return self.current_session

    # Modified power control methods to use queue
    def turn_on_lv_for_selected_modules(self):
        """Turn on LV for all selected modules."""
        if not self.marta_safe:
            self.message_box.setText(
                f"MARTA not safe, cannot turn on LV:\n{self.marta_log_msg}"
            )
            self.message_box.exec_()
            return

        for item in self.moduleList.selectedItems():
            module_name = item.text(1)
            if module_name in self.mounted_modules:
                module_info = self.mounted_modules[module_name]
                lv_channel = module_info.get("LV")
                if lv_channel:
                    self.caen_lv_on_wrap(lv_channel)
            time.sleep(0.1)

    def turn_off_lv_for_selected_modules(self):
        """Turn off LV for all selected modules."""

        for item in self.moduleList.selectedItems():
            module_name = item.text(1)
            if module_name in self.mounted_modules:
                module_info = self.mounted_modules[module_name]
                lv_channel = module_info.get("LV")
                if lv_channel:
                    self.caen_lv_off(lv_channel)
            time.sleep(0.1)

    def turn_on_hv_for_selected_modules(self):
        """Turn on HV for all selected modules."""
        if self.light_on:
            self.message_box.setText("Light is on, cannot turn on HV.")
            self.message_box.exec_()
            return

        for item in self.moduleList.selectedItems():
            module_name = item.text(1)
            if module_name in self.mounted_modules:
                module_info = self.mounted_modules[module_name]
                hv_channel = module_info.get("HV")
                if hv_channel:
                    self.caen_hv_on_wrap(hv_channel)
            time.sleep(0.1)

    def turn_off_hv_for_selected_modules(self):
        """Turn off HV for all selected modules."""
        for item in self.moduleList.selectedItems():
            module_name = item.text(1)
            if module_name in self.mounted_modules:
                module_info = self.mounted_modules[module_name]
                hv_channel = module_info.get("HV")
                if hv_channel:
                    self.caen_hv_off(hv_channel)
            time.sleep(0.1)

    def caen_hv_on_wrap(self, channel):
        """Wrapper for HV on with safety check."""
        if self.light_on:
            self.message_box.setText("Light is on, cannot turn on HV.")
            self.message_box.exec_()
            return
        else:
            self.caen.on(channel)

    def caen_lv_on_wrap(self, channel):
        """Wrapper for LV on with safety check."""
        if not self.marta_safe:
            self.message_box.setText(
                f"MARTA not safe, cannot turn on LV:\n{self.marta_log_msg}"
            )
            self.message_box.exec_()
            return
        else:
            self.caen.on(channel)

    def caen_lv_off(self, channel):
        """Queue LV off command."""
        self.caen.off(channel)

    def caen_hv_off(self, channel):
        """Queue HV off command."""
        self.caen.off(channel)

    def populate_from_config(
        self, caen, modules, number_of_modules, thermal_camera_system=None
    ):
        """Populate the moduleList QTreeWidget with module data from a config list."""
        if number_of_modules < 1:
            return
        self.moduleList.clear()

        # Store thermal camera system for later use
        self.thermal_camera_system = thermal_camera_system

        # Create all items first
        values = {
            str(i): [str(i), "", "", "", "", "", "", "", "", ""]
            for i in range(1, number_of_modules + 1)
        }

        # Fill the moduleList with the values first
        for i in values:
            item = QtWidgets.QTreeWidgetItem(values[i])
            self.moduleList.addTopLevelItem(item)

        self.caen = caen
        self.mounted_modules = modules.copy()
        self.update_module_list()

        self.MODULE_ANGULAR_WIDTH = 360 / (number_of_modules / 2)

        # Now update items with module info and add buttons
        for module_name, module_info in modules.items():
            module_position = str(module_info.get("mounted_on", "-").split(";")[1])
            if module_position == "-":
                module_angular_position = -1
                module_side = "Undefined"
            else:
                # Calculate angular position based on module position
                module_angular_position = (int(module_position) - 1) % (
                    number_of_modules / 2
                ) * self.MODULE_ANGULAR_WIDTH + (self.MODULE_ANGULAR_WIDTH / 2) * (
                    1 if int(module_position) <= (number_of_modules / 2) else 0
                )
                module_side = (
                    "13" if int(module_position) <= (number_of_modules / 2) else "24"
                )

            self.mounted_modules[module_name][
                "angular_position"
            ] = module_angular_position
            self.mounted_modules[module_name]["side"] = module_side
            item_index = int(module_position) - 1
            fc7 = module_info.get("FC7", "")
            speed = module_info.get("speed", "Unknown")
            hv_channel = module_info.get("HV", "")
            lv_channel = module_info.get("LV", "")

            if item_index < self.moduleList.topLevelItemCount():
                item = self.moduleList.topLevelItem(item_index)
                item.setText(1, module_name)
                item.setText(2, str(f"{speed};{fc7}"))
                item.setText(3, str(f"{hv_channel};{lv_channel}"))
                item.setText(4, str(module_info.get("LV_value", "")))
                item.setText(5, str(module_info.get("LV_I_value", "")))
                item.setText(6, str(module_info.get("HV_value", "")))
                item.setText(7, str(module_info.get("HV_I_value", "")))
                item.setText(8, str(module_info.get("temperature", "")))
                item.setText(9, module_info.get("testing", ""))

                # Create action buttons
                actions_widget = QtWidgets.QWidget()
                layout = QtWidgets.QHBoxLayout(actions_widget)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(2)

                # Use queued commands for buttons
                btn_lv_on = QtWidgets.QPushButton("LV On")
                btn_lv_on.clicked.connect(
                    lambda checked, ch=module_info.get("LV"): self.caen_lv_on_wrap(ch)
                )

                btn_lv_off = QtWidgets.QPushButton("LV Off")
                btn_lv_off.clicked.connect(
                    lambda checked, ch=module_info.get("LV"): self.caen_lv_off(ch)
                )

                btn_hv_on = QtWidgets.QPushButton("HV On")
                btn_hv_on.clicked.connect(
                    lambda checked, ch=module_info.get("HV"): self.caen_hv_on_wrap(ch)
                )

                btn_hv_off = QtWidgets.QPushButton("HV Off")
                btn_hv_off.clicked.connect(
                    lambda checked, ch=module_info.get("HV"): self.caen_hv_off(ch)
                )

                # Connect test buttons to test functions
                btn_start_test = QtWidgets.QPushButton("Test On")
                btn_start_test.clicked.connect(
                    lambda checked, mod=module_name: self.start_single_module_test(mod)
                )

                btn_stop_test = QtWidgets.QPushButton("Test Off")
                btn_stop_test.clicked.connect(
                    lambda checked, mod=module_name: self.stop_single_module_test(mod)
                )

                # Connect camera button to focus function
                btn_focus_camera = QtWidgets.QPushButton("Camera")
                btn_focus_camera.clicked.connect(
                    lambda checked, mod=module_name: self.focus_camera_on_module(
                        mod, self.thermal_camera_system
                    )
                )

                for btn in [
                    btn_lv_on,
                    btn_lv_off,
                    btn_hv_on,
                    btn_hv_off,
                    btn_start_test,
                    btn_stop_test,
                    btn_focus_camera,
                ]:
                    btn.setFixedWidth(60)
                    layout.addWidget(btn)

                self.moduleList.setItemWidget(item, 10, actions_widget)

        self.update_timer.start(self.update_interval)

    def set_test_command(self):
        """Set the test command from the combobox selection."""
        if not self.test_command:
            self.test_command = list(TEST_SPECS_MAP.keys())[0]
            self.test_spec
        else:
            selected_test = self.select_test_combobox.currentText()
            self.test_command = selected_test
        self.test_spec = TEST_SPECS_MAP.get(self.test_command)
        print(f"Test command set to: {self.test_command}")

    def run_test_for_selected_modules(self):
        """Run the test command for all selected modules."""
        # check if operator field is  non empty
        if not self.operator_le.text().strip():
            self._show_message("Please enter operator name before starting a test.")
            return
        selected_modules = [item.text(1) for item in self.moduleList.selectedItems()]
        if not selected_modules:
            self._show_message("No modules selected for testing.")
            return

        # Add all selected modules to the test queue
        added_modules = []
        for module_name in selected_modules:
            if self._add_module_to_queue(module_name):
                added_modules.append(module_name)

        if added_modules:
            logger.debug(
                f"Added {len(added_modules)} modules to test queue: {added_modules}"
            )
            self.process_test_queue()

    def process_test_queue(self):
        """Process the next test in the queue if no test is currently running."""
        if self.current_worker is not None:
            logger.debug("Test already running, waiting for completion...")
            return

        if not self.test_queue:
            logger.debug("No tests in queue.")
            return

        # Get the next module from the queue
        module_name = self.test_queue.pop(0)
        logger.debug(
            f"Starting test for module: {module_name} ({len(self.test_queue)} remaining in queue)"
        )
        self._start_test_for_module(module_name)

    def _start_test_for_module(self, module_name):
        """Start the actual test execution for a module."""
        if self.current_worker is not None:
            logger.debug(
                f"Cannot start test for {module_name}: another test is already running"
            )
            return

        # Update testing status
        self._update_module_testing_status(module_name, "Running")

        # Create and configure worker
        self.current_worker = CommandWorker(self.test_spec.command)
        self.current_worker.placeholders = {
            "module_id": module_name,
            "ring_id": self.ring_id,
            "fiber_endpoint": self.mounted_modules[module_name].get("FC7", "N/A"),
            "session": self.get_session(),
        }

        # Connect signals and start
        self.current_worker.finished.connect(self.test_finished)
        self.current_worker.start()
        logger.debug(f"Test started for module: {module_name}")

    def test_finished(self, success, stdout, stderr):
        """Handle test completion and start next test in queue."""
        module_name = self.current_worker.placeholders.get("module_id", "Unknown")

        # Update status based on result
        status = "Passed" if success else "Failed"
        self._update_module_testing_status(module_name, status)

        # Log results
        if success:
            logger.debug(f"Test completed successfully for module: {module_name}")
            logger.debug(f"Output: {stdout}")
            self.test_spec.process_result(stdout)
        else:
            logger.debug(f"Test failed for module: {module_name}")
            logger.debug(f"Error: {stderr}")

        # Show result message if enabled
        if self._show_test_results:
            self._show_test_result_message(module_name, success, stdout, stderr)

        # Clean up and process next test
        self._cleanup_current_worker()
        self.process_test_queue()

    def _show_test_result_message(self, module_name, success, stdout, stderr):
        """Show test result message box."""
        self.message_box.setText(
            f"Test finished for module: {module_name}\n"
            f"Status: {'SUCCESS' if success else 'FAILED'}\n"
            f"Output: {stdout[:200]}{'...' if len(stdout) > 200 else ''}\n"
            f"Error: {stderr[:200]}{'...' if len(stderr) > 200 else ''}"
        )
        # self.message_box.exec_()

    def stop_all_tests(self):
        """Stop the current test and clear the test queue."""
        if self.current_worker:
            logger.debug("Stopping current test...")
            self.current_worker.terminate_process()
            self._cleanup_current_worker()

        if self.test_queue:
            logger.debug(f"Clearing {len(self.test_queue)} tests from queue")
            # Update status for queued modules
            for module_name in self.test_queue:
                self._update_module_testing_status(module_name, "Cancelled")
            self.test_queue.clear()

        logger.debug("All tests stopped.")

    def select_all_modules(self):
        """Select all modules in the moduleList QTreeWidget."""
        for i in range(self.moduleList.topLevelItemCount()):
            item = self.moduleList.topLevelItem(i)
            item.setSelected(True)
        logger.debug("All modules selected.")

    def start_single_module_test(self, module_name):
        """Start test for a single module via button click."""
        # check if operator field is  non empty
        #        if not self.operator_field.text().strip():
        #            self._show_message("Please enter operator name before starting a test.")

        if self._add_module_to_queue(module_name):
            logger.debug(f"Added module {module_name} to test queue via button click")
            self.process_test_queue()

    def stop_single_module_test(self, module_name):
        """Stop test for a single module via button click."""
        if self._remove_module_from_testing(module_name):
            return

    def _add_module_to_queue(self, module_name):
        """Add a module to the test queue with validation. Returns True if added successfully."""
        if module_name not in self.mounted_modules:
            return False

        # Check if module is already in queue
        if module_name in self.test_queue:
            return False

        # Check if module is currently being tested
        if self._is_module_currently_testing(module_name):
            return False

        # Add to queue and update status
        self.test_queue.append(module_name)
        self._update_module_testing_status(module_name, "Queued")
        return True

    def _remove_module_from_testing(self, module_name):
        """Remove a module from current testing or queue. Returns True if removed successfully."""
        # Check if module is currently being tested
        if self._is_module_currently_testing(module_name):
            logger.debug(f"Stopping current test for module: {module_name}")
            self.current_worker.terminate_process()
            self._cleanup_current_worker()
            self._update_module_testing_status(module_name, "Stopped")
            self.process_test_queue()
            return True

        # Check if module is in the queue
        if module_name in self.test_queue:
            self.test_queue.remove(module_name)
            logger.debug(f"Removed module {module_name} from test queue")
            self._update_module_testing_status(module_name, "Removed")
            return True

        return False

    def _is_module_currently_testing(self, module_name):
        """Check if a module is currently being tested."""
        return (
            self.current_worker
            and self.current_worker.placeholders.get("module_id") == module_name
        )

    def _update_module_testing_status(self, module_name, status):
        """Update the testing status for a module."""
        if module_name in self.mounted_modules:
            self.mounted_modules[module_name]["testing"] = status

    def _show_message(self, message):
        """Show a message box with the given message."""
        logger.debug(message)
        self.message_box.setText(message)
        self.message_box.exec_()

    def _cleanup_current_worker(self):
        """Clean up the current worker and reset state."""
        if self.current_worker:
            try:
                self.current_worker.finished.disconnect(self.test_finished)
            except TypeError:
                pass  # Signal was already disconnected
            self.current_worker = None

    def update_module_list(self):
        """Update the moduleList QTreeWidget with the latest module information."""
        for i in range(self.moduleList.topLevelItemCount()):
            item = self.moduleList.topLevelItem(i)
            module_name = item.text(1)
            if module_name in self.mounted_modules:
                self.update_module_info(module_name)
                module_info = self.mounted_modules[module_name]

                # Update all data columns
                item.setText(4, str(module_info.get("LV_value", "")))
                item.setText(5, str(module_info.get("LV_I_value", "")))
                item.setText(6, str(module_info.get("HV_value", "")))
                item.setText(7, str(module_info.get("HV_I_value", "")))
                item.setText(8, str(module_info.get("temperature", "")))

                # Update testing status with visual indicators
                self._update_testing_status_display(
                    item, module_info.get("testing", "")
                )
            else:
                # Clear testing status for empty slots
                item.setText(9, "")
        logger.debug("Module list updated.")

    def _update_testing_status_display(self, item, testing_status):
        """Update the testing status display with visual indicators."""
        status_map = {
            "Running": "Running",
            "Queued": "Queued",
            "Passed": "Passed",
            "Failed": "Failed",
            "Stopped": "Stopped",
            "Cancelled": "Cancelled",
            "Removed": "Removed",
        }
        display_text = status_map.get(testing_status, testing_status)
        item.setText(9, display_text)

    def update_module_info(self, module_name):
        """Update the module information in the moduleList QTreeWidget."""
        if module_name in self.mounted_modules:
            lv_channel = self.mounted_modules[module_name].get("LV")
            hv_channel = self.mounted_modules[module_name].get("HV")
            # Get the v and i values from the CAEN object
            response = self.caen.last_response
            if response:
                hv_v = f"caen_{hv_channel}_Voltage"
                hv_i = f"caen_{hv_channel}_Current"
                hv_on = f"caen_{hv_channel}_IsOn"
                lv_v = f"caen_{lv_channel}_Voltage"
                lv_i = f"caen_{lv_channel}_Current"
                lv_on = f"caen_{lv_channel}_IsOn"

                self.mounted_modules[module_name]["HV_value"] = response.get(hv_v, 0)
                self.mounted_modules[module_name]["HV_I_value"] = response.get(hv_i, 0)
                self.mounted_modules[module_name]["HV_on"] = response.get(hv_on, False)
                self.mounted_modules[module_name]["LV_value"] = response.get(lv_v, 0)
                self.mounted_modules[module_name]["LV_I_value"] = response.get(lv_i, 0)
                self.mounted_modules[module_name]["LV_on"] = response.get(lv_on, False)
            else:
                logger.debug(f"No response from CAEN for module: {module_name}")
                self.mounted_modules[module_name]["HV_value"] = 0
                self.mounted_modules[module_name]["HV_I_value"] = 0
                self.mounted_modules[module_name]["LV_value"] = 0
                self.mounted_modules[module_name]["LV_I_value"] = 0
        else:
            logger.debug(f"Module {module_name} not found in mounted modules.")
            return

    def get_used_channels(self):
        """Get a list of active LV and HV channels."""
        active_channels = {"LV": [], "HV": []}
        for module_name, module_info in self.mounted_modules.items():
            if module_info.get("LV_on", False):
                active_channels["LV"].append(module_info.get("LV"))
            if module_info.get("HV_on", False):
                active_channels["HV"].append(module_info.get("HV"))
        return active_channels

    def set_show_test_results(self, show=True):
        """Control whether test result popups are shown."""
        self._show_test_results = show

    def get_test_status(self):
        """Get current test status information."""
        return {
            "is_testing": self.current_worker is not None,
            "queue_length": len(self.test_queue),
            "current_module": (
                self.current_worker.placeholders.get("module_id")
                if self.current_worker
                else None
            ),
            "queued_modules": self.test_queue.copy(),
        }

    def focus_camera_on_module(self, module_name, thermal_camera_system):
        """Focus the appropriate camera on the specified module based on angular position and side."""
        if module_name not in self.mounted_modules:
            logger.debug(f"Module {module_name} not found in mounted modules.")
            return

        module_info = self.mounted_modules[module_name]
        angular_position = module_info.get("angular_position", -1)
        side = module_info.get("side", "Undefined")

        if angular_position == -1 or side == "Undefined":
            logger.debug(
                f"Invalid position data for module {module_name}: position={angular_position}, side={side}"
            )
            return

        # Choose camera pair based on side
        camera_pair = self._get_camera_pair_for_side(side)
        if not camera_pair:
            logger.debug(f"No camera pair available for side {side}")
            return

        # Choose specific camera based on angular position
        selected_camera = self._select_camera_for_position(
            camera_pair, angular_position
        )

        logger.debug(
            f"Focusing camera {selected_camera} on module {module_name} at angular position {angular_position}° (side {side})"
        )

        # Move the camera to the angular position using the thermal camera system
        if thermal_camera_system:
            # self.camera_status_message_box.setText(
            #     f"Moving camera {selected_camera} to {angular_position}° for module {module_name} (side {side})"
            # )
            # self.camera_status_message_box.exec_()
            self._move_camera_to_angular_position(
                thermal_camera_system, selected_camera, angular_position
            )
        else:
            logger.debug(f"No thermal camera system available")

    def _get_camera_pair_for_side(self, side):
        """Get the camera pair based on the module side."""
        # Camera pairs mapping - adjust based on your actual camera setup
        camera_pairs = {
            "13": {"camera1": 1, "camera3": 3},  # Side 12 uses cameras 1 and 2
            "24": {"camera2": 2, "camera4": 4},  # Side 34 uses cameras 3 and 4
        }

        return camera_pairs.get(side, None)

    def __fill_message_box(self, camera_pair, angular_position):
        """Fill the message box with camera selection options based on angular position."""
        self.camera_status_message_box = QtWidgets.QMessageBox()
        self.camera_status_message_box.setWindowTitle("Camera Selection")
        self.camera_status_message_box.setIcon(QtWidgets.QMessageBox.Information)
        self.camera_status_message_box.setText(
            f"Select camera for angular position {angular_position}°:"
        )
        for camera_name in camera_pair:
            shown_camera_name = camera_name.replace("camera", "Camera ")
            self.camera_status_message_box.addButton(
                shown_camera_name, QtWidgets.QMessageBox.AcceptRole
            )
        self.camera_status_message_box.setStandardButtons(QtWidgets.QMessageBox.Cancel)
        self.camera_status_message_box.setDefaultButton(QtWidgets.QMessageBox.Cancel)
        self.camera_status_message_box.setEscapeButton(QtWidgets.QMessageBox.Cancel)

    def _select_camera_for_position(self, camera_pair, angular_position):
        """Select the appropriate camera based on angular position within the pair."""

        # Normalize angular position to 0-360 range
        normalized_angle = angular_position % 360

        # Get camera names from the pair
        camera_names = list(camera_pair.keys())

        # # Simple logic: use first camera for 0-180°, second for 180-360°
        # # Adjust this logic based on your actual camera positioning
        # if normalized_angle <= 180:
        #     selected_camera = camera_names[0]
        # else:
        #     selected_camera = camera_names[1]

        # Open a dialog to select camera based on angular position
        self.__fill_message_box(camera_pair, normalized_angle)
        result = self.camera_status_message_box.exec_()
        if result == QtWidgets.QMessageBox.Cancel:
            logger.debug("Camera selection cancelled by user.")
            return None
        selected_camera = self.camera_status_message_box.clickedButton().text()
        selected_camera = selected_camera.replace("Camera ", "camera")
        return camera_pair[selected_camera]

    def _move_camera_to_angular_position(
        self, thermal_camera, camera_id, angular_position
    ):
        """Move the specified camera to the target angular position."""
        try:
            # Use the thermal camera GUI's move_camera method
            success = thermal_camera.move_camera(camera_id, angular_position)
            if success:
                logger.debug(
                    f"Camera {camera_id} moved successfully to {angular_position}°"
                )
            else:
                logger.debug(
                    f"Failed to move camera {camera_id} to {angular_position}°"
                )

        except Exception as e:
            logger.debug(f"Error moving camera {camera_id}: {str(e)}")

    def get_camera_status_for_module(self, module_name):
        """Get camera information for a specific module."""
        if module_name not in self.mounted_modules:
            return None

        module_info = self.mounted_modules[module_name]
        angular_position = module_info.get("angular_position", -1)
        side = module_info.get("side", "Undefined")

        if angular_position == -1 or side == "Undefined":
            return None

        camera_pair = self._get_camera_pair_for_side(side)
        if not camera_pair:
            return None

        selected_camera = self._select_camera_for_position(
            camera_pair, angular_position
        )

        return {
            "module_name": module_name,
            "angular_position": angular_position,
            "side": side,
            "camera_pair": camera_pair,
            "selected_camera": selected_camera,
        }

    def start_temperature_monitoring(self):
        command = "runCalibration -f PS_Module_fc7ot6_og345.xml -c monitoronly -b"
        self.monitoring_worker = CommandWorker(command)
        self.monitoring_worker.start()

    def stop_temperature_monitoring(self):
        if hasattr(self, "monitoring_worker") and self.monitoring_worker:
            self.monitoring_worker.terminate_process()
            self.monitoring_worker = None
