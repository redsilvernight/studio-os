from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from studio_contracts.auth import Role
from studio_contracts.discovery import (
    CapabilityState,
    DiscoveryIntent,
    ProductCapability,
    ProductDiscovery,
)

from studio_api.db.models.build import GitHubIntegrationModel
from studio_api.db.models.project import ProjectModel
from studio_api.services.authz import Principal, project_visibility_clause
from studio_api.services.heartbeats import parse_stored_capabilities
from studio_api.settings import Settings


@dataclass(frozen=True)
class CapabilitySpec:
    key: str
    title: str
    summary: str
    example: str
    endpoint: str
    project: bool = False
    write_only: bool = False


CATALOGUE = (
    CapabilitySpec(
        "projects",
        "Projets",
        "Créer et retrouver les projets suivis.",
        "Comment démarrer mon projet ?",
        "/api/v1/projects",
    ),
    CapabilitySpec(
        "tasks",
        "Tâches",
        "Découper le travail et suivre son état.",
        "Prépare les tâches nécessaires à cette fonctionnalité.",
        "/api/v1/tasks",
        True,
    ),
    CapabilitySpec(
        "roadmaps",
        "Roadmaps",
        "Organiser étapes, dépendances et critères de validation.",
        "Propose une roadmap mesurable pour ce projet.",
        "/api/v1/roadmaps/import",
        True,
    ),
    CapabilitySpec(
        "sessions",
        "Sessions et contexte",
        "Reprendre le travail avec son contexte et laisser un handoff.",
        "Reprends cette tâche à partir du dernier handoff.",
        "/api/v1/start-work",
        True,
    ),
    CapabilitySpec(
        "vault",
        "Vault natif",
        "Conserver et rechercher les connaissances durables des projets.",
        "Retrouve les connaissances sourcées sur cette partie du projet.",
        "/api/v1/vault/search",
    ),
    CapabilitySpec(
        "decisions",
        "Décisions DEC",
        "Consulter les choix validés et proposer ceux qui engagent la suite.",
        "Quelles décisions s'appliquent à cette tâche ?",
        "/api/v1/decisions",
    ),
    CapabilitySpec(
        "coordination",
        "Coordination",
        "Signaler les travaux en cours et les ressources utilisées.",
        "Signale que cette tâche utilise ces fichiers.",
        "/api/v1/coordination",
        True,
        True,
    ),
    CapabilitySpec(
        "library",
        "Bibliothèque IA",
        "Découvrir les définitions, leurs versions et leur résolution.",
        "Explique la résolution de cet agent sans modifier la bibliothèque.",
        "/api/v1/library",
    ),
    CapabilitySpec(
        "agents",
        "Identités d'agents",
        "Retrouver les identités durables et leurs traces d'exécution.",
        "Retrouve l'identité de ce harnais et de ce modèle observé.",
        "/api/v1/agents",
    ),
    CapabilitySpec(
        "runtimes",
        "Runtimes et liaisons",
        "Choisir les environnements et modèles d'exécution autorisés.",
        "Quels runtimes sont compatibles avec cet agent ?",
        "/api/v1/runtimes",
    ),
    CapabilitySpec(
        "launches",
        "Lancements",
        "Demander une exécution sur une machine autorisée.",
        "Qu'est-ce qui manque pour lancer cette tâche sur ce poste ?",
        "/api/v1/projects/{project_id}/task-launches",
        True,
        True,
    ),
    CapabilitySpec(
        "transfers",
        "Transferts",
        "Échanger des fichiers via le stockage, avec droits et rétention.",
        "Prépare un transfert de build pour le projet.",
        "/api/v1/transfers",
    ),
    CapabilitySpec(
        "builds",
        "Builds et CI",
        "Consulter les résultats CI reçus des dépôts connectés.",
        "Montre le dernier résultat CI disponible.",
        "/api/v1/builds",
        True,
    ),
    CapabilitySpec(
        "setup",
        "Configuration du poste",
        "Diagnostiquer Git, les outils IA et leurs raccordements.",
        "Qu'est-ce qui manque dans ma configuration ?",
        "/api/v1/machines",
    ),
    CapabilitySpec(
        "review",
        "Revue",
        "Retrouver les éléments qui attendent une relecture ou une décision.",
        "Qu'est-ce qui attend ma validation ?",
        "/api/v1/review-queue",
    ),
    CapabilitySpec(
        "activity",
        "Activité",
        "Lire les événements et la chronologie du projet.",
        "Qu'est-ce qui a changé depuis mon dernier passage ?",
        "/api/v1/events",
        True,
    ),
    CapabilitySpec(
        "usage",
        "Consommation",
        "Consulter les mesures d'utilisation et les budgets déclarés.",
        "Montre la consommation mesurée de ce projet.",
        "/api/v1/usage/summary",
        True,
    ),
    CapabilitySpec(
        "producer",
        "Analyses de projet",
        "Analyser priorités et blocages sans modifier les tâches.",
        "Quels blocages sont visibles dans ce projet ?",
        "/api/v1/producer-jobs",
        True,
        True,
    ),
)


async def discover_product(
    session: AsyncSession,
    principal: Principal,
    settings: Settings,
    *,
    intent: DiscoveryIntent = "overview",
    key: str | None = None,
    limit: int = 6,
) -> ProductDiscovery:
    if intent not in {"overview", "start_project", "configuration"}:
        raise HTTPException(422, detail={"error_code": "invalid_argument", "field": "intent"})
    if not 1 <= limit <= 24:
        raise HTTPException(422, detail={"error_code": "invalid_argument", "field": "limit"})
    if key is not None and len(key) > 80:
        raise HTTPException(422, detail={"error_code": "invalid_argument", "field": "key"})
    if key is not None and key not in {item.key for item in CATALOGUE}:
        raise HTTPException(404, detail={"error_code": "capability_not_found"})
    projects_query = select(ProjectModel.id).where(ProjectModel.archived.is_(False)).limit(1)
    project_filter = project_visibility_clause(principal, ProjectModel.id)
    if project_filter is not None:
        projects_query = projects_query.where(project_filter)
    has_project = (await session.execute(projects_query)).first() is not None
    ci_query = (
        select(GitHubIntegrationModel.id).where(GitHubIntegrationModel.enabled.is_(True)).limit(1)
    )
    ci_filter = project_visibility_clause(principal, GitHubIntegrationModel.project_id)
    if ci_filter is not None:
        ci_query = ci_query.where(ci_filter)
    has_ci = (await session.execute(ci_query)).first() is not None
    report = parse_stored_capabilities(principal.machine.capabilities)
    report_at = principal.machine.capabilities_reported_at
    fresh = report_at is not None and datetime.now(UTC) - report_at < timedelta(
        seconds=settings.heartbeat_offline_after_seconds
    )
    writer = principal.role != Role.READONLY
    has_registered_project = False
    if report is not None and report.project_ids:
        has_registered_project = (
            await session.execute(projects_query.where(ProjectModel.id.in_(report.project_ids)))
        ).first() is not None
    items: list[ProductCapability] = []
    for spec in CATALOGUE:
        if key is not None and spec.key != key:
            continue
        state: CapabilityState = "available"
        reason: str | None = None
        restrictions = []
        if spec.write_only and not writer:
            state, reason = "not_authorized", "Votre rôle permet la lecture, pas cette action."
        elif spec.project and not has_project:
            state, reason = "needs_configuration", "Aucun projet accessible n'est encore suivi."
        elif spec.key == "builds" and not has_ci:
            state, reason = (
                "needs_configuration",
                "Aucune connexion CI activée sur vos projets accessibles.",
            )
        elif spec.key in {"launches", "setup"}:
            if report is None or not fresh:
                state, reason = (
                    "needs_configuration",
                    "Le poste n'a pas transmis de diagnostic récent.",
                )
            elif spec.key == "launches" and report.launch_safety is not True:
                state, reason = (
                    "unsupported",
                    "Ce client ne prend pas en charge le contrôle de lancement requis.",
                )
            elif spec.key == "launches" and not report.accepts_launches:
                state, reason = (
                    "needs_configuration",
                    "Les lancements ne sont pas autorisés sur ce poste.",
                )
            elif spec.key == "launches" and not has_registered_project:
                state, reason = (
                    "needs_configuration",
                    "Aucun projet accessible n'est enregistré sur ce poste.",
                )
            elif spec.key == "launches" and not any(h.configured for h in report.harnesses):
                state, reason = "needs_configuration", "Aucun harnais n'est configuré sur ce poste."
            elif spec.key == "launches" and report.running_launches >= report.max_launches:
                state, reason = (
                    "needs_configuration",
                    "Aucun créneau libre : attendre une fin ou revoir la limite locale.",
                )
        write_allowed = writer
        if spec.key == "projects":
            write_allowed = principal.role in {Role.ADMIN, Role.DEVELOPER}
            restrictions.append("La création d'un projet exige un rôle admin ou developer.")
        if spec.key == "decisions":
            restrictions.append(
                "Seul un admin peut accepter ou remplacer une DEC ; un agent peut proposer."
            )
        if spec.key == "setup" and reason is None:
            reason = "Git et les fichiers locaux restent à vérifier dans Configurer ce poste."
        if not writer:
            restrictions.append("Écriture non autorisée pour votre rôle.")
        detail = key is not None
        prerequisites = ["Une connexion Studi'OS authentifiée."]
        if spec.project:
            prerequisites.append("Un projet suivi et accessible.")
        if spec.key == "setup":
            prerequisites.append(
                "Desktop connecté ou CLI installé sur ce poste ; "
                "tout changement doit être confirmé."
            )
        elif spec.key == "agents":
            prerequisites.append(
                "Le harnais doit exposer le fournisseur et le modèle effectivement utilisés."
            )
        elif spec.key == "launches":
            prerequisites.append(
                "Dossier enregistré, harnais configuré, opt-in et créneau libre sur le poste cible."
            )
        elif spec.key == "builds":
            prerequisites.append("Une connexion CI activée sur le projet concerné.")
        elif spec.key == "transfers":
            prerequisites.append(
                "Stockage accessible, quotas suffisants et autorisation sur le fichier."
            )
        items.append(
            ProductCapability(
                key=spec.key,
                title=spec.title,
                summary=spec.summary,
                state=state,
                reason=reason,
                write_allowed=write_allowed,
                example=spec.example if detail else None,
                prerequisites=prerequisites if detail else [],
                restrictions=restrictions if detail else [],
            )
        )
    if intent == "configuration" and key is None:
        items = [item for item in items if item.state != "available" or item.key == "setup"]
    elif intent == "start_project" and key is None:
        wanted = {"projects", "tasks", "roadmaps", "setup", "vault", "decisions"}
        items = [item for item in items if item.key in wanted]
    next_steps = (
        [
            "Vérifier Git dans Configurer ce poste, puis relancer le diagnostic.",
            "Créer ou sélectionner un projet et enregistrer son dossier.",
            "Définir les tâches et leurs critères ; versionner localement sans distant imposé.",
            "Démarrer ou reprendre une tâche ; conserver connaissances et DEC dans le vault natif.",
        ]
        if intent == "start_project"
        else []
    )
    return ProductDiscovery(
        intent=intent,
        summary="Studi'OS organise le travail, les connaissances et les exécutions du studio. "
        "Les états reposent sur vos droits, la configuration et les rapports reçus du poste.",
        capabilities=items[:limit],
        additional_available=max(0, len(items) - limit),
        next_steps=next_steps,
    )
