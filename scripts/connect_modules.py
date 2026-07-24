#!/usr/bin/python
# Automatically connect MOUNTED modules (from our LOCAL db) to their tracker rings
# in the CENTRAL CMS db, mirroring the logic of mount_modules.py.
#
# IMPORTANT: first source py4dbupload/bin/setup.sh to set up the environment, then run:
#   python3 connect_modules.py --dry_run        # analyse only, no writes (RECOMMENDED first)
#   python3 connect_modules.py                  # actually upload the connect XMLs to PROD
#
# What it does:
#   1. Reads the list of MOUNTED modules from the LOCAL db (/modules_on_ring).
#      Each entry gives moduleName, mounted_on ("RING;POSITION") and details.LOCATION.
#   2. For each (module, ring, position) fetches the CENTRAL db status. All PS module
#      data (location, current parent, position index) comes from the p9020 table
#      (kind_of_part_id of "PS Module"), which contains EVERY PS module, including
#      mock ones that are missing from the trkr_ps_modules_v view. The ring's children
#      are the p9020 rows whose PART_PARENT_ID == the ring's part id, and each child's
#      slot is its APOSITION_INDEX.
#   3. Connects (uploads a connect XML) ONLY when:
#        - the module's LOCAL location is Pisa (IT-Pisa[INFN Pisa]),  AND
#        - module AND ring are in Pisa in the CENTRAL db,             AND
#        - the target slot is FREE in the CENTRAL db.
#      Slot occupancy = a module that is BOTH a child of the ring (PART_PARENT_ID)
#      AND carries that APOSITION_INDEX. A lingering position index without the
#      parent link does NOT count as occupied.
#
# --dry_run stops after steps 1 & 2 (plus all the step-3 checks/warnings) and prints
# exactly which connect operations it WOULD perform, without touching the db.
#
# Output policy: the full, detailed per-module report is ALWAYS written to a log file.
#   - --dry_run also prints that full detail to the screen.
#   - a real run prints only the concise picture (what is being connected and whether
#     it succeeded, plus the "already correct" and "slot taken by another module"
#     warnings); the long uninteresting skip lists stay in the log file only.

import argparse
import datetime
import os
import sys

import requests
from lxml import etree

from py4dbupload.modules.Utils import DBaccess, DBupload

# Reuse the exact connect-XML builder from the mounting script so the produced
# XML is identical to a manual mount_modules.py connect.
from mount_modules import build_connect_xml

# --- Configuration -----------------------------------------------------------
API_URL = "http://192.168.0.45:5000"          # LOCAL integration db
MODULES_ON_RING_ENDPOINT = "/modules_on_ring"  # GET -> list of mounted modules

CENTRAL_DB = "trker_cmsr"                       # production central db (read)
UPLOAD_DB = "cmsr"                              # production central db (write)
PISA_CENTRAL_LOCATION = "Pisa"                 # location_name in trkr_locations_v
PISA_LOCAL_TOKEN = "pisa"                       # substring match on LOCATION strings

# p9020 = the per-part attribute table for kind_of_part "PS Module". Unlike
# trkr_ps_modules_v it lists EVERY PS module (incl. mock), with LOCATION (string),
# PART_PARENT_ID and APOSITION_INDEX.
PS_MODULE_TABLE = "p9020"
RING_KIND = "TBPS Ring"


# --- Small helpers -----------------------------------------------------------
# data_query returns JSON rows whose keys are the camelCase of the column name
# (name_label -> 'nameLabel', aposition_index -> 'apositionIndex', etc.).

def _sql_str(value):
    """Quote a value as an SQL string literal, escaping single quotes."""
    return "'" + str(value).replace("'", "''") + "'"


def _to_int(value):
    """Best-effort int() that returns None for empty/non-numeric values."""
    if value is None or str(value).strip() == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def get_pisa_location_id(db):
    """Resolve the central Pisa location_id once (e.g. 4240)."""
    return db.get_location_id(PISA_CENTRAL_LOCATION)


def get_ring_info(db, ring_label):
    """Return {'part_id': str, 'location_id': str} for a ring, or None if absent."""
    query = (
        "SELECT p.id, p.location_id "
        f"FROM {db.database}.parts p "
        f"WHERE p.name_label = {_sql_str(ring_label)} "
        f"AND p.kind_of_part = {_sql_str(RING_KIND)}"
    )
    rows = db.data_query(query)
    if not rows:
        return None
    return {
        "part_id": str(rows[0].get("id")),
        "location_id": str(rows[0].get("locationId")),
    }


def get_ring_children(db, ring_part_id):
    """Return the live children of a ring from p9020 (by PART_PARENT_ID) as a list
    of {'name', 'position', 'location'}. Covers every PS module, mock included."""
    query = (
        "SELECT m.name_label, m.aposition_index, m.location "
        f"FROM {db.database}.{PS_MODULE_TABLE} m "
        f"WHERE m.part_parent_id = {ring_part_id}"
    )
    rows = db.data_query(query)
    children = []
    for row in rows or []:
        children.append(
            {
                "name": row.get("nameLabel"),
                "position": _to_int(row.get("apositionIndex")),
                "location": row.get("location"),
            }
        )
    return children


def get_module_central(db, module_label):
    """Return central PS-module data from p9020, or None if the module is absent.
    {'location', 'part_parent_id', 'position'} -- a returned position does NOT imply
    the module is currently a child of any ring (the attribute can linger)."""
    query = (
        "SELECT m.name_label, m.location, m.part_parent_id, m.aposition_index "
        f"FROM {db.database}.{PS_MODULE_TABLE} m "
        f"WHERE m.name_label = {_sql_str(module_label)}"
    )
    rows = db.data_query(query)
    if not rows:
        return None
    row = rows[0]
    return {
        "location": row.get("location"),
        "part_parent_id": (
            str(row.get("partParentId"))
            if row.get("partParentId") is not None
            else None
        ),
        "position": _to_int(row.get("apositionIndex")),
    }


# --- Step 1: read the LOCAL db ----------------------------------------------

def fetch_mounted_modules():
    """GET the list of mounted modules from the local db.
    Returns a list of dicts: {moduleName, ring, position, local_location, raw_mounted_on}."""
    url = API_URL + MODULES_ON_RING_ENDPOINT
    resp = requests.get(url, timeout=30)
    resp.raise_for_status()
    data = resp.json()

    parsed = []
    for entry in data:
        name = entry.get("moduleName")
        mounted_on = entry.get("mounted_on", "") or ""
        location = (entry.get("details", {}) or {}).get("LOCATION", "")

        ring, position = None, None
        if ";" in mounted_on:
            ring, pos_str = mounted_on.split(";", 1)
            ring = ring.strip()
            position = _to_int(pos_str.strip())

        parsed.append(
            {
                "moduleName": name,
                "ring": ring,
                "position": position,
                "local_location": location,
                "raw_mounted_on": mounted_on,
            }
        )
    return parsed


# --- Step 2 + 3 checks: evaluate one module ----------------------------------
# Decision codes
CONNECT = "CONNECT"
SKIP_LOCAL_NOT_PISA = "SKIP_LOCAL_NOT_PISA"
SKIP_BAD_MOUNTED_ON = "SKIP_BAD_MOUNTED_ON"
SKIP_MODULE_NOT_FOUND = "SKIP_MODULE_NOT_FOUND"
SKIP_RING_NOT_FOUND = "SKIP_RING_NOT_FOUND"
SKIP_NOT_PISA = "SKIP_NOT_PISA"
SKIP_ALREADY_CORRECT = "SKIP_ALREADY_CORRECT"
SKIP_SLOT_TAKEN_OTHER = "SKIP_SLOT_TAKEN_OTHER"

# Decisions that deserve attention on a real run (printed to screen).
NOTABLE_SKIPS = (SKIP_ALREADY_CORRECT, SKIP_SLOT_TAKEN_OTHER)


def evaluate_module(db, pisa_id, item, ring_info_cache, ring_children_cache):
    """Run all checks for one mounted-module entry and return a result dict
    describing the decision, the gathered status and any warnings.
    No writes are performed here. Ring lookups are cached across modules."""
    module = item["moduleName"]
    ring = item["ring"]
    position = item["position"]
    local_location = item["local_location"]

    result = {
        "module": module,
        "ring": ring,
        "position": position,
        "local_location": local_location,
        "checks": {},
        "warnings": [],
        "decision": None,
        "reason": "",
    }
    checks = result["checks"]

    # --- Local LOCATION gate (must be Pisa) ---
    local_is_pisa = PISA_LOCAL_TOKEN in (local_location or "").lower()
    checks["local_pisa"] = local_is_pisa
    if not local_is_pisa:
        result["decision"] = SKIP_LOCAL_NOT_PISA
        result["reason"] = f"local LOCATION '{local_location}' is not Pisa"
        return result

    # --- Sanity on mounted_on ---
    if not ring or position is None:
        result["decision"] = SKIP_BAD_MOUNTED_ON
        result["reason"] = (
            f"could not parse ring/position from '{item['raw_mounted_on']}'"
        )
        return result

    # --- Ring lookup (cached) ---
    if ring not in ring_info_cache:
        ring_info_cache[ring] = get_ring_info(db, ring)
    ring_info = ring_info_cache[ring]
    if ring_info is None:
        result["decision"] = SKIP_RING_NOT_FOUND
        result["reason"] = f"ring {ring} not found in central db"
        return result
    ring_part_id = ring_info["part_id"]

    # --- Module lookup (p9020) ---
    module_central = get_module_central(db, module)
    if module_central is None:
        result["decision"] = SKIP_MODULE_NOT_FOUND
        result["reason"] = f"module {module} not found in central db (p9020)"
        return result
    checks["central_module_location"] = module_central["location"]
    checks["central_module_parent_id"] = module_central["part_parent_id"]

    # --- Pisa membership (ring by location_id, module by LOCATION string) ---
    ring_pisa = str(ring_info["location_id"]) == str(pisa_id)
    module_pisa = PISA_LOCAL_TOKEN in (module_central["location"] or "").lower()
    checks["central_ring_pisa"] = ring_pisa
    checks["central_module_pisa"] = module_pisa
    if not (module_pisa and ring_pisa):
        bad = []
        if not module_pisa:
            bad.append(f"module loc='{module_central['location']}'")
        if not ring_pisa:
            bad.append(f"ring loc_id={ring_info['location_id']}")
        result["decision"] = SKIP_NOT_PISA
        result["reason"] = "not in central Pisa: " + ", ".join(bad)
        return result

    # --- Slot occupancy: child-of-ring (PART_PARENT_ID) AND matching position ---
    if ring not in ring_children_cache:
        ring_children_cache[ring] = get_ring_children(db, ring_part_id)
    children = ring_children_cache[ring]

    occupant = None
    unknown_position_children = []
    for child in children:
        if child["name"] is None:
            continue
        if child["position"] is None:
            unknown_position_children.append(child["name"])
            continue
        if child["position"] == position:
            occupant = child["name"]
            break

    checks["central_ring_children"] = [c["name"] for c in children]
    checks["central_slot_occupant"] = occupant
    if unknown_position_children:
        result["warnings"].append(
            "ring has children with unreadable position index "
            f"(occupancy may be incomplete): {unknown_position_children}"
        )

    # --- Decide ---
    if occupant is None:
        result["decision"] = CONNECT
        result["reason"] = f"slot {ring};{position} is free in central db"
        parent_id = module_central["part_parent_id"]
        if parent_id and parent_id != ring_part_id:
            result["warnings"].append(
                f"module is currently a child of part_id {parent_id} in central db; "
                "connecting will re-parent it"
            )
    elif occupant == module:
        # Occupant comes from the children-by-parent list, so this guarantees the
        # module is already correctly parented AND at the right position.
        result["decision"] = SKIP_ALREADY_CORRECT
        result["reason"] = (
            f"slot {ring};{position} already holds {module} in central db (OK)"
        )
    else:
        result["decision"] = SKIP_SLOT_TAKEN_OTHER
        result["reason"] = (
            f"slot {ring};{position} is occupied by a DIFFERENT module "
            f"'{occupant}' in central db (local db expects {module})"
        )

    return result


# --- Step 3 action: perform the connect (writes) -----------------------------

def perform_connect(uploader, result, output_dir, position_status="Attached"):
    """Build + upload the connect XML for one CONNECT result. Returns the
    written filename. Raises on upload failure."""
    module = result["module"]
    ring = result["ring"]
    position = result["position"]

    xml_root = build_connect_xml(ring, module, position, position_status)

    os.makedirs(output_dir, exist_ok=True)
    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.join(output_dir, f"connect_{ring}_{module}_{timestamp}.xml")
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
    uploader.upload_data(filename)
    return filename


# --- Reporting ---------------------------------------------------------------

def _bucket(results):
    """Group results by decision into the buckets used for reporting."""
    return {
        "connect": [r for r in results if r["decision"] == CONNECT],
        "already": [r for r in results if r["decision"] == SKIP_ALREADY_CORRECT],
        "taken": [r for r in results if r["decision"] == SKIP_SLOT_TAKEN_OTHER],
        "other": [
            r
            for r in results
            if r["decision"] not in (CONNECT,) + NOTABLE_SKIPS
        ],
    }


def _format_detail_block(r):
    """Full, multi-line description of one evaluated module (for the log file
    and for the dry-run screen output)."""
    lines = [f"\n• {r['module']}  ->  {r['ring']};{r['position']}"]
    lines.append(f"    local LOCATION : {r['local_location']}")
    for key, val in r["checks"].items():
        lines.append(f"    {key:28s}: {val}")
    lines.append(f"    DECISION       : {r['decision']}  ({r['reason']})")
    for w in r["warnings"]:
        lines.append(f"    !! WARNING     : {w}")
    return "\n".join(lines)


def write_full_report(results, path, pisa_id, dry_run):
    """Always-written, full detail report (every module, every skip)."""
    buckets = _bucket(results)
    with open(path, "w") as f:
        f.write("connect_modules report\n")
        f.write(f"generated: {datetime.datetime.now().isoformat()}\n")
        f.write(f"mode: {'DRY-RUN' if dry_run else 'EXECUTE'}\n")
        f.write(f"central Pisa location_id: {pisa_id}\n")
        f.write(f"modules evaluated: {len(results)}\n")
        f.write(
            "to_connect={c}  already_correct={a}  slot_taken_other={t}  other_skips={o}\n".format(
                c=len(buckets["connect"]),
                a=len(buckets["already"]),
                t=len(buckets["taken"]),
                o=len(buckets["other"]),
            )
        )
        f.write("\n" + "=" * 78 + "\nPER-MODULE DETAIL\n" + "=" * 78 + "\n")
        for r in results:
            f.write(_format_detail_block(r) + "\n")
    return buckets


def print_dry_run(results, buckets, log_path):
    """Verbose screen output for --dry_run."""
    print("\n" + "=" * 78)
    print("PER-MODULE STATUS (dry-run)")
    print("=" * 78)
    for r in results:
        print(_format_detail_block(r))

    print("\n" + "=" * 78)
    print("SUMMARY (dry-run)")
    print("=" * 78)
    print(f"\nWOULD CONNECT ({len(buckets['connect'])}):")
    for r in buckets["connect"]:
        print(f"    + {r['module']}  ->  {r['ring']} @ position {r['position']}")
    print(f"\nALREADY CORRECT ({len(buckets['already'])}):")
    for r in buckets["already"]:
        print(f"    = {r['module']}  ->  {r['ring']};{r['position']}")
    print(f"\nSLOT TAKEN BY ANOTHER MODULE ({len(buckets['taken'])}):")
    for r in buckets["taken"]:
        print(
            f"    x {r['module']}  ->  {r['ring']};{r['position']}  "
            f"({r['checks'].get('central_slot_occupant')} is there)"
        )
    print(f"\nOTHER SKIPS ({len(buckets['other'])}):")
    for r in buckets["other"]:
        print(
            f"    - {r['module']}  ->  {r['ring']};{r['position']}  "
            f"[{r['decision']}] {r['reason']}"
        )
    print(f"\nFull report written to: {log_path}")
    print("\n[dry-run] stopping before step 3. No data was written.")


def print_notable(buckets, log_path):
    """Concise screen output for a real run: only the warnings worth seeing."""
    print(f"\nALREADY CORRECT in central db ({len(buckets['already'])}):")
    for r in buckets["already"]:
        print(f"    = {r['module']}  ->  {r['ring']};{r['position']}")
    print(f"\n!! SLOT TAKEN BY ANOTHER MODULE ({len(buckets['taken'])}):")
    for r in buckets["taken"]:
        print(
            f"    x {r['module']}  ->  {r['ring']};{r['position']}  "
            f"(central has {r['checks'].get('central_slot_occupant')})"
        )
    if buckets["other"]:
        print(
            f"\n{len(buckets['other'])} other module(s) skipped "
            f"(not Pisa / not found / bad data) -- see {log_path}"
        )


# --- Main --------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(
        description="Connect MOUNTED modules (local db) to rings in the central CMS db."
    )
    parser.add_argument(
        "--dry_run",
        action="store_true",
        help="Run steps 1 & 2 plus all step-3 checks, print what WOULD be done, "
        "and exit WITHOUT writing anything to the central db.",
    )
    parser.add_argument(
        "--ring", default=None, help="Only process modules mounted on this ring."
    )
    parser.add_argument(
        "--module", default=None, help="Only process this module name_label."
    )
    parser.add_argument(
        "--integration-status",
        default="Attached",
        help="Module Integration Status to set on connect (default: Attached).",
    )
    parser.add_argument(
        "--yes",
        action="store_true",
        help="Skip the interactive confirmation before writing to PROD.",
    )
    args = parser.parse_args()

    timestamp = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    log_path = os.path.join(
        "connect_reports", f"connect_report_{timestamp}.txt"
    )
    os.makedirs("connect_reports", exist_ok=True)

    # --- Step 1: local db ---
    print(f"[1] Fetching mounted modules from {API_URL}{MODULES_ON_RING_ENDPOINT} ...")
    try:
        items = fetch_mounted_modules()
    except Exception as e:
        print(f"Error fetching local mounted modules: {e}")
        return 1
    print(f"    got {len(items)} mounted module(s).")

    if args.ring:
        items = [i for i in items if i["ring"] == args.ring]
    if args.module:
        items = [i for i in items if i["moduleName"] == args.module]
    if not items:
        print("    nothing to process after filtering.")
        return 0

    # --- Step 2 + step-3 checks: central db (read only) ---
    print(f"[2] Reading central db ({CENTRAL_DB}) and evaluating checks ...")
    db = DBaccess(database=CENTRAL_DB, verbose=False, login_type="login")

    pisa_id = get_pisa_location_id(db)
    if pisa_id is None:
        print(
            f"Error: could not resolve central Pisa location id for "
            f"'{PISA_CENTRAL_LOCATION}'."
        )
        return 1
    print(f"    central Pisa location_id = {pisa_id}")

    ring_info_cache = {}
    ring_children_cache = {}
    results = []
    for item in items:
        results.append(
            evaluate_module(db, pisa_id, item, ring_info_cache, ring_children_cache)
        )

    # Always write the full report to file.
    buckets = write_full_report(results, log_path, pisa_id, dry_run=args.dry_run)

    if args.dry_run:
        print_dry_run(results, buckets, log_path)
        return 0

    # --- Step 3: writes ---
    print(f"\nFull details written to: {log_path}")
    to_connect = buckets["connect"]
    if not to_connect:
        print("Nothing to connect.")
        print_notable(buckets, log_path)
        return 0

    print(f"\nTO CONNECT ({len(to_connect)}):")
    for r in to_connect:
        print(f"    + {r['module']}  ->  {r['ring']} @ position {r['position']}")

    if not args.yes:
        print(f"\nAbout to upload {len(to_connect)} connect XML(s) to PROD ({UPLOAD_DB}).")
        answer = input("Proceed? [y/N] ").strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted. No writes performed.")
            return 0

    path = os.path.dirname(os.environ.get("DBLOADER"))
    uploader = DBupload(
        database=UPLOAD_DB,
        verbose=True,
        path_to_dbloader_api=path,
        login_type="login",
    )

    output_dir = "xml_submissions"
    failures = 0
    print()
    for r in to_connect:
        try:
            fname = perform_connect(
                uploader, r, output_dir, position_status=args.integration_status
            )
            print(f"    OK   {r['module']} -> {r['ring']}@{r['position']}  ({fname})")
        except Exception as e:
            failures += 1
            print(f"    FAIL {r['module']} -> {r['ring']}@{r['position']}: {e}")

    print(f"\nConnected {len(to_connect) - failures}/{len(to_connect)}, {failures} failed.")
    print_notable(buckets, log_path)
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
