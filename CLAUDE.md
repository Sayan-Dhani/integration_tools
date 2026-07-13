# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this project is

A PyQt5 instrument control suite for CMS detector module testing at Pisa (CERN). Operators select a module, connect cables, and run automated electrical tests while the system monitors cooling safety in real time.

## Running the applications

```bash
# Main module testing GUI
python integration.py

# Coldroom / MARTA cooling monitor GUI
python cold.py

# Run all tests
python -m pytest tests/
# or
python -m unittest discover tests/

# Run a single test file
python -m unittest tests.test_module_db
python -m unittest tests.test_integration
```

Tests use `unittest` with mocked GUI components — hardware is not required to run them.

## Architecture

Two independent PyQt5 applications share some library code:

### `integration.py` (main testing app, ~2272 lines)
- Subclasses `ui/integration_gui.py` (auto-generated from Qt Designer — **never edit directly**)
- Creates `CAENControl`, `ModuleDB`, and a raw `paho.mqtt.client` at startup
- One giant `on_mqtt_message()` handles ALL incoming MQTT topics
- Tests run via `CommandWorker(QThread)` wrapping `subprocess.Popen` — **not** `subprocess.run`
- GUI updates from MQTT thread must go through `pyqtSignal` — direct widget writes from non-main threads crash randomly

### `cold.py` (coldroom monitor, ~2000 lines)
- Subclasses `coldroom/marta_coldroom.ui`
- Owns a `System` object (`coldroom/system.py`) which holds the single shared `_status` dict
- `MartaColdRoomMQTTClient` writes to `_status`; `coldroom/safety.py` reads it
- A `QTimer` fires `soft_interlock_check()` every **5 seconds** → calls `soft_interlock_loop()` → cuts LV if cooling is lost
- `self.system._martacoldroom` can be `None` if the MQTT broker is unreachable at startup — always guard before calling methods on it

### `coldroom/system.py`
Initializes `_status` with keys: `marta`, `coldroom`, `thermal_camera`, `caen`, `cleanroom`, `coldroomair`. The key `serviceroom` is **never populated** — code that requires it will silently fail.

### `coldroom/safety.py`
All safety logic is here. Key functions:
- `soft_interlock_loop(system_status, caen_ch_status, used_channels, caen, publish_alarm)` — main 5-second safety loop; returns `(bool, str)`
- `Is_it_safe_to_on_lv(...)` — returns a **tuple** `(bool, str)`; callers must unpack, not compare directly
- `check_marta_on_for_OT/IT(system_status)` — uses `marta.fsm_state` as primary signal; `serviceroom` valve data is optional
- `switch_all_lv_off(caen, used_channels)` — the actual power cutoff action

### Communication layers
| Protocol | Target | Used by |
|----------|--------|---------|
| HTTP REST | `pccmslab1:5000` (MongoDB) | `db/module_db.py` |
| TCP binary | `192.168.0.45:7000` (CAEN HV/LV) | `caen/caenGUI.py` |
| VISA/TCP | `192.168.0.16` (Rigol DP116A) | `power_supply/` |
| MQTT | `pccmslab1:1883` | everything else |
| subprocess | Ph2_ACF test framework | `CommandWorker` |

MQTT topics are defined in `settings_coldroom.yaml` and `settings_integration.yaml`.

## Key invariants

- **MARTA FSM state** is the primary CO2 cooling indicator. States `"DISCONNECTED"`, `"NONE"`, `""` mean cooling is off. This is what `check_marta_on_for_OT/IT` reads — not valve data.
- `used_channels` dict format: `{"LV": [...channel_ids...], "HV": [...channel_ids...]}` — sourced from `modules_list_tab.get_used_channels()`, which currently only returns OT channels.
- `caen.on(channel)` / `caen.off(channel)` — the CAEN API for LV/HV control.
- Qt Designer `.ui` files are compiled to `*_gui.py` — the `ui/` and `coldroom/*.ui` files are the source of truth for layouts, not the generated Python.

## Known open bugs (issues.md)

Critical bugs not yet fixed:
- **BUG-01** `integration.py:792` — thermal safety interlock uses `self.caenGUI` (doesn't exist); should be `self.caen`
- **BUG-02** `integration.py:418` — `new_session()` crashes if API call fails; must check `success` before indexing `result`
- **BUG-03** `coldroom/system.py:213` — `cleanup()` calls `loop_start()` instead of `loop_stop()` on the thermal camera client
- **BUG-04** `coldroom/command_worker.py` — `terminate_process()` calls `.poll()` on `CompletedProcess`; switch to `Popen`
- **BUG-05** `power_supply/power_supply_ctrl.py:204` — `QMainWindow` imported inside `__main__` guard, causing `NameError` when called as a library