from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional
from uuid import uuid4

from pydantic import BaseModel, Field, field_validator


class Role(str, Enum):
    MANIPULATEUR = "manipulateur"
    PHYSICIEN = "physicien"
    ONCOLOGUE = "oncologue"
    DOSIMETRISTE = "dosimetrist"
    COORDINATION = "coordination"


class DossierStatus(str, Enum):
    A_PREPARER = "A_PREPARER"
    PRESCRIPTION_VALIDEE = "PRESCRIPTION_VALIDEE"
    CONTOURS_VALIDES = "CONTOURS_VALIDES"
    PLAN_EN_REVUE = "PLAN_EN_REVUE"
    PLAN_VALIDE = "PLAN_VALIDE"
    PRET_POUR_TRAITEMENT = "PRET_POUR_TRAITEMENT"
    EN_TRAITEMENT = "EN_TRAITEMENT"
    CLOTURE = "CLOTURE"
    A_REPRENDRE_CONTOURAGE = "A_REPRENDRE_CONTOURAGE"


class ChecklistState(BaseModel):
    identity_validated: bool = False
    prescription_signed: bool = False
    contours_locked: bool = False
    qa_dosimetrie: bool = False
    signature_oncologue: bool = False
    qa_machine_jour: bool = False

    @classmethod
    def from_context(cls, context: Optional[Dict[str, bool]]) -> "ChecklistState":
        return cls(**(context or {}))


class Patient(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    external_id: Optional[str] = None
    nom: str
    prenom: str
    pathologie: Optional[str] = None
    medecins_referents: List[str] = Field(default_factory=list)


class Dossier(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    patient_id: str
    machine: Optional[str] = None
    protocole: Optional[str] = None
    statut: DossierStatus = DossierStatus.A_PREPARER
    priorite: Optional[str] = None
    etiquettes: List[str] = Field(default_factory=list)
    checklists: ChecklistState = Field(default_factory=ChecklistState)
    historique: List["Transition"] = Field(default_factory=list)

    @field_validator("historique", mode="before")
    @classmethod
    def default_history(cls, v):
        return v or []


class Transition(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    dossier_id: str
    ancien_statut: DossierStatus
    nouveau_statut: DossierStatus
    horodatage: datetime = Field(default_factory=datetime.utcnow)
    auteur: str
    role: Role
    commentaire: Optional[str] = None


class TransitionRequest(BaseModel):
    cible: DossierStatus
    contexte: Optional[Dict[str, bool]] = None
    commentaire: Optional[str] = None
    acteur: Optional[str] = None
    role: Optional[Role] = None

    @field_validator("contexte", mode="before")
    @classmethod
    def none_to_empty(cls, v):
        return v or {}


class Message(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    dossier_id: str
    auteur: str
    role: Role
    texte: str
    mentions: List[str] = Field(default_factory=list)
    pieces_jointes: List[str] = Field(default_factory=list)
    visibilite: str = "equipe"
    horodatage: datetime = Field(default_factory=datetime.utcnow)


class Notification(BaseModel):
    id: str = Field(default_factory=lambda: str(uuid4()))
    type: str
    message: str
    severity: str = "info"
    dossier_id: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)


class ErrorResponse(BaseModel):
    detail: str


class TransitionConfig(BaseModel):
    source: DossierStatus
    targets: List[DossierStatus]


class RoleConfig(BaseModel):
    status: DossierStatus
    roles: List[Role]


class ChecklistConfig(BaseModel):
    status: DossierStatus
    requirement: Optional[str] = None


class WorkflowSnapshot(BaseModel):
    transitions: Dict[DossierStatus, List[DossierStatus]]
    checklist_requirements: Dict[DossierStatus, Optional[str]]
    allowed_roles: Dict[DossierStatus, List[Role]]
    status_order: List[DossierStatus]


class ChecklistUpdate(BaseModel):
    flags: Dict[str, bool]


class DossierDetail(BaseModel):
    dossier: Dossier
    patient: Patient
    messages: List[Message]
    historique: List[Transition]

