from pathlib import Path

from studio_client.config import default_config_path
from studio_client.daemon.local_features import LocalFeatureRegistry
from studio_client.daemon.service import main
from studio_code_graph import CodeGraphService
from studio_code_graph.graphify import GraphifyProvider
from studio_workspaces import registry_config_source, registry_watch_source

if __name__ == "__main__":
    data_root: Path = default_config_path().parent
    cache_root = data_root / "cache"
    local_features = LocalFeatureRegistry(
        workspace_configs=registry_config_source(data_root),
        cache_root=cache_root,
        code_graph_service=CodeGraphService([GraphifyProvider()], cache_root / "code-graph"),
    )
    raise SystemExit(
        main(
            workspace_source=registry_watch_source(data_root),
            local_features=local_features,
        )
    )
