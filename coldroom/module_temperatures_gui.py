from PyQt5 import QtWidgets, uic
from PyQt5.QtCore import QTimer
from PyQt5.QtGui import QFont, QColor
import logging
import json
import os
import numpy as np
import yaml
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.backends.backend_qt5agg import NavigationToolbar2QT as NavigationToolbar
from matplotlib.figure import Figure
import paho.mqtt.client as mqtt
import datetime

logger = logging.getLogger(__name__)


class ModuleTemperaturesTAB(QtWidgets.QMainWindow):
    def __init__(self, system_obj):
        super(ModuleTemperaturesTAB, self).__init__()
        self.system = system_obj
        # Load UI from file
        ui_file = os.path.join(os.path.dirname(__file__), "module_temperatures.ui")
        uic.loadUi(ui_file, self)

        # Initialize scaling modes - default to CO2 scaling
        self.use_co2_scaling_stitched = (
            True  # Default to CO2 scaling for stitched views
        )
        self.use_co2_scaling_temperature_plot = (
            True  # Default to CO2 scaling for temperature plot
        )

        # Initialize stitching-related attributes
        # Initialize camera-specific FOV values (default to 20 degrees for all cameras)
        self.camera_fovs = {
            "camera1": 20,
            "camera2": 20,
            "camera3": 20,
            "camera4": 20,
        }

        self.config_file = os.path.join(os.path.dirname(__file__), "camera_config.yaml")
        self.camera_positions = self.load_camera_config()
        self.mounted_modules = None
        self.number_of_modules = None

        # Setup UI components
        self.setup_stitched_views()
        self.reset_figures_PB.clicked.connect(self.reset_camera_views)
        self.snapshot_PB.clicked.connect(self.snapshot)

        self.setup_fov_sliders()

        # Set default temperature range to CO2 and connect signal
        if hasattr(self, "t_range_comboBox"):
            self.t_range_comboBox.setCurrentText("CO2")
            self.t_range_comboBox.currentTextChanged.connect(
                self.on_temperature_range_changed
            )

        # Setup update timer
        self.update_timer = QTimer()
        self.update_timer.timeout.connect(self.update_displays)
        self.update_timer.start(1000)  # Update every second

        logger.info("Module temperatures tab initialized")

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
                if self.validate_camera_config(config):
                    return config
                else:
                    logger.warning("Invalid camera config, using defaults")
                    self.save_camera_config(default_config)
                    return default_config
            else:
                logger.info("Camera config file not found, creating with defaults")
                self.save_camera_config(default_config)
                return default_config

        except yaml.YAMLError as e:
            logger.error(f"Error parsing YAML config file: {e}")
            self.save_camera_config(default_config)
            return default_config
        except Exception as e:
            logger.error(f"Error loading camera config: {e}")
            self.save_camera_config(default_config)
            return default_config

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

            return True
        except Exception as e:
            logger.error(f"Error validating config: {e}")
            return False

    def setup_stitched_views(self):
        """Setup matplotlib figures for stitched camera views"""
        try:
            # Create stitched view for each camera
            self.stitched_figs = []
            self.stitched_canvases = []
            self.stitched_images = []
            self.stitched_axes = []
            self.stitched_toolbars = []  # Add toolbar list

            # Get the tab widget from the UI
            self.stitched_tab_widget = self.findChild(QtWidgets.QTabWidget, "tabWidget")

            for graphics_view in [
                self.graphics_1,
                self.graphics_2,
                self.graphics_3,
                self.graphics_4,
            ]:
                scene = QtWidgets.QGraphicsScene()
                graphics_view.setScene(scene)

                # Create figure and canvas with proper aspect ratio for 360-degree view
                fig = Figure(figsize=(12, 3.5), dpi=100, tight_layout=True)
                canvas = FigureCanvas(fig)

                # Create navigation toolbar
                toolbar = NavigationToolbar(canvas, self)

                # Create widget to hold toolbar and canvas
                plot_widget = QtWidgets.QWidget()
                plot_layout = QtWidgets.QVBoxLayout(plot_widget)
                plot_layout.addWidget(toolbar)
                plot_layout.addWidget(canvas)
                plot_layout.setContentsMargins(0, 0, 0, 0)

                # Add the combined widget to the scene
                scene.addWidget(plot_widget)

                # Create axes and image
                ax = fig.add_subplot(111)
                # Initialize with a 360-degree wide array
                img = ax.imshow(
                    np.zeros((24, 360)),  # Full 360-degree width
                    cmap="plasma",
                    aspect="auto",  # Use 'auto' to fill the space
                    interpolation="nearest",
                    extent=[0, 360, 0, 24],  # Set the extent to match degrees
                )

                # Set up coordinate formatter for stitched views
                ax.format_coord = (
                    lambda x, y, ax_ref=ax, img_ref=img: self.format_coord_stitched(
                        x, y, ax_ref, img_ref
                    )
                )

                # Set up the axes for degrees
                ax.set_xticks(np.linspace(0, 360, 9))  # Ticks every 45 degrees
                ax.set_yticks([])

                # Add colorbar
                cbar = fig.colorbar(img, fraction=0.046, pad=0.04)
                cbar.ax.tick_params(labelsize=8)

                # Adjust subplot parameters to maximize image space
                fig.subplots_adjust(left=0.05, right=0.95, top=0.95, bottom=0.15)

                # Store references
                self.stitched_figs.append(fig)
                self.stitched_canvases.append(canvas)
                self.stitched_images.append(img)
                self.stitched_axes.append(ax)
                self.stitched_toolbars.append(toolbar)

            self.setup_temperature_plot()

            logger.info("Stitched views with navigation toolbars initialized")

        except Exception as e:
            logger.error(f"Error setting up stitched views: {e}")

    def format_coord_stitched(self, x, y, ax, img):
        """Format coordinates for stitched view to show angle and temperature"""
        try:
            # Get the image data
            data = img.get_array()

            # Convert coordinates to array indices
            numrows, numcols = data.shape
            col = int(x * numcols / 360)  # Convert angle to column index
            row = int(y)  # Direct pixel row

            # Check if coordinates are within bounds
            if 0 <= col < numcols and 0 <= row < numrows:
                temp_value = data[row, col]
                return f"Angle={x:.1f}°, Row={row}, T={temp_value:.1f}°C"
            else:
                return f"Angle={x:.1f}°, Row={y:.1f}"

        except Exception as e:
            logger.error(f"Error formatting stitched coordinates: {e}")
            return f"Angle={x:.1f}°, Row={y:.1f}"

    def snapshot(self):
        """Save current camera views and temperature plot, using timedate for unique filenames"""
        try:

            timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            base_filename = f"snapshot_{timestamp}"

            save_dir = os.path.join(os.path.dirname(__file__), "snapshots")
            if not os.path.exists(save_dir):
                os.makedirs(save_dir)

            # Save stitched images
            for i, (fig, canvas) in enumerate(
                zip(self.stitched_figs, self.stitched_canvases)
            ):
                filename = f"{base_filename}_view_camera{i+1}.png"
                filename = os.path.join(save_dir, filename)
                fig.savefig(filename, dpi=300)
                logger.info(f"Saved stitched image for camera {i+1} as {filename}")

            # Save temperature plot
            if hasattr(self, "temp_fig"):
                temp_filename = f"{base_filename}_temperature_plot.png"
                temp_filename = os.path.join(save_dir, temp_filename)
                self.temp_fig.savefig(temp_filename, dpi=300)
                logger.info(f"Saved temperature plot as {temp_filename}")

        except Exception as e:
            logger.error(f"Error saving snapshot: {e}")

    def setup_temperature_plot(self):
        """Setup temperature plotting tab"""
        try:
            # Get the existing tab widget
            tab_widget = self.findChild(QtWidgets.QTabWidget, "tabWidget")

            if tab_widget is None:
                logger.warning("Tab widget not found in UI")
                return

            # Create a new tab for temperature plot
            temp_tab = QtWidgets.QWidget()
            temp_layout = QtWidgets.QVBoxLayout(temp_tab)

            # Create graphics view for temperature plot
            temp_graphics_view = QtWidgets.QGraphicsView()
            temp_layout.addWidget(temp_graphics_view)

            # Add the new tab to the tab widget
            tab_widget.addTab(temp_tab, "Temperature Plot")

            # Create scene and canvas for temperature plot
            temp_scene = QtWidgets.QGraphicsScene()
            temp_graphics_view.setScene(temp_scene)

            # Create matplotlib figure for temperature plot
            self.temp_fig = Figure(figsize=(12, 4), dpi=100, tight_layout=True)
            self.temp_canvas = FigureCanvas(self.temp_fig)

            # Create navigation toolbar for temperature plot
            self.temp_toolbar = NavigationToolbar(self.temp_canvas, self)

            # Create widget to hold toolbar and canvas
            temp_plot_widget = QtWidgets.QWidget()
            temp_plot_layout = QtWidgets.QVBoxLayout(temp_plot_widget)
            temp_plot_layout.addWidget(self.temp_toolbar)
            temp_plot_layout.addWidget(self.temp_canvas)
            temp_plot_layout.setContentsMargins(0, 0, 0, 0)

            # Add to scene
            temp_scene.addWidget(temp_plot_widget)

            # Create axes for temperature plot
            self.temp_ax = self.temp_fig.add_subplot(111)
            self.temp_ax.set_xlabel("Angle (degrees)")
            self.temp_ax.set_ylabel("T (°C)")
            self.temp_ax.grid(True, alpha=0.3, which="both")
            self.temp_ax.set_xlim(0, 360)

            # Set up coordinate formatter for temperature plot
            self.temp_ax.format_coord = lambda x, y: f"Angle={x:.1f}°, T={y:.1f}°C"

            # Set x-axis ticks every 45 degrees for better readability
            self.temp_ax.set_xticks(np.linspace(0, 360, 9))

            # Initialize empty line plots for each camera (max and min)
            self.temp_lines = {}
            colors = ["red", "blue", "green", "orange"]

            for i in range(4):
                camera_name = f"camera{i+1}"
                color = colors[i]

                # Create lines for max and min temperatures
                (max_line,) = self.temp_ax.plot(
                    [], [], "o-", color=color, label=f"{camera_name} Max", markersize=3
                )
                (min_line,) = self.temp_ax.plot(
                    [],
                    [],
                    "s--",
                    color=color,
                    label=f"{camera_name} Min",
                    markersize=3,
                    alpha=0.7,
                )

                self.temp_lines[f"{camera_name}_max"] = max_line
                self.temp_lines[f"{camera_name}_min"] = min_line

            # Add legend with better positioning to account for module annotations
            self.temp_ax.legend(
                bbox_to_anchor=(1.0, 0.5), loc="center left", fontsize=8, frameon=False
            )

            # Adjust layout to make room for legend and module annotations
            self.temp_fig.subplots_adjust(right=0.82, top=0.85)

            logger.info(
                "Temperature plot tab with navigation toolbar added successfully"
            )

        except Exception as e:
            logger.error(f"Error setting up temperature plot: {e}")

    def update_temperature_plot_co2_scale(self):
        """Update temperature plot using CO2 temperature-based Y-axis scaling"""
        try:
            if not hasattr(self, "temp_ax"):
                return

            # Get CO2 temperature for Y-axis range
            co2_temp = 0.0  # Default fallback
            try:
                marta_status = self.system.status.get("marta", {})
                co2_temp = float(marta_status.get("TT06_CO2", 0.0))
            except (ValueError, TypeError):
                logger.warning(
                    "Could not get CO2 temperature from MARTA status, using default range for temperature plot"
                )
                co2_temp = 0.0

            # Calculate Y-axis range: CO2 temp to CO2 temp + 20
            y_min = co2_temp
            y_max = co2_temp + 20.0

            # Get temperature data from thermal camera
            if hasattr(
                self.system._thermalcamera, "_stitching_max_temperature"
            ) and hasattr(self.system._thermalcamera, "_stitching_min_temperature"):

                for i in range(4):
                    camera_name = (
                        f"camera{i}"  # This matches the thermal_camera.py naming
                    )
                    camera_display_name = f"camera{i+1}"  # This matches the GUI naming

                    if (
                        camera_name
                        in self.system._thermalcamera._stitching_max_temperature
                        and camera_name
                        in self.system._thermalcamera._stitching_min_temperature
                    ):

                        max_temp_data = (
                            self.system._thermalcamera._stitching_max_temperature[
                                camera_name
                            ]
                        )
                        min_temp_data = (
                            self.system._thermalcamera._stitching_min_temperature[
                                camera_name
                            ]
                        )

                        if max_temp_data and min_temp_data:
                            # Extract positions and temperatures
                            positions = []
                            max_temps = []
                            min_temps = []

                            # Get all positions that have both max and min data
                            common_positions = set(max_temp_data.keys()) & set(
                                min_temp_data.keys()
                            )

                            for pos in sorted(common_positions, key=float):
                                # Apply camera position offset to get effective position
                                effective_position = (
                                    float(pos)
                                    + self.camera_positions[camera_display_name][
                                        "position"
                                    ]
                                ) % 360

                                positions.append(effective_position)
                                max_temps.append(max_temp_data[pos])
                                min_temps.append(min_temp_data[pos])

                            if positions and max_temps:
                                # Filter spikes from max temperatures using simple method
                                filtered_max_temps = self.simple_spike_filter(max_temps)

                                # Update the plot lines
                                self.temp_lines[f"{camera_display_name}_max"].set_data(
                                    positions, filtered_max_temps
                                )
                                self.temp_lines[f"{camera_display_name}_min"].set_data(
                                    positions, min_temps
                                )

            # Set fixed Y-axis range based on CO2 temperature
            self.temp_ax.set_ylim(y_min, y_max)

            # Add module annotations to the temperature plot
            self.add_module_annotations_to_temperature_plot()

            # Redraw the canvas
            self.temp_canvas.draw()

            logger.debug(
                f"Updated temperature plot with CO2-based Y-axis range: {y_min:.1f}°C to {y_max:.1f}°C (CO2 temp: {co2_temp:.1f}°C)"
            )

        except Exception as e:
            logger.error(f"Error updating temperature plot with CO2 scale: {e}")

    def update_temperature_plot_auto_scale(self):
        """Update temperature plot using automatic Y-axis scaling based on data"""
        try:
            if not hasattr(self, "temp_ax"):
                return

            # Get temperature data and update plot lines
            all_temps = []

            if hasattr(
                self.system._thermalcamera, "_stitching_max_temperature"
            ) and hasattr(self.system._thermalcamera, "_stitching_min_temperature"):

                for i in range(4):
                    camera_name = (
                        f"camera{i}"  # This matches the thermal_camera.py naming
                    )
                    camera_display_name = f"camera{i+1}"  # This matches the GUI naming

                    if (
                        camera_name
                        in self.system._thermalcamera._stitching_max_temperature
                        and camera_name
                        in self.system._thermalcamera._stitching_min_temperature
                    ):

                        max_temp_data = (
                            self.system._thermalcamera._stitching_max_temperature[
                                camera_name
                            ]
                        )
                        min_temp_data = (
                            self.system._thermalcamera._stitching_min_temperature[
                                camera_name
                            ]
                        )

                        if max_temp_data and min_temp_data:
                            # Extract positions and temperatures
                            positions = []
                            max_temps = []
                            min_temps = []

                            # Get all positions that have both max and min data
                            common_positions = set(max_temp_data.keys()) & set(
                                min_temp_data.keys()
                            )

                            for pos in sorted(common_positions, key=float):
                                # Apply camera position offset to get effective position
                                effective_position = (
                                    float(pos)
                                    + self.camera_positions[camera_display_name][
                                        "position"
                                    ]
                                ) % 360

                                positions.append(effective_position)
                                max_temps.append(max_temp_data[pos])
                                min_temps.append(min_temp_data[pos])

                            if positions and max_temps:
                                # Filter spikes from max temperatures using simple method
                                filtered_max_temps = self.simple_spike_filter(max_temps)

                                # Update the plot lines
                                self.temp_lines[f"{camera_display_name}_max"].set_data(
                                    positions, filtered_max_temps
                                )
                                self.temp_lines[f"{camera_display_name}_min"].set_data(
                                    positions, min_temps
                                )

                                # Collect all temperature values for auto-scaling
                                all_temps.extend(filtered_max_temps)
                                all_temps.extend(min_temps)

            # Auto-scale the Y-axis based on all temperature data
            if all_temps:
                temp_min = min(all_temps)
                temp_max = max(all_temps)
                temp_range = temp_max - temp_min
                margin = temp_range * 0.1 if temp_range > 0 else 1.0

                self.temp_ax.set_ylim(temp_min - margin, temp_max + margin)

                logger.debug(
                    f"Updated temperature plot with auto-scale Y-axis range: {temp_min - margin:.1f}°C to {temp_max + margin:.1f}°C"
                )

            # Add module annotations to the temperature plot
            self.add_module_annotations_to_temperature_plot()

            # Redraw the canvas
            self.temp_canvas.draw()

        except Exception as e:
            logger.error(f"Error updating temperature plot with auto scale: {e}")

    def update_temperature_plot(self):
        """Update the temperature plot with current data"""
        try:
            if self.use_co2_scaling_temperature_plot:
                self.update_temperature_plot_co2_scale()
            else:
                self.update_temperature_plot_auto_scale()
        except Exception as e:
            logger.error(f"Error updating temperature plot: {e}")

    def add_module_annotations_to_temperature_plot(self):
        """Add module name annotations to the temperature plot"""
        try:
            if self.mounted_modules is None:
                logger.debug("No mounted modules available for temperature plot")
                return

            # Clear previous module annotations
            for txt in self.temp_ax.texts[:]:
                if hasattr(txt, "_module_annotation"):
                    txt.remove()

            # Remove previous module annotation lines
            for line in self.temp_ax.lines[:]:
                if hasattr(line, "_module_annotation"):
                    line.remove()

            # Add annotations for all mounted modules
            annotation_count = 0
            for module_name, module_info in self.mounted_modules.items():
                module_position = module_info["angular_position"]
                module_side = module_info["side"]

                # Get module slot information if available
                if "mounted_on" in module_info and ";" in str(
                    module_info["mounted_on"]
                ):
                    module_slot = str(module_info["mounted_on"]).split(";")[1]
                else:
                    module_slot = "-"

                # Create annotation text with side information for clarity
                annotation_text = f"{module_slot}:{module_name}"

                logger.debug(
                    f"Adding temperature plot annotation '{annotation_text}' at x={module_position}"
                )

                # Add text annotation at the top of the plot with rotation
                y_top = self.temp_ax.get_ylim()[1]
                text_obj = self.temp_ax.text(
                    module_position,
                    y_top,
                    annotation_text,
                    fontsize=6,
                    color="black",
                    ha="left",
                    va="bottom",
                    rotation=45,
                    clip_on=False,  # Allow text to extend beyond plot area
                    transform=self.temp_ax.transData,
                )

                # Mark as module annotation for easy removal
                text_obj._module_annotation = True

                # Add a dashed vertical line to mark the exact position
                # Use different colors based on side for better distinction
                line_color = (
                    "black"
                    if module_side == "13"
                    else "gray" if module_side == "24" else "gray"
                )
                line_obj = self.temp_ax.axvline(
                    x=module_position,
                    color=line_color,
                    linestyle="--",
                    alpha=0.5,
                    linewidth=1,
                )

                # Mark as module annotation for easy removal
                line_obj._module_annotation = True

                annotation_count += 1
                logger.debug(
                    f"Added temperature plot annotation {annotation_count}: {annotation_text} at position {module_position}"
                )

            logger.info(
                f"Added {annotation_count} module annotations to temperature plot"
            )

            # Adjust the top margin to make room for the angled text
            current_top = self.temp_fig.subplotpars.top
            if current_top > 0.85:  # Only adjust if not already adjusted
                self.temp_fig.subplots_adjust(top=0.85)

            # Force redraw
            self.temp_fig.canvas.draw_idle()

        except Exception as e:
            logger.error(f"Error adding module annotations to temperature plot: {e}")

    def simple_spike_filter(self, temps, max_change=5.0):
        """Simple spike filter - replaces values that change too much from neighbors"""
        if len(temps) < 3:
            return temps

        filtered = temps.copy()

        for i in range(1, len(temps) - 1):
            prev_temp = filtered[i - 1]
            curr_temp = temps[i]
            next_temp = temps[i + 1]

            # Check if current value is very different from both neighbors
            if (
                abs(curr_temp - prev_temp) > max_change
                and abs(curr_temp - next_temp) > max_change
            ):
                # Replace with average of neighbors
                filtered[i] = (prev_temp + next_temp) / 2

        return filtered

    def stitch_multiple_images(
        self, images, positions, temp_min, temp_max, camera_name, full_coverage=360
    ):
        """Stitch multiple images from different positions into a panorama"""
        # Get dimensions of a single image
        h, w = images[0].shape

        camera_fov = self.get_camera_fov(camera_name)

        # Calculate total width based on full coverage and FOV
        total_width = int(w * full_coverage / camera_fov)

        # Create canvas and count arrays for tracking overlaps
        panorama = np.zeros((h, total_width), dtype=np.float32)
        overlap_count = np.zeros((h, total_width), dtype=np.float32)

        # Place images on canvas based on absolute position within the full range
        for img, angle in zip(images, positions):
            # Calculate x offset based on absolute angle position in the full range
            # Normalize angle to 0-360 range if needed
            norm_angle = angle % full_coverage

            # Center the FOV around the camera position by subtracting half FOV
            # This makes the camera position the center of the image rather than the left edge
            centered_angle = (norm_angle - camera_fov / 2) % full_coverage
            x_offset = int(centered_angle * w / camera_fov)

            # Make sure offset is within bounds
            if x_offset >= 0 and x_offset + w <= total_width:
                # Add image to panorama (accumulate values)
                panorama[:, x_offset : x_offset + w] += img
                # Increment counter for overlapping pixels
                overlap_count[:, x_offset : x_offset + w] += 1
            else:
                # Handle case where image would wrap around
                if x_offset < 0:
                    # Image starts before 0, wrap around to the end
                    wrap_width = abs(x_offset)
                    # Add wrapped part at the end
                    panorama[:, total_width - wrap_width :] += img[:, :wrap_width]
                    overlap_count[:, total_width - wrap_width :] += 1
                    # Add remaining part at the beginning
                    panorama[:, : w - wrap_width] += img[:, wrap_width:]
                    overlap_count[:, : w - wrap_width] += 1
                elif x_offset + w > total_width:
                    # Image extends beyond total_width, wrap around to the beginning
                    wrap_width = total_width - x_offset
                    # Add first part
                    panorama[:, x_offset:] += img[:, :wrap_width]
                    overlap_count[:, x_offset:] += 1
                    # Add second part (wrap around)
                    panorama[:, : w - wrap_width] += img[:, wrap_width:]
                    overlap_count[:, : w - wrap_width] += 1

        # Compute mean for overlapping regions (avoid division by zero)
        mask = overlap_count > 0
        panorama[mask] = panorama[mask] / overlap_count[mask]

        # Convert to uint8 for display - use actual temperature range
        if np.isclose(temp_min, temp_max):
            temp_max = (
                temp_min + 1.0
            )  # Add a small difference to avoid division by zero

        # Create normalized array with proper handling of NaN values
        panorama_norm = np.zeros_like(panorama)
        valid_mask = ~np.isnan(panorama)
        panorama_norm[valid_mask] = (
            255 * (panorama[valid_mask] - temp_min) / (temp_max - temp_min)
        )

        # Areas without data will be black (0)
        panorama_norm = np.nan_to_num(panorama_norm, nan=0.0)  # Convert NaNs to 0
        panorama_norm = np.clip(
            panorama_norm, 0, 255
        )  # Ensure values are in valid range
        panorama_norm = panorama_norm.astype(np.uint8)

        return panorama_norm, panorama

    def update_displays(self):
        """Update all displays with current data"""
        try:
            if self.use_co2_scaling_stitched:
                self.update_displays_co2_scale()
            else:
                self.update_displays_auto_scale()

            self.update_temperature_table()
        except Exception as e:
            logger.error(f"Error updating displays: {e}")

    def update_displays_co2_scale(self):
        """Update displays using CO2 temperature-based scaling"""
        # This is the current implementation above - CO2 scaling
        try:
            # Get CO2 temperature for colorbar range
            co2_temp = 0.0  # Default fallback
            try:
                marta_status = self.system.status.get("marta", {})
                co2_temp = float(marta_status.get("TT06_CO2", 0.0))
            except (ValueError, TypeError):
                logger.warning(
                    "Could not get CO2 temperature from MARTA status, using default range for stitched views"
                )
                co2_temp = 0.0

            # Calculate colorbar range: CO2 temp to CO2 temp + 20
            colorbar_min = co2_temp
            colorbar_max = co2_temp + 15.0

            # Get stitching data from thermal camera
            if hasattr(self.system._thermalcamera, "_stitching_data"):
                for i, (camera_name, camera_data) in enumerate(
                    self.system._thermalcamera._stitching_data.items()
                ):
                    # add +1 to the camera name to match the UI naming
                    camera_index = int(camera_name[-1]) + 1
                    camera_name = f"camera{camera_index}"
                    if camera_data:  # If we have data for this camera
                        # Get all images and positions
                        images = []
                        positions = []

                        # Collect all images and positions
                        for pos, pos_images in camera_data.items():
                            if pos_images:  # If we have images at this position
                                # Keep only the last image at this position
                                last_img = pos_images[-1]
                                images.append(last_img)
                                positions.append(
                                    float(pos)
                                    + self.camera_positions[camera_name]["position"]
                                )

                        if images:  # If we have any images to stitch
                            # Create stitched panorama using CO2 temperature range
                            panorama_norm, panorama = self.stitch_multiple_images(
                                images,
                                positions,
                                colorbar_min,
                                colorbar_max,
                                camera_name,
                                full_coverage=360,
                            )

                            # Ensure the panorama is properly sized for 360 degrees
                            if panorama.shape[1] != 360:
                                # Resize to 360 degrees if needed
                                from scipy.ndimage import zoom

                                zoom_factor = (1, 360 / panorama.shape[1])
                                panorama = zoom(panorama, zoom_factor, order=1)

                            # Update the stitched view with CO2-based scaling
                            self.stitched_images[camera_index - 1].set_array(panorama)
                            self.stitched_images[camera_index - 1].set_clim(
                                colorbar_min, colorbar_max
                            )

                            # Clear previous annotations and add module names
                            ax = self.stitched_axes[camera_index - 1]
                            # Remove previous text annotations and lines (but keep camera position lines)
                            for txt in ax.texts[:]:
                                if hasattr(txt, "_module_annotation"):
                                    txt.remove()

                            # Remove previous annotation lines (both module and camera position)
                            for line in ax.lines[:]:
                                if hasattr(line, "_module_annotation") or hasattr(
                                    line, "_camera_position"
                                ):
                                    line.remove()

                            # Add camera position line (red dashed line showing current camera position)
                            current_camera_pos = self.get_camera_effective_position(
                                camera_index
                            )
                            if current_camera_pos is not None:
                                camera_line = ax.axvline(
                                    x=current_camera_pos,
                                    color="red",
                                    linestyle="--",
                                    alpha=0.8,
                                    linewidth=2,
                                    label=f"Camera {camera_index} Position",
                                )
                                # Mark as camera position line for easy removal
                                camera_line._camera_position = True

                            # Add module annotations if we have mounted modules
                            if self.mounted_modules is not None:
                                self.add_module_annotations_to_stitched_image(
                                    ax, camera_name
                                )
                            else:
                                logger.debug(
                                    f"No mounted modules available for {camera_name}"
                                )

                            # Update colorbar with CO2-based range
                            cbar = self.stitched_images[camera_index - 1].colorbar
                            if cbar is not None:
                                cbar.set_ticks(
                                    np.linspace(colorbar_min, colorbar_max, 5)
                                )
                                cbar.set_ticklabels(
                                    [
                                        f"{temp:.1f}°C"
                                        for temp in np.linspace(
                                            colorbar_min, colorbar_max, 5
                                        )
                                    ]
                                )

                            # Draw canvas
                            self.stitched_canvases[camera_index - 1].draw()

                            logger.debug(
                                f"Updated stitched view for camera {camera_index} with CO2 range: {colorbar_min:.1f}°C to {colorbar_max:.1f}°C"
                            )

            # Update temperature plot
            self.update_temperature_plot()

        except Exception as e:
            logger.error(f"Error creating stitched images: {e}")
            logger.error(f"Error details: {str(e)}", exc_info=True)

    def update_displays_auto_scale(self):
        """Update displays using automatic scaling based on image data"""
        try:
            # Get stitching data from thermal camera
            if hasattr(self.system._thermalcamera, "_stitching_data"):
                for i, (camera_name, camera_data) in enumerate(
                    self.system._thermalcamera._stitching_data.items()
                ):
                    camera_index = int(camera_name[-1]) + 1
                    camera_ui_name = f"camera{camera_index}"
                    if camera_data:
                        # Get all images and positions
                        images = []
                        positions = []
                        temp_min = float("inf")
                        temp_max = float("-inf")

                        # Collect all images and positions
                        for pos, pos_images in camera_data.items():
                            if pos_images:
                                last_img = pos_images[-1]
                                images.append(last_img)
                                positions.append(
                                    float(pos)
                                    + self.camera_positions[camera_ui_name]["position"]
                                )

                                # Update temperature range based on actual data
                                temp_min = min(temp_min, last_img.min())
                                temp_max = max(temp_max, last_img.max())

                        if images:
                            # Create stitched panorama using actual temperature range
                            panorama_norm, panorama = self.stitch_multiple_images(
                                images,
                                positions,
                                temp_min,
                                temp_max,
                                camera_ui_name,
                                full_coverage=360,
                            )

                            # Ensure the panorama is properly sized for 360 degrees
                            if panorama.shape[1] != 360:
                                from scipy.ndimage import zoom

                                zoom_factor = (1, 360 / panorama.shape[1])
                                panorama = zoom(panorama, zoom_factor, order=1)

                            # Update the stitched view with auto-scaling
                            self.stitched_images[camera_index - 1].set_array(panorama)
                            self.stitched_images[camera_index - 1].set_clim(
                                temp_min, temp_max
                            )

                            # Clear previous annotations and add new ones
                            ax = self.stitched_axes[camera_index - 1]
                            for txt in ax.texts[:]:
                                if hasattr(txt, "_module_annotation"):
                                    txt.remove()

                            for line in ax.lines[:]:
                                if hasattr(line, "_module_annotation") or hasattr(
                                    line, "_camera_position"
                                ):
                                    line.remove()

                            # Add camera position line
                            current_camera_pos = self.get_camera_effective_position(
                                camera_index
                            )
                            if current_camera_pos is not None:
                                camera_line = ax.axvline(
                                    x=current_camera_pos,
                                    color="red",
                                    linestyle="--",
                                    alpha=0.8,
                                    linewidth=2,
                                    label=f"Camera {camera_index} Position",
                                )
                                camera_line._camera_position = True

                            # Add module annotations
                            if self.mounted_modules is not None:
                                self.add_module_annotations_to_stitched_image(
                                    ax, camera_ui_name
                                )

                            # Update colorbar with auto-scale range
                            cbar = self.stitched_images[camera_index - 1].colorbar
                            if cbar is not None:
                                cbar.set_ticks(np.linspace(temp_min, temp_max, 5))
                                cbar.set_ticklabels(
                                    [
                                        f"{temp:.1f}°C"
                                        for temp in np.linspace(temp_min, temp_max, 5)
                                    ]
                                )

                            # Draw canvas
                            self.stitched_canvases[camera_index - 1].draw()

                            logger.debug(
                                f"Updated stitched view for camera {camera_index} with auto-scale range: {temp_min:.1f}°C to {temp_max:.1f}°C"
                            )

            # Update temperature plot
            self.update_temperature_plot()

        except Exception as e:
            logger.error(f"Error creating stitched images with auto-scale: {e}")

    def reset_camera_views(self):
        """Reset camera views to initial state"""
        try:
            # Clear stitched images
            for ax in self.stitched_axes:
                ax.clear()
            for img in self.stitched_images:
                img.set_array(np.zeros((24, 360)))

            # Redraw canvases
            for canvas in self.stitched_canvases:
                canvas.draw()

            logger.info("Camera views reset successfully")

            self.system._thermalcamera._stitching_data = {}  # Clear stitching data
            self.system._thermalcamera._stitching_max_temperature = {}
            self.system._thermalcamera._stitching_min_temperature = {}

            # Remove the temperature plot tab if it exists
            tab_widget = self.findChild(QtWidgets.QTabWidget, "tabWidget")
            if tab_widget is not None:
                # Find the Temperature Plot tab by iterating through tabs
                for i in range(tab_widget.count()):
                    if tab_widget.tabText(i) == "Temperature Plot":
                        tab_widget.removeTab(i)
                        logger.info("Removed existing Temperature Plot tab")
                        break

            self.setup_stitched_views()

        except Exception as e:
            logger.error(f"Error resetting camera views: {e}")

    def update_stitched_images(self):
        """Update stitched images for all cameras"""
        try:
            if not hasattr(self.system._thermalcamera, "_stitching_data"):
                return

            stitching_data = self.system._thermalcamera._stitching_data

            for i, camera_name in enumerate(
                ["camera1", "camera2", "camera3", "camera4"]
            ):
                if (
                    camera_name in stitching_data
                    and len(stitching_data[camera_name]) > 0
                    and i < len(self.stitched_axes)
                ):

                    # Get images and positions for this camera
                    camera_data = stitching_data[camera_name]
                    positions = list(camera_data.keys())
                    images = [camera_data[pos]["image"] for pos in positions]

                    if len(images) > 0:
                        # Get temperature range for this camera
                        max_temps = (
                            self.system._thermalcamera._stitching_max_temperature.get(
                                camera_name, {}
                            )
                        )
                        min_temps = (
                            self.system._thermalcamera._stitching_min_temperature.get(
                                camera_name, {}
                            )
                        )

                        if max_temps and min_temps:
                            temp_max = max(max_temps.values())
                            temp_min = min(min_temps.values())

                            # Stitch images
                            stitched_image, _ = self.stitch_multiple_images(
                                images, positions, temp_min, temp_max, camera_name
                            )

                            # Update display
                            if i < len(self.stitched_images):
                                self.stitched_images[i].set_data(stitched_image)
                                self.stitched_images[i].set_clim(0, 255)
                                self.stitched_canvases[i].draw()

        except Exception as e:
            logger.error(f"Error updating stitched images: {e}")

    def add_module_annotations_to_stitched_image(self, ax, camera_name):
        """Add module name annotations to the stitched image"""
        try:
            if self.mounted_modules is None:
                logger.debug(f"No mounted modules available for {camera_name}")
                return

            # Get camera side for filtering
            camera_side = self.camera_positions[camera_name]["side"]

            # Convert side format for comparison
            if camera_side == "Front":
                target_side = "13"
            elif camera_side == "Back":
                target_side = "24"
            else:
                target_side = camera_side

            logger.debug(
                f"Camera {camera_name} side: {camera_side}, target_side: {target_side}"
            )

            # Clear previous annotations
            # Remove previous text annotations and lines
            for txt in ax.texts[:]:
                if hasattr(txt, "_module_annotation"):
                    txt.remove()

            # Remove previous module annotation lines
            for line in ax.lines[:]:
                if hasattr(line, "_module_annotation"):
                    line.remove()

            # Add annotations for modules on the same side as this camera
            annotation_count = 0
            for module_name, module_info in self.mounted_modules.items():
                module_side = module_info["side"]
                module_position = module_info["angular_position"]

                logger.debug(
                    f"Module {module_name}: side={module_side}, position={module_position}"
                )

                # Only show modules on the same side as the camera
                if module_side == target_side:
                    # Calculate the module's position relative to the camera's view
                    # The stitched image shows 360 degrees with 0 at the left edge
                    module_x_pos = module_position

                    # Get module slot information if available
                    if "mounted_on" in module_info and ";" in str(
                        module_info["mounted_on"]
                    ):
                        module_slot = str(module_info["mounted_on"]).split(";")[1]
                    else:
                        module_slot = "-"

                    # Create annotation text
                    annotation_text = f"{module_slot}:{module_name}"

                    logger.debug(
                        f"Adding annotation '{annotation_text}' at x={module_x_pos}"
                    )

                    # Add text annotation on the top x-axis with 45-degree rotation
                    text_obj = ax.text(
                        module_x_pos,
                        ax.get_ylim()[1],  # Position at the top of the plot
                        annotation_text,
                        fontsize=6,
                        color="black",
                        ha="left",  # Right-align for better readability with rotation
                        va="bottom",
                        rotation=45,
                        # weight='bold',
                        clip_on=False,  # Allow text to extend beyond plot area
                    )

                    # Mark as module annotation for easy removal
                    text_obj._module_annotation = True

                    # Add a dashed vertical line to mark the exact position
                    line_obj = ax.axvline(
                        x=module_x_pos,
                        color="black",
                        linestyle="--",
                        alpha=0.7,
                        linewidth=1.5,
                    )

                    # Mark as module annotation for easy removal
                    line_obj._module_annotation = True

                    annotation_count += 1
                    logger.debug(
                        f"Added annotation {annotation_count}: {annotation_text} at position {module_x_pos}"
                    )

            logger.info(
                f"Added {annotation_count} module annotations for {camera_name} on side {camera_side}"
            )

            # Adjust the top margin to make room for the angled text
            # Get current subplot parameters
            current_top = ax.figure.subplotpars.top
            if current_top > 0.85:  # Only adjust if not already adjusted
                ax.figure.subplots_adjust(top=0.85)

            # Force redraw
            ax.figure.canvas.draw_idle()

        except Exception as e:
            logger.error(f"Error adding module annotations: {e}")

    def setup_fov_sliders(self):
        """Setup and connect FOV sliders for each camera"""
        try:
            # Dictionary to map sliders to cameras and labels
            slider_config = {
                "horizontalSlider": {"camera": "camera1", "label": "label_14"},
                "horizontalSlider_2": {"camera": "camera2", "label": "label_15"},
                "horizontalSlider_3": {"camera": "camera3", "label": "label_16"},
                "horizontalSlider_4": {"camera": "camera4", "label": "label_17"},
            }

            for slider_name, config in slider_config.items():
                # Get slider and label widgets
                slider = self.findChild(QtWidgets.QSlider, slider_name)
                label = self.findChild(QtWidgets.QLabel, config["label"])

                if slider and label:
                    camera_name = config["camera"]

                    # Set initial slider value and label text
                    initial_fov = self.camera_fovs[camera_name]
                    slider.setValue(initial_fov)
                    label.setText(str(initial_fov))

                    # Connect slider to update function using lambda to capture camera name
                    slider.valueChanged.connect(
                        lambda value, cam=camera_name, lbl=label: self.on_fov_changed(
                            cam, value, lbl
                        )
                    )

                    logger.info(
                        f"Connected FOV slider for {camera_name}, initial value: {initial_fov}"
                    )
                else:
                    logger.warning(
                        f"Could not find slider '{slider_name}' or label '{config['label']}'"
                    )

        except Exception as e:
            logger.error(f"Error setting up FOV sliders: {e}")

    def on_fov_changed(self, camera_name, fov_value, label):
        """Handle FOV slider value changes"""
        try:
            # Update the camera's FOV value
            self.camera_fovs[camera_name] = fov_value

            # Update the label to show current value
            label.setText(str(fov_value))

            logger.info(f"FOV for {camera_name} changed to {fov_value} degrees")

            # Optionally trigger immediate update of displays
            # Note: This might cause frequent updates while dragging the slider
            # You can uncomment this if you want real-time updates
            # self.update_displays()

        except Exception as e:
            logger.error(f"Error handling FOV change for {camera_name}: {e}")

    def get_camera_fov(self, camera_name):
        """Get the current FOV for a specific camera"""
        return self.camera_fovs.get(camera_name, 20)  # Default to 20 if not found

    def generate_module_temperature_names(self):
        objs = ["SSA", "MPA"]
        hybrids = ["H0", "H1"]
        results = []
        for hybrid in hybrids:
            for obj in objs:
                for i in range(8):
                    offset = 8 * int(obj == "MPA")
                    results.append(f"{obj}_{hybrid}_{i+offset}")
        return results

    def setup_module_temperature_table(self):
        """Setup the module temperature table with proper headers and structure"""
        try:
            # Get the table widget
            table = self.module_temp_table

            # Determine number of modules (default to 36 if not set)
            num_modules = self.number_of_modules if self.number_of_modules else 36

            temp_keys = self.generate_module_temperature_names()
            self.temp_keys = temp_keys  # Store for later use
            table.setRowCount(len(temp_keys))
            table.setColumnCount(num_modules)

            # Set horizontal headers (module positions/slots)
            horizontal_headers = []
            for i in range(1, num_modules + 1):
                horizontal_headers.append(str(i))  # Slot numbers from 1 to num_modules
            table.setHorizontalHeaderLabels(horizontal_headers)

            # Set vertical headers (temperature keys)
            vertical_headers = (
                temp_keys.copy()
            )  # Copy temperature keys for vertical headers
            table.setVerticalHeaderLabels(vertical_headers)
            # Populate the table with empty strings initially
            for row in range(len(temp_keys)):
                for col in range(num_modules):
                    table.setItem(row, col, QtWidgets.QTableWidgetItem("-"))
            # Adjust column widths
            table.resizeColumnsToContents()

            # Set the font size for better readability
            font = QFont()
            font.setPointSize(6)
            table.setFont(font)

            # Ajust the row heights
            for row in range(len(temp_keys)):
                table.setRowHeight(row, 20)

            logger.info(
                f"Module temperature table setup completed: {len(temp_keys)} temperature keys, {num_modules} module slots"
            )
        except Exception as e:
            logger.error(f"Error setting up module temperature table: {e}")

    def start_temperature_monitoring(self):
        """Start monitoring module temperatures via MQTT"""
        try:
            self.mqtt_client = ModuleTempMQTT(self.system)
            self.mqtt_client.gui_reference = self
            self.mqtt_client.loop_start()
        except Exception as e:
            logger.error(f"Error starting temperature monitoring: {e}")

    def stop_temperature_monitoring(self):
        """Stop monitoring module temperatures via MQTT"""
        try:
            if hasattr(self, "mqtt_client"):
                self.mqtt_client.loop_stop()
                del self.mqtt_client
                logger.info("Stopped temperature monitoring")
            else:
                logger.warning("No MQTT client to stop")
        except Exception as e:
            logger.error(f"Error stopping temperature monitoring: {e}")

    def update_temperature_table(self):
        """Update the module temperature table with current data"""
        try:
            if not hasattr(self, "mqtt_client"):
                logger.warning(
                    "MQTT client not initialized, cannot update temperature table"
                )
                return

            # Get the latest status from the MQTT client
            status = self.mqtt_client.status

            # Clear the table first
            self.module_temp_table.clearContents()

            # Populate the table only for the fuseId present in the status
            for monitored_fuse_id, temp_data in status.items():
                for mounted_module, mounted_module_info in self.mounted_modules.items():
                    mounted_module_fuse_id = mounted_module_info.get("fuseId", None)
                    if mounted_module_fuse_id is None:
                        # logger.warning(f"Mounted module {mounted_module} does not have a fuseId, skipping")
                        continue
                    if mounted_module_fuse_id == monitored_fuse_id:
                        column_index = int(
                            mounted_module_info.get("mounted_on", "-").split(";")[1]
                        )
                        if (
                            column_index is not None
                            and column_index < self.module_temp_table.columnCount()
                        ):
                            for temp_key, temperature in temp_data.items():
                                if temp_key in self.temp_keys:
                                    if (
                                        temp_key
                                        in mounted_module_info["temperature_offsets"]
                                    ):
                                        temperature += mounted_module_info[
                                            "temperature_offsets"
                                        ][temp_key]
                                        item = QtWidgets.QTableWidgetItem(
                                            f"{temperature:.1f}"
                                        )
                                    else:
                                        # change the color of the cell to red if no offset is found
                                        item = QtWidgets.QTableWidgetItem(
                                            f"{temperature:.1f}"
                                        )
                                        item.setBackground(QColor(255, 0, 0))
                                    row_index = self.temp_keys.index(temp_key)
                                    self.module_temp_table.setItem(
                                        row_index, column_index - 1, item
                                    )

            # Note: Removed the publishing logic from here - it's now handled in handle_message

        except Exception as e:
            logger.error(f"Error updating temperature table: {e}")

    def publish_calibrated_data(self, fuse_id, temp_data):
        """Publish calibrated temperature data for a specific module"""
        print(fuse_id, temp_data)
        try:
            if not hasattr(self, "mqtt_client"):
                logger.warning(
                    "MQTT client not initialized, cannot publish calibrated data"
                )
                return

            to_publish = {}

            # Find the mounted module with this fuse_id
            for mounted_module, mounted_module_info in self.mounted_modules.items():
                mounted_module_fuse_id = mounted_module_info.get("fuseId", None)
                if mounted_module_fuse_id == fuse_id:
                    # Process temperature data for this module
                    for temp_key, temperature in temp_data.items():
                        if temp_key in self.temp_keys:
                            if temp_key in mounted_module_info["temperature_offsets"]:
                                calibrated_temp = (
                                    temperature
                                    + mounted_module_info["temperature_offsets"][
                                        temp_key
                                    ]
                                )
                                original_key = self.mqtt_client.key_map.get(
                                    temp_key, temp_key
                                )
                                to_publish[original_key] = calibrated_temp
                            else:
                                logger.warning(
                                    f"No offset found for {temp_key} in module {mounted_module}"
                                )

                    break  # Found the module, no need to continue

            # Publish the calibrated data if we have any
            if to_publish:
                topic = f"{self.mqtt_client.BASE_TOPIC}/calib_data"
                payload = json.dumps(to_publish)
                self.mqtt_client.client.publish(topic, payload)
                logger.info(
                    f"Published calibrated temperature data for fuse_id {fuse_id}: {to_publish}"
                )
            else:
                logger.debug(
                    f"No calibrated temperature data to publish for fuse_id {fuse_id}"
                )

        except Exception as e:
            logger.error(f"Error publishing calibrated data: {e}")

    def set_stitched_scaling_mode(self, use_co2_scale=True):
        """Set the scaling mode for stitched camera views

        Args:
            use_co2_scale (bool): If True, use CO2 temperature range. If False, use auto-scaling.
        """
        try:
            self.use_co2_scaling_stitched = use_co2_scale
            logger.info(
                f"Stitched views scaling mode set to: {'CO2 temperature range' if use_co2_scale else 'Auto-scale'}"
            )

            # Immediately update the displays with the new scaling
            self.update_displays()

        except Exception as e:
            logger.error(f"Error setting stitched scaling mode: {e}")

    def set_scaling_mode(self, use_co2_scale=True):
        """Set the scaling mode for both stitched views and temperature plot

        Args:
            use_co2_scale (bool): If True, use CO2 temperature range. If False, use auto-scaling.
        """
        try:
            self.use_co2_scaling_stitched = use_co2_scale
            self.use_co2_scaling_temperature_plot = use_co2_scale

            logger.info(
                f"Module temperatures scaling mode set to: {'CO2 temperature range' if use_co2_scale else 'Auto-scale'}"
            )

            # Update the ComboBox to reflect the change
            if hasattr(self, "t_range_comboBox"):
                combo_text = "CO2" if use_co2_scale else "Auto"
                self.t_range_comboBox.setCurrentText(combo_text)

            # Immediately update the displays with the new scaling
            self.update_displays()

        except Exception as e:
            logger.error(f"Error setting scaling mode: {e}")

    def on_temperature_range_changed(self, text):
        """Handle temperature range selection change"""
        try:
            if text == "CO2":
                self.use_co2_scaling_stitched = True
                self.use_co2_scaling_temperature_plot = True
                logger.info("Module temperatures scaling set to CO2-based scaling")
            elif text == "Auto":
                self.use_co2_scaling_stitched = False
                self.use_co2_scaling_temperature_plot = False
                logger.info("Module temperatures scaling set to auto-scaling")
            else:
                logger.warning(f"Unknown temperature range option: {text}")
                return

            # Immediately update displays with new scaling mode
            self.update_displays()

        except Exception as e:
            logger.error(f"Error changing module temperatures range: {e}")


class ModuleTempMQTT:
    """MQTT client for module temperature updates"""

    BASE_TOPIC = "/ph2acf"
    TOPIC = "/ph2acf/data"

    def __init__(self, system):
        self.system = system
        self.status = {}
        self.key_map = {}
        self.client = mqtt.Client()
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect
        self.mqtt_settings = self.system._settings["mqtt"]
        self.gui_reference = None
        try:
            self.client.connect(
                self.mqtt_settings["broker"], self.mqtt_settings["port"], keepalive=60
            )
            logger.info(
                f"Connected to MQTT broker at {self.system.BROKER}:{self.system.PORT}"
            )
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")

    def on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection"""
        if rc == 0:
            self.client.subscribe(self.TOPIC)
            logger.info(f"Subscribed to topic: {self.TOPIC}")
        else:
            logger.error(f"Failed to connect with result code {rc}")

    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            if msg.topic == self.TOPIC:
                payload = json.loads(msg.payload.decode("utf-8"))
                fuse_id, temp_data = self.handle_message(payload)
                if fuse_id and temp_data and self.gui_reference:
                    self.gui_reference.publish_calibrated_data(fuse_id, temp_data)
            else:
                logger.warning(f"Received message on unknown topic: {msg.topic}")
        except Exception as e:
            logger.error(f"Error handling message: {e}")

    def on_disconnect(self, client, userdata, rc):
        """Handle MQTT disconnection"""
        if rc != 0:
            logger.error(f"Unexpected disconnection: {rc}")
        else:
            logger.info("Disconnected from MQTT broker")

    def loop_start(self):
        """Start the MQTT loop"""
        try:
            self.client.loop_start()
            logger.info("MQTT loop started")
        except Exception as e:
            logger.error(f"Error starting MQTT loop: {e}")

    def loop_stop(self):
        """Stop the MQTT loop"""
        try:
            self.client.loop_stop()
            logger.info("MQTT loop stopped")
        except Exception as e:
            logger.error(f"Error stopping MQTT loop: {e}")

    def handle_message(self, payload):
        """Handle incoming MQTT messages"""
        result = {}
        fuseId = None
        for key in payload.keys():
            if "fuseId" in key:
                fuseId = payload[key]
            if "_temp" in key and "_C" in key:
                # e.g. SSA_BE0_H7_C6_temp or MPA_BE0_H0_C7_temp
                split = key.split("_")
                component = split[0]
                be = split[1]
                hybrid = split[2]
                be_id = int(be.split("BE")[1])
                hybrid_id = int(hybrid.split("H")[1]) % 2  # H0 or H1
                chip_id = int(split[3].split("C")[1])
                temperature = payload[key]
                new_key = f"{component}_H{hybrid_id}_{chip_id}"
                result[new_key] = temperature
                self.key_map[new_key] = key
        # Update the system status with the new temperature data
        if fuseId:
            self.status.update({fuseId: result})
            logger.debug(f"Updated temperature data for fuse_id {fuseId}")
        print(result)
        return fuseId, result
