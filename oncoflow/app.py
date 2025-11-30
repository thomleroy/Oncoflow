from __future__ import annotations

import os

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from .models import (
    ChecklistConfig,
    ChecklistUpdate,
    Dossier,
    DossierDetail,
    DossierStatus,
    ErrorResponse,
    Message,
    Patient,
    Role,
    RoleConfig,
    TransitionConfig,
    TransitionRequest,
    WorkflowSnapshot,
)
from .repository import TransitionError, repo
from .workflow import engine

app = FastAPI(title="Oncoflow API", version="0.1.0")
app.mount("/static", StaticFiles(directory="oncoflow/static"), name="static")
templates = Jinja2Templates(directory="oncoflow/templates")

API_KEY = os.getenv("ONCOFLOW_API_KEY", "devkey")


def require_admin(api_key: str | None = Header(default=None, alias="X-API-Key")):
    if API_KEY and api_key != API_KEY:
        raise HTTPException(status_code=401, detail="API key invalide")
    return True


class Identity(BaseModel):
    utilisateur: str
    role: Role


def require_identity(
    x_user: str | None = Header(default=None, alias="X-User"),
    x_role: str | None = Header(default=None, alias="X-Role"),
) -> Identity:
    if not x_user or not x_role:
        raise HTTPException(
            status_code=401, detail="Entetes X-User et X-Role requis pour l'action"
        )
    try:
        role = Role(x_role)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail="Role inconnu") from exc
    return Identity(utilisateur=x_user, role=role)


def get_repo():
    return repo


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/", response_class=HTMLResponse)
def admin_dashboard(request: Request):
    config = engine.snapshot().model_dump(mode="json")
    return templates.TemplateResponse(
        "admin.html",
        {
            "request": request,
            "config": config,
            "statuses": list(DossierStatus),
            "checklist_fields": list(repo.get_checklist_fields()),
        },
    )


@app.get("/board", response_class=HTMLResponse)
def board_dashboard(request: Request):
    config = engine.snapshot().model_dump(mode="json")
    return templates.TemplateResponse(
        "board.html",
        {
            "request": request,
            "config": config,
            "statuses": list(DossierStatus),
        },
    )


@app.post(
    "/patients",
    response_model=Patient,
    responses={400: {"model": ErrorResponse}},
)
def create_patient_endpoint(
    patient: Patient, storage=Depends(get_repo), identity: Identity = Depends(require_identity)
):
    if hasattr(storage, "patient_exists") and storage.patient_exists(patient.id):
        raise HTTPException(status_code=400, detail="Patient deja existant")
    created = storage.create_patient(
        nom=patient.nom,
        prenom=patient.prenom,
        pathologie=patient.pathologie,
        medecins_referents=patient.medecins_referents,
        external_id=patient.external_id,
    )
    return created


@app.get("/patients", response_model=list[Patient])
def list_patients(storage=Depends(get_repo)):
    if hasattr(storage, "list_patients"):
        return storage.list_patients()
    return []


@app.post(
    "/dossiers",
    response_model=Dossier,
    responses={404: {"model": ErrorResponse}},
)
def create_dossier_endpoint(
    dossier: Dossier, storage=Depends(get_repo), identity: Identity = Depends(require_identity)
):
    try:
        created = storage.create_dossier(
            patient_id=dossier.patient_id,
            machine=dossier.machine,
            protocole=dossier.protocole,
            priorite=dossier.priorite,
            etiquettes=dossier.etiquettes,
        )
        return created
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/dossiers", response_model=list[Dossier])
def list_dossiers(storage=Depends(get_repo)):
    return storage.list_dossiers()


@app.get(
    "/dossiers/{dossier_id}",
    response_model=Dossier,
    responses={404: {"model": ErrorResponse}},
)
def get_dossier(dossier_id: str, storage=Depends(get_repo)):
    try:
        return storage.get_dossier(dossier_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/dossiers/{dossier_id}/transition",
    response_model=Dossier,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
def transition_dossier(
    dossier_id: str,
    request: TransitionRequest,
    storage=Depends(get_repo),
    identity: Identity = Depends(require_identity),
):
    acteur = request.acteur or identity.utilisateur
    role = request.role or identity.role

    if request.acteur and request.acteur != identity.utilisateur:
        raise HTTPException(
            status_code=403, detail="L'acteur doit correspondre a l'entete X-User"
        )
    if request.role and request.role != identity.role:
        raise HTTPException(
            status_code=403, detail="Le role doit correspondre a l'entete X-Role"
        )

    filled_request = request.model_copy(update={"acteur": acteur, "role": role})

    try:
        storage.apply_transition(dossier_id, filled_request)
        return storage.get_dossier(dossier_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get(
    "/dossiers/{dossier_id}/fhir", responses={404: {"model": ErrorResponse}}
)
def dossier_fhir(dossier_id: str, storage=Depends(get_repo)):
    try:
        dossier = storage.get_dossier(dossier_id)
        patient = storage.get_patient(dossier.patient_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return {
        "resourceType": "Bundle",
        "type": "collection",
        "entry": [
            {
                "resource": {
                    "resourceType": "Patient",
                    "id": patient.external_id or patient.id,
                    "name": [
                        {"family": patient.nom, "given": [patient.prenom]},
                    ],
                    "identifier": patient.external_id,
                    "condition": patient.pathologie,
                }
            },
            {
                "resource": {
                    "resourceType": "Procedure",
                    "id": dossier.id,
                    "status": dossier.statut.value.lower(),
                    "code": {"text": dossier.protocole or "Radiotherapie"},
                    "reason": patient.pathologie,
                    "performer": dossier.machine,
                    "note": [
                        {"text": t.commentaire or t.nouveau_statut.value}
                        for t in dossier.historique
                    ],
                }
            },
        ],
    }


@app.get(
    "/dossiers/{dossier_id}/messages",
    response_model=list[Message],
    responses={404: {"model": ErrorResponse}},
)
def list_messages(dossier_id: str, storage=Depends(get_repo)):
    try:
        return storage.list_messages(dossier_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get(
    "/dossiers/{dossier_id}/historique",
    response_model=list[dict],
    responses={404: {"model": ErrorResponse}},
)
def dossier_history(dossier_id: str, storage=Depends(get_repo)):
    try:
        return [t.model_dump(mode="json") for t in storage.get_history(dossier_id)]
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/dossiers/{dossier_id}/messages",
    response_model=Message,
    responses={404: {"model": ErrorResponse}},
)
def add_message(
    dossier_id: str,
    message: Message,
    storage=Depends(get_repo),
    identity: Identity = Depends(require_identity),
):
    if message.auteur != identity.utilisateur or message.role != identity.role:
        raise HTTPException(
            status_code=403,
            detail="L'auteur et le role doivent correspondre aux entetes X-User/X-Role",
        )
    try:
        created = storage.add_message(
            dossier_id=dossier_id,
            auteur=message.auteur,
            role=message.role,
            texte=message.texte,
            mentions=message.mentions,
            pieces_jointes=message.pieces_jointes,
            visibilite=message.visibilite,
        )
        return created
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/admin/workflow", response_model=WorkflowSnapshot, dependencies=[Depends(require_admin)])
def get_workflow_config():
    snapshot = engine.snapshot()
    return snapshot


@app.put(
    "/admin/workflow/transitions",
    response_model=WorkflowSnapshot,
    responses={400: {"model": ErrorResponse}},
    dependencies=[Depends(require_admin)],
)
def update_transitions(config: TransitionConfig):
    try:
        engine.update_transitions(config.source, config.targets)
        return engine.snapshot()
    except TransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put(
    "/admin/workflow/roles",
    response_model=WorkflowSnapshot,
    responses={400: {"model": ErrorResponse}},
    dependencies=[Depends(require_admin)],
)
def update_roles(config: RoleConfig):
    try:
        engine.update_allowed_roles(config.status, config.roles)
        return engine.snapshot()
    except TransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.put(
    "/admin/workflow/checklist",
    response_model=WorkflowSnapshot,
    responses={400: {"model": ErrorResponse}},
    dependencies=[Depends(require_admin)],
)
def update_checklist(config: ChecklistConfig):
    try:
        engine.update_checklist_requirement(config.status, config.requirement)
        return engine.snapshot()
    except TransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.get("/ui/dossiers")
def grouped_dossiers(storage=Depends(get_repo)):
    return storage.list_dossiers_grouped()


@app.get("/ui/dossiers/{dossier_id}", response_model=DossierDetail)
def dossier_detail(dossier_id: str, storage=Depends(get_repo)):
    try:
        return storage.get_dossier_detail(dossier_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.post(
    "/dossiers/{dossier_id}/checklists",
    response_model=Dossier,
    responses={404: {"model": ErrorResponse}},
)
def update_checklists_endpoint(
    dossier_id: str,
    payload: ChecklistUpdate,
    storage=Depends(get_repo),
    identity: Identity = Depends(require_identity),
):
    try:
        updated = storage.update_checklists(
            dossier_id, payload.flags, identity.utilisateur, identity.role
        )
        return updated
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.get("/notifications")
def list_notifications(storage=Depends(get_repo)):
    return [n.model_dump(mode="json") for n in storage.list_notifications()]


@app.get("/admin/audit", dependencies=[Depends(require_admin)])
def audit_log(storage=Depends(get_repo)):
    return [t.model_dump(mode="json") for t in storage.list_audit_log()]


@app.post("/admin/demo/seed", dependencies=[Depends(require_admin)])
def seed_demo(storage=Depends(get_repo)):
    storage.seed_demo()
    return storage.list_dossiers_grouped()


__all__ = ["app"]
