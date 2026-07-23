"""
Unit tests for coldroom/safety.py.

All tests use MagicMock CAEN and plain dicts for system_status / caen_ch_status
so no real hardware or MQTT broker is required.

Minimal "fully safe" system_status:
    {
        "marta":    {"fsm_state": "RUNNING"},
        "coldroom": {},   # required guard key in Is_it_safe_to_on_lv
    }
Extend per-test to trigger the specific condition under test.
"""


"""
# All tests, grouped by class with progress
python -m pytest tests/test_safety.py -v

# Just a quick pass/fail summary (no names)
python -m pytest tests/test_safety.py
"""

import datetime
import logging
import unittest
from unittest.mock import MagicMock, call

# Silence safety.py's logger during tests — the interlock messages are expected
# output of intentional test conditions, not real alarms.
logging.getLogger("coldroom.safety").setLevel(logging.CRITICAL)

from coldroom.safety import (
    check_door_safe_to_open,
    check_marta_on_for_IT,
    check_marta_on_for_OT,
    soft_interlock_loop,
    switch_all_hv_off,
    switch_all_lv_off,
)


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

def _safe_status():
    """Minimal system_status for a fully connected, safe system."""
    return {
        "marta": {"fsm_state": "RUNNING"},
        "coldroom": {},
    }


def _make_caen():
    """MagicMock CAEN that records every .off() call without touching hardware."""
    caen = MagicMock()
    caen.off = MagicMock()
    return caen


def _all_off(lv=("LV0.1",), hv=("HV0.1",)):
    """caen_ch_status dict with every listed channel reported as OFF."""
    status = {}
    for ch in lv:
        status[f"caen_{ch}_IsOn"] = False
    for ch in hv:
        status[f"caen_{ch}_IsOn"] = False
    return status


def _recent_ts():
    """A last_update timestamp that is less than 10 minutes old."""
    return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _stale_ts():
    """A last_update timestamp that is more than 10 minutes old."""
    return (datetime.datetime.now() - datetime.timedelta(minutes=15)).strftime(
        "%Y-%m-%d %H:%M:%S"
    )


USED = {"LV": ["LV0.1"], "HV": ["HV0.1"]}
USED_MULTI = {"LV": ["LV0.1", "LV0.2"], "HV": ["HV0.1", "HV0.2"]}


# ---------------------------------------------------------------------------
# soft_interlock_loop
# ---------------------------------------------------------------------------

class TestSoftInterlock(unittest.TestCase):
    """5-second safety loop: monitors MARTA state and cuts power if cooling is lost."""

    # ---- Condition 1: MARTA is not safe (FSM state bad / no coldroom data) --

    def test_marta_disconnected_lv_on_triggers_shutdown(self):
        """Classic danger: cooling lost, LV still energised."""
        caen = _make_caen()
        status = {"marta": {"fsm_state": "DISCONNECTED"}}
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}
        published = []

        is_safe, msg = soft_interlock_loop(
            status, ch_status, USED, caen, published.append
        )

        self.assertFalse(is_safe)
        caen.off.assert_called()
        self.assertEqual(len(published), 1)
        self.assertIn("SAFETY INTERLOCK", published[0])

    def test_marta_disconnected_hv_only_on_triggers_shutdown(self):
        """HV alone being on is sufficient to trigger the interlock."""
        caen = _make_caen()
        status = {"marta": {"fsm_state": "DISCONNECTED"}}
        ch_status = {"caen_LV0.1_IsOn": False, "caen_HV0.1_IsOn": True}

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen)

        self.assertFalse(is_safe)
        caen.off.assert_called()

    def test_marta_disconnected_all_power_off_no_action(self):
        """MARTA gone but everything already off — nothing to protect, no action."""
        caen = _make_caen()
        status = {"marta": {"fsm_state": "DISCONNECTED"}}
        ch_status = _all_off()

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen)

        caen.off.assert_not_called()
        self.assertTrue(is_safe)

    def test_marta_fsm_none_treated_as_disconnected(self):
        """FSM state 'NONE' is an offline indicator."""
        caen = _make_caen()
        status = {"marta": {"fsm_state": "NONE"}}
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen)

        self.assertFalse(is_safe)
        caen.off.assert_called()

    def test_marta_fsm_empty_string_treated_as_disconnected(self):
        """Empty FSM state means MARTA has not reported yet — assume offline."""
        caen = _make_caen()
        status = {"marta": {"fsm_state": ""}}
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen)

        self.assertFalse(is_safe)
        caen.off.assert_called()

    def test_missing_coldroom_key_with_power_on_triggers_shutdown(self):
        """Is_it_safe_to_on_lv requires 'coldroom' to be present; without it → unsafe."""
        caen = _make_caen()
        status = {"marta": {"fsm_state": "RUNNING"}}  # no 'coldroom'
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen)

        self.assertFalse(is_safe)
        caen.off.assert_called()

    # ---- Condition 2: MARTA connected but OT CO2 not flowing ----------------

    def test_marta_running_ot_valve_closed_triggers_shutdown(self):
        """MARTA connected but serviceroom reports OT valve closed → cut power."""
        caen = _make_caen()
        status = {
            "marta": {"fsm_state": "RUNNING"},
            "coldroom": {},
            "serviceroom": {"outer_valve": 0},
        }
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}

        is_safe, msg = soft_interlock_loop(status, ch_status, USED, caen)

        self.assertFalse(is_safe)
        caen.off.assert_called()
        self.assertIn("OT CO2", msg)

    def test_marta_running_ot_valve_open_is_safe(self):
        """Valve confirmed open → no protective action."""
        caen = _make_caen()
        status = {
            "marta": {"fsm_state": "RUNNING"},
            "coldroom": {},
            "serviceroom": {"outer_valve": 1},
        }
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen)

        self.assertTrue(is_safe)
        caen.off.assert_not_called()

    def test_marta_running_no_serviceroom_falls_back_to_fsm(self):
        """Without serviceroom data, RUNNING FSM state is trusted for OT."""
        caen = _make_caen()
        status = _safe_status()  # no 'serviceroom' key
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen)

        self.assertTrue(is_safe)
        caen.off.assert_not_called()

    def test_ot_valve_closed_but_power_off_no_action(self):
        """OT CO2 not flowing, but all channels already off — nothing to cut."""
        caen = _make_caen()
        status = {
            "marta": {"fsm_state": "RUNNING"},
            "coldroom": {},
            "serviceroom": {"outer_valve": 0},
        }
        ch_status = _all_off()

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen)

        self.assertTrue(is_safe)
        caen.off.assert_not_called()

    # ---- Fully safe baseline ------------------------------------------------

    def test_fully_safe_baseline_no_action(self):
        """MARTA running, OT confirmed via FSM, all power off → safe."""
        caen = _make_caen()
        is_safe, _ = soft_interlock_loop(_safe_status(), _all_off(), USED, caen)
        self.assertTrue(is_safe)
        caen.off.assert_not_called()

    # ---- HV/LV shutdown ordering — critical safety invariant ----------------

    def test_hv_cut_before_lv(self):
        """
        HV must be switched off BEFORE LV.
        Cutting LV first while HV is still ramped risks an uncontrolled
        discharge through the silicon sensors.
        """
        caen = _make_caen()
        status = {"marta": {"fsm_state": "DISCONNECTED"}}
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": True}

        soft_interlock_loop(status, ch_status, USED, caen)

        calls = caen.off.call_args_list
        self.assertEqual(len(calls), 2)
        self.assertEqual(calls[0], call("HV0.1"))
        self.assertEqual(calls[1], call("LV0.1"))

    def test_all_channels_shut_down_and_hv_first(self):
        """With multiple channels, every channel is cut and all HV calls precede all LV calls."""
        caen = _make_caen()
        status = {"marta": {"fsm_state": "DISCONNECTED"}}
        ch_status = {
            "caen_LV0.1_IsOn": True, "caen_LV0.2_IsOn": True,
            "caen_HV0.1_IsOn": True, "caen_HV0.2_IsOn": True,
        }

        soft_interlock_loop(status, ch_status, USED_MULTI, caen)

        turned_off = [c.args[0] for c in caen.off.call_args_list]
        for ch in ("HV0.1", "HV0.2", "LV0.1", "LV0.2"):
            self.assertIn(ch, turned_off)

        hv_last = max(i for i, ch in enumerate(turned_off) if ch.startswith("HV"))
        lv_first = min(i for i, ch in enumerate(turned_off) if ch.startswith("LV"))
        self.assertLess(hv_last, lv_first, "All HV calls must precede all LV calls")

    # ---- Alarm publishing ---------------------------------------------------

    def test_alarm_published_exactly_once_per_trip(self):
        caen = _make_caen()
        status = {"marta": {"fsm_state": "DISCONNECTED"}}
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}
        published = []

        soft_interlock_loop(status, ch_status, USED, caen, published.append)

        self.assertEqual(len(published), 1)

    def test_publish_alarm_none_does_not_crash(self):
        """publish_alarm=None is the test/dry-run mode — must not raise."""
        caen = _make_caen()
        status = {"marta": {"fsm_state": "DISCONNECTED"}}
        ch_status = {"caen_LV0.1_IsOn": True, "caen_HV0.1_IsOn": False}

        is_safe, _ = soft_interlock_loop(status, ch_status, USED, caen, publish_alarm=None)

        self.assertFalse(is_safe)

    def test_no_alarm_when_everything_safe(self):
        caen = _make_caen()
        published = []

        soft_interlock_loop(_safe_status(), _all_off(), USED, caen, published.append)

        self.assertEqual(len(published), 0)


# ---------------------------------------------------------------------------
# check_door_safe_to_open
# ---------------------------------------------------------------------------

class TestDoorSafety(unittest.TestCase):
    """Door can be opened only when dew point is safe AND HV is off."""

    def _door_safe_status(self, min_temp=-5.0, dew_point=-10.0):
        """
        Fully safe status for door-open check:
          min internal temp (-5 °C) comfortably above dew point (-10 °C) + 1 °C margin.
        """
        return {
            "coldroom": {"ch_temperature": {"value": min_temp}},
            "marta": {"TT05_CO2": min_temp, "TT06_CO2": min_temp},
            "cleanroom": {"dewpoint": dew_point, "last_update": _recent_ts()},
        }

    # ---- Missing data guards ------------------------------------------------

    def test_no_coldroom_key_returns_false(self):
        is_safe, msg = check_door_safe_to_open({}, {}, USED)
        self.assertFalse(is_safe)
        self.assertIn("coldroom", msg.lower())

    def test_no_cleanroom_last_update_treats_as_expired(self):
        status = {"coldroom": {}, "cleanroom": {"dewpoint": -10.0}}  # no last_update
        is_safe, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertFalse(is_safe)
        self.assertIn("expired", msg)

    def test_stale_cleanroom_data_blocks_door(self):
        status = {
            "coldroom": {},
            "cleanroom": {"dewpoint": -10.0, "last_update": _stale_ts()},
        }
        is_safe, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertFalse(is_safe)
        self.assertIn("expired", msg)

    def test_unparseable_timestamp_treated_as_expired(self):
        status = {
            "coldroom": {},
            "cleanroom": {"dewpoint": -10.0, "last_update": "not-a-date"},
        }
        is_safe, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertFalse(is_safe)
        self.assertIn("expired", msg)

    def test_no_internal_temps_blocks_door(self):
        """No MARTA or coldroom temperatures → cannot verify dew point."""
        status = {
            "coldroom": {},  # no ch_temperature
            "cleanroom": {"dewpoint": -10.0, "last_update": _recent_ts()},
        }
        is_safe, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertFalse(is_safe)
        self.assertIn("temperature", msg.lower())

    def test_no_dewpoint_reading_blocks_door(self):
        status = {
            "coldroom": {"ch_temperature": {"value": -5.0}},
            "marta": {"TT05_CO2": -5.0},
            "cleanroom": {"last_update": _recent_ts()},  # no "dewpoint" key
        }
        is_safe, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertFalse(is_safe)
        self.assertIn("dew point", msg.lower())

    # ---- Dew point logic ----------------------------------------------------

    def test_safe_when_temp_well_above_dew_point(self):
        """-5 °C internal > -10 °C dew + 1 °C margin (-9 °C) → safe."""
        status = self._door_safe_status(min_temp=-5.0, dew_point=-10.0)
        is_safe, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertTrue(is_safe)
        self.assertIn("YES", msg)

    def test_unsafe_when_temp_below_dew_point_plus_margin(self):
        """-10 °C internal ≤ -9 °C margin → condensation risk."""
        status = self._door_safe_status(min_temp=-10.0, dew_point=-10.0)
        is_safe, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertFalse(is_safe)
        self.assertIn("NO", msg)

    def test_exact_margin_boundary_is_unsafe(self):
        """Condition is strictly >; equal to margin means not safe."""
        # min_temp == dew_point + 1  →  -9 == -10 + 1  →  NOT strictly greater
        status = self._door_safe_status(min_temp=-9.0, dew_point=-10.0)
        is_safe, _ = check_door_safe_to_open(status, _all_off(), USED)
        self.assertFalse(is_safe)

    def test_dew_point_reason_includes_actual_temperatures(self):
        """Message must show the numeric values so operators know the actual margin."""
        status = self._door_safe_status(min_temp=-5.0, dew_point=-10.0)
        _, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertIn("-5.0", msg)
        self.assertIn("-10.0", msg)

    # ---- HV checks ----------------------------------------------------------

    def test_hv_on_blocks_door_and_lists_channel(self):
        status = self._door_safe_status()
        ch_status = {"caen_HV0.1_IsOn": True}
        is_safe, msg = check_door_safe_to_open(status, ch_status, USED)
        self.assertFalse(is_safe)
        self.assertIn("NO", msg)
        self.assertIn("HV0.1", msg)

    def test_hv_off_passes_hv_check(self):
        status = self._door_safe_status()
        is_safe, msg = check_door_safe_to_open(status, _all_off(), USED)
        self.assertTrue(is_safe)
        self.assertIn("all HV channels are off", msg)

    def test_multiple_hv_channels_one_on_blocks_and_names_it(self):
        status = self._door_safe_status()
        ch_status = {"caen_HV0.1_IsOn": False, "caen_HV0.2_IsOn": True}
        used = {"LV": ["LV0.1"], "HV": ["HV0.1", "HV0.2"]}
        is_safe, msg = check_door_safe_to_open(status, ch_status, used)
        self.assertFalse(is_safe)
        self.assertIn("HV0.2", msg)
        self.assertNotIn("HV0.1", msg)  # off channels should not appear

    # ---- Combined verdict ---------------------------------------------------

    def test_both_conditions_met_allows_door(self):
        status = self._door_safe_status()
        is_safe, _ = check_door_safe_to_open(status, _all_off(), USED)
        self.assertTrue(is_safe)

    def test_dew_point_ok_but_hv_on_blocks_door(self):
        status = self._door_safe_status()
        is_safe, _ = check_door_safe_to_open(status, {"caen_HV0.1_IsOn": True}, USED)
        self.assertFalse(is_safe)

    def test_hv_off_but_dew_point_unsafe_blocks_door(self):
        # min_temp at margin → dew point not safe
        status = self._door_safe_status(min_temp=-9.0, dew_point=-10.0)
        is_safe, _ = check_door_safe_to_open(status, _all_off(), USED)
        self.assertFalse(is_safe)


# ---------------------------------------------------------------------------
# check_marta_on_for_OT / IT
# ---------------------------------------------------------------------------

class TestMartaCO2Flow(unittest.TestCase):
    """OT and IT valve checks: FSM state is primary; valve data refines when available."""

    # ---- OT -----------------------------------------------------------------

    def test_ot_no_marta_data_returns_false(self):
        self.assertFalse(check_marta_on_for_OT({}))

    def test_ot_fsm_disconnected_returns_false(self):
        self.assertFalse(check_marta_on_for_OT({"marta": {"fsm_state": "DISCONNECTED"}}))

    def test_ot_fsm_none_returns_false(self):
        self.assertFalse(check_marta_on_for_OT({"marta": {"fsm_state": "NONE"}}))

    def test_ot_fsm_empty_returns_false(self):
        self.assertFalse(check_marta_on_for_OT({"marta": {"fsm_state": ""}}))

    def test_ot_running_no_serviceroom_trusts_fsm(self):
        """Without valve data, RUNNING FSM state is sufficient."""
        self.assertTrue(check_marta_on_for_OT({"marta": {"fsm_state": "RUNNING"}}))

    def test_ot_running_outer_valve_open_returns_true(self):
        status = {"marta": {"fsm_state": "RUNNING"}, "serviceroom": {"outer_valve": 1}}
        self.assertTrue(check_marta_on_for_OT(status))

    def test_ot_running_outer_valve_closed_returns_false(self):
        """Valve data overrides FSM state — closed valve means no CO2 to OT."""
        status = {"marta": {"fsm_state": "RUNNING"}, "serviceroom": {"outer_valve": 0}}
        self.assertFalse(check_marta_on_for_OT(status))

    # ---- IT -----------------------------------------------------------------

    def test_it_no_marta_data_returns_false(self):
        self.assertFalse(check_marta_on_for_IT({}))

    def test_it_fsm_disconnected_returns_false(self):
        self.assertFalse(check_marta_on_for_IT({"marta": {"fsm_state": "DISCONNECTED"}}))

    def test_it_running_no_serviceroom_trusts_fsm(self):
        self.assertTrue(check_marta_on_for_IT({"marta": {"fsm_state": "RUNNING"}}))

    def test_it_running_inner_valve_open_returns_true(self):
        status = {"marta": {"fsm_state": "RUNNING"}, "serviceroom": {"inner_valve": 1}}
        self.assertTrue(check_marta_on_for_IT(status))

    def test_it_running_inner_valve_closed_returns_false(self):
        status = {"marta": {"fsm_state": "RUNNING"}, "serviceroom": {"inner_valve": 0}}
        self.assertFalse(check_marta_on_for_IT(status))

    def test_ot_and_it_valves_are_independent(self):
        """OT valve closed should not affect IT result and vice versa."""
        status = {
            "marta": {"fsm_state": "RUNNING"},
            "serviceroom": {"outer_valve": 0, "inner_valve": 1},
        }
        self.assertFalse(check_marta_on_for_OT(status))
        self.assertTrue(check_marta_on_for_IT(status))


# ---------------------------------------------------------------------------
# switch_all_hv_off / switch_all_lv_off
# ---------------------------------------------------------------------------

class TestSwitchHelpers(unittest.TestCase):
    """Direct tests for the channel-switching primitives."""

    def test_switch_hv_off_calls_caen_off_for_each_channel(self):
        caen = _make_caen()
        used = {"LV": [], "HV": ["HV0.1", "HV0.2"]}
        result = switch_all_hv_off(caen, used)
        self.assertTrue(result)
        caen.off.assert_any_call("HV0.1")
        caen.off.assert_any_call("HV0.2")

    def test_switch_lv_off_calls_caen_off_for_each_channel(self):
        caen = _make_caen()
        used = {"LV": ["LV0.1", "LV0.2"], "HV": []}
        result = switch_all_lv_off(caen, used)
        self.assertTrue(result)
        caen.off.assert_any_call("LV0.1")
        caen.off.assert_any_call("LV0.2")

    def test_switch_hv_off_skips_none_entries(self):
        caen = _make_caen()
        used = {"LV": [], "HV": [None, "HV0.1"]}
        switch_all_hv_off(caen, used)
        caen.off.assert_called_once_with("HV0.1")

    def test_switch_lv_off_skips_none_entries(self):
        caen = _make_caen()
        used = {"LV": [None, "LV0.1"], "HV": []}
        switch_all_lv_off(caen, used)
        caen.off.assert_called_once_with("LV0.1")

    def test_switch_hv_returns_false_on_caen_error(self):
        caen = _make_caen()
        caen.off.side_effect = RuntimeError("TCP connection lost")
        result = switch_all_hv_off(caen, {"LV": [], "HV": ["HV0.1"]})
        self.assertFalse(result)

    def test_switch_lv_returns_false_on_caen_error(self):
        caen = _make_caen()
        caen.off.side_effect = RuntimeError("TCP connection lost")
        result = switch_all_lv_off(caen, {"LV": ["LV0.1"], "HV": []})
        self.assertFalse(result)

    def test_empty_channel_lists_return_true_without_calling_off(self):
        """No channels configured — nothing to do, still success."""
        caen = _make_caen()
        self.assertTrue(switch_all_hv_off(caen, {"LV": [], "HV": []}))
        self.assertTrue(switch_all_lv_off(caen, {"LV": [], "HV": []}))
        caen.off.assert_not_called()


if __name__ == "__main__":
    unittest.main()
