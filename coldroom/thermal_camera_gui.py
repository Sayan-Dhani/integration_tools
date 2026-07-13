from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import QTimer
import logging
import json
import os
import numpy as np
import yaml
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import datetime

logger = logging.getLogger(__name__)


class ThermalCameraTab(QtWidgets.QWidget):
    def __init__(self, system):
        super(ThermalCameraTab, self).__init__()
        self.system = system

        # Load the UI file into a QMainWindow
        self.widget = QtWidgets.QMainWindow()
        uic.loadUi(
            os.path.join(os.path.dirname(__file__), "thermal_camera.ui"), self.widget
        )
        self.ui = self.widget  # Assign the loaded UI to self.ui

        # Initialize camera positions from config file
        self.config_file = os.path.join(os.path.dirname(__file__), "camera_config.yaml")
        self.camera_positions = self.load_camera_config()
        self.camera_fov = 20  # Field of view in degrees for each camera

        # Create layout for this widget and add the UI
        self.layout = QtWidgets.QVBoxLayout(self)
        self.layout.addWidget(self.widget)

        # Initialize matplotlib figures
        self.setup_camera_views()

        # Connect signals
        self.connect_signals()
        self.update_camera_displays()

        # Set default temperature range to CO2 and connect signal
        if hasattr(self.ui, "t_range_comboBox"):
            self.ui.t_range_comboBox.setCurrentText("CO2")
            self.ui.t_range_comboBox.currentTextChanged.connect(
                self.on_temperature_range_changed
            )

        # Setup update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_status)
        self.update_timer.start(1000)  # Update every second

        # Disable controls until thermal camera is started
        self.enable_controls(False)
        self.mounted_modules = None

        # Initialize scaling mode - default to CO2 scaling
        self.use_co2_scaling = True

        logger.info("Thermal camera tab initialized")

    def get_camera_modules_map(self):
        if self.mounted_modules is None:
            logger.debug(
                "Mounted modules not set, returning default camera modules map"
            )
            return {
                "camera1": "Unknown",
                "camera2": "Unknown",
                "camera3": "Unknown",
                "camera4": "Unknown",
            }
        # For each module and camera position, get the closest module within 20 degrees
        camera_modules = {}
        absolute_position = self.get_current_system_position()
        for module_name, module_info in self.mounted_modules.items():
            module_position = module_info["angular_position"]
            module_side = module_info["side"]
            if module_side == "13":
                module_side = "Front"
            elif module_side == "24":
                module_side = "Back"
            close_camera = False
            for camera_name, camera_offset in self.camera_positions.items():
                camera_position = (absolute_position + camera_offset["position"]) % 360
                module_slot = str(module_info.get("mounted_on", "-").split(";")[1])
                if (
                    abs(module_position - camera_position) <= 20
                    and module_side == camera_offset["side"]
                ):
                    camera_modules[camera_name] = f"{module_slot};{module_name}"
                    close_camera = True
                    break
            if not close_camera:
                # Use Unknown if no close camera found
                for camera_name in self.camera_positions.keys():
                    if camera_name not in camera_modules:
                        camera_modules[camera_name] = "Unknown"
        return camera_modules

    def load_camera_config(self):
        """Load camera positions from YAML config file"""
        default_config = {
            "camera1": {"position": 0, "side": "Front"},
            "camera2": {"position": 0, "side": "Back"},
            "camera3": {"position": 180, "side": "Front"},
            "camera4": {"position": 180, "side": "Back"},
        }

        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, "r") as f:
                    config = yaml.safe_load(f)

                # Validate the config structure
                if self.validate_camera_config(config):
                    logger.info(f"Camera config loaded from {self.config_file}")
                    return config
                else:
                    logger.warning("Invalid camera config structure, using defaults")
                    # Save default config to file
                    self.save_camera_config(default_config)
                    return default_config
            else:
                logger.info(
                    f"Config file not found at {self.config_file}, creating with defaults"
                )
                # Save default config to file
                self.save_camera_config(default_config)
                return default_config

        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML config file: {e}")
            # Save default config to file
            self.save_camera_config(default_config)
            return default_config
        except Exception as e:
            logger.error(f"Error loading camera config: {e}")
            # Save default config to file
            self.save_camera_config(default_config)
            return default_config

    def validate_camera_config(self, config):
        """Validate the camera config structure"""
        try:
            if not isinstance(config, dict):
                return False

            required_cameras = ["camera1", "camera2", "camera3", "camera4"]
            for camera in required_cameras:
                if camera not in config:
                    return False
                if not isinstance(config[camera], dict):
                    return False
                if "position" not in config[camera] or "side" not in config[camera]:
                    return False
                if not isinstance(config[camera]["position"], (int, float)):
                    return False
                if not isinstance(config[camera]["side"], str):
                    return False

            return True
        except Exception as e:
            logger.error(f"Error validating config: {e}")
            return False

    def save_camera_config(self, config=None):
        """Save camera positions to YAML config file"""
        try:
            if config is None:
                config = self.camera_positions

            with open(self.config_file, "w") as f:
                yaml.safe_dump(config, f, default_flow_style=False, indent=2)

            logger.info(f"Camera config saved to {self.config_file}")

        except Exception as e:
            logger.error(f"Error saving camera config: {e}")

    def setup_camera_views(self):
        """Setup matplotlib figures for camera views with navigation toolbar"""
        try:
            # Create scene and canvas for individual cameras view
            scene1 = QtWidgets.QGraphicsScene()
            self.ui.graphicsView.setScene(scene1)

            # Create matplotlib figure for individual cameras with adjusted size
            self.cameras_fig = Figure(figsize=(8, 5), dpi=100)  # Increased width
            self.cameras_canvas = FigureCanvas(self.cameras_fig)

            # Create navigation toolbar for camera views
            self.cameras_toolbar = NavigationToolbar(self.cameras_canvas, self.widget)

            # Create a widget to hold both toolbar and canvas
            camera_widget = QtWidgets.QWidget()
            camera_layout = QtWidgets.QVBoxLayout(camera_widget)
            camera_layout.addWidget(self.cameras_toolbar)
            camera_layout.addWidget(self.cameras_canvas)
            camera_layout.setContentsMargins(0, 0, 0, 0)

            # Add the combined widget to the scene
            scene1.addWidget(camera_widget)

            # Create 2x2 grid for cameras with minimal spacing
            self.cameras_axes = self.cameras_fig.subplots(
                2, 2, gridspec_kw={"hspace": 0.15, "wspace": 0.1}
            )
            self.camera_images = []

            # Initialize camera images with proper sizing and coordinate formatting
            camera_index = 0  # Add counter for sequential numbering
            for i in range(2):
                for j in range(2):
                    ax = self.cameras_axes[i, j]
                    img = ax.imshow(
                        np.zeros((24, 32)),
                        cmap="plasma",
                        aspect="equal",
                        interpolation="nearest",
                    )
                    self.camera_images.append(img)
                    camera_index += 1  # Increment for each camera
                    ax.set_title(f"Camera {camera_index}")
                    ax.set_xticks([])
                    ax.set_yticks([])

                    # Set up coordinate formatter to show temperature values
                    ax.format_coord = lambda x, y, ax_ref=ax, img_ref=img: self.format_coord_temperature(
                        x, y, ax_ref, img_ref
                    )

                    # Add colorbar with proper sizing
                    cbar = self.cameras_fig.colorbar(
                        img, ax=ax, fraction=0.046, pad=0.04
                    )
                    cbar.ax.tick_params(labelsize=8)

            # Adjust subplot parameters to remove excess whitespace
            self.cameras_fig.subplots_adjust(
                left=0.05, right=0.95, top=0.95, bottom=0.05
            )

            logger.info("Camera views with navigation toolbar initialized")

        except Exception as e:
            logger.error(f"Error setting up camera views: {e}")

    def format_coord_temperature(self, x, y, ax, img):
        """Format coordinates to show pixel position and temperature value"""
        try:
            # Get the image data
            data = img.get_array()

            # Convert mouse coordinates to array indices
            numrows, numcols = data.shape
            col = int(x + 0.5)
            row = int(y + 0.5)

            # Check if coordinates are within bounds
            if 0 <= col < numcols and 0 <= row < numrows:
                temp_value = data[row, col]
                return f"x={col}, y={row}, T={temp_value:.1f}°C"
            else:
                return f"x={x:.1f}, y={y:.1f}"

        except Exception as e:
            logger.error(f"Error formatting coordinates: {e}")
            return f"x={x:.1f}, y={y:.1f}"

    def snapshot(self):
        """Save current camera views"""
        try:
            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"snapshot_{timestamp}"

            save_dir = os.path.join(os.path.dirname(__file__), "snapshots")
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)

            # Save individual camera views
            img = self.camera_images[0]
            filename = f"{base_filename}_cameras.png"
            filename = os.path.join(save_dir, filename)
            img.figure.savefig(filename, bbox_inches="tight", dpi=300)

        except Exception as e:
            logger.error(f"Error saving snapshot: {e}")

    def enable_controls(self, enabled=True):
        """Enable or disable all controls except Start Thermal Camera button"""
        controls = [
            self.ui.rotate_PB,
            self.ui.go_to_PB,
            self.ui.calibrate_PB,
            self.ui.set_abs_pos_PB,
            self.ui.export_abs_pos_PB,
            #            self.ui.get_frms_PB,
            self.ui.relse_mtr_PB,
            self.ui.run_PB,
            self.ui.stop_PB,
            self.ui.ip_DAngle_LE,
            self.ui.ip_angle_LE,
            self.ui.ip_angle_LE_2,  # This is the 90-degree angle input
            self.ui.ip_abs_pos_LE,
            self.ui.direction_combo,  # Direction combobox
        ]
        for control in controls:
            control.setEnabled(enabled)

    def connect_signals(self):
        """Connect UI signals to their handlers"""
        try:
            # Connect buttons to their respective functions
            self.ui.relse_mtr_PB_2.clicked.connect(self.start_thermal_camera)
            self.ui.rotate_PB.clicked.connect(self.rotate)
            self.ui.go_to_PB.clicked.connect(self.go_to)
            self.ui.calibrate_PB.clicked.connect(self.calibrate)
            self.ui.set_abs_pos_PB.clicked.connect(self.set_absolute_position)
            self.ui.export_abs_pos_PB.clicked.connect(self.export_absolute_position)
            #           self.ui.get_frms_PB.clicked.connect(self.get_frames)
            self.ui.relse_mtr_PB.clicked.connect(self.release_motor)
            self.ui.run_PB.clicked.connect(self.run)
            self.ui.stop_PB.clicked.connect(self.stop)
            self.ui.snapshot_PB.clicked.connect(self.snapshot)

            # Connect camera coordinate setting buttons
            self.ui.camera_set_pos_button_1.clicked.connect(
                lambda: self.set_camera_position(1)
            )
            self.ui.camera_set_pos_button_2.clicked.connect(
                lambda: self.set_camera_position(2)
            )
            self.ui.camera_set_pos_button_3.clicked.connect(
                lambda: self.set_camera_position(3)
            )
            self.ui.camera_set_pos_button_4.clicked.connect(
                lambda: self.set_camera_position(4)
            )

            logger.info("Thermal camera signals connected")
        except Exception as e:
            logger.error(f"Error connecting signals: {e}")

    def set_camera_position(self, camera_id):
        """Set the position for a specific camera"""
        try:
            # Get the line edit widget for this camera
            pos_le = getattr(self.ui, f"camera_pos_le_{camera_id}")

            # Parse the new position
            try:
                new_position = float(pos_le.text())
            except ValueError:
                logger.error(
                    f"Invalid position value for camera {camera_id}: {pos_le.text()}"
                )
                return

            # Validate position range (0-360 degrees)
            if not (0 <= new_position <= 360):
                logger.error(
                    f"Position out of range for camera {camera_id}: {new_position}. Must be 0-360°"
                )
                return

            # Update camera position offset in our data structure
            camera_name = f"camera{camera_id}"
            if camera_name in self.camera_positions:
                old_offset = self.camera_positions[camera_name]["position"]
                self.camera_positions[camera_name]["position"] = new_position

                # Save the updated config to file
                self.save_camera_config()

                # Update the display labels immediately to reflect the new offset
                self.update_camera_displays()

                logger.info(
                    f"Camera {camera_id} offset updated from {old_offset}° to {new_position}° and saved to config"
                )

        except Exception as e:
            logger.error(f"Error setting position for camera {camera_id}: {e}")

    def update_camera_displays(self):
        """Update the camera position and side display labels"""
        try:
            # Get current system position (either from status or from our tracking)
            current_system_pos = self.get_current_system_position()
            camera_modules_map = self.get_camera_modules_map()
            logger.debug(f"Camera modules map: {camera_modules_map}")

            for i, (camera_name, camera_info) in enumerate(
                self.camera_positions.items(), 1
            ):
                # Calculate effective position based on current system position and camera offset
                camera_offset = camera_info["position"]
                effective_position = (current_system_pos + camera_offset) % 360

                # Update position label with effective position
                pos_label = getattr(self.ui, f"camera_pos_label_{i}")
                pos_label.setText(f"{effective_position:.1f}°")

                # Update side label
                side_label = getattr(self.ui, f"camera_side_label_{i}")
                side_label.setText(camera_info["side"])

                module_label = getattr(self.ui, f"camera_module_label_{i}")
                module_label.setText(camera_modules_map.get(camera_name, "Unknown"))

        except Exception as e:
            logger.error(f"Error updating camera displays: {e}")

    def move_camera(self, camera_id, target_angle):
        """Move a specific camera to a target angular position using go_to function"""
        try:
            camera_name = f"camera{camera_id}"
            if camera_name not in self.camera_positions:
                logger.error(f"Invalid camera ID: {camera_id}")
                return False

            # Get the current camera position offset
            camera_offset = self.camera_positions[camera_name]["position"]

            # Calculate the absolute position needed for the system
            # Since camera1 has the same absolute position as the system,
            # other cameras need to account for their offset
            if camera_id == 1:
                # Camera 1: target angle = absolute position
                absolute_position = target_angle
            else:
                # Other cameras: need to calculate based on their offset from camera1
                # The system needs to move to (target_angle - camera_offset)
                # so that this camera ends up at target_angle
                absolute_position = target_angle - camera_offset

            # Normalize to 0-360 range
            absolute_position = absolute_position % 360

            logger.info(f"Moving camera {camera_id} to target {target_angle}°")
            logger.info(
                f"Camera offset: {camera_offset}°, calculated absolute position: {absolute_position}°"
            )

            # Use the go_to function to move to the calculated absolute position
            if self.system._thermalcamera:
                self.system._thermalcamera.go_to({"position": absolute_position})

                # After movement, calculate and display actual positions for all cameras
                # Wait a moment for the system to update (you might want to make this more robust)
                self._update_all_camera_positions_after_move(absolute_position)

                logger.info(
                    f"Camera {camera_id} moved to target position {target_angle}°"
                )
                return True
            else:
                logger.error("Thermal camera system not available")
                return False

        except ValueError as e:
            logger.error(f"Invalid target angle for camera {camera_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error moving camera {camera_id} to {target_angle}°: {e}")
            return False

    def _update_all_camera_positions_after_move(self, new_system_position):
        """Update all camera position displays after a system movement"""
        try:
            # Calculate actual effective positions for all cameras based on new system position
            for camera_name, camera_info in self.camera_positions.items():
                camera_offset = camera_info["position"]
                # Calculate the actual effective position of this camera
                effective_position = (new_system_position + camera_offset) % 360

                # Log the calculated position for verification
                camera_id = camera_name.replace("camera", "")
                logger.debug(
                    f"Camera {camera_id}: system_pos={new_system_position}°, offset={camera_offset}°, effective={effective_position}°"
                )

            # Update the display with calculated positions
            self.update_camera_displays()

        except Exception as e:
            logger.error(f"Error updating camera positions after move: {e}")

    def get_current_system_position(self):
        """Get the current absolute position of the thermal camera system"""
        try:
            if self.system and hasattr(self.system, "status"):
                status = self.system.status.get("thermal_camera", {})
                return status.get("position", 0.0)
            return 0.0
        except Exception as e:
            logger.error(f"Error getting current system position: {e}")
            return 0.0

    def get_camera_effective_position(self, camera_id):
        """Get the effective angular position of a specific camera"""
        try:
            system_position = self.get_current_system_position()
            camera_name = f"camera{camera_id}"

            if camera_name in self.camera_positions:
                camera_offset = self.camera_positions[camera_name]["position"]
                effective_position = (system_position + camera_offset) % 360
                return effective_position
            else:
                logger.error(f"Invalid camera ID: {camera_id}")
                return None
        except Exception as e:
            logger.error(
                f"Error calculating effective position for camera {camera_id}: {e}"
            )
            return None

    def update_status(self):
        """Update UI with current thermal camera status"""
        try:
            if not self.system or not hasattr(self.system, "status"):
                return

            status = self.system.status.get("thermal_camera", {})
            if not status:
                return

            # Update position display
            if "position" in status:
                self.ui.ip_limiting_angle_lbl_2.setText(f"{status['position']:.2f}")

            streaming = status.get("streaming", False)
            self.ui.streamin_image_flag.setStyleSheet(
                "background-color: green;" if streaming else "background-color: red;"
            )
            running = status.get("running", False)
            self.ui.run_stat_flg.setStyleSheet(
                "background-color: green;" if running else "background-color: red;"
            )

            switch_state = status.get("switch_state", False)
            self.ui.switch_state_flag.setStyleSheet(
                "background-color: green;" if switch_state else "background-color: red;"
            )

            # Update camera images based on current scaling mode
            if hasattr(self.system._thermalcamera, "_images"):
                if self.use_co2_scaling:
                    self.update_camera_images_co2_scale()
                else:
                    self.update_camera_images_auto_scale()

            self.update_camera_displays()

        except Exception as e:
            logger.error(f"Error updating status: {e}")
            logger.error(f"Error details: {str(e)}", exc_info=True)

    def update_camera_images_co2_scale(self):
        """Update camera images using CO2 temperature-based scaling"""
        try:
            # Get CO2 temperature for colorbar range
            co2_temp = 0.0  # Default fallback
            try:
                marta_status = self.system.status.get("marta", {})
                co2_temp = float(marta_status.get("TT06_CO2", 0.0))
            except (ValueError, TypeError):
                logger.warning(
                    "Could not get CO2 temperature from MARTA status, using default range"
                )
                co2_temp = 0.0

            # Calculate colorbar range: CO2 temp to CO2 temp + 20
            colorbar_min = co2_temp
            colorbar_max = co2_temp + 15.0

            # Update individual camera views
            for i, (camera_name, image_data) in enumerate(
                self.system._thermalcamera._images.items()
            ):
                if isinstance(image_data, np.ndarray):
                    # Convert to float if needed
                    if image_data.dtype != np.float64:
                        try:
                            image_data = image_data.astype(np.float64)
                        except (ValueError, TypeError) as e:
                            logger.error(f"Failed to convert image data to float: {e}")
                            continue

                    # Update individual camera view
                    self.camera_images[i].set_array(image_data)

                    # Use CO2-based temperature range for consistent scaling
                    self.camera_images[i].set_clim(colorbar_min, colorbar_max)

                    # Update colorbar ticks for camera view
                    cbar = self.camera_images[i].colorbar
                    if cbar is not None:
                        cbar.set_ticks(np.linspace(colorbar_min, colorbar_max, 5))
                        cbar.set_ticklabels(
                            [
                                f"{temp:.1f}°C"
                                for temp in np.linspace(colorbar_min, colorbar_max, 5)
                            ]
                        )

            # Draw camera canvas
            self.cameras_canvas.draw()

            logger.debug(
                f"Updated camera images with CO2 range: {colorbar_min:.1f}°C to {colorbar_max:.1f}°C (CO2 temp: {co2_temp:.1f}°C)"
            )

        except Exception as e:
            logger.error(f"Error updating camera images with CO2 scale: {e}")

    def update_camera_images_auto_scale(self):
        """Update camera images using automatic scaling based on image data"""
        try:
            # Update individual camera views with auto-scaling
            for i, (camera_name, image_data) in enumerate(
                self.system._thermalcamera._images.items()
            ):
                if isinstance(image_data, np.ndarray):
                    # Convert to float if needed
                    if image_data.dtype != np.float64:
                        try:
                            image_data = image_data.astype(np.float64)
                        except (ValueError, TypeError) as e:
                            logger.error(f"Failed to convert image data to float: {e}")
                            continue

                    # Update individual camera view
                    self.camera_images[i].set_array(image_data)

                    # Calculate temperature range for automatic scaling
                    vmin = np.nanmin(image_data)
                    vmax = np.nanmax(image_data)
                    self.camera_images[i].set_clim(vmin, vmax)

                    # Update colorbar ticks for camera view
                    cbar = self.camera_images[i].colorbar
                    if cbar is not None:
                        cbar.set_ticks(np.linspace(vmin, vmax, 5))
                        cbar.set_ticklabels(
                            [f"{temp:.1f}°C" for temp in np.linspace(vmin, vmax, 5)]
                        )

            # Draw camera canvas
            self.cameras_canvas.draw()

            logger.debug("Updated camera images with auto-scale")

        except Exception as e:
            logger.error(f"Error updating camera images with auto scale: {e}")

    def set_scaling_mode(self, use_co2_scale=True):
        """Set the scaling mode for camera images

        Args:
            use_co2_scale (bool): If True, use CO2 temperature range. If False, use auto-scaling.
        """
        try:
            self.use_co2_scaling = use_co2_scale
            logger.info(
                f"Camera scaling mode set to: {'CO2 temperature range' if use_co2_scale else 'Auto-scale'}"
            )

            # Update the ComboBox to reflect the change
            if hasattr(self.ui, "t_range_comboBox"):
                combo_text = "CO2" if use_co2_scale else "Auto"
                self.ui.t_range_comboBox.setCurrentText(combo_text)

            # Immediately update the display with the new scaling
            if hasattr(self.system._thermalcamera, "_images"):
                if use_co2_scale:
                    self.update_camera_images_co2_scale()
                else:
                    self.update_camera_images_auto_scale()

        except Exception as e:
            logger.error(f"Error setting scaling mode: {e}")

    def on_temperature_range_changed(self, text):
        """Handle temperature range selection change"""
        try:
            if text == "CO2":
                self.use_co2_scaling = True
                logger.info("Thermal camera scaling set to CO2-based scaling")
            elif text == "Auto":
                self.use_co2_scaling = False
                logger.info("Thermal camera scaling set to auto-scaling")
            else:
                logger.warning(f"Unknown temperature range option: {text}")
                return

            # Immediately update camera images with new scaling mode
            if hasattr(self.system._thermalcamera, "_images"):
                if self.use_co2_scaling:
                    self.update_camera_images_co2_scale()
                else:
                    self.update_camera_images_auto_scale()

        except Exception as e:
            logger.error(f"Error changing thermal camera temperature range: {e}")

    def rotate(self):
        """Rotate the thermal camera by the specified angle"""
        try:
            angle = float(self.ui.ip_DAngle_LE.text())
            if self.system._thermalcamera:
                direction = (
                    "bw"
                    if self.ui.direction_combo.currentText() == "Clockwise"
                    else "fw"
                )
                self.system._thermalcamera.rotate(
                    {"angle": angle, "direction": direction}
                )
                logger.info(f"Rotating camera by {angle} degrees")
        except ValueError:
            logger.error("Invalid angle value")
        except Exception as e:
            logger.error(f"Error rotating camera: {e}")

    def go_to(self):
        """Go to the specified angle"""
        try:
            angle = float(self.ui.ip_angle_LE.text())
            if self.system._thermalcamera:
                self.system._thermalcamera.go_to({"position": angle})
                logger.info(f"Moving camera to {angle} degrees")
                self.update_camera_displays()
        except ValueError:
            logger.error("Invalid angle value")
        except Exception as e:
            logger.error(f"Error moving camera: {e}")

    def calibrate(self):
        """Calibrate the thermal camera"""
        try:
            # Use ip_angle_LE_2 which contains the 90-degree angle input
            limit = float(self.ui.ip_angle_LE_2.text())
            if self.system._thermalcamera:
                direction = (
                    "bw"
                    if self.ui.direction_combo.currentText() == "Clockwise"
                    else "fw"
                )
                self.system._thermalcamera.calibrate(
                    {"prudence": limit, "direction": direction}
                )
                logger.info(f"Calibrating camera with limit {limit} degrees")
                self.update_camera_displays()
        except ValueError:
            logger.error("Invalid angle limit value")
        except Exception as e:
            logger.error(f"Error calibrating camera: {e}")

    def set_absolute_position(self):
        """Set the absolute position"""
        try:
            position = float(self.ui.ip_abs_pos_LE.text())
            if self.system._thermalcamera:
                self.system._thermalcamera.set_absolute_position({"value": position})
                logger.info(f"Setting absolute position to {position}")
                self.update_camera_displays()
        except ValueError:
            logger.error("Invalid position value")
        except Exception as e:
            logger.error(f"Error setting absolute position: {e}")

    def export_absolute_position(self):
        """Export the absolute position"""
        try:
            if self.system._thermalcamera:
                self.system._thermalcamera.export_absolute_position({})
                logger.info("Exporting absolute position")
        except Exception as e:
            logger.error(f"Error exporting absolute position: {e}")

    def get_frames(self):
        """Get frames from all cameras"""
        try:
            if self.system._thermalcamera:
                self.system._thermalcamera.get_frames({})
                logger.info("Getting frames from all cameras")
        except Exception as e:
            logger.error(f"Error getting frames: {e}")

    def release_motor(self):
        """Release the stepper motor"""
        try:
            if self.system._thermalcamera:
                self.system._thermalcamera.release({})
                logger.info("Releasing stepper motor")
        except Exception as e:
            logger.error(f"Error releasing motor: {e}")

    def run(self):
        """Start the thermal camera process"""
        try:
            if self.system._thermalcamera:
                self.system._thermalcamera.run({})
                logger.info("Starting thermal camera process")
        except Exception as e:
            logger.error(f"Error starting process: {e}")

    def stop(self):
        """Stop the thermal camera process"""
        try:
            if self.system._thermalcamera:
                self.system._thermalcamera.stop({})
                logger.info("Stopping thermal camera process")
                self.update_camera_displays()
        except Exception as e:
            logger.error(f"Error stopping process: {e}")

    def start_thermal_camera(self):
        """Initialize and start the thermal camera"""
        try:
            if self.system._thermalcamera:
                # Add logging to check available methods
                logger.info("Starting thermal camera")

                # Try using init method instead of initialize
                self.system._thermalcamera.init({})
                self.enable_controls(True)
                # self.ui.relse_mtr_PB_2.setEnabled(False)  # Disable start button
                logger.info("Thermal camera initialized")
                self.update_camera_displays()
        except Exception as e:
            logger.error(f"Error using alternative init method: {e}")
            self.enable_controls(False)
            self.ui.relse_mtr_PB_2.setEnabled(True)  # Re-enable start button

    def closeEvent(self, event):
        """Handle widget close event"""
        try:
            self.update_timer.stop()
            event.accept()
        except Exception as e:
            logger.error(f"Error in close event: {e}")
            event.accept()
