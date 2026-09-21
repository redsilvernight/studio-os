from pathlib import Path

from studio_client.config import default_config_path
from studio_client.daemon.service import main
from studio_workspaces import registry_watch_source

if __name__ == "__main__":
    data_root: Path = default_config_path().parent
    raise SystemExit(main(workspace_source=registry_watch_source(data_root)))
