#!/usr/bin/env python3

import argparse
import json
import sys
import requests
import logging

#── Logging ─────────────────────────────────────────────────────────────
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

#── Constants ────────────────────────────────────────────────────────────
OBJECT_TYPES = {
    "virtual_machine": {
        "endpoint": "virtualization/virtual-machines",
    },
    "device": {
        "endpoint": "dcim/devices",
    },
}

#── Functions ────────────────────────────────────────────────────────────

def create_session(token):
    session = requests.Session()
    session.headers.update({
        'Authorization': f'Token {token}',
        'Content-Type': 'application/json',
        'Accept': 'application/json',
    })
    return session

def get_objects_with_local_context(session, base_url, include_devices=False):
    """
    Return list of dicts with type, id, name, and local_context_data.
    """
    results = []

    for obj_type in ["virtual_machine", "device"]:
        if obj_type == "device" and not include_devices:
            continue

        endpoint = f"{base_url}/api/{OBJECT_TYPES[obj_type]['endpoint']}/?limit=1000"
        while endpoint:
            resp = session.get(endpoint)
            if not resp.ok:
                logger.error(f"Failed to fetch {obj_type}s: {resp.status_code} {resp.text}")
                break
            data = resp.json()
            for obj in data.get("results", []):
                if obj.get("local_context_data"):
                    results.append({
                        "type": obj_type,
                        "id": obj["id"],
                        "name": obj["name"],
                        "local_context_data": obj["local_context_data"]
                    })
            endpoint = data.get("next")

    return results

def export_to_file(data, filename):
    try:
        with open(filename, 'w') as f:
            json.dump(data, f, indent=2)
        logger.info(f"Exported {len(data)} entries to {filename}")
    except Exception as e:
        logger.error(f"Failed to write to {filename}: {e}")
        sys.exit(1)

def import_from_file(filename):
    try:
        with open(filename) as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read {filename}: {e}")
        sys.exit(1)

def find_object_url(session, base_url, obj_type, name, obj_id):
    """
    Try to find object by name. Fallback to ID if needed.
    """
    endpoint = f"{base_url}/api/{OBJECT_TYPES[obj_type]['endpoint']}/"
    params = {'name': name}
    resp = session.get(endpoint, params=params)
    if resp.ok and resp.json().get("results"):
        return resp.json()["results"][0]["url"]

    # fallback: direct ID
    detail_url = f"{endpoint}{obj_id}/"
    resp = session.get(detail_url)
    if resp.ok:
        return detail_url

    logger.error(f"{obj_type} '{name}' (ID {obj_id}) not found on destination")
    return None

def apply_local_context(session, detail_url, local_data):
    payload = {'local_context_data': local_data}
    resp = session.patch(detail_url, json=payload)
    if resp.ok:
        return True
    logger.error(f"PATCH failed for {detail_url}: {resp.status_code} {resp.text.strip()}")
    return False

def transfer_contexts(source_data, dest_session, dest_url):
    total = len(source_data)
    applied = skipped = 0

    for entry in source_data:
        obj_type = entry["type"]
        obj_id = entry["id"]
        name = entry["name"]
        local_data = entry["local_context_data"]

        logger.info(f"Applying context to {obj_type} '{name}' (ID {obj_id})")
        detail_url = find_object_url(dest_session, dest_url, obj_type, name, obj_id)
        if not detail_url:
            continue

        if apply_local_context(dest_session, detail_url, local_data):
            applied += 1

    logger.info(f"Done: {applied} contexts applied, {total - applied} failed")

#── Main CLI ─────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="NetBox local context transfer tool")
    subparsers = parser.add_subparsers(dest="command", required=True)

    # Export command
    export = subparsers.add_parser("export")
    export.add_argument("--source-url", required=True)
    export.add_argument("--source-token", required=True)
    export.add_argument("--output", required=True)
    export.add_argument("--include-devices", action="store_true")

    # Import command
    imp = subparsers.add_parser("import")
    imp.add_argument("--dest-url", required=True)
    imp.add_argument("--dest-token", required=True)
    imp.add_argument("--input", required=True)

    # Transfer (direct)
    transfer = subparsers.add_parser("transfer")
    transfer.add_argument("--source-url", required=True)
    transfer.add_argument("--source-token", required=True)
    transfer.add_argument("--dest-url", required=True)
    transfer.add_argument("--dest-token", required=True)
    transfer.add_argument("--include-devices", action="store_true")

    args = parser.parse_args()

    if args.command == "export":
        src_session = create_session(args.source_token)
        data = get_objects_with_local_context(src_session, args.source_url.rstrip('/'), args.include_devices)
        export_to_file(data, args.output)

    elif args.command == "import":
        data = import_from_file(args.input)
        dest_session = create_session(args.dest_token)
        transfer_contexts(data, dest_session, args.dest_url.rstrip('/'))

    elif args.command == "transfer":
        src_session = create_session(args.source_token)
        dest_session = create_session(args.dest_token)
        data = get_objects_with_local_context(src_session, args.source_url.rstrip('/'), args.include_devices)
        transfer_contexts(data, dest_session, args.dest_url.rstrip('/'))

if __name__ == "__main__":
    main()
