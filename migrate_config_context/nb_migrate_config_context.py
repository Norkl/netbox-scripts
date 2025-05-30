#!/usr/bin/env python3

import requests
import argparse
import json
import logging
import sys

# Configure logging for traceability
#logging.basicConfig(level=logging.INFO, format='%(asctime)s %(levelname)s: %(message)s')
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s %(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

def get_all_config_contexts(base_url, token):
    """Retrieve all config contexts from a NetBox instance via REST API."""
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    url = f"{base_url.rstrip('/')}/api/extras/config-contexts/?limit=0"
    contexts = []
    try:
        response = requests.get(url, headers=headers)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logger.error(f"Failed to retrieve config contexts from {base_url}: {e}")
        sys.exit(1)
    contexts.extend(data.get('results', []))
    # Handle pagination if present
    while data.get('next'):
        try:
            response = requests.get(data['next'], headers=headers)
            response.raise_for_status()
            data = response.json()
            contexts.extend(data.get('results', []))
        except Exception as e:
            logger.error(f"Error during pagination: {e}")
            break
    logger.info(f"Retrieved {len(contexts)} config contexts from {base_url}")
    return contexts

def find_context_by_name(base_url, token, name):
    """Find a config context by name in the destination instance."""
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    url = f"{base_url.rstrip('/')}/api/extras/config-contexts/"
    params = {"name": name}
    try:
        response = requests.get(url, headers=headers, params=params)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to query config contexts on dest for name '{name}': {e}")
        return None
    data = response.json().get('results', [])
    return data[0] if data else None

def compare_contexts(source, dest):
    """Compare key fields of two config contexts. Return True if they differ."""
    keys = ['weight', 'data', 'is_active', 'description']
    for key in keys:
        if source.get(key) != dest.get(key):
            return True
    # Compare assignment lists (IDs); dest may contain nested dicts with 'id'.
    list_fields = ['regions', 'site_groups', 'sites', 'locations', 'device_types',
                   'roles', 'platforms', 'cluster_types', 'cluster_groups', 'clusters',
                   'tenant_groups', 'tenants', 'tags']
    for field in list_fields:
        src_list = sorted(source.get(field) or [])
        dest_items = dest.get(field) or []
        dst_ids = []
        for item in dest_items:
            if isinstance(item, dict) and 'id' in item:
                dst_ids.append(item['id'])
            else:
                dst_ids.append(item)
        if sorted(src_list) != sorted(dst_ids):
            return True
    return False

def map_assignments_to_dest(assignments, base_url, token):
    """
    Map assignment lists from a source context to destination IDs.
    Special-case tags: if the source gives integer IDs, carry them over directly.
    """
    headers = {"Authorization": f"Token {token}", "Content-Type": "application/json"}
    lookup = {
        'regions':        (f"{base_url.rstrip('/')}/api/dcim/regions/",        'slug'),
        'site_groups':    (f"{base_url.rstrip('/')}/api/dcim/site-groups/",   'slug'),
        'sites':          (f"{base_url.rstrip('/')}/api/dcim/sites/",         'slug'),
        'locations':      (f"{base_url.rstrip('/')}/api/dcim/locations/",     'slug'),
        'device_types':   (f"{base_url.rstrip('/')}/api/dcim/device-types/",  'slug'),
        'roles':          (f"{base_url.rstrip('/')}/api/dcim/device-roles/",  'slug'),
        'platforms':      (f"{base_url.rstrip('/')}/api/dcim/platforms/",    'slug'),
        'cluster_types':  (f"{base_url.rstrip('/')}/api/virtualization/cluster-types/", 'slug'),
        'cluster_groups': (f"{base_url.rstrip('/')}/api/virtualization/cluster-groups/", 'slug'),
        'clusters':       (f"{base_url.rstrip('/')}/api/virtualization/clusters/",  'name'),
        'tenant_groups':  (f"{base_url.rstrip('/')}/api/tenancy/tenant-groups/", 'slug'),
        'tenants':        (f"{base_url.rstrip('/')}/api/tenancy/tenants/",      'slug'),
        # Do NOT include tags here — we’ll handle them below
    }
    mapping = {}
    for field, values in assignments.items():
        if not values:
            continue
        ids = []

        # Special-case tags: assume ints are direct IDs; dicts use slug lookup
        if field == 'tags':
            for obj in values:
                if isinstance(obj, int):
                    ids.append(obj)
                elif isinstance(obj, dict) and 'slug' in obj:
                    # Look up by slug
                    resp = requests.get(
                        f"{base_url.rstrip('/')}/api/extras/tags/",
                        headers=headers,
                        params={'slug': obj['slug']}
                    )
                    if resp.ok and resp.json().get('results'):
                        ids.append(resp.json()['results'][0]['id'])
                    else:
                        logger.warning(f"Tag '{obj['slug']}' not found on destination, skipping")
            mapping[field] = ids
            continue

        # All other fields use the generic lookup table
        if field not in lookup:
            continue
        endpoint, filter_key = lookup[field]
        for obj in values:
            # obj may be dict or int
            term = None
            if isinstance(obj, dict):
                term = obj.get('slug') or obj.get('name') or str(obj.get('id'))
            else:
                term = str(obj)
            resp = requests.get(endpoint, headers=headers, params={filter_key: term})
            if not resp.ok or not resp.json().get('results'):
                logger.warning(f"{field[:-1].capitalize()} '{term}' not found, skipping")
                continue
            ids.append(resp.json()['results'][0]['id'])
        mapping[field] = ids

    return mapping

def create_or_update_context(source_ctx, dest_base, dest_token):
    """Create or update a single config context in the destination."""
    name = source_ctx.get('name')
    existing = find_context_by_name(dest_base, dest_token, name)
    payload = {
        'name': name,
        'weight': source_ctx.get('weight'),
        'data': source_ctx.get('data'),
        'is_active': source_ctx.get('is_active', True),
        'description': source_ctx.get('description', '')
    }
    # Include all assignment fields (empty list if missing)
    assignments = {k: source_ctx.get(k, []) for k in [
        'regions', 'site_groups', 'sites', 'locations', 'device_types',
        'roles', 'platforms', 'cluster_types', 'cluster_groups', 'clusters',
        'tenant_groups', 'tenants', 'tags'
    ]}
    # Map assignments to dest object IDs
    dest_assign_ids = map_assignments_to_dest(assignments, dest_base, dest_token)
    payload.update(dest_assign_ids)
    headers = {"Authorization": f"Token {dest_token}", "Content-Type": "application/json"}

    if existing:
        # Compare and update if changed
        url_detail = existing.get('url')
        try:
            resp = requests.get(url_detail, headers=headers)
            resp.raise_for_status()
            dest_ctx = resp.json()
        except Exception as e:
            logger.error(f"Failed to retrieve context '{name}' from dest for comparison: {e}")
            return 'error'
        if compare_contexts(payload, dest_ctx):
            logger.info(f"Updating config context '{name}'")
            try:
                resp = requests.patch(url_detail, headers=headers, data=json.dumps(payload))
                resp.raise_for_status()
                return 'updated'
            except Exception as e:
                logger.error(f"Failed to update context '{name}' on destination: {e}")
                return 'error'
        else:
            logger.info(f"No changes for config context '{name}', skipping.")
            return 'skipped'
    else:
        # Create a new context
        logger.info(f"Creating config context '{name}'")
        url_list = f"{dest_base.rstrip('/')}/api/extras/config-contexts/"
        try:
            resp = requests.post(url_list, headers=headers, data=json.dumps(payload))
            resp.raise_for_status()
            return 'created'
        except requests.HTTPError:
            # Log status, response body, and the JSON payload
            logger.error(
                f"Failed to CREATE context '{name}':\n"
                f"  Status: {resp.status_code}\n"
                f"  Response: {resp.text}\n"
                f"  Payload:\n{json.dumps(payload, indent=2)}"
            )
            return 'error'

def main():
    parser = argparse.ArgumentParser(description="Migrate config contexts between two NetBox instances.")
    parser.add_argument("--source-url", required=not ("--import-file" in sys.argv),
                        help="URL of source NetBox (e.g. http://netbox-3.4.2)")
    parser.add_argument("--source-token", required=not ("--import-file" in sys.argv),
                        help="API token for source NetBox")
    parser.add_argument("--dest-url", required=not ("--export-file" in sys.argv),
                        help="URL of destination NetBox (e.g. http://netbox-4.2.2)")
    parser.add_argument("--dest-token", required=not ("--export-file" in sys.argv),
                        help="API token for destination NetBox")
    parser.add_argument("--export-file", help="Export source contexts to a local JSON file")
    parser.add_argument("--import-file", help="Import config contexts from a local JSON file to destination")
    args = parser.parse_args()

    # Determine source contexts (API or file)
    if args.import_file:
        try:
            with open(args.import_file, 'r') as f:
                source_contexts = json.load(f)
            logger.info(f"Loaded {len(source_contexts)} contexts from file {args.import_file}")
        except Exception as e:
            logger.error(f"Failed to read file {args.import_file}: {e}")
            sys.exit(1)
    else:
        source_contexts = get_all_config_contexts(args.source_url, args.source_token)
        # If exporting to file, do so and exit
        if args.export_file:
            try:
                with open(args.export_file, 'w') as f:
                    json.dump(source_contexts, f, indent=2)
                logger.info(f"Exported {len(source_contexts)} contexts to {args.export_file}")
            except Exception as e:
                logger.error(f"Failed to write to file {args.export_file}: {e}")
            return

    # If not importing from file, test destination connection
    if not args.import_file:
        try:
            test_url = f"{args.dest_url.rstrip('/')}/api/extras/config-contexts/?limit=1"
            resp = requests.get(test_url, headers={"Authorization": f"Token {args.dest_token}"})
            resp.raise_for_status()
        except Exception as e:
            logger.error(f"Failed to connect to destination NetBox: {e}")
            sys.exit(1)

    created = updated = skipped = 0
    for ctx in source_contexts:
        result = create_or_update_context(ctx, args.dest_url, args.dest_token)
        if result == 'created':
            created += 1
        elif result == 'updated':
            updated += 1
        elif result == 'skipped':
            skipped += 1

    logger.info(f"Migration complete: {created} created, {updated} updated, {skipped} skipped.")

if __name__ == "__main__":
    main()
