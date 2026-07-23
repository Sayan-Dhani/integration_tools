import os
import datetime
import yaml
import logging

logger = logging.getLogger(__name__)

safety_settings = {
    "internal_temperatures": [
        "TT05_CO2",  # MARTA supply temperature
        "TT06_CO2",  # MARTA return temperature
        "ch_temperature",  # Coldroom temperature
    ]
}

### Safety functions ###
# Example of a safety function
# def check_dummy_condition(*args, **kwargs):
#     # Dummy condition check
#     return True


def check_dew_point(system_status):
    logger.debug(f"Checking dew point: {system_status}")
    try:
        # Get the three required temperature values
        marta_supply_temp = system_status.get("marta", {}).get("TT05_CO2")
        marta_return_temp = system_status.get("marta", {}).get("TT06_CO2")
        coldroom_temp = (
            system_status.get("coldroom", {}).get("ch_temperature", {}).get("value")
        )
        # coldroom = system_status.get("coldroom", {})
        # logger.debug(f"Coldroom: {coldroom.get('CmdDoorUnlock_Reff')}")
        # door_status = system_status.get("coldroom", {}).get("CmdDoorUnlock_Reff")
        # logger.debug(f"Door status: {door_status}")

        # Create list of available temperatures
        internal_temperatures = []
        if marta_supply_temp is not None:
            internal_temperatures.append(marta_supply_temp)
        if marta_return_temp is not None:
            internal_temperatures.append(marta_return_temp)
        if coldroom_temp is not None:
            internal_temperatures.append(coldroom_temp)

        # logger.debug(f"Available temperatures: {internal_temperatures}")

        # Only proceed if we have all three temperatures
        # if len(internal_temperatures) != 3:
        #     logger.debug(f"Not all temperatures available. Found {len(internal_temperatures)} out of 3")
        #     return False

        # Get the minimum temperature among the three
        min_temperature = min(internal_temperatures)

        if "coldroom" not in system_status:
            logger.debug("Coldroom data not available")
            return (
                False  # Conservative approach - if we can't check, assume it's unsafe
            )

        # Check if environment data exists
        if (
            "cleanroom" not in system_status
            or "dewpoint" not in system_status["cleanroom"]
        ):
            return False  # Conservative approach
        reference_dew_point = system_status["cleanroom"][
            "dewpoint"
        ]  # External dewpoint
        logger.debug(f"Reference dew point: {reference_dew_point}")
        delta = 1  # Allowable delta between dew point and temperature
        return min_temperature > reference_dew_point + delta
    except Exception as e:
        logger.debug(f"Error in check_dew_point: {str(e)}")
        return False  # Conservative approach - a bare False, not a truthy tuple


def check_door_status(system_status):
    try:
        if (
            "coldroom" not in system_status
            or "CmdDoorUnlock_Reff" not in system_status["coldroom"]
        ):
            return False  # Conservative approach
        return system_status["coldroom"]["CmdDoorUnlock_Reff"] == 1  # Door is open
    except Exception as e:
        logger.debug(f"Error in check_door_status: {str(e)}")
        return False  # Conservative approach - a bare False, not a truthy tuple


def check_light_status(system_status):
    try:
        if "coldroom" not in system_status or "light" not in system_status["coldroom"]:
            return False  # Conservative approach
        return system_status["coldroom"]["light"] == 1  # Light is on
    except Exception as e:
        logger.debug(f"Error in check_light_status: {str(e)}")
        return False  # Conservative approach - a bare False, not a truthy tuple


def check_any_hv_on(caen_ch_status, used_channels):
    try:
        # Check if any used channel is on
        hv_on = False
        for channel in used_channels["HV"]:
            ch_str = f"caen_{channel}_IsOn"
            if bool(caen_ch_status.get(ch_str, False)):
                hv_on = True
                break
        return hv_on
    except Exception as e:
        logger.debug(f"Error in check_any_hv_on: {str(e)}")
        # Conservative approach - if we can't check, assume HV is on (unsafe).
        # Return a bare True, not a truthy tuple, so callers' `not hv_on` works.
        return True


def check_cleanroom_expired(elapsed_time, threshold=600):
    return elapsed_time > threshold


def interpret_door_safety(is_safe):
    """
    Human-readable verdict for the 'Safe to open' LED, so the operator is told
    what the light means instead of having to infer it from the colour.
    """
    if is_safe:
        return "SAFE TO OPEN — you may open the door."
    return "DO NOT OPEN — conditions are unsafe, keep the door closed."


def interpret_soft_interlock(is_safe):
    """
    Human-readable verdict for the 'Soft Interlock' LED.

    Note: green means "no protective action needed" (e.g. LV is off), not
    necessarily "safe to energize LV" — the detailed message says which.
    """
    if is_safe:
        return "OK — no protective action needed (LV is protected)."
    return "INTERLOCK TRIPPED — unsafe condition, LV has been switched off."


def check_door_safe_to_open(system_status, caen_ch_status, used_channels):
    """
    Check if it's safe to open the door based on multiple safety conditions.
    Returns True if it's safe to open the door, False otherwise.
    """
    log_msg = ""
    try:
        # Check if we have all necessary data
        if "coldroom" not in system_status:
            return False, "coldroom data not available — assuming unsafe"

        # 1. Check if dew point conditions are safe.
        # Cleanroom status carries a "last_update" timestamp string, not an
        # "elapsed_time" value — derive the age from it here.
        last_update = system_status.get("cleanroom", {}).get("last_update")
        if last_update is None:
            clean_room_expired = True  # No cleanroom data → treat as expired
        else:
            try:
                last_dt = datetime.datetime.strptime(
                    last_update, "%Y-%m-%d %H:%M:%S"
                )
                elapsed_time = (datetime.datetime.now() - last_dt).total_seconds()
                clean_room_expired = check_cleanroom_expired(elapsed_time)
            except (ValueError, TypeError) as e:
                logger.debug(f"Could not parse cleanroom last_update: {str(e)}")
                clean_room_expired = True  # Unparseable → treat as expired
        # Pull raw values used by check_dew_point so we can show the actual numbers.
        marta_supply = system_status.get("marta", {}).get("TT05_CO2")
        marta_return  = system_status.get("marta", {}).get("TT06_CO2")
        coldroom_t    = system_status.get("coldroom", {}).get("ch_temperature", {}).get("value")
        temps         = [t for t in [marta_supply, marta_return, coldroom_t] if t is not None]
        ext_dew       = system_status.get("cleanroom", {}).get("dewpoint")

        if clean_room_expired:
            dew_point_safe = False
            dew_reason = "cleanroom sensor data expired (no update in >10 min)"
            log_msg += "!!! Warning: Cleanroom data expired, not able to check dew point !!!\n"
        elif not temps:
            dew_point_safe = False
            dew_reason = "no internal temperature readings available"
        elif ext_dew is None:
            dew_point_safe = False
            dew_reason = "no dew point reading from cleanroom sensor"
        else:
            dew_point_safe = check_dew_point(system_status)
            min_t = min(temps)
            if dew_point_safe:
                dew_reason = (
                    f"min internal temp {min_t:.1f}°C > "
                    f"dew point {ext_dew:.1f}°C + 1°C safety margin"
                )
            else:
                dew_reason = (
                    f"min internal temp {min_t:.1f}°C ≤ "
                    f"dew point {ext_dew:.1f}°C + 1°C safety margin"
                )
                log_msg += "!!! Warning: Dew point conditions are not safe for opening door !!!\n"
        log_msg += f"Dew point safe: {'YES' if dew_point_safe else 'NO'} ({dew_reason})\n"

        # 2. Check if high voltage is off
        hv_on   = check_any_hv_on(caen_ch_status, used_channels)
        hv_safe = not hv_on
        if not hv_safe:
            on_hv = [
                ch for ch in used_channels.get("HV", [])
                if ch and bool(caen_ch_status.get(f"caen_{ch}_IsOn", False))
            ]
            hv_reason = f"channel(s) still ON: {on_hv}" if on_hv else "HV status uncertain"
            log_msg += "!!! Warning: High voltage is ON, not safe to open door !!!\n"
        else:
            hv_reason = "all HV channels are off"
        log_msg += f"High voltage safe: {'YES' if hv_safe else 'NO'} ({hv_reason})\n"

        # 3. Check if light is off (light should be off when opening door)
        # light_off = not check_light_status(system_status)

        # 4. Check if door is currently closed (can't open if already open)
        door_closed = not check_door_status(system_status)
        if not door_closed and not (hv_safe or dew_point_safe):
            log_msg += f"!!! Warning: Door open when conditions are unsafe !!!\n"

        # It's safe to open the door if:
        # - Dew point conditions are safe
        # - High voltage is safe
        # - Light is off
        # - Door is currently closed
        is_safe = dew_point_safe and hv_safe
        return is_safe, log_msg

    except Exception as e:
        logger.debug(f"Error in check_door_safe_to_open: {str(e)}")
        return False, "Error checking door safety"


def check_light_safe_to_turn_on(system_status, caen_ch_status, used_channels):
    """
    Check if it's safe to turn on the light based on multiple safety conditions.
    Returns True if it's safe to turn on the light, False otherwise.
    """
    log_msg = ""
    try:
        # Check if we have all necessary data
        if "coldroom" not in system_status:
            return (
                False  # Conservative approach - if we can't check, assume it's unsafe
            )

        # Check if high voltage is off
        hv_on = check_any_hv_on(caen_ch_status, used_channels)
        log_msg += f"High voltage on: {hv_on}\n"
        is_safe = not hv_on
        return is_safe

    except Exception as e:
        logger.debug(f"Error in check_light_safe_to_turn_on: {str(e)}")
        return False  # Conservative approach - if we can't check, assume it's unsafe


def check_marta_safe(system_status):
    try:
        if "marta" not in system_status:
            return False, "MARTA data not available"
        if system_status["marta"].get("fsm_state") == "DISCONNECTED":
            return False, "MARTA is disconnected"
        else:
            return True, "MARTA status OK"
    except Exception as e:
        logger.debug(f"Error in check_marta_safe: {str(e)}")
        return False, "Error checking MARTA status"


# def check_lv_safe_on:

# def check_marta_on_for_ot
# def check_marta_on_for_it

# def switch_all_lv_off


# def soft_interlock_loop: ### describe only highlevel
# if condition then : action
# if ! check_lv_safe_on and something_on : switch_all_lv_off()

# when performing an active safety action here we send a msg to the alarm topic "/alarm"


def Is_any_lv_on(caen_ch_status, used_channels):
    """
    Check if any LV channel is on.
    Returns True if any LV channel is on, False if all are off.
    """
    try:
        for channel in used_channels["LV"]:
            if channel is None:
                continue
            ch_str = f"caen_{channel}_IsOn"
            if bool(caen_ch_status.get(ch_str, False)):
                logger.info(f"LV channel {channel} is ON")
                return True
        return False
    except Exception as e:
        logger.debug(f"Error in Is_any_lv_on: {str(e)}")
        return True  # Conservative - assume LV is on if we can't check


def Is_it_safe_to_on_lv(system_status, caen_ch_status, used_channels):
    """
    Check if it's safe to turn on LV channels based on multiple safety conditions.
    Returns True if it's safe to turn on LV channels, False otherwise.
    """
    log_msg = ""
    try:
        # Check if we have all necessary data
        if "coldroom" not in system_status:
            return False, "coldroom data not available — assuming unsafe"

        # Check if MARTA is running
        marta_safe, marta_msg = check_marta_safe(system_status)
        log_msg += f"MARTA safe: {marta_safe} ({marta_msg})\n"

        # It's safe to turn on LV channels if MARTA is safe
        is_safe = marta_safe
        return is_safe, log_msg

    except Exception as e:
        logger.debug(f"Error in Is_it_safe_to_on_lv: {str(e)}")
        return False, "Error checking LV safety"


# def check_lv_safe_on(caen_ch_status, used_channels):
#     """
#     Check if any LV channel is on.
#     Returns True if any LV channel is on, False if all are off.
#     """
#     try:
#         for channel in used_channels["LV"]:
#             if channel is None:
#                 continue
#             ch_str = f"caen_{channel}_IsOn"
#             if bool(caen_ch_status.get(ch_str, False)):
#                 return True
#         return False
#     except Exception as e:
#         logger.debug(f"Error in check_lv_safe_on: {str(e)}")
#         return True  # Conservative - assume LV is on if we can't check


def check_marta_on_for_OT(system_status):
    """
    Check if MARTA CO2 supply is active for OT (Outer Tracker).

    Primary signal: MARTA FSM state is not disconnected/idle.
    Secondary signal: outer_valve from serviceroom data (used when available).
    Returns True only when CO2 is confirmed to be flowing to OT modules.
    """
    try:
        if "marta" not in system_status:
            logger.debug("MARTA data not available, treating OT CO2 as OFF")
            return False

        fsm_state = system_status["marta"].get("fsm_state", "")
        logger.info(f"Checking MARTA OT status: fsm_state={fsm_state!r}")

        if fsm_state in ("DISCONNECTED", "NONE", ""):
            logger.info("MARTA is disconnected/idle, OT CO2 is OFF")
            return False

        # If serviceroom valve data is available, use it for a precise check.
        # Without it, fall back to FSM state as the best available indicator.
        if "serviceroom" in system_status:
            OT_valve = system_status["serviceroom"].get("outer_valve", 0)
            logger.info(f"MARTA OT valve status: outer_valve={OT_valve}")
            if OT_valve != 1:
                logger.info("OT valve is closed, OT CO2 is OFF")
                return False
        else:
            logger.debug("Serviceroom data unavailable, relying on MARTA FSM state for OT check")

        return True

    except Exception as e:
        logger.debug(f"Error in check_marta_on_for_OT: {str(e)}")
        return False


def check_marta_on_for_IT(system_status):
    """
    Check if MARTA CO2 supply is active for IT (Inner Tracker).

    Primary signal: MARTA FSM state is not disconnected/idle.
    Secondary signal: inner_valve from serviceroom data (used when available).
    Returns True only when CO2 is confirmed to be flowing to IT modules.
    """
    try:
        if "marta" not in system_status:
            logger.debug("MARTA data not available, treating IT CO2 as OFF")
            return False

        fsm_state = system_status["marta"].get("fsm_state", "")
        logger.info(f"Checking MARTA IT status: fsm_state={fsm_state!r}")

        if fsm_state in ("DISCONNECTED", "NONE", ""):
            logger.info("MARTA is disconnected/idle, IT CO2 is OFF")
            return False

        # If serviceroom valve data is available, use it for a precise check.
        if "serviceroom" in system_status:
            IT_valve = system_status["serviceroom"].get("inner_valve", 0)
            logger.info(f"MARTA IT valve status: inner_valve={IT_valve}")
            if IT_valve != 1:
                logger.info("IT valve is closed, IT CO2 is OFF")
                return False
        else:
            logger.debug("Serviceroom data unavailable, relying on MARTA FSM state for IT check")

        return True

    except Exception as e:
        logger.debug(f"Error in check_marta_on_for_IT: {str(e)}")
        return False


def switch_all_hv_off(caen, used_channels):
    """
    Turn off all HV channels.
    Must be called BEFORE switch_all_lv_off — cutting LV while HV is still
    ramped risks a sudden uncontrolled discharge through the silicon sensors.
    Returns True if all commands were sent successfully.
    """
    try:
        for channel in used_channels["HV"]:
            if channel is None:
                continue
            logger.warning(f"Safety interlock: turning off HV channel {channel}")
            caen.off(channel)
        return True
    except Exception as e:
        logger.error(f"Error in switch_all_hv_off: {str(e)}")
        return False


def switch_all_lv_off(caen, used_channels):
    """
    Turn off all LV channels.
    Always call switch_all_hv_off first so HV has been cut before LV is removed.
    Returns True if all commands were sent successfully.
    """
    try:
        for channel in used_channels["LV"]:
            logger.info(f"Attempting to turn off LV channel {channel}")
            if channel is None:
                continue
            logger.warning(f"Safety interlock: turning off LV channel {channel}")
            caen.off(channel)
        return True
    except Exception as e:
        logger.error(f"Error in switch_all_lv_off: {str(e)}")
        return False


def soft_interlock_loop(
    system_status, caen_ch_status, used_channels, caen, publish_alarm=None
):
    """
    Soft interlock loop - monitors safety conditions and takes protective action.

    Decision tree (evaluated every ~5 s):
      1. If MARTA is not in a safe/connected state AND any power (HV or LV) is on
             → switch all HV off first, then all LV off
      2. Else if any power is on AND MARTA CO2 is not flowing to OT modules
             → switch all HV off first, then all LV off
      HV is always cut before LV to avoid an uncontrolled discharge
      through the silicon sensors.
      (IT modules share the same MARTA CO2 system; a full MARTA shutdown
       is caught by condition 1.  Per-valve IT protection requires
       serviceroom data to be subscribed — see check_marta_on_for_IT.)

    A message is published to /alarm whenever a protective action fires.

    Args:
        system_status (dict): Full system status including MARTA, coldroom, etc.
        caen_ch_status (dict): CAEN channel status with caen_{channel}_IsOn keys.
        used_channels (dict): Active channel list {"LV": [...], "HV": [...]}.
        caen: CAEN control object with on()/off() methods.
        publish_alarm (callable, optional): publish_alarm(message_string)

    Returns:
        tuple: (is_safe: bool, message: str)
    """
    try:
        lv_on = Is_any_lv_on(caen_ch_status, used_channels)
        # Is_it_safe_to_on_lv returns (bool, str) — unpack properly
        lv_safe_to_on, lv_safe_msg = Is_it_safe_to_on_lv(
            system_status, caen_ch_status, used_channels
        )
        marta_ot = check_marta_on_for_OT(system_status)
        marta_it = check_marta_on_for_IT(system_status)

        lv_status = "ON" if lv_on else "OFF"
        marta_ot_status = "RUNNING" if marta_ot else "NOT RUNNING"
        marta_it_status = "RUNNING" if marta_it else "NOT RUNNING"

        log_msg = (
            f"\nSoft interlock: LV={lv_status}, "
            f"MARTA_OT={marta_ot_status}, MARTA_IT={marta_it_status}\n"
        )
        logger.info(log_msg)

        hv_on = check_any_hv_on(caen_ch_status, used_channels)
        hv_status = "ON" if hv_on else "OFF"
        log_msg += f"HV={hv_status}\n"

        # --- Condition 1: MARTA itself is not safe (e.g. disconnected) ---
        if not lv_safe_to_on:
            log_msg += "\n!!! Warning: MARTA not safe — LV safe to turn on: NO\n"
            log_msg += lv_safe_msg
            if lv_on or hv_on:
                alarm_msg = (
                    "SAFETY INTERLOCK: MARTA is not in a safe state and power is ON. "
                    "Turning off all HV then LV channels to prevent module damage."
                )
                logger.warning(alarm_msg)
                switch_all_hv_off(caen, used_channels)
                switch_all_lv_off(caen, used_channels)
                if publish_alarm:
                    publish_alarm(alarm_msg)
                return False, alarm_msg
            return True, log_msg

        log_msg += "\nLV safe to turn on: YES\n"

        # --- Condition 2: MARTA connected but CO2 not flowing to OT ---
        if (lv_on or hv_on) and not marta_ot:
            alarm_msg = (
                "SAFETY INTERLOCK: Power is ON but MARTA OT CO2 is not flowing. "
                "Turning off all HV then LV channels to prevent module damage."
            )
            logger.warning(alarm_msg)
            switch_all_hv_off(caen, used_channels)
            switch_all_lv_off(caen, used_channels)
            if publish_alarm:
                publish_alarm(alarm_msg)
            return False, alarm_msg

        log_msg += "\nAll safety conditions met.\n"
        logger.info(log_msg)
        return True, log_msg

    except Exception as e:
        err_msg = f"Error in soft_interlock_loop: {str(e)}"
        logger.error(err_msg)
        return False, err_msg
