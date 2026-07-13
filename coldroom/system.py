import os
import yaml
import threading
import time
import sys
import logging
from .thermal_camera import ThermalCameraMQTTClient
from .marta_coldroom import MartaColdRoomMQTTClient

logger = logging.getLogger(__name__)


class System:
    def __init__(self):
        logger.info("Initializing System...")
        # Load settings
        self._settings = {}  # Initialize private settings variable
        try:
            with open(
                os.path.join(
                    os.path.dirname(__file__), os.pardir, "settings_coldroom.yaml"
                ),
                "r",
            ) as f:
                self._settings = yaml.safe_load(f)
                logger.debug("Settings loaded successfully")
                logger.debug(f"MQTT Broker: {self._settings['mqtt']['broker']}")
                logger.debug(f"MQTT Port: {self._settings['mqtt']['port']}")
        except Exception as e:
            logger.error(f"Error loading settings: {e}")
            self._settings = {
                "mqtt": {"broker": "localhost", "port": 1883},
                "Cleanroom": {"mqtt_topic": "/environment/HumAndTemp001/#"},
                "MARTA": {"mqtt_topic": "/MARTA/#"},
                "Coldroom": {"mqtt_topic": "/coldroom/#"},
                "ThermalCamera": {"mqtt_topic": "/thermalcamera/#"},
            }

        # Global variables
        self.BROKER = self._settings["mqtt"]["broker"]
        self.PORT = self._settings["mqtt"]["port"]
        self._status = {
            "marta": {},
            "coldroom": {},
            "thermal_camera": {},
            "caen": {},
            "cleanroom": {},
            "coldroomair": {},
        }
        self.safety_flags = {
            "door_locked": True,
            "sleep": True,
            "hv_safe": False,
        }  # Default value to safest state

        # Thread control
        self._mqtt_thread = None
        self._thread_stop = False
        self._caen_thread = None
        self._caen_thread_stop = False

        # Initialize MQTT clients
        logger.info("Initializing MQTT clients...")
        try:
            self._martacoldroom = MartaColdRoomMQTTClient(self)
            logger.info("MARTA/Coldroom/Cleanroom client initialized")
        except Exception as e:
            logger.error(f"Error initializing MARTA/Coldroom/Cleanroom client: {e}")
            self._martacoldroom = None

        try:
            self._thermalcamera = ThermalCameraMQTTClient(self)
            logger.info("Thermal Camera client initialized")
        except Exception as e:
            logger.error(f"Error initializing Thermal Camera client: {e}")
            self._thermalcamera = None

        try:
            self._caen = None
        except Exception as e:
            logger.error(f"Error initializing CAEN client: {e}")
            self._caen = None

        # Start MQTT thread if any client is initialized
        if any([self._martacoldroom, self._thermalcamera]):
            self.start_mqtt_thread()

    @property
    def settings(self):
        """Get the current settings"""
        return self._settings

    @settings.setter
    def settings(self, value):
        """Update settings and save to file"""
        if not isinstance(value, dict):
            raise ValueError("Settings must be a dictionary")
        self._settings = value
        try:
            with open(
                os.path.join(os.path.dirname(__file__), "settings.yaml"), "w"
            ) as f:
                yaml.dump(self._settings, f, default_flow_style=False)
        except Exception as e:
            logger.error(f"Error saving settings: {e}")

    @property
    def status(self):
        return self._status

    def update_status(self, status):
        try:
            assert isinstance(status, dict)
            self._status.update(status)
            logger.debug(f"Status updated: {status}")
        except AssertionError:
            logger.error("Invalid status update - must be a dictionary")

    def has_valid_status(self):
        is_valid = True
        for subsystem in self._status.values():
            if subsystem == {}:
                is_valid = False
                break
        return is_valid

    def start_mqtt_thread(self):
        """Start MQTT thread to handle client loops"""
        logger.info("Starting MQTT thread...")
        if self._mqtt_thread is None or not self._mqtt_thread.is_alive():
            self._thread_stop = False
            self._mqtt_thread = threading.Thread(target=self._mqtt_loop)
            self._mqtt_thread.daemon = True
            self._mqtt_thread.start()
            logger.info("MQTT thread started")

            # Start CAEN status update thread
            if self._caen and not self._caen_thread:
                self._caen_thread_stop = False
                self._caen_thread = threading.Thread(target=self._caen_status_loop)
                self._caen_thread.daemon = True
                self._caen_thread.start()
                logger.info("CAEN status thread started")
        else:
            logger.warning("MQTT thread already running")

    def stop_mqtt_thread(self):
        """Stop MQTT thread"""
        logger.info("Stopping MQTT thread...")
        if self._mqtt_thread and self._mqtt_thread.is_alive():
            self._thread_stop = True
            self._mqtt_thread.join(timeout=2)
            logger.info("MQTT thread stopped")

            # Stop CAEN status thread
            if self._caen_thread and self._caen_thread.is_alive():
                self._caen_thread_stop = True
                self._caen_thread.join(timeout=2)
                logger.info("CAEN status thread stopped")
        else:
            logger.debug("No MQTT thread running")

    def _mqtt_loop(self):
        """Main MQTT loop that starts all client loops"""
        logger.info("Starting MQTT client loops...")
        try:
            # Start client loops
            if self._martacoldroom:
                logger.debug("Starting MARTA/Coldroom/Cleanroom client loops")
                self._martacoldroom.start_client_loops()

            if self._thermalcamera:
                logger.debug("Starting Thermal Camera client loop")
                self._thermalcamera.loop_start()

            logger.info("All MQTT client loops started")

            # Keep thread running
            while not self._thread_stop:
                time.sleep(1)

        except Exception as e:
            logger.error(f"Error in MQTT loop: {e}")
        finally:
            logger.info("MQTT loop ending, stopping client loops...")

    def _caen_status_loop(self):
        """Background thread to periodically update CAEN status"""
        while not self._caen_thread_stop:
            try:
                if self._caen:
                    status = self._caen.get_status()
                    if status:
                        self.update_status({"caen": status})
            except Exception as e:
                logger.error(f"Error in CAEN status loop: {e}")
            time.sleep(2)

    def cleanup(self):
        """Clean up resources"""
        logger.info("Cleaning up resources...")
        try:
            # Stop MQTT thread first
            self.stop_mqtt_thread()

            # Stop individual client loops
            if hasattr(self, "_martacoldroom") and self._martacoldroom:
                logger.debug("Stopping MARTA/Coldroom/Cleanroom client loops")
                self._martacoldroom.stop_client_loops()

            if hasattr(self, "_thermalcamera") and self._thermalcamera:
                logger.debug("Stopping Thermal Camera client loop")
                self._thermalcamera.loop_start()

            if hasattr(self, "_caen") and self._caen:
                logger.debug("Disconnecting CAEN TCP client")
                self._caen.disconnect()

            logger.info("All resources cleaned up")

        except Exception as e:
            logger.error(f"Error during cleanup: {e}")
