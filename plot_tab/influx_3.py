import os
from datetime import datetime, timedelta
from influxdb_client import InfluxDBClient
import matplotlib.pyplot as plt

verbose = 0  # Set to 1 for basic output, 2 for more detailed, 3 for debug-level output


def getInfluxQueryAPI():
    token_location = os.path.join(os.path.dirname(__file__), "influx.sct")
    token = open(os.path.expanduser(token_location)).read().strip()
    client = InfluxDBClient(url="http://pccmslab1:8086/", token=token)
    return client.query_api()


def get_sensor_hierarchy():
    """Get the complete sensor hierarchy organized by topic"""
    query_api = getInfluxQueryAPI()

    try:
        # Query to get all unique topics
        topics_query = """
        from(bucket: "sensor_data")
          |> range(start: -1h)
          |> filter(fn: (r) => r._measurement == "mqtt_consumer")
          |> keep(columns: ["topic"])
          |> distinct(column: "topic")
          |> sort()
        """

        # Query to get fields for a specific topic
        fields_query_template = """
        from(bucket: "sensor_data")
          |> range(start: -1h)
          |> filter(fn: (r) => r._measurement == "mqtt_consumer")
          |> filter(fn: (r) => r.topic == "{topic}")
          |> keep(columns: ["_field"])
          |> distinct(column: "_field")
          |> sort()
        """

        # Get all topics
        topics = []
        topics_result = query_api.query(topics_query, org="pisaoutertracker")
        for table in topics_result:
            for record in table.records:
                topics.append(record.get_value())

        if not topics:
            print("No topics found in mqtt_consumer measurement")
            return {}

        # For each topic, get its fields
        topic_sensors = {}
        for topic in sorted(topics):
            fields_result = query_api.query(
                fields_query_template.format(topic=topic), org="pisaoutertracker"
            )
            fields = []
            for table in fields_result:
                for record in table.records:
                    fields.append(record.get_value())

            if fields:
                topic_sensors[topic] = sorted(fields)

        return topic_sensors

    except Exception as e:
        print(f"Error fetching sensor list: {e}")
        return {}


def print_sensor_hierarchy(topic_sensors):
    """Print the sensor hierarchy in a tree-like structure"""
    if not topic_sensors:
        print("No sensor data available")
        return

    print("\nSensor Hierarchy:")
    print("sensor_data (bucket)")
    print("└── mqtt_consumer (measurement)")

    for topic, sensors in topic_sensors.items():
        print(f"    └── {topic}")
        for sensor in sensors:
            print(f"        └── {sensor}")

    print(f"\nTotal topics: {len(topic_sensors)}")
    total_sensors = sum(len(sensors) for sensors in topic_sensors.values())
    print(f"Total sensors: {total_sensors}")


def getSensorValueAt(timestamp, sensorName, org="pisaoutertracker"):
    """Get a single sensor value at a specific timestamp"""
    window = timedelta(seconds=30)
    timestamp = datetime.fromisoformat(timestamp)
    start_window = (timestamp - window).isoformat("T") + "Z"
    end_window = (timestamp + window).isoformat("T") + "Z"
    query = f"""
    from(bucket: "sensor_data")
        |> range(start: {start_window}, stop: {end_window})
        |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer")
        |> filter(fn: (r) => r["_field"] == "{sensorName}")
        |> aggregateWindow(every: 1s, fn: mean, createEmpty: false)
        |> yield(name: "mean")
    """
    tables = getInfluxQueryAPI().query(query, org=org)
    values = [record.get_value() for table in tables for record in table.records]
    return sum(values) / len(values) if values else None


def getSensorValueSeries(start_time, end_time, sensorName, org="pisaoutertracker"):
    """Get time series data for a sensor"""
    query = f"""
    from(bucket: "sensor_data")
        |> range(start: {start_time}, stop: {end_time})
        |> filter(fn: (r) => r["_measurement"] == "mqtt_consumer")
        |> filter(fn: (r) => r["_field"] == "{sensorName}")
        |> aggregateWindow(every: 1m, fn: mean, createEmpty: false)
        |> yield(name: "mean")
    """

    tables = getInfluxQueryAPI().query(query, org=org)
    timestamps = []
    values = []
    for table in tables:
        for record in table.records:
            timestamps.append(record.get_time())
            values.append(record.get_value())
    return timestamps, values


def plot_sensor_data(start_time, end_time, sensorNames):
    """Plot multiple sensors in subplots"""
    if not sensorNames:
        print("No sensors specified for plotting")
        return

    num_sensors = len(sensorNames)
    fig, axes = plt.subplots(num_sensors, 1, figsize=(12, 6 * num_sensors), sharex=True)

    if num_sensors == 1:
        axes = [axes]

    for i, sensor in enumerate(sensorNames):
        timestamps, values = getSensorValueSeries(start_time, end_time, sensor)

        if not timestamps:
            print(f"No data found for {sensor}")
            continue

        axes[i].plot(timestamps, values, marker="o", linestyle="-", label=sensor)
        axes[i].set_title(f"Sensor: {sensor}")
        axes[i].set_ylabel("Value")
        axes[i].grid(True)
        axes[i].legend()

    axes[-1].set_xlabel("Time")
    plt.xticks(rotation=45)
    plt.tight_layout()
    plt.show()


def interactive_menu():
    """Interactive menu for exploring and plotting sensors"""
    topic_sensors = get_sensor_hierarchy()
    if not topic_sensors:
        return

    while True:
        print("\n===== Sensor Data Explorer =====")
        print("1. View sensor hierarchy")
        print("2. Plot sensor data")
        print("3. Exit")

        choice = input("Select an option (1-3): ").strip()

        if choice == "1":
            print_sensor_hierarchy(topic_sensors)

        elif choice == "2":
            # Select topic
            print("\nAvailable Topics:")
            topics = sorted(topic_sensors.keys())
            for i, topic in enumerate(topics, 1):
                print(f"{i}. {topic}")

            topic_choice = input(
                "\nSelect a topic (number) or 'b' to go back: "
            ).strip()
            if topic_choice.lower() == "b":
                continue

            try:
                selected_topic = topics[int(topic_choice) - 1]
            except (ValueError, IndexError):
                print("Invalid selection")
                continue

            # Select sensors
            sensors = topic_sensors[selected_topic]
            print(f"\nAvailable Sensors in {selected_topic}:")
            for i, sensor in enumerate(sensors, 1):
                print(f"{i}. {sensor}")

            sensor_choices = input(
                "\nSelect sensors (comma-separated numbers) or 'b' to go back: "
            ).strip()
            if sensor_choices.lower() == "b":
                continue

            try:
                selected_indices = [
                    int(x.strip()) - 1 for x in sensor_choices.split(",")
                ]
                selected_sensors = [
                    sensors[i] for i in selected_indices if 0 <= i < len(sensors)
                ]

                if not selected_sensors:
                    print("No valid sensors selected")
                    continue

                # Get time range
                print("\nEnter time range (UTC):")
                start_time = input("Start time (YYYY-MM-DDTHH:MM:SSZ): ").strip()
                end_time = input("End time (YYYY-MM-DDTHH:MM:SSZ): ").strip()

                # Plot the data
                plot_sensor_data(start_time, end_time, selected_sensors)

            except ValueError:
                print("Invalid sensor selection")

        elif choice == "3":
            break

        else:
            print("Invalid choice")


if __name__ == "__main__":
    interactive_menu()
