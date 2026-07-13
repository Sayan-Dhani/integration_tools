# Integration Tools — Simplified Workflow & Architecture
> Covers the `integration_tools_new` repository as of branch `fix-safely-and-coldroom-power-supply`

---

## 1. What this software does

This is a **PyQt5 desktop GUI suite** used at CERN/Pisa for testing CMS Outer Tracker and Inner Tracker modules. It lets operators:

- Track detector modules in a database (inventory, mounting status, connections)
- Run automated electrical tests on individual modules (check ID, noise tests)
- Control and monitor the CAEN high-voltage / low-voltage power supply
- Monitor and control the cold room and MARTA CO₂ cooling system
- Watch a rotating thermal camera and spot overheating in real time
- Enforce safety interlocks (dew point, HV status, door status)

---

## 2. High-level architecture

```
┌─────────────────────────────────────────────────────────────┐
│                  integration.py  (MainApp)                  │
│   Main GUI window — ties everything together                │
│                                                             │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌───────────┐    │
│  │ Module   │  │  CAEN    │  │  MQTT    │  │  Shell    │    │
│  │  DB Tab  │  │ Control  │  │ listener │  │ Commands  │    │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬─────┘    │
│       │              │              │               │       │
└───────┼──────────────┼──────────────┼───────────────┼───────┘
        │              │              │               │
   HTTP REST        TCP socket    MQTT broker     subprocess
   (module DB)     (CAEN server)  (pccmslab1)    (Ph2_ACF tests)

┌─────────────────────────────────┐
│   cold.py / marta_coldroom.py   │
│   Coldroom / MARTA GUI          │
│                                 │
│  ┌──────────┐  ┌─────────────┐  │
│  │ System   │  │ Safety      │  │
│  │ (MQTT)   │  │ Interlocks  │  │
│  └──────────┘  └─────────────┘  │
└─────────────────────────────────┘

┌──────────────────────────────────┐
│  power_supply/power_supply_ctrl  │
│  Rigol DP116A GUI (standalone)   │
│  Connects via VISA/TCP           │
└──────────────────────────────────┘
```

---

## 3. Entry points

| Script | Purpose |
|--------|---------|
| `python integration.py` | Main integration GUI (most used) |
| `python cold.py` | Coldroom / MARTA monitoring GUI |
| `python power_supply/power_supply_ctrl.py` | Standalone Rigol power supply panel |
| `python caen/caenGUIall.py` | Standalone CAEN multi-channel panel |
| `python Inner_tracker_GUI/caenGUIall_v2.py` | Inner Tracker CAEN panel |

---

## 4. Main Integration GUI — step-by-step workflow

### 4.1 Application startup (`integration.py`)

```
app starts
  │
  ├─ load UI from ui/integration.ui
  ├─ load settings from ~/.config/integration_ui/settings.yaml
  │    (falls back to settings_integration.yaml in repo)
  ├─ create ModuleDB widget → queries REST API at db_url/modules
  ├─ create CAENControl object → starts 2-second timer to poll CAEN
  ├─ connect to MQTT broker → subscribe to:
  │    /ar/thermal/image      (thermal camera frames)
  │    /ph2acf/data           (chip temperatures from Ph2_ACF)
  │    /air/status            (dry-air system)
  │    shellies/ventola/...   (fan power monitor via Shelly plug)
  └─ restore last session ring from ~/.config/integration_ui/lastsession.txt
```

### 4.2 Selecting a module for testing

```
Operator types ring name in Ring field  (e.g. "L1_47_A#1")
  │
  ├─ split_ring_and_position() extracts ring ID and slot number
  ├─ draw_ring() redraws the circular ring diagram
  │    blue rectangles = slots with mounted modules
  │    red rectangle   = currently selected slot
  │
  └─ Operator clicks a rectangle OR types in Position field
       │
       ├─ If a module is mounted there, the Module ID field auto-fills
       └─ Operator can also manually type a Module ID
            │
            └─ module_changed() fires:
                 ├─ load_module_details() → GET /modules/{id}
                 │    stores module data, extracts lpGBT fuse ID
                 │    (used to match incoming Ph2_ACF temperature data)
                 └─ queries /snapshot to restore fiber & power dropdowns
```

### 4.3 Connecting fiber and power

```
Fiber dropdown   (SfibA, SfibB, E3;1 … E3;5)
Power dropdown   (BINT1, R01;M1.1 … R01;M3.12)

  ├─ Connect Power button → POST /disconnect_all_detSide, then POST /connect
  ├─ Connect Fiber button → same pattern
  │
  └─ Status LEDs update automatically:
       green = connected and matches selected module
       yellow = connected but to a different module
       red    = not connected
```

Connections are stored in the REST database and reflected back in the Module Inventory tab.

### 4.4 Running tests

Three test buttons trigger shell commands defined in Settings:

```
[Check ID]          → runs check_id_command
  │  expands {module_id}, {fiber_endpoint}, {session}, etc.
  │
  └─ CommandWorker (QThread) runs the command
       ├─ success: LED turns green, enables next tests, parses module ID from stdout
       └─ fail:    LED turns red

[HV OFF Test]       → runs light_on_command
  │  (noise test with room lights ON, HV OFF)
  └─ same pattern; parses noise results from DB on success

[HV ON Test]        → runs dark_test_command
  │  (dark noise + calibration, HV ON)
  └─ on success: queries /module_test_analysis/{name}
       extracts per-chip Average SSA/MPA noise
       displays result in the Noise table label
```

The `{fiber_endpoint}` placeholder is resolved at test time from the live connection snapshot — it encodes which FC7 board and optical group to use.

All commands are cancellable via the Cancel button (kills the worker thread).

### 4.5 Thermal camera feedback

```
MQTT /ar/thermal/image  →  on_mqtt_message()
  │  raw bytes: 24×32 float array (768 floats × 4 bytes)
  │
  ├─ reshapes to 24×32, updates thermal image plot
  ├─ tracks min/max/avg trend over last 600 samples
  ├─ publishes summary to /integration/thermalcamera
  │
  └─ Safety thresholds:
       Tmax > 45 °C → CAEN safe_lv_off() (ramp HV down first, then kill LV)
       Tmax > 50 °C → immediate HV + LV off
```

### 4.6 Ph2_ACF chip temperature overlay

```
MQTT /ph2acf/data  →  on_mqtt_message()
  │  JSON with lpGBT fuse ID and per-chip temperatures
  │
  ├─ filters to only process data matching current module's fuse ID
  ├─ looks up temperature offsets from module DB record
  ├─ computes SSA mean/max and MPA mean/max
  └─ overlays on the same thermal trend plot (dashed lines if offsets missing)
```

### 4.7 Mounting / unmounting modules

```
Mount button:
  1. Validate: module ID, ring ID, position all filled
  2. Check no module already at target position
  3. Check module not already mounted elsewhere
  4. PUT /modules/{id}  with  mounted_on = "L1;5", status = "MOUNTED"
  5. Redraw ring (slot turns blue)

Unmount button:
  1. PUT /modules/{id}  with  mounted_on = "", status = "un-mounted"
  2. Redraw ring (slot turns black)
```

---

## 5. Database layer (`db/module_db.py` + REST API)

The module database is a **MongoDB backend** exposed through a REST API at `http://pccmslab1:5000`.

Key endpoints used:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/modules` | GET | List all modules |
| `/modules/{id}` | GET/PUT | Fetch or update one module |
| `/sessions` | POST | Create a test session |
| `/connect` | POST | Record a cable connection |
| `/disconnect_all_detSide` | POST | Remove all crate-side connections |
| `/disconnect_all_crateSide` | POST | Remove all detector-side connections |
| `/snapshot` | POST | Walk connection graph from a cable |
| `/module_test_analysis/{name}` | GET | Fetch analysis results |
| `/generic_module_query` | POST | MongoDB-style query |

**Module record structure** (simplified):

```json
{
  "moduleName": "PS_26_IPG-10005",
  "status": "MOUNTED",
  "mounted_on": "L1_47_A#1;5",
  "position": "OnDet@ L1_47_A#1;5",
  "grade": "A+",
  "hwId": 12345,
  "children": {
    "lpGBT": { "CHILD_SERIAL_NUMBER": "12345" },
    "PS Read-out Hybrid": { "details": { "ALPGBT_BANDWIDTH": "10Gbps" } }
  },
  "details": { "LOCATION": "Pisa", "DESCRIPTION": "..." },
  "temperature_offset": { "SSA_H0_0": -2.1, "MPA_H0_8": 1.3, ... }
}
```

The `ModuleDB` widget (tab "Module Inventory") filters by location (Pisa), speed (5G/10G), spacer type, grade, and status, and lets operators view/edit any field and disconnect cable connections.

---

## 6. CAEN control (`caen/caenGUI.py`)

```
CAENControl
  │
  ├─ CAENQueryThread (QThread)
  │    connects TCP socket to 192.168.0.45:7000 per query
  │    sends custom text protocol:  "GetStatus,PowerSupplyId:caen"
  │    parses response:  "caen_HV0.11_IsOn:1,caen_HV0.11_Voltage:100.0,..."
  │
  ├─ 2-second QTimer → fires update() → sends GetStatus query
  │    → updates LV/HV LEDs and voltage/current labels
  │
  ├─ LV On/Off buttons  → send TurnOn/TurnOff commands
  ├─ HV On/Off buttons  → same
  │
  └─ safe_lv_off():
       first call: ramp HV down (TurnOff HV), set flag lv_off_when_hv_off=True
       second call (or when HV voltage ≤ 10 V): also turn off LV
       (ensures LV is never cut before HV ramps safely)
```

The channels are updated dynamically when a module is selected:
- `setLV("LV7.5")` — called when the module's LV cable path is resolved
- `setHV("HV2.3")` — called when the module's HV cable path is resolved

---

## 7. Coldroom system (`coldroom/`)

The coldroom GUI (`cold.py`) and its supporting classes form an independent subsystem:

```
System (coldroom/system.py)
  │
  ├─ loads settings_coldroom.yaml
  ├─ holds shared _status dict:
  │    { "marta": {}, "coldroom": {}, "thermal_camera": {}, "cleanroom": {},
  │      "caen": {}, "coldroomair": {} }
  │
  ├─ MartaColdRoomMQTTClient  (subscribes to /MARTA/#, /coldroom/#, /environment/#, etc.)
  │    ├─ parses temperatures, humidity, dew point, door status
  │    ├─ handles CO₂ sensor data
  │    └─ sends commands: start_chiller, stop_co2, set_temperature_setpoint, etc.
  │
  └─ ThermalCameraMQTTClient  (subscribes to /thermalcamera/#)
       ├─ receives 24×32 float images + position from rotating camera
       ├─ accumulates last 5 images per angular position
       └─ used by ModuleTemperaturesTAB to stitch 360° panoramas
```

### Coldroom safety flow

Every MQTT message triggers safety checks in `marta_coldroom.py → on_message()`:

```
on_message received
  │
  ├─ update relevant subsystem status
  │
  └─ if has_valid_status():   ← all subsystems have reported at least once
       │
       ├─ check_dew_point():
       │    min(MARTA_supply_T, MARTA_return_T, coldroom_T) > dewpoint + 1°C ?
       │    → sets safety_flags["door_locked"]
       │
       ├─ check_door_status():
       │    is CmdDoorUnlock_Reff == 1?
       │    → sets safety_flags["sleep"]
       │
       └─ check_door_safe_to_open():
            dew point safe AND HV off?
            → sets safety_flags["door_safe"]
```

The `soft_interlock_loop` (called externally) checks:
- If LV is ON but MARTA OT is not running → publish alarm to `/alarm`
- (The actual `switch_all_lv_off()` call is currently commented out — see BUG-13)

---

## 8. Thermal camera panorama stitching (`coldroom/module_temperatures_gui.py`)

```
Camera rotates around the detector ring (0°–360°)
  │
  ├─ At each angular position, ThermalCameraMQTTClient receives a 24×32 image
  ├─ Stores last 5 images per position per camera in _stitching_data
  │
  └─ ModuleTemperaturesTAB.update_displays() (every 1 second)
       │
       ├─ For each camera (0–3):
       │    ├─ Collect all (position, image) pairs
       │    ├─ stitch_multiple_images():
       │    │    - places each image on a (24 × total_width) canvas
       │    │      at the pixel column corresponding to its angle
       │    │    - averages overlapping regions
       │    │    - normalises to 8-bit using either CO₂ temp range or auto range
       │    └─ displays as a 360°-wide false-colour strip
       │
       ├─ Overlays mounted module names at their angular positions
       └─ Temperature plot tab: per-camera max/min vs angle (with spike filter)
```

Colour scale can be fixed (CO₂ return temperature as baseline, +15/+20 °C range) or auto-scaled.

---

## 9. Power supply — Rigol DP116A (`power_supply/`)

A **simple standalone panel** (not embedded in the main GUI):

```
PowerSupplyController
  │
  ├─ connects via PyVISA over TCP: TCPIP0::192.168.0.16::INSTR
  ├─ 1-second QTimer → queries MEAS:VOLT? and MEAS:CURR?
  ├─ Set Voltage button → APPLY {voltage}
  ├─ Set Current button → SOUR:CURR {current}
  ├─ Power ON/OFF → OUTP:STAT ON/OFF
  └─ closeEvent: turns off supply, closes VISA resource
```

`scripts/rigolDP116A.py` is a CLI version of the same instrument control.

---

## 10. Settings files

| File | Loaded by | Key settings |
|------|-----------|--------------|
| `settings_integration.yaml` | `integration.py`, `db/module_db.py` | `db_url`, `mqtt_server`, test commands, topic names |
| `settings_coldroom.yaml` | `coldroom/system.py` | MQTT broker, per-subsystem topic names |
| `~/.config/integration_ui/settings.yaml` | `integration.py` (overrides bundled) | user-local overrides |
| `~/.config/integration_ui/lastsession.txt` | `integration.py` | remembers last selected ring |
| `coldroom/camera_config.yaml` | `module_temperatures_gui.py` | camera angular offsets and Front/Back side assignment |

---

## 11. Communication summary

```
┌────────────────────────────────────────────────────────────────┐
│  MQTT broker (pccmslab1:1883)                                  │
│                                                                │
│  /ar/thermal/image           ← thermal camera raw frames       │
│  /thermalcamera/#            ← camera state + per-camera imgs  │
│  /ph2acf/data                ← chip temperatures from Ph2_ACF  │
│  /MARTA/#                    ← MARTA CO₂ chiller status/cmd    │
│  /coldroom/#                 ← coldroom state/cmd              │
│  /environment/HumAndTemp001/#← cleanroom T/RH/dewpoint         │
│  /ble/CO2-1                  ← CO₂ sensor                      │
│  /air/status                 ← dry-air on/off                  │
│  /air/control                ← dry-air command                 │
│  /alarm                      ← safety alarm messages           │
│  shellies/ventola/...        ← fan power via Shelly plug       │
│  shellies/coldroomair/...    ← coldroom air bypass via Shelly  │
└────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────┐
│  REST API (pccmslab1:5000)          │
│  Module database (MongoDB backend)  │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│  TCP 192.168.0.45:7000              │
│  CAEN power supply daemon           │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│  TCP 192.168.0.16 (VISA/INSTR)      │
│  Rigol DP116A power supply          │
└─────────────────────────────────────┘

┌─────────────────────────────────────┐
│  HTTP 192.168.0.204 (Shelly relay)  │
│  Dry-air bypass valve               │
└─────────────────────────────────────┘
```

---

## 12. Typical operator session flow

```
1. Start integration.py
2. Last ring auto-loaded from lastsession.txt
3. Click slot on ring diagram  →  Module ID auto-fills (if mounted)
4. Verify fiber (SfibX) and power (R01;Mx.y) dropdowns show correct connections
   (green LEDs = confirmed connected)
5. Fill in Operator and Comments fields
6. Click [Check ID]
   →  runs moduleTest.py --board FC7OT8 --slot 2 -c readOnlyID
   →  LED turns green, module ID confirmed
7. Click [HV OFF Test]
   →  runs eyeOpening test
   →  LED turns green
8. Click [HV ON Test]
   →  runs calibrationandpedenoise
   →  noise table updates with SSA/MPA values per hybrid
9. Monitor thermal plot during test (Tmax displayed live)
10. Click [Show Results] or [Open in Browser] to view full HTML analysis
11. If moving to next module: type new ring position or click ring diagram
    →  test LEDs reset automatically
```
