import json
import paho.mqtt.client as mqtt
import requests
import sys
import logging
import datetime
import time

from .safety import *

logger = logging.getLogger(__name__)


class MartaColdRoomMQTTClient:

    def __init__(self, system_obj):
        self._system = system_obj

        # Initialize topics
        self.TOPIC_CLEANROOM = system_obj.settings["Cleanroom"]["mqtt_topic"]
        self.TOPIC_BASE_CLEANROOM = self.TOPIC_CLEANROOM.replace("#", "")
        self.TOPIC_MARTA = system_obj.settings["MARTA"]["mqtt_topic"]
        self.TOPIC_BASE_MARTA = self.TOPIC_MARTA.replace("#", "")
        self.TOPIC_COLDROOM = system_obj.settings["Coldroom"]["mqtt_topic"]
        self.TOPIC_BASE_COLDROOM = self.TOPIC_COLDROOM.replace("#", "")
        self.TOPIC_CO2_SENSOR = system_obj.settings["Coldroom"]["co2_sensor_topic"]
        self.TOPIC_COLDROOM_AIR = system_obj.settings["Coldroom"]["shellies_air_topic"]
        self.TOPIC_ALARM = "/alarm"

        self.DRY_AIR_BYPASS_URL = "http://192.168.0.204/relay/0?turn="

        logger.info("Initializing MQTT client with topics:")
        logger.info(f"Cleanroom topic: {self.TOPIC_CLEANROOM}")
        logger.info(f"MARTA topic: {self.TOPIC_MARTA}")
        logger.info(f"Coldroom topic: {self.TOPIC_COLDROOM}")
        logger.info(f"CO2 sensor topic: {self.TOPIC_CO2_SENSOR}")

        # Create single MQTT client
        self._client = mqtt.Client()
        self._client.on_connect = self.on_connect
        self._client.on_message = self.on_message

        # Set connection parameters
        self._client.keepalive = 60
        self._client.connect_timeout = 5

        # Initialize status dictionaries
        self._marta_status = {}
        self._coldroom_state = {}
        self._dry_air_bypass_status = None
        self._cleanroom_status = {}
        self._co2_sensor_data = {}
        self._current_topic = None
        self._cleanroom_last_update_timer = time.time()
        self._cleanroom_last_update_elapsed_time = 0

        # Connect to broker
        try:
            logger.debug(f"Connecting to MQTT broker at {self._system.BROKER}:{self._system.PORT}")
            self._client.connect(self._system.BROKER, self._system.PORT, keepalive=60)
            logger.debug("MQTT client connected successfully")
        except Exception as e:
            logger.error(f"Error connecting to MQTT broker: {e}")
            raise

        # Start client loop
        self.start_client_loops()

    def start_client_loops(self):
        """Start the MQTT client loop to process network traffic"""
        logger.debug("Starting MQTT client loop")
        self._client.loop_start()
        logger.debug("MQTT client loop started")

    def stop_client_loops(self):
        """Stop the MQTT client loop"""
        logger.debug("Stopping MQTT client loop")
        self._client.loop_stop()
        logger.debug("MQTT client loop stopped")

    def on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            logger.info("Connected to MQTT broker, subscribing to topics...")
            # Subscribe to all topics
            self._client.subscribe(self.TOPIC_CLEANROOM)
            logger.info(f"Subscribed to Cleanroom topic: {self.TOPIC_CLEANROOM}")
            self._client.subscribe(self.TOPIC_MARTA)
            logger.info(f"Subscribed to MARTA topic: {self.TOPIC_MARTA}")
            self._client.subscribe(self.TOPIC_COLDROOM)
            logger.info(f"Subscribed to Coldroom topic: {self.TOPIC_COLDROOM}")
            self._client.subscribe(self.TOPIC_CO2_SENSOR)
            logger.info(f"Subscribed to CO2 sensor topic: {self.TOPIC_CO2_SENSOR}")
            self._client.subscribe(self.TOPIC_ALARM)
            self.publish_cmd("refresh", "marta", "")
            self._client.subscribe(self.TOPIC_COLDROOM_AIR)
            logger.info(f"Subscribed to Coldroom Air topic: {self.TOPIC_COLDROOM_AIR}")
        else:
            logger.error(f"Connection failed with result code {rc}")

    def on_message(self, client, userdata, msg):
        logger.info(f"Received MQTT message on topic: {msg.topic}")
        # logger.info(f"Payload: {msg.payload}")
        try:
            payload = msg.payload.decode()
            logger.info(f"Payload: {payload}")
        except:
            logger.error("Could not decode payload as string")
            return

        # Store msg.topic for use in handle_cleanroom_status_message
        self._current_topic = msg.topic
        logger.info(f"Current topic: {self._current_topic}")

        # Handle Cleanroom messages (with leading slash)
        if msg.topic.startswith(self.TOPIC_BASE_CLEANROOM[:-1]):
            logger.info(f"Processing Cleanroom environment message: {msg.topic}")
            self.handle_cleanroom_status_message(msg.payload)
            logger.info(f"Updated Cleanroom status: {self._cleanroom_status}")

        # Handle Coldroom Air messages
        elif msg.topic.startswith(self.TOPIC_COLDROOM_AIR):  # Add Coldroom Air topic
            logger.info("Processing Coldroom Air message")
            self.handle_air_bypass_message(msg.payload)
            logger.info(f"Updated Coldroom Air status: {self._coldroom_state.get('air_bypass_status', None)}")

        # Handle MARTA messages
        elif msg.topic.startswith(self.TOPIC_BASE_MARTA):  # Add MARTA topic
            if "status" in msg.topic:
                logger.info("Processing MARTA status message")
                self.handle_marta_status_message(msg.payload)
                logger.info(f"Updated MARTA status: {self._marta_status}")

        # Handle Coldroom messages
        elif msg.topic.startswith(self.TOPIC_BASE_COLDROOM):  # Add Coldroom topic
            if "state" in msg.topic:
                logger.info("Processing Coldroom state message")
                self.handle_coldroom_state_message(msg.payload)
                logger.info(f"Updated Coldroom state: {self._coldroom_state}")
        elif "alarm" in msg.topic:
            logger.info("Processing Coldroom alarm message")
            # alarm is a string
            alarm = msg.payload.decode()
            if "MyKratos" in alarm:
                logger.info("Received MyKratos alarm")
                self._system.update_status({"alarm": alarm})
                logger.info(f"Updated alarm status: {self._system.status['alarm']}")

        # Handle CO2 sensor messages
        elif msg.topic == self.TOPIC_CO2_SENSOR:  # Add CO2 sensor topic
            logger.info("Processing CO2 sensor message")
            self.handle_co2_sensor_message(msg.payload)
            logger.info(f"Updated CO2 sensor data: {self._co2_sensor_data}")
        else:
            logger.warning(f"Received message on unknown topic: {msg.topic}")

        # Safety checks
        if self._system.has_valid_status():
            self._system.safety_flags["door_locked"] = not check_dew_point(self._system.status)
            self._system.safety_flags["sleep"] = check_door_status(self._system.status)
            self._system.safety_flags["door_safe"] = check_door_safe_to_open(self._system.status)
            logger.debug(f"Safety flags updated: {self._system.safety_flags}")

    def publish_cmd(self, command, target, payload):
        """
        Publish a command to either MARTA or Coldroom or Cleanroom

        Args:
            command (str): The command to send
            target (str): Either 'marta' or 'coldroom' or 'cleanroom'
            payload: The command payload
        """
        logger.debug("Publishing", command, target, payload)
        if target == "marta":  # Add MARTA topic
            topic = f"{self.TOPIC_BASE_MARTA}cmd/{command}"
        elif target == "cleanroom":  # Add cleanroom topic
            topic = f"{self.TOPIC_BASE_CLEANROOM}cmd/{command}"
        else:  # Add Coldroom topic
            topic = f"{self.TOPIC_BASE_COLDROOM}cmd/{command}"

        logger.info(f"Sending command '{command}' to {target} with payload: {payload}")
        ret = self._client.publish(topic, payload)
        logger.debug(ret)

    def publish_door_safety_status(self, is_safe):
        """
        Publish the door safety status to a specific MQTT topic.

        Args:
            is_safe (bool): True if the door is safe to open, False otherwise.
        """
        topic = f"{self.TOPIC_BASE_COLDROOM}safe_to_open"
        payload = int(is_safe)
        print(f"Publishing door safety status: {payload} to topic: {topic}")
        ret = self._client.publish(topic, payload)
        logger.debug(ret)

    ### MARTA ###

    def handle_marta_status_message(self, payload):
        try:
            self._marta_status.update(json.loads(payload))
            logger.debug(f"Parsed MARTA status: {self._marta_status}")
            self._system.update_status({"marta": self._marta_status})
        except Exception as e:
            logger.error(f"Error parsing MARTA status message: {e}")

    ## Commands ##

    def start_chiller(self, payload):
        self.publish_cmd("start_chiller", "marta", payload)

    def start_co2(self, payload):
        self.publish_cmd("start_co2", "marta", payload)

    def stop_co2(self, payload):
        self.publish_cmd("stop_co2", "marta", payload)

    def stop_chiller(self, payload):
        self.publish_cmd("stop_chiller", "marta", payload)

    def set_flow_active(self, payload):
        self.publish_cmd("set_flow_active", "marta", payload)

    def set_temperature_setpoint(self, payload):
        self.publish_cmd("set_temperature_setpoint", "marta", payload)

    def set_speed_setpoint(self, payload):
        self.publish_cmd("set_speed_setpoint", "marta", payload)

    def set_flow_setpoint(self, payload):
        self.publish_cmd("set_flow_setpoint", "marta", payload)

    def clear_alarms(self, payload):
        self.publish_cmd("clear_alarms", "marta", payload)

    def reconnect(self, payload):
        self.publish_cmd("reconnect", "marta", payload)

    def refresh(self, payload):
        self.publish_cmd("refresh", "marta", payload)

    ### CLEANROOM ###

    def handle_cleanroom_status_message(self, payload):
        try:
            # Parse the payload
            data = json.loads(payload)
            logger.info(f"Processing cleanroom data: {data}")

            # Initialize cleanroom status if empty
            if not self._cleanroom_status:
                self._cleanroom_status = {
                    "temperature": None,
                    "humidity": None,
                    "dewpoint": None,
                    "pressure": None,
                    "last_update": None,
                }

            # Update cleanroom status based on topic
            if isinstance(data, dict):
                if "temperature" in data or "temp" in data:
                    self._cleanroom_status["temperature"] = float(data.get("temperature", data.get("temp")))
                    logger.info(f"Updated temperature: {self._cleanroom_status['temperature']}")
                if "RH" in data or "humidity" in data:
                    self._cleanroom_status["humidity"] = float(data.get("RH", data.get("humidity")))
                    logger.info(f"Updated humidity: {self._cleanroom_status['humidity']}")
                if "dewpoint" in data:
                    self._cleanroom_status["dewpoint"] = float(data["dewpoint"])
                    logger.info(f"Updated dewpoint: {self._cleanroom_status['dewpoint']}")
                if "Pressure" in data:
                    self._cleanroom_status["pressure"] = float(data["Pressure"])
                    logger.info(f"Updated pressure: {self._cleanroom_status['pressure']}")

                self._cleanroom_status["last_update"] = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                self._cleanroom_last_update_timer = time.time()
                self._cleanroom_last_update_elapsed_time = 0

            logger.info(f"Current cleanroom status: {self._cleanroom_status}")
            self._system.update_status({"cleanroom": self._cleanroom_status})
        except Exception as e:
            logger.error(f"Error parsing Cleanroom status message: {e}")
            logger.error(f"Payload was: {payload}")

    ### COLDROOM ###

    def handle_coldroom_state_message(self, payload):
        try:
            self._coldroom_state = json.loads(payload)
            logger.debug(f"Parsed Coldroom state: {self._coldroom_state}")

            # Update control states
            if "ch_temperature" in self._coldroom_state:
                if "status" in self._coldroom_state["ch_temperature"]:
                    self._coldroom_state["temperature_control"] = self._coldroom_state["ch_temperature"]["status"]
            if "ch_humidity" in self._coldroom_state:
                if "status" in self._coldroom_state["ch_humidity"]:
                    self._coldroom_state["humidity_control"] = self._coldroom_state["ch_humidity"]["status"]
            self._system.update_status({"coldroom": self._coldroom_state})
        except Exception as e:
            logger.error(f"Error parsing Coldroom state message: {e}")

    def handle_air_bypass_message(self, payload):
        try:
            data = json.loads(payload)
            logger.debug(f"Parsed Coldroom air bypass data: {data}")
            self._dry_air_bypass_status = data["apower"] > 0.1
            self._system._status["coldroomair"]["air_bypass_status"] = self._dry_air_bypass_status
        except Exception as e:
            logger.error(f"Error parsing Coldroom air bypass message: {e}")

    ## Commands ##

    def set_temperature(self, payload):
        self.publish_cmd("set_temperature", "coldroom", payload)

    def set_humidity(self, payload):
        self.publish_cmd("set_humidity", "coldroom", payload)

    def control_light(self, payload):
        self.publish_cmd("control_light", "coldroom", payload)

    def control_temperature(self, payload):
        self.publish_cmd("control_temperature", "coldroom", payload)

    def control_humidity(self, payload):
        self.publish_cmd("control_humidity", "coldroom", payload)

    def control_external_dry_air(self, payload):
        self.publish_cmd("control_external_dry_air", "coldroom", payload)

    def reset_alarms(self, payload):
        self.publish_cmd("reset_alarms", "coldroom", payload)

    def run(self, payload=1):
        self.publish_cmd("run", "coldroom", payload)

    def stop(self, payload=1):
        logger.debug("Stopping", payload)
        self.publish_cmd("stop", "coldroom", payload)

    def handle_co2_sensor_message(self, payload):
        """Handle incoming CO2 sensor messages"""
        try:
            self._co2_sensor_data = json.loads(payload)
            logger.debug(f"Parsed CO2 sensor data: {self._co2_sensor_data}")
            self._system.update_status({"co2_sensor": self._co2_sensor_data})
        except Exception as e:
            logger.error(f"Error parsing CO2 sensor message: {e}")

    ### Http Methods ###
    def dry_air_bypass_on(self):
        """Turn on dry air bypass via HTTP request to Shellie device"""
        try:
            response = requests.get(self.DRY_AIR_BYPASS_URL + "on", timeout=5)
            if response.status_code == 200:
                logger.info("Dry air bypass turned ON successfully")
            else:
                logger.error(f"Failed to turn ON dry air bypass, status code: {response.status_code}")
        except Exception as e:
            logger.error(f"Error turning ON dry air bypass: {e}")

    def dry_air_bypass_off(self):
        """Turn off dry air bypass via HTTP request to Shellie device"""
        try:
            response = requests.get(self.DRY_AIR_BYPASS_URL + "off", timeout=5)
            if response.status_code == 200:
                logger.info("Dry air bypass turned OFF successfully")
            else:
                logger.error(f"Failed to turn OFF dry air bypass, status code: {response.status_code}")
        except Exception as e:
            logger.error(f"Error turning OFF dry air bypass: {e}")

    ### Properties ###
    @property
    def marta_status(self):
        return self._marta_status

    @property
    def cleanroom_status(self):
        return self._cleanroom_status

    @property
    def coldroom_state(self):
        return self._coldroom_state

    @property
    def door_locked(self):
        return self._system.safety_flags.get("door_locked", True)  # Default to True (safe) if not available
