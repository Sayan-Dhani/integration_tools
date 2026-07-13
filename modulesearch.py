#!/usr/bin/env python3
import sys
import argparse
from db.utils import *


def print_module_info(module_name):
    print(f"********** module: {module_name} ***********")
    # get module connections
    module_connections = get_module_endpoints(module_name)
    if not module_connections:
        print(f"Module '{module_name}' not found or has no connections.")
        return False

    for conn_type, conn_value in module_connections.items():
        if conn_value:
            print(f"{conn_type}: {conn_value}")
        else:
            print(f"{conn_type}: Not connected")

    module = get_module(module_name)
    if module:
        print(f"Mounted_on: {module.get('mounted_on', 'N/A')}")
        print(f"Speed: {get_module_speed(module)}")
        print(f"lpGBT_Version: {get_module_lpgbtVersion(module)}")
    else:
        print(f"Module details for '{module_name}' not found.")
    return True


def main():
    parser = argparse.ArgumentParser(description="Search for module information.")
    parser.add_argument(
        "search_terms", nargs="*", help="Module names or FC7 identifiers to search for."
    )
    parser.add_argument(
        "-r",
        "--reverse",
        action="store_true",
        help="Reverse search from FC7 identifier (format: FC7_NAME_PORT).",
    )

    args = parser.parse_args()

    if not args.search_terms:
        parser.print_help()
        sys.exit(0)

    for term in args.search_terms:
        if args.reverse:
            # logic for reverse search
            if "_" in term:
                fc7, port = term.rsplit("_", 1)
            else:
                print(f"Invalid FC7 identifier format: {term}. Expected FC7NAME_PORT.")
                continue

            module_name = get_module_name_from_fc7(fc7, port)
            if module_name:
                print_module_info(module_name)
            else:
                print(f"No module found for FC7: {fc7} Port: {port}")
        else:
            if not print_module_info(term):
                # Optionally handle module not found
                pass


if __name__ == "__main__":
    main()
