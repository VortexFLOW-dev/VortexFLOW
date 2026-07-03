# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at https://mozilla.org/MPL/2.0/.

from fastapi import APIRouter
from app.api.v1 import (
    agent,
    audit,
    auth,
    auth_sso,
    catalog,
    certs,
    components,
    dashboard,
    events,
    notifications,
    users,
    instances,
    vrl_transforms,
    recovery,
    routes,
    settings,
    fleets,
    tokens,
    transform_stages,
    vm,
)

api_router = APIRouter()

api_router.include_router(vm.router, prefix="/vm", tags=["vm"])
api_router.include_router(auth.router, prefix="/auth", tags=["auth"])
api_router.include_router(auth_sso.router, prefix="/auth", tags=["auth-sso"])
api_router.include_router(users.router, prefix="/users", tags=["users"])
api_router.include_router(instances.router, prefix="/instances", tags=["instances"])
api_router.include_router(
    vrl_transforms.router, prefix="/transforms", tags=["transforms"]
)
api_router.include_router(recovery.router, prefix="/recovery", tags=["recovery"])
api_router.include_router(fleets.router, prefix="/fleets", tags=["fleets"])
api_router.include_router(routes.router, prefix="/routes", tags=["routes"])
api_router.include_router(components.router, prefix="/components", tags=["components"])
api_router.include_router(dashboard.router, prefix="/dashboard", tags=["dashboard"])
api_router.include_router(events.router, prefix="/events", tags=["events"])
api_router.include_router(
    notifications.router, prefix="/notifications", tags=["notifications"]
)
api_router.include_router(settings.router, prefix="/settings", tags=["settings"])
api_router.include_router(certs.router, prefix="/certs", tags=["certs"])
api_router.include_router(agent.router, prefix="/agent", tags=["agent"])
api_router.include_router(audit.router, prefix="/audit", tags=["audit"])
api_router.include_router(tokens.router, prefix="/tokens", tags=["tokens"])
api_router.include_router(catalog.router, prefix="/catalog", tags=["catalog"])
api_router.include_router(
    transform_stages.router, prefix="/transform-stages", tags=["transform-stages"]
)
