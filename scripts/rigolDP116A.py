import pyvisa as visa
import time
import argparse

# Define the IP address of the Rigol DP1116A power supply
ip_address = "192.168.0.16"

# Connect to the device via Ethernet using VISA
rm = visa.ResourceManager()
power_supply = rm.open_resource(f"TCPIP0::{ip_address}::INSTR")


# Function to turn the power supply ON
def power_on():
    try:
        power_supply.write("OUTP:STAT ON\x00")  # Turn on output
        print("Power Supply is ON.")
    except Exception as e:
        print(f"Error turning on power supply: {e}")


# Function to turn the power supply OFF
def power_off():
    try:
        power_supply.write("OUTP:STAT OFF\x00")  # Turn off output
        print("Power Supply is OFF.")
    except Exception as e:
        print(f"Error turning off power supply: {e}")


# Function to set the voltage
def set_voltage(voltage):
    try:
        power_supply.write(f"APPLY {voltage}\x00")  # Set voltage
        print(f"Voltage set to {voltage}V.")
    except Exception as e:
        print(f"Error setting voltage: {e}")


# Function to set the current
def set_current(current):
    try:
        power_supply.write(f"SOUR:CURR {current}\x00")  # Set current
        print(f"Current set to {current}A.")
    except Exception as e:
        print(f"Error setting current: {e}")


# Function to read voltage
def read_voltage():
    try:
        voltage = power_supply.query("MEAS:VOLT?\x00")  # Query voltage
        print(f"Voltage: {voltage} V")
    except Exception as e:
        print(f"Error reading voltage: {e}")


# Function to read current
def read_current():
    try:
        current = power_supply.query("MEAS:CURR?\x00")  # Query current
        print(f"Current: {current} A")
    except Exception as e:
        print(f"Error reading current: {e}")


# Main function to handle command-line arguments
def main():
    parser = argparse.ArgumentParser(
        description="Control Rigol DP1116A Power Supply via VISA."
    )

    # Command-line arguments
    parser.add_argument(
        "-v", "--voltage", type=float, help="Set the voltage (in volts)"
    )
    parser.add_argument("-i", "--current", type=float, help="Set the current (in amps)")
    parser.add_argument("--on", action="store_true", help="Turn the power supply ON")
    parser.add_argument("--off", action="store_true", help="Turn the power supply OFF")

    args = parser.parse_args()

    # Turn on power supply if --on is specified
    if args.on:
        power_on()

    # Turn off power supply if --off is specified
    if args.off:
        power_off()

    # Set voltage if specified with -v argument
    if args.voltage is not None:
        set_voltage(args.voltage)

    # Set current if specified with -i argument
    if args.current is not None:
        set_current(args.current)

    # Read and print voltage and current values
    time.sleep(1)
    read_voltage()
    read_current()

    # Optional: Add delay before turning off power supply after all operations


#    if not args.on and not args.off:
#        time.sleep(2)
#        power_off()

if __name__ == "__main__":
    main()
