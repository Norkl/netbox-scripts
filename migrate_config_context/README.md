# Migrate config context between two netbox instances

NetBox does not have support for exporting and importing config contexts.
This script helps with that. 


```
usage: netbox_migrate_config_context.py [-h] --source-url SOURCE_URL --source-token SOURCE_TOKEN --dest-url DEST_URL --dest-token DEST_TOKEN
                                        [--export-file EXPORT_FILE] [--import-file IMPORT_FILE]
```
