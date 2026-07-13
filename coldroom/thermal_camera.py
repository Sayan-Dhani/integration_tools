import struct
import json
import paho.mqtt.client as mqtt
import base64
import time
import numpy as np
import logging

logger = logging.getLogger(__name__)


class ThermalCameraMQTTClient:
    def __init__(self, system_obj):
        self._system = system_obj
        self.TOPIC = system_obj.settings["ThermalCamera"]["mqtt_topic"]
        self.TOPIC_BASE = self.TOPIC.replace("#", "")

        # Initialize data structures
        self._status = {}
        self._stitching_data = {}
        self._stitching_max_temperature = {}
        self._stitching_min_temperature = {}
        self._images = {f"camera{i}": np.zeros((24, 32)) for i in range(4)}
        self._figure_data = None
        self._circular_data = None

        # Create MQTT client
        self._client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1)
        self._client.on_connect = self.on_connect
        self._client.on_message = self.on_message
        self._client.on_disconnect = self.on_disconnect

        # Set connection parameters
        self._client.keepalive = 60
        self._client.connect_timeout = 5

        try:
            self._client.connect(self._system.BROKER, self._system.PORT, keepalive=60)
            logger.info(
                f"Connected to MQTT broker at {self._system.BROKER}:{self._system.PORT}"
            )
        except Exception as e:
            logger.error(f"Failed to connect to MQTT broker: {e}")
            raise

    def on_connect(self, client, userdata, flags, rc):
        """Handle MQTT connection"""
        if rc == 0:
            self._client.subscribe(self.TOPIC)
            logger.info(f"Subscribed to topic: {self.TOPIC}")
        else:
            logger.error(f"Failed to connect with result code {rc}")

    def on_message(self, client, userdata, msg):
        """Handle incoming MQTT messages"""
        try:
            if "state" in msg.topic:
                self.handle_state_message(msg.payload)
            elif ("camera" in msg.topic) and ("image" not in msg.topic):
                self.handle_camera_message(msg.topic, msg.payload)
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

    def handle_state_message(self, payload):
        """Handle incoming state messages"""
        try:
            self._status = json.loads(payload)
            self._system.update_status({"thermal_camera": self._status})
            logger.debug("Updated thermal camera status")
        except Exception as e:
            logger.error(f"Error handling state message: {e}")

    def handle_camera_message(self, topic, payload):
        """Handle incoming camera messages"""
        try:
            camera_name = topic.split("/")[2]
            data = json.loads(payload)

            # Decode image data
            image_data = base64.b64decode(data["image"])
            position = float(data["position"])

            # Convert to float array
            flo_arr = [
                struct.unpack("f", image_data[i : i + 4])[0]
                for i in range(0, len(image_data), 4)
            ]

            # Process image
            processed_image = np.flip(
                np.rot90(np.array(flo_arr).reshape(24, 32)), axis=0
            )

            # Store for stitching - accumulate images for each position
            if camera_name not in self._stitching_data:
                self._stitching_data[camera_name] = {}
            if position not in self._stitching_data[camera_name]:
                self._stitching_data[camera_name][position] = []

            # Add the new image to the list for this position
            self._stitching_data[camera_name][position].append(processed_image)

            # Keep only the last 5 images for each position to prevent memory issues
            if len(self._stitching_data[camera_name][position]) > 5:
                self._stitching_data[camera_name][position] = self._stitching_data[
                    camera_name
                ][position][-5:]

            # Update current image
            self._images[camera_name] = processed_image

            max_temperature = float(data["max_temperature"])
            min_temperature = float(data["min_temperature"])
            if camera_name not in self._stitching_max_temperature:
                self._stitching_max_temperature[camera_name] = {}
            if camera_name not in self._stitching_min_temperature:
                self._stitching_min_temperature[camera_name] = {}
            self._stitching_max_temperature[camera_name][position] = max_temperature
            self._stitching_min_temperature[camera_name][position] = min_temperature

            # Try to stitch images
            # self.__stitch_images()

            logger.debug(f"Processed image from {camera_name} at position {position}")

        except Exception as e:
            logger.error(f"Error handling camera message: {e}")

    # def __stitch_images(self):
    #     """Attempt to stitch images together"""
    #     try:
    #         if self._stitching_data:
    #             self._figure_data, self._circular_data = process_all_cameras(
    #                 self._stitching_data, self._system.settings
    #             )
    #             logger.debug("Stitched camera images")
    #     except Exception as e:
    #         logger.error(f"Error stitching images: {e}")

    def publish_cmd(self, command, params=None):
        """Publish a command to the MQTT broker"""
        logger.debug(command)
        try:
            if params is None:
                params = {}
            payload = json.dumps(params)
            logger.debug(f"{self.TOPIC_BASE}cmd/{command}", payload)
            self._client.publish(f"{self.TOPIC_BASE}cmd/{command}", payload)
            logger.debug(f"Published command: {command} with params: {params}")
        except Exception as e:
            logger.error(f"Error publishing command: {e}")
            raise e

    ### Commands ###
    def rotate(self, payload):
        """Rotate the camera by a delta angle"""
        self.publish_cmd("rotate", payload)

    def go_to(self, payload):
        """Go to a specific angle"""
        self.publish_cmd("go_to", payload)

    def calibrate(self, payload):
        """Calibrate the camera system"""
        self.publish_cmd("calibrate", payload)

    def get_switch_state(self, payload):
        """Get the state of the limit switches"""
        self.publish_cmd("get_switch_state", payload)

    def set_absolute_position(self, payload):
        """Set the absolute position"""
        self.publish_cmd("set_absolute_position", payload)

    def export_absolute_position(self, payload):
        """Export the current absolute position"""
        self.publish_cmd("export_absolute_position", payload)

    def import_absolute_position(self, payload):
        """Import a saved absolute position"""
        self.publish_cmd("import_absolute_position", payload)

    def get_frame(self, payload):
        """Get a single frame from the cameras"""
        self.publish_cmd("get_frame", payload)

    def get_frames(self, payload):
        """Get frames from all cameras"""
        self.publish_cmd("get_frames", payload)

    def init(self, payload):
        """Initialize the camera system"""
        self.publish_cmd("init", payload)

    def release(self, payload):
        """Release the stepper motor"""
        self.publish_cmd("release", payload)

    def run(self, payload):
        """Start the camera process"""
        self.publish_cmd("run", payload)

    def stop(self, payload):
        """Stop the camera process"""
        self.publish_cmd("stop", payload)

    ### MQTT Client Loop ###
    def loop_start(self):
        """Start the MQTT client loop"""
        try:
            self._client.loop_start()
            logger.info("Started MQTT client loop for Thermal Camera")
        except Exception as e:
            logger.error(f"Error starting MQTT loop: {e}")

    def loop_stop(self):
        """Stop the MQTT client loop"""
        try:
            self._client.loop_stop()
            logger.info("Stopped MQTT client loop")
        except Exception as e:
            logger.error(f"Error stopping MQTT loop: {e}")
