#!/usr/bin/env python3
import threading
import ui.integration_gui as integration_gui
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QLineEdit,
    QLabel,
    QFormLayout,
    QTreeWidgetItem,
    QTreeWidget,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QHBoxLayout,
    QSpacerItem,
    QSizePolicy,
    QComboBox,
)
from PyQt5.QtGui import QPen
from PyQt5.QtCore import Qt, QTimer, pyqtSignal, QObject, QThread, QSize, QUrl
from PyQt5.QtWidgets import QGraphicsScene, QGraphicsView
from PyQt5.QtWebEngineWidgets import QWebEngineView
from math import *
import requests
import subprocess
import yaml
import os
import paho.mqtt.client as mqtt
import struct
import numpy as np
from caen.caenGUI import CAENControl
import json

# Set matplotlib backend before importing pyplot
import matplotlib

matplotlib.use("Qt5Agg")
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from mpl_toolkits.axes_grid1 import make_axes_locatable
import struct
import numpy as np

import webbrowser
import os.path
import re
from datetime import datetime
from db.module_db import ModuleDB
from db.utils import get_module_fuse_id


# Add this class near the top of the file
class LogEmitter(QObject):
    """Helper class to emit log messages from any thread"""

    log_message = pyqtSignal(str)


# Add new CommandWorker class
class CommandWorker(QThread):
    finished = pyqtSignal(bool, str, str)  # success, stdout, stderr

    def __init__(self, command):
        super().__init__()
        self.command = command

    def run(self):
        try:
            expanded_command = self.command
            # open spinning wheel dialog
            result = subprocess.run(
                expanded_command, shell=True, capture_output=True, text=True
            )
            self.finished.emit(result.returncode == 0, result.stdout, result.stderr)
            # create a waiting dialog
            # Create a waiting dialog

        except Exception as e:
            self.finished.emit(False, "", str(e))


class MainApp(integration_gui.Ui_MainWindow):
    def __init__(self, window):
        # First call setupUi to create all UI elements from the .ui file
        self.setupUi(window)

        # Add Ph2ACF topic to API settings layout programmatically
        # Need to do this before load_settings
        self.ph2acfTopicLabel = QLabel("Ph2ACF Topic:")
        self.ph2acfTopicLE = QLineEdit()
        self.ph2acfTopicLE.setObjectName("ph2acfTopicLE")
        self.formLayout_2.addRow(self.ph2acfTopicLabel, self.ph2acfTopicLE)

        # Load settings before setting up connections
        self.load_settings()

        # Connect settings change
        self.ph2acfTopicLE.textChanged.connect(self.save_settings)

        # Create ModuleDB instance
        self.module_db = ModuleDB()

        # Replace inventory and details tabs with ModuleDB tabs

        self.tabWidget.insertTab(1, self.module_db.ui.tab_2, "Module Inventory")
        self.tabWidget.insertTab(
            2, self.module_db.ui.moduleDetailsTab, "Module Details"
        )

        # Connect module selection signal
        self.module_db.module_selected.connect(self.on_module_selected)
        self.module_db.ui.viewDetailsPB.clicked.connect(self.view_module_details)

        # Set stretch factors for the main grid layout to make left side expand more
        #        grid_layout = self.tab.layout()
        #        grid_layout.setColumnStretch(0, 2)  # Left column gets 2 parts
        #        grid_layout.setColumnStretch(1, 1)  # Right column gets 1 part

        # Set up square aspect ratio for graphics view
        self.graphicsView.setMinimumSize(300, 300)
        self.graphicsView.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.graphicsView.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

        # Create a custom resize event for the graphics view
        # def resizeEvent(event):
        #     # Get the smaller of width or height
        #     size = min(event.size().width(), event.size().height())
        #     # Create a square size
        #     square_size = QSize(size, size)
        #     # Resize to square
        #     self.graphicsView.resize(square_size)
        #     # Call parent resize event
        #     QGraphicsView.resizeEvent(self.graphicsView, event)

        # # Attach the custom resize event
        # self.graphicsView.resizeEvent = resizeEvent

        # Initialize log emitter
        self.log_emitter = LogEmitter()
        self.log_emitter.log_message.connect(self.append_log)

        # Fix text format setting
        self.placeholdersHelpLabel.setTextFormat(Qt.PlainText)

        # Initialize MQTT client to None
        self.client = None

        # Initialize air state
        self.air_state = False

        # Store the full module list for filtering - initialize before using
        self.all_modules = []

        # # Add search box - move this before connecting signals
        # searchLayout = QHBoxLayout()
        # searchLabel = QLabel("Search:")
        # self.searchBox = QLineEdit()
        # self.searchBox.setPlaceholderText("Search modules...")
        # searchLayout.addWidget(searchLabel)
        # searchLayout.addWidget(self.searchBox)
        # searchLayout.addStretch()

        # # Insert search layout before the tree widget
        # layout = self.tab_2.layout()
        # layout.insertLayout(1, searchLayout)

        # Enable sorting
        # self.treeWidget.setSortingEnabled(True)

        # Enable sorting
        # self.treeWidget.setSortingEnabled(True)

        # Initialize lists for Ph2ACF temperatures
        self.ph2acf_time = []
        self.ssa_mean_values = []
        self.ssa_max_values = []
        self.mpa_mean_values = []
        self.mpa_max_values = []
        self.current_fuse_id = None

        # Setup module details tab
        #   self.setup_module_details_tab()

        # Now connect signals after UI elements exist
        # self.searchBox.textChanged.connect(self.filter_modules)
        self.ringLE.returnPressed.connect(self.split_ring_and_position)
        self.positionLE.returnPressed.connect(self.draw_ring)
        self.mountPB.clicked.connect(self.mount_module)
        self.unmountPB.clicked.connect(self.unmount_module)

        # Initialize mounted modules dict
        self.mounted_modules = {}
        self.analysisURL = ""
        fibers = ["SfibA", "SfibB"]
        fibers += [f"E3;{x}" for x in range(1, 6)]
        powers = ["BINT1"]
        powers += [f"R01;M1.{x}" for x in range(1, 13)]
        powers += [f"R01;M2.{x}" for x in range(1, 13)]
        powers += [f"R01;M3.{x}" for x in range(1, 13)]
        self.layers_to_filters = {
            "L1_47": {
                "spacer": "2.6mm",
                "speed": "10G",
            },
            "L1_60": {
                "spacer": "4.0mm",
                "speed": "10G",
            },
            "L1_72": {
                "spacer": "4.0mm",
                "speed": "10G",
            },
            # 40,55,68
            "L2_40": {
                "spacer": "2.6mm",
                "speed": "10G",
            },
            "L2_55": {
                "spacer": "2.6mm",
                "speed": "10G",
            },
            "L2_68": {
                "spacer": "4.0mm",
                "speed": "10G",
            },
            "L3": {
                "spacer": "2.6mm",
                "speed": "5G",
            },
        }
        self.fiberCB.addItems(fibers)
        self.powerCB.addItems(powers)
        self.number_of_modules = 18

        #                config_dir = os.path.expanduser("~/.config/integration_ui")
        # load last session from ~/.config/integration_ui/lastsession.txt

        # Setup thermal camera plotting
        self.setup_thermal_plot()

        # Setup CAEN control
        self.caen = CAENControl(self)

        # Connect button signals
        self.checkIDPB.clicked.connect(self.run_check_id)
        self.hvOFFTestPB.clicked.connect(self.run_light_on_test)
        self.hvONTestPB.clicked.connect(self.run_dark_test)
        self.connectPowerPB.clicked.connect(self.connect_power)
        self.connectFiberPB.clicked.connect(self.connect_fiber)

        # Connect settings-related signals
        self.checkIDCommandLE.textChanged.connect(self.save_settings)
        self.lightOnCommandLE.textChanged.connect(self.save_settings)
        self.darkTestCommandLE.textChanged.connect(self.save_settings)
        self.dbEndpointLE.textChanged.connect(self.save_settings)
        self.mqttServerLE.textChanged.connect(self.save_settings)
        self.mqttTopicLE.textChanged.connect(self.save_settings)
        self.airCommandLE.textChanged.connect(self.save_settings)
        self.resultsUrlLE.textChanged.connect(self.save_settings)

        # Connect Apply button
        self.applySettingsPB.clicked.connect(self.apply_settings)

        # Initial MQTT setup
        self.setup_mqtt()

        # # Connect filter signals
        # self.speedCB.currentTextChanged.connect(self.update_module_list)
        # self.spacerCB.currentTextChanged.connect(self.update_module_list)
        # self.spacerCB_2.currentTextChanged.connect(self.update_module_list)
        # self.spacerCB_3.currentTextChanged.connect(self.update_module_list)

        # # Initial module list load
        self.update_module_list()

        # # Connect select module button
        # self.selectModulePB.clicked.connect(self.select_module)

        # # Enable selection mode for tree widget
        # self.treeWidget.setSelectionMode(QTreeWidget.SingleSelection)

        # Connect selection changes
        self.moduleLE.textChanged.connect(self.module_changed)
        self.powerCB.currentTextChanged.connect(self.update_connection_status)
        self.fiberCB.currentTextChanged.connect(self.update_connection_status)
        self.fiber_endpoint = ""

        # Initial connection status check
        QTimer.singleShot(
            100, self.update_connection_status
        )  # Small delay to ensure UI is ready

        # Connect module details buttons
        # self.editDetailsButton.clicked.connect(self.edit_selected_detail)
        # self.saveDetailsButton.clicked.connect(self.save_module_details)

        # Setup inventory buttons
        # self.setup_inventory_buttons()

        # Initialize current module tracking
        self.current_module_id = None

        # Initialize test states
        self.checkIDLED.setStyleSheet("background-color: rgb(255, 255, 0);")  # Yellow
        self.hvOFFTestLED.setStyleSheet("background-color: rgb(255, 255, 0);")
        self.hvONTestLED.setStyleSheet("background-color: rgb(255, 255, 0);")

        # Disable tests 2 and 3 initially
        #        self.hvOFFTestPB.setEnabled(False)
        #        self.hvONTestPB.setEnabled(False)

        # Track command workers
        self.current_worker = None

        # Connect module ID changes to reset test states
        self.moduleLE.textChanged.connect(self.reset_test_states)

        # Connect module selection to reset test states
        self.module_db.ui.selectModulePB.clicked.connect(self.reset_test_states)

        self.logsPB.clicked.connect(self.open_ph2acf_log)

        # Connect module ID changes to load details
        #        self.moduleLE.textChanged.connect(self.load_module_details)

        # Populate layer type combo box
        # self.ui.layertypeCB.clear()
        # self.ui.layertypeCB.addItem("any")
        # self.ui.layertypeCB.addItems(sorted(self.layers_to_filters.keys()))

        # Connect signals
        # self.ui.layertypeCB.currentTextChanged.connect(self.update_filters_from_layer)
        self.ringLE.textChanged.connect(self.update_layer_from_ring)

        # Connect module ID changes to check mounting status
        self.moduleLE.textChanged.connect(self.check_module_mounting_status)

        session_file = os.path.join(
            os.path.expanduser("~/.config/integration_ui"), "lastsession.txt"
        )
        if os.path.exists(session_file):
            with open(session_file, "r") as f:
                session = f.read().strip()
                self.ringLE.setText(session)
                self.split_ring_and_position()
        else:
            self.ringLE.setText("L1")
            self.split_ring_and_position()

        self.draw_ring()

        # Connect air control buttons
        self.airONPB.clicked.connect(lambda: self.control_air(True))
        self.airOFFPB.clicked.connect(lambda: self.control_air(False))

        # Connect test results button
        self.showPB.clicked.connect(self.show_test_results)

        # Store max temperature
        self.max_temperature = 0.0

        # Connect open in browser button
        self.openInBrowserPB.clicked.connect(self.open_results_in_browser)

        self.current_module_data = {}
        self.current_session = None
        self.current_session_operator = None
        self.current_session_comments = None
        self.current_module_id = None
        self.pbstatus = {}
        self.airLed.setStyleSheet("background-color: yellow;")

        # define test session for DB

    #         session = {
    #             "operator": self.BI_Operator_line.text(),
    #             "timestamp": datetime.now().strftime('%Y-%m-%dT%H:%M:%S'),
    #                     "description": self.SeshDescription_db.text(),
    #             "temperatures": {
    #                 "low": self.BI_LowTemp_dsb.value(),
    #                     "high": self.BI_HighTemp_dsb.value(),
    #                     },
    #                         "nCycles": self.BI_NCycles_sb.value(),
    # #                        "status": "Open" #to be implemented
    #             "modulesList": [],
    #                 }
    def disable_test_pbs_enable_cancel(self):
        self.pbstatus = {
            self.checkIDPB: self.checkIDPB.isEnabled(),
            self.hvOFFTestPB: self.hvOFFTestPB.isEnabled(),
            self.hvONTestPB: self.hvONTestPB.isEnabled(),
        }
        self.checkIDPB.setEnabled(False)
        self.hvOFFTestPB.setEnabled(False)
        self.hvONTestPB.setEnabled(False)
        self.cancelPB.setEnabled(True)

    def reset_test_pbs(self):
        print("Resetting test PBs")
        print(self.pbstatus)
        for pb, status in self.pbstatus.items():
            pb.setEnabled(status)
        self.cancelPB.setEnabled(False)

    def new_session(self):
        session = {
            "operator": self.operatorLE.text(),
            "description": "INTEGRATION: " + self.commentsLE.text(),
            "timestamp": datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
            "modulesList": [self.moduleLE.text()],
        }
        # create new session in DB
        success, result = self.make_api_request("sessions", "POST", session)
        self.current_session = result["sessionName"]
        self.current_module_id = self.moduleLE.text()
        self.current_session_operator = self.operatorLE.text()
        self.current_session_comments = self.commentsLE.text()
        print(self.current_session)
        return self.current_session

    def get_session(self):
        if self.current_session is None:
            return self.new_session()
        if (
            self.current_session_operator != self.operatorLE.text()
            or self.current_session_comments != self.commentsLE.text()
        ):
            return self.new_session()
        if self.moduleLE.text() != self.current_module_id:
            return self.new_session()
        return self.current_session

    def setup_thermal_plot(self):
        self.fig, (self.ax1, self.ax2) = plt.subplots(2, 1, figsize=(8, 6))

        # First plot: Image
        self.im = self.ax1.imshow(np.random.rand(24, 32) * 30 + 10, cmap="plasma")
        divider1 = make_axes_locatable(self.ax1)
        self.cax1 = divider1.append_axes("right", size="5%", pad=0.05)
        plt.colorbar(self.im, cax=self.cax1)

        # Second plot: Trend
        self.time = []
        self.min_values = []
        self.max_values = []
        self.avg_values = []

        (self.line_min,) = self.ax2.plot(self.time, self.min_values, label="Min")
        (self.line_max,) = self.ax2.plot(self.time, self.max_values, label="Max")
        (self.line_avg,) = self.ax2.plot(self.time, self.avg_values, label="Avg")

        # SSA/MPA trend lines
        (self.line_ssa_mean,) = self.ax2.plot(
            [], [], label="SSA Mean", linestyle="-", marker="s", markersize=3
        )
        (self.line_ssa_max,) = self.ax2.plot(
            [], [], label="SSA Max", linestyle="-", marker="^", markersize=3
        )
        (self.line_mpa_mean,) = self.ax2.plot(
            [], [], label="MPA Mean", linestyle="-", marker="o", markersize=3
        )
        (self.line_mpa_max,) = self.ax2.plot(
            [], [], label="MPA Max", linestyle="-", marker="v", markersize=3
        )

        self.ax2.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M:%S"))
        self.ax2.legend(fontsize="xx-small", loc="upper left", ncol=2)

        # Create canvas and add to layout
        self.canvas = FigureCanvas(self.fig)
        layout = QVBoxLayout(self.plotWidget)
        layout.addWidget(self.canvas)

    def get_settings_file(self):
        """Get the settings file path"""
        config_file = os.path.join(
            os.path.expanduser("~/.config/integration_ui"), "settings.yaml"
        )
        bundled_file = os.path.join(
            os.path.dirname(__file__), "settings_integration.yaml"
        )
        if os.path.exists(config_file):
            return config_file
        elif os.path.exists(bundled_file):
            return bundled_file
        else:
            return config_file

    def load_settings(self):
        """Load settings from YAML file"""
        try:
            with open(self.get_settings_file(), "r") as f:
                settings = yaml.safe_load(f)

            if settings:
                print(settings)
                print(self.get_settings_file())
                # Load database URL
                self.dbEndpointLE.setText(
                    settings.get("db_url", "http://localhost:5000")
                )

                # Load MQTT settings
                self.mqttServerLE.setText(
                    settings.get("mqtt_server", "test.mosquitto.org")
                )
                self.mqttTopicLE.setText(
                    settings.get("mqtt_topic", "/ar/thermal/image")
                )

                # Load command settings
                self.checkIDCommandLE.setText(settings.get("check_id_command", ""))
                self.lightOnCommandLE.setText(settings.get("light_on_command", ""))
                self.darkTestCommandLE.setText(settings.get("dark_test_command", ""))
                self.airCommandLE.setText(settings.get("air_command", "air.sh {airOn}"))
                self.ph2acfTopicLE.setText(settings.get("ph2acf_topic", "/ph2acf/data"))
                self.resultsUrlLE.setText(
                    settings.get("results_url", "file:Results/html/latest/index.html")
                )

        except FileNotFoundError:
            # Use defaults if no settings file exists
            self.save_settings()

    def get_api_url(self, endpoint=""):
        """Get full API URL with endpoint"""
        base_url = self.dbEndpointLE.text().rstrip("/")
        return f"{base_url}/{endpoint.lstrip('/')}" if endpoint else base_url

    def save_settings(self):
        """Save settings to YAML file"""
        settings = {
            "db_url": self.dbEndpointLE.text(),
            "mqtt_server": self.mqttServerLE.text(),
            "mqtt_topic": self.mqttTopicLE.text(),
            # Add command settings
            "check_id_command": self.checkIDCommandLE.text(),
            "light_on_command": self.lightOnCommandLE.text(),
            "dark_test_command": self.darkTestCommandLE.text(),
            "air_command": self.airCommandLE.text(),
            "ph2acf_topic": self.ph2acfTopicLE.text(),
            "results_url": self.resultsUrlLE.text(),
        }

        try:
            # Ensure config directory exists
            config_dir = os.path.dirname(self.get_settings_file())
            os.makedirs(config_dir, exist_ok=True)

            with open(self.get_settings_file(), "w") as f:
                yaml.dump(settings, f, default_flow_style=False)
        except Exception as e:
            self.log_output(f"Error saving settings: {e}")

    def setup_mqtt(self):
        """Setup MQTT client with error handling"""
        try:
            # Disconnect existing client if any
            if self.client:
                try:
                    self.client.disconnect()
                    self.client.loop_stop()
                except:
                    pass

            self.client = mqtt.Client()
            self.client.on_connect = self.on_mqtt_connect
            self.client.on_message = self.on_mqtt_message
            self.client.on_disconnect = self.on_mqtt_disconnect

            # Use settings from UI
            mqtt_server = self.mqttServerLE.text()

            # Connect with timeout
            self.log_output(f"Connecting to MQTT server: {mqtt_server}")
            self.client.connect_async(mqtt_server, 1883, 60)
            self.client.loop_start()

        except Exception as e:
            self.log_output(f"MQTT Setup Error: {str(e)}")
            # Don't let MQTT errors crash the UI
            return False
        return True

    def on_mqtt_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection"""
        try:
            if rc == 0:
                self.log_output("Connected to MQTT server")
                mqtt_topic = self.mqttTopicLE.text()
                ph2acf_topic = self.ph2acfTopicLE.text()
                self.log_output(f"Subscribing to topics: {mqtt_topic}, {ph2acf_topic}")
                client.subscribe(
                    [
                        ("/air/status", 0),
                        (mqtt_topic, 0),
                        (ph2acf_topic, 0),
                        ("shellies/ventola/status/switch:0", 0),
                    ]
                )
            else:
                self.log_output(f"MQTT Connection failed with code {rc}")
        except Exception as e:
            self.log_output(f"MQTT Connect Error: {str(e)}")

    def on_mqtt_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection"""
        try:
            self.log_output("Disconnected from MQTT server")
            if rc != 0:
                self.log_output(
                    "Unexpected disconnection. Will attempt to reconnect..."
                )
        except Exception as e:
            self.log_output(f"MQTT Disconnect Error: {str(e)}")

    def on_mqtt_message(self, client, userdata, msg):
        """Handle MQTT messages with error protection"""
        #        print(msg.topic)
        if msg.topic == "shellies/ventola/status/switch:0":
            j = json.loads(msg.payload)
            print(j)
            if j.get("apower", 0) > 0.1:
                self.airLed.setStyleSheet("background-color: green;")
            else:
                self.airLed.setStyleSheet("background-color: red;")

        elif msg.topic == "/air/status":
            #           print(msg.payload)
            if int(msg.payload) == 1:
                self.airLed.setStyleSheet("background-color: green;")
            else:
                self.airLed.setStyleSheet("background-color: red;")
        elif msg.topic == self.ph2acfTopicLE.text():
            try:
                data = json.loads(msg.payload)
                # Only process if fuseId matches (and is not None)
                fuse_id_msg = data.get("LpGBT_OG0_fuseId")
                if (
                    self.current_fuse_id is not None
                    and fuse_id_msg is not None
                    and int(fuse_id_msg) == int(self.current_fuse_id)
                ):
                    # We have matching data, extract temperatures
                    ssa_temps = []
                    mpa_temps = []
                    missing_any_offset = False

                    offsets = {}
                    if self.current_module_data:
                        if "temperature_offset" in self.current_module_data:
                            offsets = self.current_module_data["temperature_offset"]
                        else:
                            # Look for alternative keys starting with 'temperature_offset'
                            variants = sorted(
                                [
                                    k
                                    for k in self.current_module_data.keys()
                                    if k.startswith("temperature_offset")
                                ]
                            )
                            if variants:
                                offsets = self.current_module_data[variants[0]]

                    if not isinstance(offsets, dict):
                        offsets = {}
                    print(offsets)
                    for key, value in data.items():
                        if key.endswith("_temp"):
                            # Extract hybrid and chip from key like SSA_H0_C0_temp
                            print(key, value)
                            parts = key.split("_")
                            if len(parts) >= 3:
                                ctype = parts[
                                    0
                                ]  # SSA or MPA (though MPA often encoded as SSA in some Ph2_ACF versions)
                                hybrid = parts[1]  # H0 or H1
                                chip = parts[2]  # C0, C1, ...

                                # Clean up indices
                                h_idx = hybrid[1:] if hybrid.startswith("H") else hybrid
                                c_idx = chip[1:] if chip.startswith("C") else chip

                                # Construct offset key like SSA_H0_0
                                # Note: The mapping provided in prompt says SSA_H0_0, MPA_H0_8 etc.
                                # We need to determine if it's SSA or MPA based on the chip index or key name.
                                # User said "SSA/MPA mean and max".
                                # Let's use the provided mapping logic: keys like SSA_H0_0
                                offset_key = f"{ctype}_{hybrid}_{c_idx}"

                                temp = float(value)
                                if offset_key in offsets:
                                    temp += float(offsets[offset_key])
                                else:
                                    missing_any_offset = True

                                if ctype == "SSA":
                                    ssa_temps.append(temp)
                                elif ctype == "MPA":
                                    mpa_temps.append(temp)
                                else:
                                    # Fallback/Mixed
                                    ssa_temps.append(temp)

                    now = datetime.now()
                    # Update trend
                    self.ph2acf_time.append(now)

                    # Keep maximum 600 values for Ph2ACF data
                    if len(self.ph2acf_time) > 600:
                        self.ph2acf_time.pop(0)
                        self.ssa_mean_values.pop(0)
                        self.ssa_max_values.pop(0)
                        self.mpa_mean_values.pop(0)
                        self.mpa_max_values.pop(0)

                    # SSA Stats
                    if ssa_temps:
                        self.ssa_mean_values.append(np.mean(ssa_temps))
                        self.ssa_max_values.append(np.max(ssa_temps))
                    else:
                        self.ssa_mean_values.append(np.nan)
                        self.ssa_max_values.append(np.nan)

                    # MPA Stats
                    if mpa_temps:
                        self.mpa_mean_values.append(np.mean(mpa_temps))
                        self.mpa_max_values.append(np.max(mpa_temps))
                    else:
                        self.mpa_mean_values.append(np.nan)
                        self.mpa_max_values.append(np.nan)

                    print(
                        f"DEBUG: SSA Mean: {self.ssa_mean_values[-1] if ssa_temps else 'N/A'}"
                    )

                    # Update plot lines
                    # Set line style based on offset presence
                    ls = "--" if missing_any_offset else "-"

                    self.line_ssa_mean.set_data(self.ph2acf_time, self.ssa_mean_values)
                    self.line_ssa_mean.set_linestyle(ls)
                    self.line_ssa_max.set_data(self.ph2acf_time, self.ssa_max_values)
                    self.line_ssa_max.set_linestyle(ls)

                    self.line_mpa_mean.set_data(self.ph2acf_time, self.mpa_mean_values)
                    self.line_mpa_mean.set_linestyle(ls)
                    self.line_mpa_max.set_data(self.ph2acf_time, self.mpa_max_values)
                    self.line_mpa_max.set_linestyle(ls)

                    self.ax2.relim()
                    self.ax2.autoscale_view()
                    self.canvas.draw()

            except Exception as e:
                self.log_output(f"Ph2ACF Message Error: {str(e)}")

        elif msg.topic == self.mqttTopicLE.text():
            try:
                flo_arr = [
                    struct.unpack("f", msg.payload[i : i + 4])[0]
                    for i in range(0, len(msg.payload), 4)
                ]

                # Update image plot
                self.im.set_data(np.array(flo_arr).reshape(24, 32))
                self.im.set_clim(18, 35)

                # Update trend plot
                now = datetime.now()
                self.time.append(now)

                self.min_values.append(min(flo_arr))
                self.max_values.append(max(flo_arr))
                self.avg_values.append(np.mean(flo_arr))
                data = {
                    "min": min(flo_arr),
                    "max": max(flo_arr),
                    "avg": np.mean(flo_arr),
                }
                ret = client.publish("/integration/thermalcamera", json.dumps(data))

                # Update max temperature display
                self.max_temperature = max(flo_arr)
                self.tMaxLabel.setText(f"Tmax: {self.max_temperature:.1f}")
                if self.max_temperature > 45:
                    self.caenGUI.safe_lv_off()
                if self.max_temperature > 50:
                    self.caenGUI.off(self.caenGUI.channels["HV"])
                    self.caenGUI.off(self.caenGUI.channels["LV"])
                # Keep maximum 600 values
                if len(self.time) > 600:
                    self.time.pop(0)
                    self.min_values.pop(0)
                    self.max_values.pop(0)
                    self.avg_values.pop(0)

                self.line_min.set_data(self.time, self.min_values)
                self.line_max.set_data(self.time, self.max_values)
                self.line_avg.set_data(self.time, self.avg_values)
                self.ax2.relim()
                self.ax2.autoscale_view()

                self.canvas.draw()

            except Exception as e:
                self.log_output(f"MQTT Message Error: {str(e)}")
        else:
            # Handle other topics if any (already handled for air and fan)
            pass

    def split_ring_and_position(self):
        ring_position = self.ringLE.text()
        config_dir = os.path.expanduser("~/.config/integration_ui")
        os.makedirs(config_dir, exist_ok=True)
        session_file = os.path.join(config_dir, "lastsession.txt")
        with open(session_file, "w") as f:
            f.write(self.ringLE.text())
        ring = ring_position
        position = "0"
        if ";" in ring_position:
            ring, position = ring_position.split(";")
        self.ringLE.setText(ring)
        self.positionLE.setText(position)
        if ring[:2] == "L1":
            self.number_of_modules = 18
        if ring[:2] == "L2":
            self.number_of_modules = 26
        if ring[:2] == "L3":
            self.number_of_modules = 36
        self.draw_ring()

    def draw_ring(self):
        # draw a ring with number_of_modules modules, each is draw as a rectangle
        # even and odd modules are drawn at different radii
        # draw in graphics view
        self.update_module_list()
        scene = QGraphicsScene()
        self.graphicsView.setScene(scene)

        # Store module coordinates for click detection
        self.module_coordinates = []

        pen = QPen()
        pen.setWidth(2)
        pen.setColor(Qt.black)
        # dashed style
        pen.setStyle(Qt.DashLine)
        radius = min(self.graphicsView.width(), self.graphicsView.height()) / 2.5
        scene.addEllipse(0, 0, radius * 2, radius * 2, pen)
        deltaphi = 360 / self.number_of_modules * 2
        # solid
        pen.setStyle(Qt.SolidLine)
        # draw two circles in the middle-top
        scene.addEllipse(radius - 7, -20, 6, 6, pen)
        scene.addEllipse(radius + 7, -20, 6, 6, pen)
        scene.addEllipse(radius - 4, -17, 1, 1, pen)
        scene.addEllipse(radius + 10, -17, 1, 1, pen)

        ring_id = self.ringLE.text()

        for i in range(1, self.number_of_modules + 1):
            phi = -(i) * deltaphi + deltaphi / 2
            phi -= 90
            if i > self.number_of_modules / 2:
                phi += deltaphi / 2

            # Check if this position has a mounted module
            position_key = f"{ring_id};{i}"
            is_mounted = position_key in self.mounted_modules

            if self.positionLE.text() == str(i):
                pen.setColor(Qt.red)
            elif is_mounted:
                pen.setColor(Qt.blue)  # Use blue for mounted positions
            else:
                pen.setColor(Qt.black)

            # Calculate module coordinates
            if i <= self.number_of_modules / 2:
                x1 = (radius * 0.95) * cos((phi + deltaphi / 4) / 180 * pi) + radius
                y1 = (radius * 0.95) * sin((phi + deltaphi / 4) / 180 * pi) + radius
                x2 = (radius * 0.95) * cos((phi - deltaphi / 4) / 180 * pi) + radius
                y2 = (radius * 0.95) * sin((phi - deltaphi / 4) / 180 * pi) + radius
                x3 = (radius * 1.1) * cos((phi + deltaphi / 4) / 180 * pi) + radius
                y3 = (radius * 1.1) * sin((phi + deltaphi / 4) / 180 * pi) + radius
                x4 = (radius * 1.1) * cos((phi - deltaphi / 4) / 180 * pi) + radius
                y4 = (radius * 1.1) * sin((phi - deltaphi / 4) / 180 * pi) + radius
            else:
                x1 = (radius * 0.9) * cos((phi + deltaphi / 4) / 180 * pi) + radius
                y1 = (radius * 0.9) * sin((phi + deltaphi / 4) / 180 * pi) + radius
                x2 = (radius * 0.9) * cos((phi - deltaphi / 4) / 180 * pi) + radius
                y2 = (radius * 0.9) * sin((phi - deltaphi / 4) / 180 * pi) + radius
                x3 = (radius * 1.05) * cos((phi + deltaphi / 4) / 180 * pi) + radius
                y3 = (radius * 1.05) * sin((phi + deltaphi / 4) / 180 * pi) + radius
                x4 = (radius * 1.05) * cos((phi - deltaphi / 4) / 180 * pi) + radius
                y4 = (radius * 1.05) * sin((phi - deltaphi / 4) / 180 * pi) + radius

            # Store module coordinates and position number
            self.module_coordinates.append(
                {"position": i, "coords": [(x1, y1), (x2, y2), (x3, y3), (x4, y4)]}
            )

            scene.addLine(x1, y1, x2, y2, pen)
            scene.addLine(x2, y2, x4, y4, pen)
            scene.addLine(x4, y4, x3, y3, pen)
            scene.addLine(x3, y3, x1, y1, pen)

            # Add module ID text for mounted modules
            if is_mounted:
                text = self.mounted_modules[position_key]
            else:
                text = str(i)
            # Calculate center point of the module
            center_x = (x1 + x3) / 2
            center_y = (y1 + y3) / 2

            # Calculate angle for radial text (in degrees)
            angle = atan2(center_y - radius, center_x - radius) * 180 / pi
            # Add 90 degrees to make text perpendicular to radius
            angle += 180 - deltaphi / 4

            text_item = scene.addText(text)
            # Center the text around its position
            text_bounds = text_item.boundingRect()
            text_item.setPos(
                (radius * 0.5) * cos(phi / 180 * pi) + radius - text_bounds.width() / 2,
                (radius * 0.5) * sin(phi / 180 * pi)
                + radius
                - text_bounds.height() / 2,
            )
            # Set the rotation around the center of the text
            text_item.setTransformOriginPoint(text_bounds.center())
            text_item.setRotation(angle)

        # Enable mouse tracking
        self.graphicsView.setMouseTracking(True)
        self.graphicsView.mousePressEvent = self.handle_ring_click
        self.graphicsView.show()

    def handle_ring_click(self, event):
        """Handle clicks on the ring diagram"""
        # Convert click coordinates to scene coordinates
        scene_pos = self.graphicsView.mapToScene(event.pos())
        x, y = scene_pos.x(), scene_pos.y()

        # Check if click is inside any module
        for module in self.module_coordinates:
            coords = module["coords"]
            # Create polygon from module coordinates
            polygon = [(x_, y_) for x_, y_ in coords]

            # Calculate bounding box for quick check
            min_x = min(x for x, _ in polygon)
            max_x = max(x for x, _ in polygon)
            min_y = min(y for _, y in polygon)
            max_y = max(y for _, y in polygon)

            # First do a bounding box check
            if min_x <= x <= max_x and min_y <= y <= max_y:
                # If in bounding box, do detailed polygon check
                if self.point_in_polygon(x, y, polygon):
                    new_position = str(module["position"])

                    # Only proceed if position actually changed
                    if new_position != self.positionLE.text():
                        self.log_output(f"Found match in module {new_position}")

                        # Update position LE
                        self.positionLE.setText(new_position)

                        # Check if a module is mounted at this position
                        ring_id = self.ringLE.text()
                        position_key = f"{ring_id};{new_position}"

                        if position_key in self.mounted_modules:
                            # Update module ID with the mounted module's ID
                            mounted_module_id = self.mounted_modules[position_key]
                            self.moduleLE.setText(mounted_module_id)

                            # Reset test states since we have a new module
                            self.reset_test_states()

                        # Redraw ring to update highlighting
                        self.draw_ring()
                    break

    def point_in_polygon(self, x, y, polygon):
        """Check if point (x,y) is inside polygon using cross product method"""

        def sign(p1, p2, p3):
            return (p1[0] - p3[0]) * (p2[1] - p3[1]) - (p2[0] - p3[0]) * (p1[1] - p3[1])

        def is_point_in_triangle(pt, v1, v2, v3):
            d1 = sign(pt, v1, v2)
            d2 = sign(pt, v2, v3)
            d3 = sign(pt, v3, v1)

            has_neg = (d1 < 0) or (d2 < 0) or (d3 < 0)
            has_pos = (d1 > 0) or (d2 > 0) or (d3 > 0)

            return not (has_neg and has_pos)

        # For quadrilateral, split into two triangles and check both
        point = (x, y)
        return is_point_in_triangle(
            point, polygon[0], polygon[1], polygon[2]
        ) or is_point_in_triangle(point, polygon[2], polygon[3], polygon[0])

    def get_placeholder_values(self):
        """Get current values for all placeholders"""
        return {
            "ring_id": self.ringLE.text(),
            "position": self.positionLE.text(),
            "module_id": self.moduleLE.text(),
            "fiber": self.fiberCB.currentText(),
            "power": self.powerCB.currentText(),
            "fiber_endpoint": self.fiber_endpoint,
            "session": self.get_session(),
        }

    def expand_placeholders(self, text):
        """Replace placeholders in text with their current values"""
        values = self.get_placeholder_values()
        try:
            return text.format(**values)
        except KeyError as e:
            self.log_output(f"Warning: Unknown placeholder {e}")
            return text
        except ValueError as e:
            self.log_output(f"Warning: Invalid placeholder format - {e}")
            return text

    def run_command(self, command):
        """Run a shell command asynchronously"""
        if self.current_worker is not None:
            self.current_worker.finished.disconnect()
            self.current_worker.terminate()
            self.current_worker.wait()

        expanded_command = self.expand_placeholders(command)
        self.log_output(f"Running command: {expanded_command}")
        self.log_output(f"Using placeholders: {self.get_placeholder_values()}")

        self.current_worker = CommandWorker(expanded_command)
        self.current_worker.finished.connect(self.handle_command_finished)
        self.current_worker.start()

    def handle_command_finished(self, success, stdout, stderr):
        """Handle command completion"""
        if stdout:
            self.log_output(f"Output:\n{stdout}")
        if stderr:
            self.log_output(f"Error:\n{stderr}")

        # Clean up worker
        if self.current_worker:
            self.current_worker.finished.disconnect()
            self.current_worker = None

    def show_error_dialog(self, message):
        """Show error dialog with the given message"""
        msg = QMessageBox()
        msg.setIcon(QMessageBox.Warning)
        msg.setText("Error")
        msg.setInformativeText(message)
        msg.setWindowTitle("Error")
        msg.exec_()

    def make_api_request(self, endpoint, method, data=None):
        """Make API request and return result"""
        url = self.get_api_url(endpoint)

        try:
            self.log_output(f"Making {method} request to: {url}")

            if data:
                self.log_output(f"With data: {data}")

            response = requests.request(
                method=method.lower(), url=url, json=data if data else None
            )

            if response.status_code != 200 and response.status_code != 201:
                error_msg = f"API Error ({response.status_code}): {response.text}"
                self.log_output(error_msg)
                self.show_error_dialog(error_msg)
                return False, None

            result = response.json()
            self.log_output(f"Response: {result}")
            return True, result
        except requests.RequestException as e:
            error_msg = f"API Error: {str(e)}"
            self.log_output(error_msg)
            self.show_error_dialog(error_msg)
            return False, str(e)

    def log_output(self, text):
        """Log output to both console and text edit"""
        print(text)
        # Emit the log message instead of directly updating the UI
        self.log_emitter.log_message.emit(text)

    def append_log(self, text):
        """Append text to log widget (called in main thread)"""
        self.commandOutputTE.appendPlainText(text)
        self.commandOutputTE.appendPlainText("")  # Add blank line
        # Scroll to bottom
        self.commandOutputTE.verticalScrollBar().setValue(
            self.commandOutputTE.verticalScrollBar().maximum()
        )

    def run_check_id(self):
        """Run Check ID test"""
        self.log_output("=== Running Check ID ===")
        # check that operator, comment and module are not empty
        if (
            self.operatorLE.text() == ""
            or self.commentsLE.text() == ""
            or self.moduleLE.text() == ""
        ):
            self.log_output("Operator, Comments and Module ID must be filled")
            # open dialog
            self.show_error_dialog("Operator, Comments and Module ID must be filled")
            return

        def handle_check_id(success, stdout, stderr):
            if success:
                self.checkIDLED.setStyleSheet(
                    "background-color: rgb(85, 170, 0);"
                )  # Green

                self.checkIDPB.setEnabled(True)
                self.hvOFFTestPB.setEnabled(True)  # Enable test 2
                self.hvONTestPB.setEnabled(True)  # Enable test 3

                # Try to parse module ID from output
                try:
                    # Assuming output format contains "Module ID: XXXX"
                    print(stdout)
                    #            module_id = stdout.split("Module ID:")[1].strip().split()[0]
                    #            self.checkIDlabel.setText(f"ID: {module_id}")
                    module_id = (
                        re.search(r"Board.*Module (.*?)\s\(", stdout).group(1).strip()
                    )
                    print(re.search(r"Module (.*?)\s\(", stdout))
                    self.checkIDlabel.setText(f"ID: {module_id}")
                except:
                    self.log_output("Could not parse module ID from output")
            else:
                self.checkIDLED.setStyleSheet("background-color: red;")
                self.hvOFFTestPB.setEnabled(False)
                self.hvONTestPB.setEnabled(False)
                self.reset_test_pbs()
            self.handle_command_finished(success, stdout, stderr)

        if self.current_worker:
            self.current_worker.finished.disconnect()
        self.current_worker = CommandWorker(
            self.expand_placeholders(self.checkIDCommandLE.text())
        )
        self.current_worker.finished.connect(handle_check_id)
        # self.current_worker.finished.connect(self.reset_test_pbs)
        # self.current_worker.finished.connect(self.handle_command_finished)
        self.disable_test_pbs_enable_cancel()
        self.cancelPB.clicked.connect(self.current_worker.terminate)
        self.cancelPB.clicked.connect(self.reset_test_pbs)

        # self.waiting_dialog = QMessageBox()
        # self.waiting_dialog.setWindowTitle("Checking ID")
        # self.waiting_dialog.setText("Wait while checking module ID")
        # #add Cancel
        # self.waiting_dialog.setStandardButtons(QMessageBox.Cancel)
        # self.waiting_dialog.buttonClicked.connect(lambda button: self.current_worker.terminate())
        # self.waiting_dialog.show()
        # self.current_worker.finished.connect(self.waiting_dialog.accept)

        self.current_worker.start()

    def run_light_on_test(self):
        """Run Light On Test"""
        self.log_output("=== Running Light On Test ===")

        def handle_light_on(success, stdout, stderr):
            if success:
                self.hvOFFTestLED.setStyleSheet(
                    "background-color: rgb(85, 170, 0);"
                )  # Green
                self.hvOFFTestCB.setChecked(True)
                self.checkIDPB.setEnabled(True)
                self.hvOFFTestPB.setEnabled(True)  # Enable test 2
                self.hvONTestPB.setEnabled(True)  # Enable test 3
                self.resultsLabel.setText(stdout[:20])
                # # Try to parse noise values from output
                # try:
                #     # Update results label with the output
                #     noise_text = "<html><head/><body><p>Noise:</p>"

                #     # Look for MPA and SSA noise values in the output
                #     mpa_noise = "0.0"
                #     ssa_noise = "0.0"

                #     for line in stdout.split('\n'):
                #         if "MPA noise:" in line:
                #             mpa_noise = line.split(":")[-1].strip()
                #         elif "SSA noise:" in line:
                #             ssa_noise = line.split(":")[-1].strip()

                #     noise_text += f"<p>MPA: {mpa_noise}</p>"
                #     noise_text += f"<p>SSA: {ssa_noise}</p>"
                #     noise_text += "</body></html>"

                #     self.resultsLabel.setText(noise_text)
                # except Exception as e:
                #     self.log_output(f"Error parsing test results: {e}")
            else:
                self.hvOFFTestLED.setStyleSheet("background-color: red;")
                self.hvOFFTestCB.setChecked(False)
                self.log_output(f"Light on test error: {stderr}")
                self.reset_test_pbs()
            self.handle_command_finished(success, stdout, stderr)

        if self.current_worker:
            self.current_worker.finished.disconnect()
        self.current_worker = CommandWorker(
            self.expand_placeholders(self.lightOnCommandLE.text())
        )
        #        self.log_worker = CommandWorker("konsole -e tail -f /home/thermal/BurnIn_moduleTest/logs/Ph2_ACF.log")
        self.current_worker.finished.connect(handle_light_on)
        #   self.current_worker.finished.connect(self.reset_test_pbs)
        #        self.current_worker.finished.connect(self.handle_command_finished)
        self.disable_test_pbs_enable_cancel()
        self.cancelPB.clicked.connect(self.current_worker.terminate)
        self.cancelPB.clicked.connect(self.reset_test_pbs)
        # self.waiting_dialog = QMessageBox()
        # self.waiting_dialog.setWindowTitle("Running Ph2_ACF")
        # self.waiting_dialog.setText("test with lights on")
        # #self.waiting_dialog.setStandardButtons(QMessageBox.NoButton)
        # self.waiting_dialog.setStandardButtons(QMessageBox.Cancel)
        # self.waiting_dialog.buttonClicked.connect(lambda button: self.current_worker.terminate())
        # self.waiting_dialog.show()
        # self.current_worker.finished.connect(self.waiting_dialog.accept)

        self.current_worker.start()

    #        self.log_worker.start()

    def run_dark_test(self):
        """Run Dark Test"""
        self.log_output("=== Running Dark Test ===")

        def handle_dark_test(success, stdout, stderr):
            if success:
                try:
                    self.hvONTestLED.setStyleSheet(
                        "background-color: rgb(85, 170, 0);"
                    )  # Green
                    self.hvONTestCB.setChecked(True)
                    self.checkIDPB.setEnabled(True)
                    self.hvOFFTestPB.setEnabled(True)  # Enable test 2
                    self.hvONTestPB.setEnabled(True)  # Enable test 3
                    # {"message": "Entry created", "moduleTestAnalysisName": "Module_PS_26_IPG-10005_Run_run590_Result_Test7"}
                    moduleTestAnalysisName = re.search(
                        r".*moduleTestAnalysisName\": \"(.*?)\"}", stdout
                    ).group(1)
                    # query DB from  http://....:5000/module_test_analysis endpoint
                    # get the result from the DB
                    analysisData = self.make_api_request(
                        "module_test_analysis/" + moduleTestAnalysisName, "GET"
                    )
                    if analysisData[0]:
                        print(analysisData[1])
                        self.analysisURL = analysisData[1]["analysisFile"]
                        res = {}
                        for k in analysisData[1]["analysisSummary"].keys():
                            print(k)
                            if "Average" in k:
                                chip = k.split("_")[-1]
                                hybrid = int(k.split("_")[-2][1:]) % 2
                                res[(hybrid, chip)] = analysisData[1][
                                    "analysisSummary"
                                ][k]

                        noise_text = "<html><head/><body><p>Noise:</p>"
                        noise_text += "<table border=1>"
                        noise_text += (
                            "<tr><th></th><th>Hybrid 0</th><th>Hybrid 1</th></tr>"
                        )
                        noise_text += (
                            "<tr><td>SSA</td><td>%2.2f</td><td>%2.2f</td></tr>"
                            % (res[(0, "SSA")], res[(1, "SSA")])
                        )
                        noise_text += (
                            "<tr><td>MPA</td><td>%2.2f</td><td>%2.2f</td></tr>"
                            % (res[(0, "MPA")], res[(1, "MPA")])
                        )
                        noise_text += "</body></html>"
                        print(noise_text)
                        self.resultsLabel.setText(noise_text)
                        # ensure label is redrawn
                        self.resultsLabel.repaint()
                        self.resultsLabel.setToolTip(
                            str(analysisData[1]["analysisSummary"])
                        )
                except Exception as e:
                    self.log_output(f"Error parsing test results: {e}")
            #                self.log_worker.terminate()

            else:
                self.hvONTestLED.setStyleSheet("background-color: red;")
                self.hvONTestCB.setChecked(False)
                self.log_output(f"Dark test error: {stderr}")
                self.reset_test_pbs()
            self.handle_command_finished(success, stdout, stderr)

        if self.current_worker:
            self.current_worker.finished.disconnect()
        self.current_worker = CommandWorker(
            self.expand_placeholders(self.darkTestCommandLE.text())
        )
        self.current_worker.finished.connect(handle_dark_test)
        #      self.current_worker.finished.connect(self.reset_test_pbs)
        # self.current_worker.finished.connect(self.handle_command_finished)
        self.disable_test_pbs_enable_cancel()
        self.cancelPB.clicked.connect(self.current_worker.terminate)
        self.cancelPB.clicked.connect(self.reset_test_pbs)

        # self.waiting_dialog = QMessageBox()
        # self.waiting_dialog.setWindowTitle("Running Ph2_ACF")
        # self.waiting_dialog.setText("test with modules in dark")
        # #self.waiting_dialog.setStandardButtons(QMessageBox.NoButton)
        # self.waiting_dialog.setStandardButtons(QMessageBox.Cancel)
        # self.waiting_dialog.buttonClicked.connect(lambda button: self.current_worker.terminate())
        # self.waiting_dialog.show()
        # self.current_worker.finished.connect(self.waiting_dialog.accept)
        # self.current_worker.finished.connect(self.log_worker.quit)

        self.current_worker.start()

    def open_ph2acf_log(self):
        self.log_worker = CommandWorker(
            "konsole -e tail -f /home/thermal/BurnIn_moduleTest/logs/Ph2_ACF.log"
        )
        self.log_worker.start()

    def disconnect_connection(self, cable_id, port):
        """Disconnect a cable's detSide connections"""
        try:
            data = {
                "cable": cable_id,
            }
            self.make_api_request(
                endpoint="disconnect_all_detSide", method="POST", data=data
            )
        except Exception as e:
            self.log_output(f"Error disconnecting: {str(e)}")

    def connect_power(self):
        self.log_output("=== Connecting Power ===")
        # First disconnect any existing connections
        self.disconnect_connection(self.powerCB.currentText(), "power")

        # Then make the new connection
        data = {
            "cable1": self.moduleLE.text(),
            "cable2": (
                self.powerCB.currentText().split(";")[0]
                if ";" in self.powerCB.currentText()
                else self.powerCB.currentText()
            ),
            "port1": "power",
            "port2": (
                ("" + self.powerCB.currentText().split(";")[1])
                if ";" in self.powerCB.currentText()
                else "power"
            ),
        }
        success, result = self.make_api_request(
            endpoint="connect", method="POST", data=data  # Simplified endpoint
        )

        # Update connection status and LEDs
        self.update_connection_status()
        self.update_connection_leds()

    def connect_fiber(self):
        self.log_output("=== Connecting Fiber ===")
        # First disconnect any existing connections
        self.disconnect_connection(self.fiberCB.currentText(), "A")

        # Then make the new connection
        fib = self.fiberCB.currentText()
        data = {
            "cable1": self.moduleLE.text(),
            "cable2": fib.split(";")[0] if ";" in fib else fib,
            "port1": "fiber",
            "port2": fib.split(";")[1] if ";" in fib else "A",
        }
        success, result = self.make_api_request(
            endpoint="connect", method="POST", data=data  # Simplified endpoint
        )

        # Update connection status and LEDs
        self.update_connection_status()
        self.update_connection_leds()

    def apply_settings(self):
        """Apply current settings"""
        self.log_output("=== Applying Settings ===")

        # Save settings to file
        self.save_settings()

        # Reconnect MQTT
        if self.setup_mqtt():
            self.log_output("MQTT settings applied successfully")
        else:
            self.log_output("Failed to apply MQTT settings")

    def update_module_list(self):
        """Update the module list based on current filters"""
        self.module_db.update_module_list()
        # Store full module list
        self.all_modules = self.module_db.all_modules

        # Update mounted modules dict
        self.mounted_modules = {
            m.get("mounted_on", ""): m.get("moduleName", "")
            for m in self.all_modules
            if m.get("mounted_on")
        }

    def disconnect_module(self, module_id):
        """Disconnect all connections for a module"""
        try:
            self.log_output(f"Disconnecting module: {module_id}")
            data = {
                "cable": module_id,
            }

            success, result = self.make_api_request(
                endpoint="disconnect_all_crateSide", method="POST", data=data
            )

            # Update the display
            self.update_module_list()
            self.update_connection_status()

        except Exception as e:
            self.log_output(f"Error disconnecting module: {str(e)}")
            self.show_error_dialog(f"Failed to disconnect module: {str(e)}")

    def module_changed(self):

        self.load_module_details()
        module_id = self.moduleLE.text()
        query = {"cable": module_id, "side": "crateSide"}
        response = requests.post(self.get_api_url("snapshot"), json=query)
        if response.status_code == 200:
            snapshot = response.json()
            print("LOADED:", snapshot.get("1", None))
            print("LOADED:", snapshot.get("3", None))
            fiber = snapshot.get("1", None)
            power = snapshot.get("3", None)
            if fiber and len(fiber["connections"]) > 0:
                fib = fiber["connections"][0]["cable"]
                fports = fiber["connections"][0]["det_port"]
                fports = [x for x in fports if x != "A"]
                self.fiberCB.setCurrentText(
                    fib + (f";{fports[0]}" if len(fports) > 0 else "")
                )
                print(fib + (f";{fports[0]}" if len(fports) > 0 else ""))
            if power and len(power["connections"]) > 0:
                pcable = power["connections"][0]["cable"]
                pports = power["connections"][0]["det_port"]
                pports = [x for x in pports if x != "power" and x != "A"]
                self.powerCB.setCurrentText(
                    pcable + (f";{pports[0]}" if len(pports) > 0 else "")
                )
                print(pcable + (f";{pports[0]}" if len(pports) > 0 else ""))

        # LOADED: {'crate_port': 'fiber', 'connections': [{'cable': 'SfibA', 'line': 1, 'det_port': ['A'], 'crate_port': ['67']}, {'cable': 'FC7OT8', 'line': 3, 'det_port': ['OG1'], 'crate_port': []}]}
        # LOADED: {'crate_port': 'power', 'connections': [{'cable': 'BINT1', 'line': 3, 'det_port': ['power'], 'crate_port': ['HV', 'HVLV']}, {'cable': 'P001', 'line': 12, 'det_port': ['A', 'B12'], 'crate_port': ['HV12']}, {'cable': 'H48', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT0', 'line': 12, 'det_port': ['12'], 'crate_port': []}]}
        # print("LOADED:",self.current_module_data["crateSide"])
        # fiber=self.current_module_data["crateSide"].get("2","")
        # power=self.current_module_data["crateSide"].get("3","")
        # print(str(fiber[0])+";"+str(fiber[1]//2),power[0]+";"+str(power[1]))
        self.update_connection_status()

    def update_connection_status(self):
        """Update the connection status labels showing both connection directions"""
        try:
            power_id = self.powerCB.currentText()
            fiber_id = self.fiberCB.currentText()
            power_id_slot = ""
            if ";" in power_id:
                power_id_slot = power_id.split(";")[1]
                power_id = power_id.split(";")[0]
            fiber_id_slot = ""
            if ";" in fiber_id:
                fiber_id_slot = fiber_id.split(";")[1]
                fiber_id = fiber_id.split(";")[0]
            # Get power connections
            power_status = set()
            module_id = self.moduleLE.text()
            if module_id:
                det_endpoint, crate_endpoints = self.get_power_endpoints_from_module(
                    module_id
                )
                if crate_endpoints:
                    for crate_endpoint in crate_endpoints:
                        power_status.add(f"{module_id} <--> {crate_endpoint}")

            # Get fiber connections
            fiber_status = set()
            if fiber_id:
                det_endpoint, crate_endpoint = self.get_fiber_endpoints(
                    fiber_id, fiber_id_slot
                )
                if det_endpoint and crate_endpoint:
                    fiber_status.add(f"{det_endpoint} <--> {crate_endpoint}")
                    self.fiber_endpoint = crate_endpoint

            # Update labels
            self.powerConnectionLabel.setText(
                "\n".join(power_status) if power_status else "Not connected"
            )
            self.fiberConnectionLabel.setText(
                "\n".join(fiber_status) if fiber_status else "Not connected"
            )

            # Update LED colors
            self.update_connection_leds()

        except Exception as e:
            self.log_output(f"Error updating connection status: {str(e)}")
            self.powerConnectionLabel.setText("Error checking status")
            self.fiberConnectionLabel.setText("Error checking status")

    def check_connection_match(self, det_endpoint):
        """Check if the detected connection matches the selected module"""

        selected_module = self.moduleLE.text()
        return selected_module == "" or selected_module == det_endpoint

    def update_connection_leds(self):
        """Update LED colors based on connection status and matching"""
        try:
            power_id = self.powerCB.currentText()
            fiber_id = self.fiberCB.currentText()
            power_id_slot = ""
            if ";" in power_id:
                power_id_slot = power_id.split(";")[1]
                power_id = power_id.split(";")[0]
            fiber_id_slot = ""
            if ";" in fiber_id:
                fiber_id_slot = fiber_id.split(";")[1]
                fiber_id = fiber_id.split(";")[0]
            # Get power connection status
            if power_id:
                det_endpoint, _ = self.get_power_endpoints(power_id, power_id_slot)
                if det_endpoint:
                    if self.check_connection_match(det_endpoint):
                        self.connectPowerLED.setStyleSheet(
                            "background-color: rgb(85, 170, 0);"
                        )  # Green
                    else:
                        self.connectPowerLED.setStyleSheet(
                            "background-color: rgb(255, 255, 0);"
                        )  # Yellow
                else:
                    self.connectPowerLED.setStyleSheet("background-color: red;")

            # Get fiber connection status
            if fiber_id:
                det_endpoint, _ = self.get_fiber_endpoints(fiber_id, fiber_id_slot)
                if det_endpoint:
                    if self.check_connection_match(det_endpoint):
                        self.connectFiberLED.setStyleSheet(
                            "background-color: rgb(85, 170, 0);"
                        )  # Green
                    else:
                        self.connectFiberLED.setStyleSheet(
                            "background-color: rgb(255, 255, 0);"
                        )  # Yellow
                else:
                    self.connectFiberLED.setStyleSheet("background-color: red;")

        except Exception as e:
            self.log_output(f"Error updating LEDs: {str(e)}")

    def get_fiber_endpoints(self, fiber_id, fiber_id_slot):
        """Get both detSide and crateSide endpoints for a fiber connection"""
        try:
            # Get detSide path
            data = {"cable": fiber_id, "side": "detSide"}
            det_response = requests.post(
                f"{self.dbEndpointLE.text()}/snapshot", json=data
            )
            if det_response.status_code != 200:
                return None, None
            det_snapshot = det_response.json()
            det_endpoint = None

            if fiber_id_slot != "":
                # filter to get only the lines with det_port=fiber_id_slot
                det_snapshot = {
                    k: v
                    for k, v in det_snapshot.items()
                    if v.get("det_port") == fiber_id_slot
                }

            for line in det_snapshot:
                if det_snapshot[line]["connections"]:
                    # Get the last connection in the detSide path
                    det_endpoint = det_snapshot[line]["connections"][-1]["cable"]
                    break

            # Get crateSide path from the module
            # f det_endpoint:
            if True:
                data = {"cable": fiber_id, "side": "crateSide"}

                crate_response = requests.post(
                    f"{self.dbEndpointLE.text()}/snapshot", json=data
                )
                if crate_response.status_code == 200:
                    crate_snapshot = crate_response.json()
                    print("Crate", crate_snapshot)
                    #     Crate {'1': {'crate_port': 'A', 'det_port': '1', 'connections': [{'cable': 'D3', 'line': 1, 'det_port': ['A'], 'crate_port': ['P12']}, {'cable': 'FC7OT5', 'line': 1, 'det_port': ['OG0'], 'crate_port': []}]}, '2': {'crate_port': 'A', 'det_port': '1', 'connections': [{'cable': 'D3', 'line': 2, 'det_port': ['A'], 'crate_port': ['P12']}, {'cable': 'FC7OT5', 'line': 2, 'det_port': ['OG0'], 'crate_port': []}]}, '3': {'crate_port': 'A', 'det_port': '2', 'connections': [{'cable': 'D3', 'line': 3, 'det_port': ['A'], 'crate_port': ['P34']}, {'cable': 'FC7OT5', 'line': 3, 'det_port': ['OG1'], 'crate_port': []}]}, '4': {'crate_port': 'A', 'det_port': '2', 'connections': [{'cable': 'D3', 'line': 4, 'det_port': ['A'], 'crate_port': ['P34']}, {'cable': 'FC7OT5', 'line': 4, 'det_port': ['OG1'], 'crate_port': []}]}, '5': {'crate_port': 'A', 'det_port': '3', 'connections': [{'cable': 'D3', 'line': 5, 'det_port': ['A'], 'crate_port': ['P56']}, {'cable': 'FC7OT5', 'line': 5, 'det_port': ['OG2'], 'crate_port': []}]}, '6': {'crate_port': 'A', 'det_port': '3', 'connections': [{'cable': 'D3', 'line': 6, 'det_port': ['A'], 'crate_port': ['P56']}, {'cable': 'FC7OT5', 'line': 6, 'det_port': ['OG2'], 'crate_port': []}]}, '7': {'crate_port': 'A', 'det_port': '4', 'connections': [{'cable': 'D3', 'line': 7, 'det_port': ['A'], 'crate_port': ['P78']}, {'cable': 'FC7OT5', 'line': 7, 'det_port': ['OG3'], 'crate_port': []}]}, '8': {'crate_port': 'A', 'det_port': '4', 'connections': [{'cable': 'D3', 'line': 8, 'det_port': ['A'], 'crate_port': ['P78']}, {'cable': 'FC7OT5', 'line': 8, 'det_port': ['OG3'], 'crate_port': []}]}, '9': {'crate_port': 'A', 'det_port': '5', 'connections': [{'cable': 'D3', 'line': 9, 'det_port': ['A'], 'crate_port': ['P910']}, {'cable': 'FC7OT5', 'line': 9, 'det_port': ['OG4'], 'crate_port': []}]}, '10': {'crate_port': 'A', 'det_port': '5', 'connections': [{'cable': 'D3', 'line': 10, 'det_port': ['A'], 'crate_port': ['P910']}, {'cable': 'FC7OT5', 'line': 10, 'det_port': ['OG4'], 'crate_port': []}]}, '11': {'crate_port': 'A', 'det_port': '6', 'connections': [{'cable': 'D3', 'line': 11, 'det_port': ['A'], 'crate_port': ['P1112']}, {'cable': 'FC7OT5', 'line': 11, 'det_port': ['OG5'], 'crate_port': []}]}, '12': {'crate_port': 'A', 'det_port': '6', 'connections': [{'cable': 'D3', 'line': 12, 'det_port': ['A'], 'crate_port': ['P1112']}, {'cable': 'FC7OT5', 'line': 12, 'det_port': ['OG5'], 'crate_port': []}]}}

                    if fiber_id_slot != "":
                        # filter to get only the lines with det_port=fiber_id_slot
                        crate_snapshot = {
                            k: v
                            for k, v in crate_snapshot.items()
                            if v["det_port"] == fiber_id_slot
                        }

                    for line in crate_snapshot.keys():
                        if (
                            line in crate_snapshot
                            and crate_snapshot[line]["connections"]
                        ):
                            last_conn = crate_snapshot[line]["connections"][-1]
                            ports = last_conn["crate_port"] + last_conn["det_port"]
                            port = ports[0] if ports else "?"
                            return det_endpoint, f"{last_conn['cable']}_{port}"

            return None, None
        except Exception as e:
            self.log_output(f"Error getting fiber endpoints: {str(e)}")
            return None, None

    def get_power_endpoints_from_module(self, module_id):
        """Get the power endpoint from the module's crateSide connections"""
        ret = (module_id, [])
        if not module_id:
            self.log_output("No module ID provided")
            return ret
        try:
            response = requests.post(
                self.get_api_url("snapshot"),
                json={"cable": module_id, "side": "crateSide"},
            )
            if response.status_code == 200:
                snapshot = response.json()
                print("json:", snapshot)
                for line in snapshot:
                    if snapshot[line]["connections"]:
                        last_conn = snapshot[line]["connections"][-1]
                        print("Last connection:", last_conn)
                        # Get the last connection in the crateSide path
                        if "FC" in last_conn["cable"]:
                            continue
                        # set LV/HV channels
                        if "XSLOT" in last_conn["cable"]:
                            self.caen.setLV(
                                "LV" + last_conn["cable"][5:] + f".{last_conn['line']}"
                            )
                        if "ASLOT" in last_conn["cable"]:
                            self.caen.setHV(
                                "HV" + last_conn["cable"][5:] + f".{last_conn['line']}"
                            )

                        ret[1].append(f"{last_conn['cable']}.{last_conn['line']}")
            print("ret", ret)
            return ret
        except Exception as e:
            self.log_output(f"Error getting power endpoint: {str(e)}")
            return ret

    def get_power_endpoints(self, power_id, power_id_slot=""):
        """Get both detSide and crateSide endpoints for power connections"""
        try:
            # Get detSide path
            query = {"cable": power_id, "side": "detSide"}

            det_response = requests.post(self.get_api_url("snapshot"), json=query)
            if det_response.status_code != 200:
                return None, []

            det_snapshot = det_response.json()
            det_endpoint = None

            if power_id_slot != "":
                # filter to get only the lines with det_port=power_id_slot
                if "B" == power_id_slot[0]:
                    power_id_slot = power_id_slot[1:]
                det_snapshot = {
                    k: v
                    for k, v in det_snapshot.items()
                    if v.get("crate_port") == "HV%s" % power_id_slot
                }

            for line in det_snapshot:
                if det_snapshot[line]["connections"]:
                    # Get the last connection in the detSide path
                    det_endpoint = det_snapshot[line]["connections"][-1]["cable"]
                    break
            print("Det endpoint", det_endpoint)
            # Get crateSide path from the module
            #            if det_endpoint:
            if True:
                crate_response = requests.post(
                    self.get_api_url("snapshot"),
                    json={"cable": power_id, "side": "crateSide"},
                )
                if crate_response.status_code == 200:
                    crate_snapshot = crate_response.json()
                    crate_endpoints = []
                    # print("PCrate_pre",crate_snapshot)
                    # PCrate_pre {'1': {'crate_port': 'HV1', 'det_port': 'A', 'connections': [{'cable': 'H36', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 1, 'det_port': ['1'], 'crate_port': []}]},
                    # '2': {'crate_port': 'HV2', 'det_port': 'A', 'connections': [{'cable': 'H37', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 2, 'det_port': ['2'], 'crate_port': []}]},
                    # '3': {'crate_port': 'HV3', 'det_port': 'A', 'connections': [{'cable': 'H38', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 3, 'det_port': ['3'], 'crate_port': []}]},
                    # '4': {'crate_port': 'HV4', 'det_port': 'A', 'connections': [{'cable': 'H39', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 4, 'det_port': ['4'], 'crate_port': []}]},
                    # '5': {'crate_port': 'HV5', 'det_port': 'A', 'connections': [{'cable': 'H40', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 5, 'det_port': ['5'], 'crate_port': []}]},
                    # '6': {'crate_port': 'HV6', 'det_port': 'A', 'connections': [{'cable': 'H41', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 6, 'det_port': ['6'], 'crate_port': []}]},
                    # '7': {'crate_port': 'HV7', 'det_port': 'A', 'connections': [{'cable': 'H42', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 7, 'det_port': ['7'], 'crate_port': []}]},
                    # '8': {'crate_port': 'HV8', 'det_port': 'A', 'connections': [{'cable': 'H43', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 8, 'det_port': ['8'], 'crate_port': []}]},
                    # '9': {'crate_port': 'HV9', 'det_port': 'A', 'connections': [{'cable': 'H44', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 9, 'det_port': ['9'], 'crate_port': []}]},
                    # '10': {'crate_port': 'HV10', 'det_port': 'A', 'connections': [{'cable': 'H45', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 10, 'det_port': ['10'], 'crate_port': []}]},
                    # '11': {'crate_port': 'HV11', 'det_port': 'A', 'connections': [{'cable': 'H46', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 11, 'det_port': ['11'], 'crate_port': []}]}, '12': {'crate_port': 'HV12', 'det_port': 'A', 'connections': [{'cable': 'H47', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'ASLOT2', 'line': 12, 'det_port': ['12'], 'crate_port': []}]},
                    # '13': {'crate_port': 'LV1', 'det_port': 'A', 'connections': [{'cable': 'L5', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT7', 'line': 5, 'det_port': ['down'], 'crate_port': []}]}, '14': {'crate_port': 'LV1', 'det_port': 'A', 'connections': [{'cable': 'L5', 'line': 2, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT7', 'line': 6, 'det_port': ['down'], 'crate_port': []}]}, '15': {'crate_port': 'LV1', 'det_port': 'A', 'connections': [{'cable': 'L5', 'line': 3, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT7', 'line': 7, 'det_port': ['down'], 'crate_port': []}]},
                    # '16': {'crate_port': 'LV1', 'det_port': 'A', 'connections': [{'cable': 'L5', 'line': 4, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT7', 'line': 8, 'det_port': ['down'], 'crate_port': []}]}, '17': {'crate_port': 'LV2', 'det_port': 'A', 'connections': [{'cable': 'L13', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT8', 'line': 1, 'det_port': ['up'], 'crate_port': []}]}, '18': {'crate_port': 'LV2', 'det_port': 'A', 'connections': [{'cable': 'L13', 'line': 2, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT8', 'line': 2, 'det_port': ['up'], 'crate_port': []}]}, '19': {'crate_port': 'LV2', 'det_port': 'A', 'connections': [{'cable': 'L13', 'line': 3, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT8', 'line': 3, 'det_port': ['up'], 'crate_port': []}]}, '20': {'crate_port': 'LV2', 'det_port': 'A', 'connections': [{'cable': 'L13', 'line': 4, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT8', 'line': 4, 'det_port': ['up'], 'crate_port': []}]}, '21': {'crate_port': 'LV3', 'det_port': 'A', 'connections': [{'cable': 'L9', 'line': 1, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT8', 'line': 5, 'det_port': ['down'], 'crate_port': []}]}, '22': {'crate_port': 'LV3', 'det_port': 'A', 'connections': [{'cable': 'L9', 'line': 2, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT8', 'line': 6, 'det_port': ['down'], 'crate_port': []}]}, '23': {'crate_port': 'LV3', 'det_port': 'A', 'connections': [{'cable': 'L9', 'line': 3, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT8', 'line': 7, 'det_port': ['down'], 'crate_port': []}]},
                    # '24': {'crate_port': 'LV3', 'det_port': 'A', 'connections': [{'cable': 'L9', 'line': 4, 'det_port': ['A'], 'crate_port': ['A']}, {'cable': 'XSLOT8', 'line': 8, 'det_port': ['down'], 'crate_port': []}]}}

                    if power_id_slot != "":
                        crate_snapshot = {
                            k: v
                            for k, v in crate_snapshot.items()
                            if v["crate_port"] == "HV%s" % power_id_slot
                            or int(k) == int(power_id_slot) + 12
                        }
                    #                   print("PCrate_post",crate_snapshot)
                    # Look at power lines (3,4)
                    for line in crate_snapshot.keys():
                        print(crate_snapshot[line]["connections"])
                        if (
                            line in crate_snapshot
                            and crate_snapshot[line]["connections"]
                        ):
                            last_conn = crate_snapshot[line]["connections"][-1]
                            ports = last_conn["crate_port"] + last_conn["det_port"]
                            port = ports[0] if ports else "?"
                            # crate_endpoints.append(f"{last_conn['cable']}_{port}_{last_conn['line']}")
                            crate_endpoints.append(
                                f"{last_conn['cable']}.{last_conn['line']}"
                            )
                            if "XSLOT" in last_conn["cable"]:
                                self.caen.setLV(
                                    "LV"
                                    + last_conn["cable"][5:]
                                    + f".{last_conn['line']}"
                                )
                            if "ASLOT" in last_conn["cable"]:
                                self.caen.setHV(
                                    "HV"
                                    + last_conn["cable"][5:]
                                    + f".{last_conn['line']}"
                                )

                    return det_endpoint, crate_endpoints

            return None, []
        except Exception as e:
            self.log_output(f"Error getting power endpoints: {str(e)}")
            return None, []

    # def setup_module_details_tab(self):
    #     """Setup the module details tab"""
    #     # Set up tree widget
    #     self.detailsTree.setHeaderLabels(['Field', 'Value'])
    #     self.detailsTree.setColumnWidth(0, 200)

    #     # Connect buttons
    #     self.editDetailsButton.clicked.connect(self.edit_selected_detail)
    #     self.saveDetailsButton.clicked.connect(self.save_module_details)

    # def populate_details_tree(self, data, parent=None):
    #     """Recursively populate the details tree with module data"""
    #     if parent is None:
    #         self.detailsTree.clear()
    #         parent = self.detailsTree

    #     if isinstance(data, dict):
    #         for key, value in sorted(data.items()):
    #             item = QTreeWidgetItem([str(key), ''])
    #             if parent == self.detailsTree:
    #                 parent.addTopLevelItem(item)
    #             else:
    #                 parent.addChild(item)
    #             self.populate_details_tree(value, item)
    #     elif isinstance(data, list):
    #         for i, value in enumerate(data):
    #             if isinstance(value, dict) and 'childName' in value:
    #                 # Special handling for child components
    #                 item = QTreeWidgetItem([value['childName'], value.get('childType', '')])
    #             else:
    #                 item = QTreeWidgetItem([f"[{i}]", ''])
    #             parent.addChild(item)
    #             self.populate_details_tree(value, item)
    #     else:
    #         parent.setText(1, str(data))

    # def edit_selected_detail(self):
    #     """Edit the selected detail"""
    #     item = self.detailsTree.currentItem()
    #     if item and item.text(1):  # Only edit leaf nodes
    #         dialog = QInputDialog()
    #         dialog.setWindowTitle("Edit Value")
    #         dialog.setLabelText(f"Edit value for {item.text(0)}:")
    #         dialog.setTextValue(item.text(1))

    #         if dialog.exec_():
    #             item.setText(1, dialog.textValue())

    def tree_to_dict(self, item):
        """Convert tree widget items back to dictionary recursively"""
        result = {}

        for i in range(item.childCount()):
            child = item.child(i)
            key = child.text(0)

            if child.childCount() > 0:
                # This is a non-leaf node, recurse
                value = self.tree_to_dict(child)
            else:
                # This is a leaf node, get its value
                value = child.text(1)
                # Try to convert to appropriate type
                try:
                    if value.lower() == "true":
                        value = True
                    elif value.lower() == "false":
                        value = False
                    elif value.isdigit():
                        value = int(value)
                    elif value.replace(".", "", 1).isdigit():
                        value = float(value)
                except:
                    pass

            # Handle nested paths using dot notation
            key_parts = key.split(".")
            current_dict = result
            for part in key_parts[:-1]:
                if part not in current_dict:
                    current_dict[part] = {}
                current_dict = current_dict[part]
            current_dict[key_parts[-1]] = value

        return result

    def merge_dicts(self, dict1, dict2):
        """Recursively merge two dictionaries"""
        result = dict1.copy()
        for key, value in dict2.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self.merge_dicts(result[key], value)
            else:
                result[key] = value
        return result

    # def save_module_details(self):
    #     """Save the modified module details back to the database"""
    #     try:
    #         # First get current module data to preserve all fields
    #         response = requests.get(self.get_api_url(f'modules/{self.current_module_id}'))
    #         if response.status_code != 200:
    #             self.log_output(f"Error fetching module: {response.text}")
    #             return

    #         current_data = response.json()

    #         # Convert tree widget back to dictionary
    #         new_data = self.tree_to_dict(self.detailsTree.invisibleRootItem())
    #         print(new_data)
    #         print(current_data)
    #         # Recursively merge the data
    #         merged_data = self.merge_dicts(current_data, new_data)

    #         # Remove _id from merged data
    #         if "_id" in merged_data:
    #             del merged_data["_id"]

    #         # Make API request to update module
    #         print(merged_data)
    #         #return #debug check what it would do
    #         response = requests.put(
    #             self.get_api_url(f'modules/{self.current_module_id}'),
    #             json=merged_data
    #         )

    #         if response.status_code == 200:
    #             self.log_output("Module details updated successfully")
    #             self.update_module_list()  # Refresh the module list to show updated data
    #         else:
    #             self.log_output(f"Error updating module: {response.text}")

    #     except Exception as e:
    #         self.log_output(f"Error saving module details: {str(e)}")

    def view_module_details(self):
        """View details for selected module"""
        # selected_items = self.treeWidget.selectedItems()
        # if not selected_items:
        #     self.log_output("No module selected")
        #     return

        # module_id = selected_items[0].text(0)  # Get module name
        # self.moduleLE.setText(module_id)  # This will trigger load_module_details
        # print("here")
        self.tabWidget.setCurrentIndex(2)

    def setup_inventory_buttons(self):
        """Setup buttons for inventory tab"""
        buttonLayout = QHBoxLayout()

        spacer = QSpacerItem(40, 20, QSizePolicy.Expanding, QSizePolicy.Minimum)
        buttonLayout.addItem(spacer)

        # Add button layout to tab

        # Connect the "View Details" button signal
        self.viewDetailsPB.clicked.connect(self.view_module_details)

    def reset_test_states(self):
        """Reset all test states to initial condition"""
        # Reset LED colors
        self.checkIDLED.setStyleSheet("background-color: rgb(255, 255, 0);")  # Yellow
        self.hvOFFTestLED.setStyleSheet("background-color: rgb(255, 255, 0);")
        self.hvONTestLED.setStyleSheet("background-color: rgb(255, 255, 0);")

        # Reset checkboxes
        self.hvOFFTestCB.setChecked(False)
        self.hvONTestCB.setChecked(False)

        # Enable tests 2 and 3
        self.hvOFFTestPB.setEnabled(True)
        self.hvONTestPB.setEnabled(True)

        # Clear ID label
        self.checkIDlabel.setText("ID:")

        # Reset results label
        self.resultsLabel.setText(
            "<html><head/><body><p>Noise:</p><p>MPA: 0.0</p><p>SSA: 0.0</p></body></html>"
        )

    def update_filters_from_layer(self, layer_type):
        """Update speed and spacer filters based on selected layer type"""
        if layer_type == "any":
            self.speedCB.setCurrentText("any")
            self.spacerCB.setCurrentText("any")
            return

        if layer_type in self.layers_to_filters:
            filters = self.layers_to_filters[layer_type]
            self.speedCB.setCurrentText(filters["speed"])
            self.spacerCB.setCurrentText(filters["spacer"])

    def update_layer_from_ring(self, ring_id):
        """Update layer type selection based on ring ID"""
        if not ring_id:
            return

        # Find matching layer type
        matching_layer = "any"
        for layer in self.layers_to_filters:
            if ring_id.startswith(layer.split("_")[0]):  # Match L1, L2, L3 part
                # If we have an exact match with the full layer (e.g. L1_47), use it
                if ring_id.startswith(layer):
                    matching_layer = layer
                    break
                # If we only match the L3 part, use it
                elif layer == "L3":
                    matching_layer = layer
                    break
                # Otherwise keep looking for a better match
                elif matching_layer == "any":
                    matching_layer = layer

        # Update layer type combo box
        self.module_db.ui.layertypeCB.setCurrentText(matching_layer)

    def mount_module(self):
        """Mount a module at the specified ring position"""
        module_id = self.moduleLE.text()
        ring_id = self.ringLE.text()
        position = self.positionLE.text()

        if not all([module_id, ring_id, position]):
            self.show_error_dialog("Please specify module ID, ring ID and position")
            return

        # Validate position is a number
        try:
            position_num = int(position)
        except ValueError:
            self.show_error_dialog(f"Invalid position: '{position}' is not a number")
            return

        # Check if position is valid for the layer
        max_positions = {"L1": 18, "L2": 26, "L3": 36}
        layer = next(
            (key for key in max_positions.keys() if ring_id.startswith(key)), None
        )
        if not layer:
            self.show_error_dialog(
                f"Invalid ring ID format: {ring_id}\n\n"
                f"Ring ID must start with one of: L1, L2, L3"
            )
            return

        if position_num < 1 or position_num > max_positions[layer]:
            self.show_error_dialog(
                f"Invalid position for {layer}\n\n"
                f"Position {position_num} is out of range.\n"
                f"Valid positions for {layer} are 1 to {max_positions[layer]}"
            )
            return

        # Check if module is already mounted somewhere
        success, modules = self.make_api_request(endpoint="modules", method="GET")
        if not success:
            self.show_error_dialog(
                "Failed to check module mounting status.\nPlease check your database connection."
            )
            return

        for module in modules:
            # Check if this module is already mounted somewhere
            if module.get("moduleName") == module_id and module.get("mounted_on"):
                self.show_error_dialog(
                    f"Module already mounted\n\n"
                    f"Module {module_id} is already mounted at position {module.get('mounted_on')}\n"
                    f"Please unmount it first if you want to move it."
                )
                return

            # Check if there's already a module in the target position
            if module.get("mounted_on") == f"{ring_id};{position}":
                self.show_error_dialog(
                    f"Position already occupied\n\n"
                    f"Position {ring_id};{position} is already occupied by module {module.get('moduleName')}\n"
                    f"Please unmount that module first."
                )
                return

        # If we get here, all validations passed
        # First get current module data
        response = requests.get(self.get_api_url(f"modules/{module_id}"))
        if response.status_code != 200:
            self.show_error_dialog(f"Error fetching module data: {response.text}")
            return

        module_data = response.json()
        mounted_on = f"{ring_id};{position}"

        # Update only the relevant fields while preserving others
        module_data["mounted_on"] = mounted_on
        module_data["status"] = "MOUNTED"
        module_data["position"] = "OnDet@ " + mounted_on
        # Remove _id from mounted_on
        if "_id" in module_data:
            del module_data["_id"]

        success, result = self.make_api_request(
            endpoint=f"modules/{module_id}", method="PUT", data=module_data
        )

        if success:
            self.log_output(f"Module {module_id} mounted at {mounted_on}")
            self.unmountPB.setEnabled(True)
            self.update_module_list()
            self.draw_ring()  # Redraw ring to show mounted modules
        else:
            self.show_error_dialog(f"Failed to mount module: {result}")

    def unmount_module(self):
        """Unmount the currently selected module"""
        module_id = self.moduleLE.text()
        print("UNMOUNTING", module_id)

        if not module_id:
            self.log_output("No module selected")
            return

        # First get current module data
        response = requests.get(self.get_api_url(f"modules/{module_id}"))
        if response.status_code != 200:
            self.log_output(f"Error fetching module: {response.text}")
            return

        module_data = response.json()

        # Update only the relevant fields while preserving others
        module_data["mounted_on"] = ""
        module_data["status"] = "un-mounted"
        if "_id" in module_data:
            del module_data["_id"]

        success, result = self.make_api_request(
            endpoint=f"modules/{module_id}", method="PUT", data=module_data
        )

        if success:
            self.log_output(f"Module {module_id} unmounted")
            self.unmountPB.setEnabled(False)
            self.update_module_list()
            self.draw_ring()  # Redraw ring to show mounted modules
        else:
            self.log_output(f"Failed to unmount module: {result}")

    def check_module_mounting_status(self):
        """Check if the current module ID is mounted and update unmount button state"""
        module_id = self.moduleLE.text()

        if not module_id:
            self.unmountPB.setEnabled(False)
            return

        # Check if this module ID exists in mounted_modules values
        is_mounted = any(
            module_id == mounted_id for mounted_id in self.mounted_modules.values()
        )
        self.unmountPB.setEnabled(is_mounted)

    def load_module_details(self):
        """Load module details in the background when module ID changes"""
        module_id = self.moduleLE.text()
        if not module_id:
            self.module_db.ui.moduleNameLabel.setText("")
            return

        try:
            response = requests.get(self.get_api_url(f"modules/{module_id}"))
            if response.status_code == 200:
                module_data = response.json()
                self.current_module_data = module_data
                self.current_module_id = module_id

                # Fetch Fuse ID
                self.current_fuse_id = get_module_fuse_id(module_data)
                self.log_output(
                    f"Module {module_id} loaded. Fuse ID: {self.current_fuse_id}"
                )

                # Reset Ph2ACF plots for new module
                self.ph2acf_time = []
                self.ssa_mean_values = []
                self.ssa_max_values = []
                self.mpa_mean_values = []
                self.mpa_max_values = []

                self.module_db.ui.moduleNameLabel.setText(module_id)
                self.module_db.populate_details_tree(module_data)
            else:
                self.log_output(f"Error fetching module details: {response.text}")
        except Exception as e:
            self.log_output(f"Error loading module details: {str(e)}")

    def control_air(self, turn_on):
        """Control air system"""
        self.air_state = turn_on
        #       command = self.airCommandLE.text().format(airOn="1" if turn_on else "0")
        command = self.airCommandLE.text().format(airOn="on" if turn_on else "off")

        def handle_air_result(success, stdout, stderr):
            pass

        if self.current_worker:
            self.current_worker.finished.disconnect()
        self.current_worker = CommandWorker(command)
        self.current_worker.finished.connect(handle_air_result)
        self.current_worker.start()

    def show_test_results(self):
        """Show test results in plots tab"""
        # Switch to plots tab
        self.tabWidget.setCurrentWidget(self.tab_5)

        # Load URL from settings and normalize path
        url = self.resultsUrlLE.text()
        if url.startswith("file:"):
            # Remove file: prefix if present and make absolute path
            url = url.replace("file:", "", 1)
            url = os.path.abspath(url)
            url = f"file://{url}"
        elif not url.startswith("http://") and not url.startswith("https://"):
            # If no protocol specified, assume local file
            url = os.path.abspath(url)
            url = f"file://{url}"

        # Try to load the content into text browser
        try:
            self.resultsBrowser.setSource(QUrl(url))
            self.resultsBrowser.reload()
            self.log_output(f"Loading results from: {url}")
        except Exception as e:
            self.resultsBrowser.setHtml(f"""
                <h2>Error loading results</h2>
                <p>Could not load: {url}</p>
                <p>Error: {str(e)}</p>
                <p>Click 'Open in System Browser' below to view results in your default web browser.</p>
            """)
            self.log_output(f"Error loading results: {str(e)}")

    def open_results_in_browser(self):
        """Open test results in system default browser"""
        #       self.analysisUrl
        #       url = self.resultsUrlLE.text()
        #       if url.startswith('file:'):
        #           url = url.replace('file:', '', 1)
        #           url = os.path.abspath(url)
        #           url = f'file://{url}'
        #       elif not url.startswith('http://') and not url.startswith('https://'):
        #           url = os.path.abspath(url)
        #           url = f'file://{url}'
        webbrowser.open(self.analysisURL)

    def on_module_selected(self, module_id):
        """Handle module selection from inventory"""
        self.moduleLE.setText(module_id)
        self.tabWidget.setCurrentIndex(0)  # Switch to first tab


def main():
    app = QApplication(sys.argv)
    window = QMainWindow()
    main_app = MainApp(window)
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    import sys

    main()
