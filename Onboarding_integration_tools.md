Onboarding: integration_tools_new
What this project is
A physics lab instrument control suite for CMS detector module testing at Pisa (CERN collaboration). Operators use it daily to:

Select a detector module from inventory
Connect fiber/power cables to it
Run 3 automated electrical tests (ID check, noise with HV off, noise with HV on)
Monitor cooling and thermal safety in real time
Think of it as a hardware dashboard — it talks to 4 different systems over 4 different protocols simultaneously.

The 4 communication layers (this is the architecture)

Your GUI  ─────── HTTP REST ──────────▶  pccmslab1:5000  (MongoDB, module inventory)
          ─────── TCP binary ───────────▶  192.168.0.45:7000  (CAEN HV/LV supply)
          ─────── VISA/TCP ─────────────▶  192.168.0.16  (Rigol DP116A bench supply)
          ─────── MQTT pub/sub ─────────▶  pccmslab1:1883  (everything else)
          ─────── subprocess ───────────▶  Ph2_ACF  (the actual detector test framework)
The MQTT broker is the nervous system: all sensor data (temperatures, cooling state, door lock, CO₂, thermal camera images) flows through it. Commands to the coldroom and MARTA also go over MQTT.

5 entry points — know which one does what
File	Role	When to touch it
integration.py	Main app — module testing, CAEN control, thermal camera, ring diagram	Most development happens here
cold.py	Coldroom + MARTA monitoring GUI	Cooling system changes
coldroom/safety.py	Safety interlock logic	Has 4 HIGH bugs — treat carefully
caen/caenGUI.py	CAEN power supply widget	HV/LV control changes
power_supply/power_supply_ctrl.py	Rigol bench supply panel	Standalone power supply work
The module test workflow (what operators actually do)

1. Open integration.py
2. Type ring name (e.g. "L1_47_A#1") → ring diagram draws
3. Click a slot → Module ID fills automatically (from DB)
4. Verify fiber (SfibA/B) and power (R01;M1.x) dropdowns are green (connected)
5. Click [Check ID] → runs Ph2_ACF → confirms module is alive
6. Click [HV OFF Test] → noise measurement, room lights on
7. Click [HV ON Test] → dark noise + calibration
8. Watch thermal plot for overheating (Tmax displayed live from thermal camera)
9. Results auto-populate the noise table
Between steps, the thermal camera and Ph2_ACF chip temperatures arrive continuously via MQTT and update the plot live.

The codebase mental model
integration.py (2272 lines) is the hub. It:

Inherits from ui/integration_gui.py (auto-generated from Qt Designer .ui file — don't edit directly)
Creates a ModuleDB widget, a CAENControl object, and a paho MQTT client
Has one giant on_mqtt_message() callback handling ALL incoming MQTT topics
Runs tests via CommandWorker(QThread) which wraps subprocess.run()
coldroom/system.py is the hub for the coldroom side. It holds one shared _status dict that all subsystems read/write. MartaColdRoomMQTTClient fills it; safety.py reads it.

db/module_db.py is the inventory tab — loads all modules from REST, filters them, shows details. All DB writes go through make_api_request() in integration.py.

The bugs you need to fix first (priority order)
These are in issues.md. Here's the action order for a new developer:

1. Fix immediately (safety-critical, will crash in production)
Bug	File	1-line fix
BUG-01	integration.py:792	self.caenGUI → self.caen (thermal shutdown is broken)
BUG-03	coldroom/system.py:213	loop_start() → loop_stop()
BUG-04	coldroom/command_worker.py:79	Switch to Popen so Cancel button works
BUG-10	coldroom/safety.py:76,88,98	Remove tuple from return False, "..." → just return False
BUG-12	coldroom/safety.py:139	Fix elapsed_time → compute from last_update
2. Fix soon (safety logic broken but not immediately crashing)
Bug	File	What's wrong
BUG-11	coldroom/safety.py:82	Checks door_status key, reads CmdDoorUnlock_Reff — KeyError
BUG-13	coldroom/safety.py:435	switch_all_lv_off() is commented out — LV never actually cuts
BUG-09	db/module_db.py:352	Disconnect button crashes — missing argument
3. Fix when you touch those areas
The MEDIUM bugs (BUG-16 through BUG-26) won't crash immediately but cause subtle wrong behaviour — stale Cancel button, GUI freezes on slow network, wrong fuse ID lookup, camera name mismatch.

Key PyQt5 patterns used in this project
You'll encounter these everywhere:

QThread for background work:


class CommandWorker(QThread):
    finished = pyqtSignal(int)  # emits when done
    def run(self):
        result = subprocess.run(...)
        self.finished.emit(result.returncode)
Signals/slots for thread-safe GUI updates (the right pattern):


# WRONG (BUG-14): updating widget from MQTT thread
self.tMaxLabel.setText("45.2")  # called from paho thread → random crashes

# RIGHT: emit a signal, catch it on main thread
self.temperatureUpdate.emit(45.2)  # signal defined as pyqtSignal(float)
QTimer for periodic polling:


self.timer = QTimer()
self.timer.timeout.connect(self.update)
self.timer.start(2000)  # fires every 2 seconds
Files to read when you want to understand a specific area
Topic	Read this file
CAEN protocol	caen/caenGUI.py — look at tcp_util and CAENQueryThread
Safety interlocks	coldroom/safety.py — all functions are self-contained
MQTT topics map	settings_coldroom.yaml + section 11 of workflow.md
Module DB fields	db/utils.py + section 5 of workflow.md
Test commands	settings_integration.yaml — check_id_command, light_on_command, dark_test_command
Ring diagram drawing	integration.py — search for draw_ring()
Thermal panorama	coldroom/module_temperatures_gui.py — stitch_multiple_images()
Suggested first week plan
Day 1: Read workflow.md fully. Run grep -n "def " integration.py to map the main class methods.
Day 2: Fix BUG-01 and BUG-03 (5 minutes each, enormous safety impact). Read safety.py fully.
Day 3: Fix BUG-10, BUG-11, BUG-12, BUG-13 in safety.py — these are all in one file and related.
Day 4: Fix BUG-04 (command_worker.py) and BUG-09 (module_db.py).
Day 5+: Work through the MEDIUM bugs in issues.md as you encounter the related features.
Ask me to explain or fix any specific bug, any file, or any concept — I have the full codebase context and can walk you through anything.