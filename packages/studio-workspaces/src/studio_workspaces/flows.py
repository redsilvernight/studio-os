from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from uuid import UUID

from studio_contracts.local.identity import ProfileRef
from studio_contracts.local.workspace import (
    LocalWorkspaceConfig,
    WorkspaceStatus,
)

from studio_workspaces.git_detection import GitRepoInfo, GitStatus, detect_git
from studio_workspaces.path_safety import check_readable, workspace_binding_key
from studio_workspaces.picker import FolderPicker
from studio_workspaces.store import WorkspaceStore, WorkspaceStoreError


class FlowKind(StrEnum):
    NEW_PROJECT_WITH_FOLDER = "new_project_with_folder"
    EXISTING_PROJECT_WITH_FOLDER = "existing_project_with_folder"
    EXISTING_PROJECT_WITHOUT_FOLDER = "existing_project_without_folder"
    ASSOCIATE_LOCAL_FOLDER = "associate_local_folder"
    EXISTING_GIT_REPO = "existing_git_repo"
    NON_GIT_FOLDER = "non_git_folder"
    WORKSPACE_MOVED = "workspace_moved"
    WORKSPACE_GONE = "workspace_gone"
    MULTI_WORKSPACE = "multi_workspace"


@dataclass(frozen=True)
class FlowResult:
    kind: FlowKind
    steps: list[str] = field(default_factory=list)
    workspace_id: UUID | None = None
    git: GitRepoInfo | None = None
    status: WorkspaceStatus | None = None
    message: str = ""


def _git_step(git: GitRepoInfo) -> str:
    if git.status == GitStatus.VALID and not git.detached:
        remote = f" (remote {git.remote})" if git.remote else " (sans remote)"
        return f"Dépôt Git détecté : branche {git.branch}{remote}."
    if git.status == GitStatus.VALID:
        return "Dépôt Git détecté en révision détachée : la surveillance reste possible."
    if git.status == GitStatus.NOT_A_REPO:
        return "Dossier sans Git : le projet fonctionnera sans surveillance de branche."
    if git.status == GitStatus.GIT_ABSENT:
        return "Git n'est pas installé : la détection de branche est indisponible."
    if git.status == GitStatus.INVALID_REPO:
        return "Dépôt Git illisible : vérifiez le dossier .git avant d'activer la surveillance."
    return "Dossier inaccessible : vérifiez l'accès avant de continuer."


def _folder_flow(
    kind: FlowKind,
    store: WorkspaceStore,
    picker: FolderPicker,
    profile: ProfileRef,
    project_id: UUID,
    workspace_id: UUID,
    intro: str,
) -> FlowResult:
    selected = picker.select_folder()
    if selected is None:
        return FlowResult(kind=kind, message="Sélection annulée : rien n'a été modifié.")
    readable = check_readable(selected.path)
    if not readable.ok:
        return FlowResult(kind=kind, message=f"Dossier refusé : {readable.reason}.")
    git = detect_git(selected.path)
    steps = [intro, f"Dossier choisi : {selected.path}.", _git_step(git)]
    return FlowResult(
        kind=kind,
        steps=steps,
        workspace_id=workspace_id,
        git=git,
        message="Confirmez ce dossier pour créer la configuration locale.",
    )


def run_flow(
    kind: FlowKind,
    store: WorkspaceStore,
    picker: FolderPicker,
    profile: ProfileRef,
    project_id: UUID,
    workspace_id: UUID,
    *,
    folder_hint: str | None = None,
) -> FlowResult:
    if kind == FlowKind.NEW_PROJECT_WITH_FOLDER:
        return _folder_flow(
            kind,
            store,
            picker,
            profile,
            project_id,
            workspace_id,
            "Nouveau projet : il sera créé sur le serveur, puis lié à ce dossier.",
        )
    if kind == FlowKind.EXISTING_PROJECT_WITH_FOLDER:
        return _folder_flow(
            kind,
            store,
            picker,
            profile,
            project_id,
            workspace_id,
            "Projet existant : ce dossier sera lié sans déplacer vos fichiers.",
        )
    if kind == FlowKind.ASSOCIATE_LOCAL_FOLDER:
        return _folder_flow(
            kind,
            store,
            picker,
            profile,
            project_id,
            workspace_id,
            "Association : vos fichiers restent en place, seul un repère local est ajouté.",
        )
    if kind == FlowKind.EXISTING_GIT_REPO:
        if folder_hint is None:
            return FlowResult(kind=kind, message="Indiquez le dossier du dépôt Git.")
        git = detect_git(folder_hint)
        return FlowResult(
            kind=kind,
            steps=[f"Dépôt examiné : {folder_hint}.", _git_step(git)],
            workspace_id=workspace_id,
            git=git,
            message="Confirmez ce dépôt pour l'associer au projet.",
        )
    if kind == FlowKind.NON_GIT_FOLDER:
        if folder_hint is None:
            return FlowResult(kind=kind, message="Indiquez le dossier à utiliser.")
        readable = check_readable(folder_hint)
        if not readable.ok:
            return FlowResult(kind=kind, message=f"Dossier refusé : {readable.reason}.")
        git = detect_git(folder_hint)
        return FlowResult(
            kind=kind,
            steps=["Dossier sans Git accepté.", _git_step(git)],
            workspace_id=workspace_id,
            git=git,
            message="Aucune surveillance Git ne sera activée pour ce dossier.",
        )
    if kind == FlowKind.EXISTING_PROJECT_WITHOUT_FOLDER:
        configs = [c for c in store.list_workspaces(profile) if c.project_id == project_id]
        steps = ["Projet utilisable sans dossier local : seul le serveur est interrogé."]
        if configs:
            steps.append(f"{len(configs)} dossier(s) déjà lié(s) à ce projet sur ce poste.")
        return FlowResult(kind=kind, steps=steps, message="Ajoutez un dossier plus tard si besoin.")
    if kind == FlowKind.WORKSPACE_MOVED:
        try:
            status = store.validate(workspace_id, profile)
        except WorkspaceStoreError as exc:
            return FlowResult(kind=kind, message=str(exc))
        steps = ["Le dossier a changé de place : vos fichiers n'ont pas été touchés."]
        if status.candidate_root is not None:
            steps.append(f"Nouvel emplacement probable : {status.candidate_root}.")
        return FlowResult(
            kind=kind,
            steps=steps,
            workspace_id=workspace_id,
            status=status,
            message="Confirmez le nouvel emplacement pour mettre à jour la configuration.",
        )
    if kind == FlowKind.WORKSPACE_GONE:
        try:
            status = store.validate(workspace_id, profile)
        except WorkspaceStoreError as exc:
            return FlowResult(kind=kind, message=str(exc))
        return FlowResult(
            kind=kind,
            steps=["Le dossier est indisponible : la configuration est conservée telle quelle."],
            workspace_id=workspace_id,
            status=status,
            message="Rétablissez l'accès, déplacez le lien, ou dissociez sans rien supprimer.",
        )
    if kind == FlowKind.MULTI_WORKSPACE:
        all_configs = store.list_workspaces(profile)
        by_root: dict[str, list[str]] = {}
        for config in all_configs:
            by_root.setdefault(workspace_binding_key(config.roots.workspace_root), []).append(
                str(config.workspace_id)
            )
        clashes = {root: ids for root, ids in by_root.items() if len(ids) > 1}
        steps = [f"{len(all_configs)} espace(s) de travail sur ce profil."]
        for root, ids in sorted(clashes.items()):
            steps.append(f"Conflit : {root} est lié {len(ids)} fois.")
        return FlowResult(kind=kind, steps=steps, message="Chaque projet garde son propre dossier.")


def summarize_features(config: LocalWorkspaceConfig) -> list[str]:
    states = {
        "Knowledge": config.features.knowledge,
        "Code Graph": config.features.code_graph,
        "Surveillance": config.features.watchers,
    }
    lines = [f"{name} : {'activé' if on else 'coupé'}" for name, on in states.items()]
    if not any(states.values()):
        lines.append("Tout est coupé : le projet reste consultable, sans index local.")
    return lines
