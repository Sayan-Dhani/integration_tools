import sys
import os
from datetime import datetime, timedelta
from PyQt5.QtWidgets import (
    QApplication,
    QMainWindow,
    QVBoxLayout,
    QWidget,
    QTreeWidgetItem,
    QMessageBox,
    QComboBox,
    QListWidget,
)
from PyQt5.QtCore import QTimer, pyqtSignal
from PyQt5.uic import loadUi
from influxdb_client import InfluxDBClient
import matplotlib.pyplot as plt
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.dates as mdates

verbose = 0


class PlotWidget(QWidget):
    def __init__(self, plot_title="Plot"):
        super().__init__()
        self.plot_title = plot_title
        self.setup_ui()

    def setup_ui(self):
        layout = QVBoxLayout()
        self.figure = Figure(figsize=(8, 4), dpi=100)
        self.canvas = FigureCanvas(self.figure)
        layout.addWidget(self.canvas)
        self.setLayout(layout)

        # Initialize with empty plot
        self.ax = self.figure.add_subplot(111)
        self.ax.set_title(self.plot_title, fontsize=10, pad=10)
        self.ax.grid(True, linestyle=":", alpha=0.3)
        self.figure.tight_layout()

    def update_plot(
        self, timestamps, values, sensor_names, topic, start_time, end_time
    ):
        """Update the plot with new data"""
        self.ax.clear()

        # Set style
        plt.style.use("seaborn-v0_8")
        self.figure.set_facecolor("#f5f5f5")
        self.ax.set_facecolor("#ffffff")

        if not timestamps or not values:
            self.ax.set_title(f"{self.plot_title}\nNo Data", fontsize=10)
            self.ax.text(
                0.5,
                0.5,
                "No data available",
                horizontalalignment="center",
                verticalalignment="center",
                transform=self.ax.transAxes,
                fontsize=9,
                alpha=0.7,
            )
        else:
            colors = ["#4C72B0", "#55A868", "#C44E52", "#8172B2", "#CCB974"]
            has_artists = False

            for i, (sensor_name, sensor_timestamps, sensor_values) in enumerate(
                zip(sensor_names, timestamps, values)
            ):
                if sensor_timestamps and sensor_values:
                    color = colors[i % len(colors)]
                    self.ax.plot(
                        sensor_timestamps,
                        sensor_values,
                        marker="o",
                        markersize=4,
                        linewidth=1.5,
                        alpha=0.8,
                        label=sensor_name,
                        color=color,
                        markerfacecolor="white",
                        markeredgewidth=1,
                    )
                    has_artists = True

            # Title and labels
            self.ax.set_title(
                f"{self.plot_title}\n{topic}", fontsize=10, pad=15, fontweight="bold"
            )
            self.ax.set_xlabel("Time", fontsize=9)
            self.ax.set_ylabel("Value", fontsize=9)

            # Legend
            if has_artists:
                legend = self.ax.legend(
                    loc="upper right",
                    fontsize=8,
                    frameon=True,
                    fancybox=True,
                    framealpha=0.8,
                    edgecolor="#cccccc",
                )
                legend.get_frame().set_linewidth(0.5)

            # Grid and borders
            self.ax.grid(True, linestyle="--", alpha=0.5)
            self.ax.spines["top"].set_visible(False)
            self.ax.spines["right"].set_visible(False)

            # Date formatting
            hours = (end_time.toSecsSinceEpoch() - start_time.toSecsSinceEpoch()) / 3600

            if hours <= 6:
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                self.ax.xaxis.set_major_locator(mdates.MinuteLocator(interval=30))
            elif hours <= 24:
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M"))
                self.ax.xaxis.set_major_locator(mdates.HourLocator(interval=2))
            else:
                self.ax.xaxis.set_major_formatter(mdates.DateFormatter("%m-%d"))
                self.ax.xaxis.set_major_locator(mdates.DayLocator())

            self.figure.autofmt_xdate(rotation=30, ha="right")

        self.figure.tight_layout()
        self.canvas.draw()


class SensorMonitor(QMainWindow):
    def __init__(self):
        super().__init__()

        # Load UI from file
        ui_file = os.path.join(os.path.dirname(__file__), "sensor_monitor.ui")
        loadUi(ui_file, self)

        self.topic_sensors = {}
        self.plot_configs = [
            {"topic": "", "sensors": []},
            {"topic": "", "sensors": []},
            {"topic": "", "sensors": []},
            {"topic": "", "sensors": []},
        ]

        self.setup_ui()
        self.setup_plots()
        self.setup_timers()
        self.load_sensor_hierarchy()
        self.setup_default_plots()

    def setup_ui(self):
        """Setup UI connections and initial state"""
        # Connect buttons
        self.refreshButton.clicked.connect(self.refresh_data)
        self.autoRefreshButton.clicked.connect(self.toggle_auto_refresh)
        self.updatePlotButton.clicked.connect(self.update_selected_plot)

        # Time range buttons
        self.lastHourButton.clicked.connect(lambda: self.set_time_range(1))
        self.last6HoursButton.clicked.connect(lambda: self.set_time_range(6))
        self.last24HoursButton.clicked.connect(lambda: self.set_time_range(24))

        # Topic selection
        self.topicCombo.currentTextChanged.connect(self.on_topic_changed)

        # Set initial time range (last hour)
        self.set_time_range(1)

        # Status
        self.statusLabel.setText("Status: Ready")

    def setup_plots(self):
        """Setup the four plot widgets"""
        self.plot_widgets = []

        # Create plot widgets
        for i in range(4):
            plot_widget = PlotWidget(f"Plot {i+1}")
            self.plot_widgets.append(plot_widget)

            # Replace placeholder widgets with actual plot widgets
            # placeholder = getattr(self, f'plotWidget{i+1}')
            placeholder = getattr(
                self, f"plotWidget{i+3}"
            )  # Note: plotWidget3-6 correspond to plots 1-4
            parent = placeholder.parent()
            layout = parent.layout()

            # Find the placeholder and replace it
            for j in range(layout.count()):
                item = layout.itemAt(j)
                if item and item.widget() == placeholder:
                    # layout.removeItem(item)
                    layout.removeWidget(placeholder)
                    placeholder.deleteLater()
                    # layout.addWidget(plot_widget, j // 2, j % 2)
                    layout.addWidget(plot_widget)
                    break

    def setup_timers(self):
        """Setup refresh timer"""
        self.refresh_timer = QTimer()
        self.refresh_timer.timeout.connect(self.refresh_plots)

    def setup_default_plots(self):
        """Setup default plots with some common sensors"""
        # This will be called after sensor hierarchy is loaded
        pass

    def load_sensor_hierarchy(self):
        """Load sensor hierarchy from InfluxDB"""
        try:
            self.statusLabel.setText("Status: Loading sensors...")
            self.topic_sensors = self.get_sensor_hierarchy()
            self.populate_sensor_tree()
            self.populate_topic_combo()
            self.statusLabel.setText(f"Status: Loaded {len(self.topic_sensors)} topics")

            # Load default plots after hierarchy is loaded
            self.load_default_plots()

        except Exception as e:
            self.statusLabel.setText(f"Status: Error loading sensors - {str(e)}")
            QMessageBox.critical(self, "Error", f"Failed to load sensors: {str(e)}")

    def load_default_plots(self):
        """Load default plots for the first two plot windows"""
        if not self.topic_sensors:
            return

        topics = list(self.topic_sensors.keys())

        # Default plot 1 - first topic, first few sensors
        if len(topics) > 0:
            topic = topics[0]
            sensors = self.topic_sensors[topic][:2]  # First 2 sensors
            self.plot_configs[0] = {"topic": topic, "sensors": sensors}
            self.update_plot(0, topic, sensors)

        # Default plot 2 - second topic if available, or first topic with different sensors
        if len(topics) > 1:
            topic = topics[1]
            sensors = self.topic_sensors[topic][:2]
            self.plot_configs[1] = {"topic": topic, "sensors": sensors}
            self.update_plot(1, topic, sensors)
        elif len(topics) > 0 and len(self.topic_sensors[topics[0]]) > 2:
            topic = topics[0]
            sensors = self.topic_sensors[topic][2:4]  # Next 2 sensors
            self.plot_configs[1] = {"topic": topic, "sensors": sensors}
            self.update_plot(1, topic, sensors)

    def get_sensor_hierarchy(self):
        """Get sensor hierarchy from InfluxDB"""
        try:
            query_api = self.getInfluxQueryAPI()

            # Query to get all unique topics
            topics_query = """
            from(bucket: "sensor_data")
              |> range(start: -24h)
              |> filter(fn: (r) => r._measurement == "mqtt_consumer")
              |> keep(columns: ["topic"])
              |> distinct(column: "topic")
              |> sort()
            """

            # Get all topics
            topics = []
            topics_result = query_api.query(topics_query, org="pisaoutertracker")
            for table in topics_result:
                for record in table.records:
                    topics.append(record.get_value())

            if not topics:
                return {}

            # For each topic, get its fields
            topic_sensors = {}
            for topic in sorted(topics):
                fields_query = f"""
                from(bucket: "sensor_data")
                  |> range(start: -24h)
                  |> filter(fn: (r) => r._measurement == "mqtt_consumer")
                  |> filter(fn: (r) => r.topic == "{topic}")
                  |> keep(columns: ["_field"])
                  |> distinct(column: "_field")
                  |> sort()
                """

                fields_result = query_api.query(fields_query, org="pisaoutertracker")
                fields = []
                for table in fields_result:
                    for record in table.records:
                        fields.append(record.get_value())

                if fields:
                    topic_sensors[topic] = sorted(fields)

            return topic_sensors

        except Exception as e:
            print(f"Error fetching sensor hierarchy: {e}")
            return {}

    def getInfluxQueryAPI(self):
        """Get InfluxDB query API"""
        token_location = os.path.join(os.path.dirname(__file__), "influx.sct")
        token = open(os.path.expanduser(token_location)).read().strip()
        client = InfluxDBClient(url="http://pccmslab1:8086/", token=token)
        return client.query_api()

    def populate_sensor_tree(self):
        """Populate the sensor tree widget"""
        self.sensorTree.clear()

        if not self.topic_sensors:
            return

        root_item = QTreeWidgetItem(self.sensorTree)
        root_item.setText(0, "sensor_data")

        mqtt_item = QTreeWidgetItem(root_item)
        mqtt_item.setText(0, "mqtt_consumer")

        for topic, sensors in self.topic_sensors.items():
            topic_item = QTreeWidgetItem(mqtt_item)
            topic_item.setText(0, f"{topic} ({len(sensors)} sensors)")

            for sensor in sensors:
                sensor_item = QTreeWidgetItem(topic_item)
                sensor_item.setText(0, sensor)

        self.sensorTree.expandAll()

    def populate_topic_combo(self):
        """Populate the topic combo box"""
        self.topicCombo.clear()
        self.topicCombo.addItems(sorted(self.topic_sensors.keys()))

    def on_topic_changed(self, topic):
        """Handle topic selection change"""
        self.sensorList.clear()
        if topic and topic in self.topic_sensors:
            self.sensorList.addItems(self.topic_sensors[topic])

    def set_time_range(self, hours):
        """Set time range for the plots"""
        end_time = datetime.now()
        start_time = end_time - timedelta(hours=hours)

        self.startTime.setDateTime(start_time)
        self.endTime.setDateTime(end_time)

    def toggle_auto_refresh(self):
        """Toggle auto refresh on/off"""
        if self.autoRefreshButton.isChecked():
            interval = self.intervalSpinBox.value() * 1000  # Convert to milliseconds
            self.refresh_timer.start(interval)
            self.autoRefreshButton.setText("Auto: ON")
            self.statusLabel.setText(
                f"Status: Auto-refresh ON ({self.intervalSpinBox.value()}s)"
            )
        else:
            self.refresh_timer.stop()
            self.autoRefreshButton.setText("Auto: OFF")
            self.statusLabel.setText("Status: Auto-refresh OFF")

    def refresh_data(self):
        """Refresh sensor data and update plots"""
        self.statusLabel.setText("Status: Refreshing data...")
        self.load_sensor_hierarchy()
        self.refresh_plots()

    def refresh_plots(self):
        """Refresh all plots with current data"""
        for i, config in enumerate(self.plot_configs):
            if config["topic"] and config["sensors"]:
                self.update_plot(i, config["topic"], config["sensors"])

    def update_selected_plot(self):
        """Update the selected plot with chosen sensors"""
        plot_index = self.plotCombo.currentIndex()
        topic = self.topicCombo.currentText()

        # Get selected sensors
        selected_sensors = []
        for i in range(self.sensorList.count()):
            item = self.sensorList.item(i)
            if item.isSelected():
                selected_sensors.append(item.text())

        if not selected_sensors:
            QMessageBox.warning(self, "Warning", "Please select at least one sensor")
            return

        # Update plot configuration
        self.plot_configs[plot_index] = {"topic": topic, "sensors": selected_sensors}
        self.update_plot(plot_index, topic, selected_sensors)

    def update_plot(self, plot_index, topic, sensor_names):
        """Update a specific plot with sensor data"""
        if plot_index >= len(self.plot_widgets):
            return

        try:
            start_time = self.startTime.dateTime()
            end_time = self.endTime.dateTime()

            timestamps = []
            values = []

            for sensor_name in sensor_names:
                sensor_timestamps, sensor_values = self.get_sensor_data(
                    start_time.toString("yyyy-MM-ddThh:mm:ss") + "Z",
                    end_time.toString("yyyy-MM-ddThh:mm:ss") + "Z",
                    sensor_name,
                    topic,
                )
                timestamps.append(sensor_timestamps)
                values.append(sensor_values)

            self.plot_widgets[plot_index].update_plot(
                timestamps, values, sensor_names, topic, start_time, end_time
            )

        except Exception as e:
            print(f"Error updating plot {plot_index}: {e}")

    def get_sensor_data(self, start_time, end_time, sensor_name, topic):
        """Get sensor data from InfluxDB"""
        try:
            query_api = self.getInfluxQueryAPI()

            query = f"""
            from(bucket: "sensor_data")
                |> range(start: {start_time}, stop: {end_time})
                |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer")
                |> filter(fn: (r) => r["topic"] == "{topic}")
                |> filter(fn: (r) => r["_field"] == "{sensor_name}")
                |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
                |> yield(name: "mean")
            """

            tables = query_api.query(query, org="pisaoutertracker")
            timestamps = []
            values = []

            for table in tables:
                for record in table.records:
                    timestamps.append(record.get_time())
                    values.append(record.get_value())

            return timestamps, values

        except Exception as e:
            print(f"Error fetching sensor data: {e}")
            return [], []


def main():
    app = QApplication(sys.argv)
    window = SensorMonitor()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
