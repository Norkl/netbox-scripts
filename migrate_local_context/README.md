# Migrate local context between netbox instances

Netbox does not have support for exporting and importing config contexts.
This script helps with that. 


```
usage: nb_import_local_contexts.py [-h] --dest-url DEST_URL --dest-token DEST_TOKEN --input-file INPUT_FILE [--include-devices]
```

Export to File
```
python3 netbox_local_context_transfer.py export \
  --source-url https://netbox.old.local \
  --source-token $SRC_TOKEN \
  --output local_contexts.json \
  --include-devices
```

Import from File
```
python3 netbox_local_context_transfer.py import \
  --dest-url https://netbox.new.local \
  --dest-token $DST_TOKEN \
  --input local_contexts.json
```

Direct Transfer
```
python3 netbox_local_context_transfer.py transfer \
  --source-url https://netbox.old.local \
  --source-token $SRC_TOKEN \
  --dest-url https://netbox.new.local \
  --dest-token $DST_TOKEN \
  --include-devices
```
