#!/usr/bin/python
# first source py4dbupload/bin/setup.sh to set up environment, then run the script with appropriate arguments
# example usage: python3 mount_modules.py PS_16_10_IPG-00005 L1_47_A#1 --position-index 2
import argparse
from py4dbupload.modules.Utils import DBaccess, DBupload
from lxml import etree
import os
import datetime

PISA_LOCATION = "Pisa"


def check_components(db, module_label, ring_label):
    # Check module location
    module_loc = db.component_location(module_label)
    if not module_loc:
        raise ValueError(f"Module {module_label} not found in database")
    print(f"Module {module_label} is in location {module_loc}")

    # Check ring location
    ring_loc = db.component_location(ring_label)
    if not ring_loc:
        raise ValueError(f"Ring {ring_label} not found in database")

    # Verify same location
    if module_loc != ring_loc:
        raise ValueError(
            f"Module and Ring are in different locations: {module_loc} vs {ring_loc}"
        )

    # Need to add a check for Tracker Detector ROOT

    # Get location name
    location_id = db.get_location_id(PISA_LOCATION)
    if module_loc != location_id:
        raise ValueError(f"Components not in PISA location")

    print(
        f"Components verified: {module_label} and {ring_label} are in {PISA_LOCATION}"
    )

    return True


def build_connect_xml(
    ring_barcode, module_label, position_index, integration_status="Attached"
):
    root = etree.Element("ROOT")
    parts = etree.SubElement(root, "PARTS")

    # Ring part
    ring = etree.SubElement(parts, "PART")
    ring.set("mode", "auto")
    etree.SubElement(ring, "KIND_OF_PART").text = "TBPS Ring"
    etree.SubElement(ring, "NAME_LABEL").text = ring_barcode

    # Children section
    children = etree.SubElement(ring, "CHILDREN")

    # Module part
    module = etree.SubElement(children, "PART")
    module.set("mode", "auto")
    etree.SubElement(module, "KIND_OF_PART").text = "PS Module"
    etree.SubElement(module, "NAME_LABEL").text = module_label

    # Add Status attribute
    attrs = etree.SubElement(module, "PREDEFINED_ATTRIBUTES")
    attr = etree.SubElement(attrs, "ATTRIBUTE")
    etree.SubElement(attr, "NAME").text = "Position Index"
    etree.SubElement(attr, "VALUE").text = f"{position_index}"

    attr2 = etree.SubElement(attrs, "ATTRIBUTE")
    etree.SubElement(attr2, "NAME").text = "Module Integration Status"
    etree.SubElement(attr2, "VALUE").text = integration_status

    return root


def build_disconnect_xml(module_label):
    root = etree.Element("ROOT")
    parts = etree.SubElement(root, "PARTS")

    # Tracker ROOT part
    tracker = etree.SubElement(parts, "PART")
    tracker.set("mode", "auto")
    etree.SubElement(tracker, "KIND_OF_PART").text = "Tracker Detector ROOT"
    etree.SubElement(tracker, "NAME_LABEL").text = "ROOT"

    # Children section
    children = etree.SubElement(tracker, "CHILDREN")

    # Module part
    module = etree.SubElement(children, "PART")
    module.set("mode", "auto")
    etree.SubElement(module, "KIND_OF_PART").text = "PS Module"
    etree.SubElement(module, "NAME_LABEL").text = module_label

    # Remove Status attribute
    attrs = etree.SubElement(module, "PREDEFINED_ATTRIBUTES")
    attr = etree.SubElement(attrs, "ATTRIBUTE")
    etree.SubElement(attr, "NAME").text = "Position Index"
    etree.SubElement(attr, "VALUE").text = "1"
    etree.SubElement(attr, "DELETED").text = "true"
    # print the XML
    # print(etree.tostring(root, pretty_print=True, xml_declaration=True, encoding='ASCII', standalone='yes'))
    return root


def main():
    parser = argparse.ArgumentParser(
        description="Connect/Disconnect modules from rings"
    )
    parser.add_argument("module_label", help="Module name label")
    parser.add_argument("ring_barcode", help="Ring barcode")
    parser.add_argument(
        "--disconnect", action="store_true", help="Disconnect instead of connect"
    )
    parser.add_argument(
        "--position-index", type=int, default=0, help="Position index for module"
    )
    parser.add_argument(
        "--integration-status",
        type=str,
        default="Attached",
        help="Module Integration Status",
    )
    args = parser.parse_args()

    # Initialize DB access
    path = os.path.dirname(os.environ.get("DBLOADER"))

    # cmsr is production database, int2r is test database
    db = DBaccess(database="trker_cmsr", verbose=True, login_type="login")
    uploader = DBupload(
        database="cmsr", verbose=True, path_to_dbloader_api=path, login_type="login"
    )

    try:
        # Verify components
        check_components(db, args.module_label, args.ring_barcode)

        # Build appropriate XML
        if args.disconnect:
            action_prefix = "disconnect"
            xml_root = build_disconnect_xml(args.module_label)
        else:
            action_prefix = "connect"
            xml_root = build_connect_xml(
                args.ring_barcode,
                args.module_label,
                args.position_index,
                args.integration_status,
            )

        # Create output directory and unique filename
        output_dir = "xml_submissions"
        os.makedirs(output_dir, exist_ok=True)
        timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        filename = os.path.join(
            output_dir,
            f"{action_prefix}_{args.ring_barcode}_{args.module_label}_{timestamp}.xml",
        )

        # Write XML file
        with open(filename, "wb") as f:
            f.write(
                etree.tostring(
                    xml_root,
                    pretty_print=True,
                    xml_declaration=True,
                    encoding="ASCII",
                    standalone="yes",
                )
            )

        # Upload to database
        uploader.upload_data(filename)

    except Exception as e:
        print(f"Error: {str(e)}")
        return 1

    return 0


if __name__ == "__main__":
    exit(main())
