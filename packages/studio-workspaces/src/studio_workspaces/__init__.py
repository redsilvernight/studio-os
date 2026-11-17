from studio_workspaces.daemon_config import WatchPlan, daemon_watch_plan
from studio_workspaces.detected import (
    DetectedRepository,
    forget_detected_repository,
    list_detected_repositories,
    record_detected_repository,
)
from studio_workspaces.flows import FlowKind, FlowResult, run_flow
from studio_workspaces.git_detection import GitRepoInfo, GitStatus, detect_git, main_repo_root
from studio_workspaces.native_picker import (
    NativeFolderPicker,
    NativePick,
    NativePickStatus,
    parse_native_pick,
)
from studio_workspaces.path_safety import (
    PathVerdict,
    check_p5_glob,
    check_readable,
    classify_local_path,
)
from studio_workspaces.picker import FolderPicker, MockFolderPicker, SelectedFolder
from studio_workspaces.registration import (
    RegistrationAction,
    WorkspaceRegistration,
    register_workspace,
)
from studio_workspaces.root_confirmation import RootConfirmationService
from studio_workspaces.secret_guard import SecretMaterialError, assert_no_secrets, scan_studio_dir
from studio_workspaces.store import DissociateResult, MarkerHit, WorkspaceStore, WorkspaceStoreError
from studio_workspaces.watch_source import (
    ConfigSource,
    WatchSource,
    WorkspaceWatchEntry,
    registry_config_source,
    registry_watch_source,
)
from studio_workspaces.workspace_bridge import WorkspaceBridge

__all__ = [
    "ConfigSource",
    "DetectedRepository",
    "DissociateResult",
    "FlowKind",
    "FlowResult",
    "FolderPicker",
    "GitRepoInfo",
    "GitStatus",
    "MarkerHit",
    "MockFolderPicker",
    "NativeFolderPicker",
    "NativePick",
    "NativePickStatus",
    "PathVerdict",
    "RegistrationAction",
    "RootConfirmationService",
    "SecretMaterialError",
    "SelectedFolder",
    "WatchPlan",
    "WatchSource",
    "WorkspaceStore",
    "WorkspaceStoreError",
    "WorkspaceBridge",
    "WorkspaceRegistration",
    "WorkspaceWatchEntry",
    "assert_no_secrets",
    "check_p5_glob",
    "check_readable",
    "classify_local_path",
    "daemon_watch_plan",
    "detect_git",
    "forget_detected_repository",
    "list_detected_repositories",
    "main_repo_root",
    "parse_native_pick",
    "record_detected_repository",
    "register_workspace",
    "registry_config_source",
    "registry_watch_source",
    "run_flow",
    "scan_studio_dir",
]
