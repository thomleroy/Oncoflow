from __future__ import annotations

from fastapi import Depends, FastAPI, HTTPException

from .models import Dossier, ErrorResponse, Message, Patient, TransitionRequest
from .repository import TransitionError, repo

app = FastAPI(title="Oncoflow API", version="0.1.0")


def get_repo():
    return repo


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.post(
    "/patients",
    response_model=Patient,
    responses={400: {"model": ErrorResponse}},
)
def create_patient_endpoint(patient: Patient, storage=Depends(get_repo)):
    if patient.id in storage.patients:
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
    return list(storage.patients.values())


@app.post(
    "/dossiers",
    response_model=Dossier,
    responses={404: {"model": ErrorResponse}},
)
def create_dossier_endpoint(dossier: Dossier, storage=Depends(get_repo)):
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
def transition_dossier(dossier_id: str, request: TransitionRequest, storage=Depends(get_repo)):
    try:
        storage.apply_transition(dossier_id, request)
        return storage.get_dossier(dossier_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except TransitionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/dossiers/{dossier_id}/messages",
    response_model=Message,
    responses={404: {"model": ErrorResponse}},
)
def add_message(dossier_id: str, message: Message, storage=Depends(get_repo)):
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


__all__ = ["app"]
