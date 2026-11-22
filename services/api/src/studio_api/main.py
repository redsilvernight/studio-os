from __future__ import annotations

import asyncio
import contextlib
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from studio_api.middleware import setup_middleware
from studio_api.observability import configure_logging
from studio_api.routers import (
    accounts,
    admission,
    agents,
    ai_integration,
    ai_work,
    auth,
    bootstrap_plan,
    budgets,
    builds,
    claims,
    coordination,
    decisions,
    discovery,
    eligibility,
    events,
    github,
    handoff,
    health,
    heartbeats,
    infra,
    initialization,
    library,
    machines,
    metrics,
    mission,
    producer,
    projects,
    resolutions,
    review_queue,
    roadmaps,
    runtime_bindings,
    runtimes,
    sessions,
    start_work,
    studio_lifecycle,
