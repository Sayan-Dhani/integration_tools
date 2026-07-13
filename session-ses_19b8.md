# Codebase overview and connections

**Session ID:** ses_19b84853cffeZtVdgrIeqyIyIP
**Created:** 5/26/2026, 3:31:14 PM
**Updated:** 5/26/2026, 3:45:22 PM

---

## User

ubderstand the whole codebase, and give me a detail overview of the project, how things are connected and working.

---

## Assistant

**Tool: read**

---

## Assistant

**Tool: task**

---

## Assistant

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

---

## Assistant

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

---

## Assistant

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

---

## Assistant

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

**Tool: read**

---

## Assistant

Here is a comprehensive overview of the project.

---

## Project: CMS Pisa Integration Tools

This is a **CMS (Compact Muon Solenoid) detector integration and testing system** for the Phase-2 Upgrade of the Inner Tracker (IT) at **CERN's Pisa site**. It provides a suite of tools to control, monitor, and test detector modules (silicon sensors) during their assembly and burn-in process.

---

### Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────┐
│                     TWO MAIN GUI APPLICATIONS                       │
│                                                                     │
│  integration.py (Burn-In Test Station)    cold.py (Cold Room Ctrl)  │
│  ┌──────────────────────────────────┐    ┌────────────────────────┐ │
│  │ Module Testing & Verification    │    │ Environmental Control  │ │
│  │ HV/LV via CAEN power supplies    │    │ MARTA CO2 Plant        │ │
│  │ Ph2_ACF readout system           │    │ Temperature/Humidity   │ │
│  │ Thermal Camera MQTT monitoring   │    │ Door/Light/Dry Air     │ │
│  │ Module mounting ring diagram     │    │ Safety interlocks      │ │
│  │ Test session management          │    │ Modules List/Layout    │ │
│  └──────────────────────────────────┘    └────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                        SHARED LAYERS                                │
│                                                                     │
│  db/            - Database REST API client (ModuleDB, utils)        │
│  caen/          - CAEN HV/LV power supply control (TCP/IP)          │
│  coldroom/      - System state, MQTT, safety, thermal camera        │
│  ui/            - PyQt5 .ui compiled GUIs                           │
│  power_supply/  - Rigol bench power supply control (USB)            │
│  plot_tab/      - InfluxDB sensor monitoring                        │
│  scripts/       - Mount modules, DB upload                          │
│  tests/         - Unit/integration tests                            │
└─────────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    EXTERNAL HARDWARE / NETWORK                       │
│                                                                     │
│  MQTT Broker (192.168.0.45)    ← Thermal Camera, Sensors, Actuators │
│  REST API (cmslabserver:5000)  ← Module database backend             │
│  CAEN Power Supply (TCP:7000)  ← HV/LV bias for modules             │
│  Ph2_ACF Test System           ← Readout board testing framework     │
│  Rigol DP116A (USB/Serial)     ← Bench power supply                  │
│  Shellies Smart Switches       ← Air/dry air control                 │
└─────────────────────────────────────────────────────────────────────┘
```

---

### Major Components

#### 1. `integration.py` — Main Burn-In Test Station GUI
- **Purpose**: The primary interface for operators testing detector modules on the integration bench
- **Key features**:
  - **Ring Diagram**: Visual representation of the detector ring with clickable module positions (`integration.py:774-877`)
  - **Test Execution Pipeline**: Three sequential tests: Check ID → Light ON Test (eyeOpening) → Dark Test (calibration+pedestal+noise) (`integration.py:1053-1201`)
  - **Command Expansion**: Placeholder system (`{module_id}`, `{fiber_endpoint}`, `{session}`) for flexible command construction (`integration.py:958-968`)
  - **MQTT Monitoring**: Subscribes to thermal camera data (`/ar/thermal/image`), Ph2_ACF temperatures (`/ph2acf/data`), and air status (`integration.py:517-751`)
  - **CAEN Power Control**: Integrated CAEN HV/LV GUI tab for biasing modules
  - **Session Management**: Creates test sessions on the database with operator info, comments, timestamp (`integration.py:390-413`)
  - **Thermal Safety**: Auto-shutdown HV/LV if temperature exceeds 45°C/50°C (`integration.py:727-731`)
  - **Module DB Integration**: Full module inventory browse, search, filter, and detail view

#### 2. `cold.py` — Cold Room & MARTA Control GUI
- **Purpose**: Full environmental control and monitoring for the cold room where modules are tested at low temperatures
- **Key features**:
  - **MARTA CO₂ Plant Control**: Temperature setpoint, chiller speed, CO₂ flow control, start/stop (`cold.py:294-492`)
  - **Cold Room Control**: Temperature/Humidity regulation, lights, dry air, door lock, run state (`cold.py:554-903`)
  - **Safety Interlocks**: Dew point checking, door safe-to-open logic, light safe-to-turn-on, HV interlock, CO₂ level monitoring (`coldroom/safety.py`)
  - **Modules List Tab**: Interactive table showing each module's position, power status (HV/LV), fiber connection, temperature, and grade (`coldroom/modules_list_gui.py`)
  - **Thermal Camera Tab**: Real-time 24×32 thermal image display, trend plots (`coldroom/thermal_camera_gui.py`)
  - **Module Temperatures Tab**: Ph2_ACF temperature monitoring with SSA/MPA mean/max trends (`coldroom/module_temperatures_gui.py`)
  - **CAEN Control**: Two CAEN tabs — one for the Outer Tracker (OT) and one for the Inner Tracker (IT)

#### 3. `db/` — Database Layer
- **`module_db.py`**: Central DB widget with module inventory tree, search/filter by layer/speed/spacer/grade, module detail view (FB, EB, connections, temperature offsets, grade, comments) (`db/module_db.py`)
- **`utils.py`**: REST API helper functions for all DB operations:
  - `get_module()` — Fetch single module by ID
  - `get_modules_on_ring()` — Query all modules mounted on a given ring
  - `get_module_endpoints()` — Get fiber/power connections for a module
  - `get_module_name_from_fc7()` — Reverse lookup from FC7 readout board + port
  - `get_ring_from_cable()` — Determine which ring a Harting cable connects to
  - `get_module_speed()`, `get_module_fuse_id()`, `get_module_lpgbtVersion()` — Various metadata lookups
- **`module_db_gui.py`**: Compiled Qt UI (`module_db.ui`) with the tree widget

#### 4. `caen/` — CAEN Power Supply Control
- **`caenGUIall.py`**: OT CAEN GUI and TCP/IP protocol client — controls HV (up to ~200V) and LV channels; queries status (current, voltage, temperature); threaded non-blocking I/O
- **`caenGUI.py`**: Simplified CAEN control used by `integration.py`
- **`caencli.py`**: CLI tool to send raw commands to CAEN power supplies

#### 5. `coldroom/` — Cold Room Subsystem
- **`system.py`**: Central `System` class holding shared state (status dict, MQTT clients, settings)
- **`marta_coldroom.py`**: `MartaColdRoomMQTTClient` — handles MQTT pub/sub for MARTA, cold room, cleanroom, CO₂ sensor, dry air bypass (`http://192.168.0.204/relay/0`)
- **`thermal_camera.py`**: `ThermalCameraMQTTClient` — receives thermal image data from MQTT
- **`safety.py`**: Safety functions — `check_dew_point()`, `check_door_safe_to_open()`, `check_light_safe_to_turn_on()`, `check_marta_safe()`, `check_any_hv_on()`
- **`modules_list_gui.py`**: Module configuration table per position
- **`module_temperatures_gui.py`**: Real-time temperature plots per module

#### 6. Standalone Tools
- **`glue_analyzer.py`** — Interactive OpenCV tool for analyzing glue contact area in module assembly images. Supports ROI selection, thresholding, gradient correction, manual painting (`glue_analyzer.py`)
- **`drawEvent.py`** — ROOT-based 3D event display for visualizing tracker hits (strips, pixels, stubs with bending) from ROOT data files (`drawEvent.py`)
- **`dbbrowser.py`** — Standalone GUI for browsing the module database
- **`dbrunsearch.py`** — CLI tool to search runs, view session details, edit session comments against the DB API
- **`modulesearch.py`** — CLI tool to query module info (connections, speed, lpGBT version) by module ID or FC7 port
- **`edit_ompo_report.py`** — PowerPoint template editor for OMPO shift reports (replaces Name/Date/Status fields)
- **`monitor_module.sh`** & **`balistic_calibration.sh`** — Shell scripts for monitoring and calibration

#### 7. `power_supply/` — Bench Power Supply
- **`rigolDP116A.py`** & **`power_supply_ctrl.py`** — Control for Rigol DP116A programmable bench power supply via USB/serial

#### 8. `plot_tab/` — Sensor Monitoring
- **`influx_3.py`** & **`sensor_monitor.py`** — InfluxDB-based sensor monitoring with historical data plotting

#### 9. `scripts/` — Utilities
- **`mount_modules.py`** — Script for mounting modules on rings
- **`py4dbupload/`** — Database upload scripts

---

### Communication & Data Flow

| Protocol / Interface | Usage |
|---|---|
| **MQTT** (paho-mqtt) | Thermal camera images, environmental sensors, actuator commands, status broadcasts |
| **REST API** (requests) | Module database CRUD operations to `cmslabserver:5000` |
| **TCP/IP** (socket) | CAEN power supply control on port 7000 |
| **USB/Serial** | Rigol DP116A bench supply |
| **Shell Commands** (subprocess) | Ph2_ACF test execution, shell scripts |
| **HTTP** (requests) | Shellies smart switch control (`192.168.0.204`) |

---

### Configuration

- **`settings_integration.yaml`**: Database URL, MQTT broker/topics, test commands (check_id, light_on, dark_test), air command, results URL
- **`settings_coldroom.yaml`**: MQTT topics for Cleanroom, Coldroom, MARTA, ThermalCamera, CO₂ sensor, Shellies air switch
- User settings saved to `~/.config/integration_ui/settings.yaml`
- Session persistence via `~/.config/integration_ui/lastsession.txt`

---

### Module Types & Geometry

The project supports three ring layers with different configurations:
- **L1** (18 modules): Three variants (47mm, 60mm, 72mm) with 2.6mm or 4.0mm spacers
- **L2** (26 modules): Three variants (40mm, 55mm, 68mm)
- **L3** (36 modules): Single variant, 5G speed, 2.6mm spacer

Each module has fiber connections (SfibA, SfibB, E3;1-5) and power connections (BINT1, R01;M1.1-12, R01;M2.1-12, R01;M3.1-12).

---

### Entry Points

| Command | Purpose |
|---|---|
| `python integration.py` | Launch Burn-In Test Station GUI |
| `python cold.py` | Launch Cold Room / MARTA Control GUI |
| `python dbbrowser.py` | Standalone Module DB browser |
| `python modulesearch.py <module_id>` | CLI module info lookup |
| `python dbrunsearch.py <run>` | CLI run/session search |
| `python glue_analyzer.py <image>` | Glue contact analysis tool |
| `python drawEvent.py -i <file>.root` | ROOT event display |
| `python edit_ompo_report.py <in.pptx> <out.pptx>` | OMPO report editor |

---

### Test Dependencies

- Python 3 with PyQt5, matplotlib, numpy, requests, paho-mqtt, pyyaml, opencv-python, python-pptx, ROOT
- Hardware: CAEN power supplies, thermal camera (FLIR/Lepton), Rigol DP116A, Shellies smart relays, FC7/Ph2_ACF readout boards

---

## User

How to save this chat in a markdown ?

---

## Assistant

**Tool: websearch**

---

## Assistant

There are a couple ways:

**Within the TUI**: Type `/export` during a conversation to export the current session.

**From the CLI** (if the TUI doesn't work):
```bash
opencode session list          # find the session ID
opencode export <session-id> --format md -o conversation.md
```

Alternatively, install a dedicated tool for this:
```bash
pip install opencode-log
opencode-log --format both     # generates both HTML and Markdown
```

Or install the autosave plugin:
```bash
npm install -g opencode-autosave-conversation
# then add to your opencode.json
```

---

