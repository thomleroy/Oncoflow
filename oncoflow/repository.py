from __future__ import annotations

from typing import Dict, List, Optional

from .models import Dossier, DossierStatus, Message, Patient, Transition, TransitionRequest
from .workflow import TransitionError, engine


class InMemoryRepository:
    def __init__(self) -> None:
        self.patients: Dict[str, Patient] = {}
        self.dossiers: Dict[str, Dossier] = {}
        self.messages: Dict[str, List[Message]] = {}

    def reset(self) -> None:
        self.patients.clear()
        self.dossiers.clear()
        self.messages.clear()

    def create_patient(
        self,
        nom: str,
        prenom: str,
        pathologie: Optional[str] = None,
        medecins_referents: Optional[List[str]] = None,
        external_id: Optional[str] = None,
    ) -> Patient:
        patient = Patient(
            nom=nom,
            prenom=prenom,
            pathologie=pathologie,
            medecins_referents=medecins_referents or [],
            external_id=external_id,
        )
        self.patients[patient.id] = patient
        return patient

    def create_dossier(
        self,
        patient_id: str,
        machine: Optional[str] = None,
        protocole: Optional[str] = None,
        priorite: Optional[str] = None,
        etiquettes: Optional[List[str]] = None,
    ) -> Dossier:
        if patient_id not in self.patients:
            raise KeyError("Patient introuvable")
        dossier = Dossier(
            patient_id=patient_id,
            machine=machine,
            protocole=protocole,
            priorite=priorite,
            etiquettes=etiquettes or [],
        )
        self.dossiers[dossier.id] = dossier
        return dossier

    def list_dossiers(self) -> List[Dossier]:
        return list(self.dossiers.values())

    def get_dossier(self, dossier_id: str) -> Dossier:
        dossier = self.dossiers.get(dossier_id)
        if not dossier:
            raise KeyError("Dossier introuvable")
        return dossier

    def add_message(
        self,
        dossier_id: str,
        auteur: str,
        role,
        texte: str,
        mentions: Optional[List[str]] = None,
        pieces_jointes: Optional[List[str]] = None,
        visibilite: str = "equipe",
    ) -> Message:
        if dossier_id not in self.dossiers:
            raise KeyError("Dossier introuvable")
        message = Message(
            dossier_id=dossier_id,
            auteur=auteur,
            role=role,
            texte=texte,
            mentions=mentions or [],
            pieces_jointes=pieces_jointes or [],
            visibilite=visibilite,
        )
        self.messages.setdefault(dossier_id, []).append(message)
        return message

    def apply_transition(self, dossier_id: str, request: TransitionRequest) -> Transition:
        dossier = self.get_dossier(dossier_id)
        merged_checklist = dossier.checklists.model_copy(update=request.contexte)
        transition = engine.apply_transition(
            dossier_id=dossier.id,
            current=dossier.statut,
            target=request.cible,
            checklist=merged_checklist,
            auteur=request.acteur,
            role=request.role,
            commentaire=request.commentaire,
        )
        dossier.statut = request.cible
        dossier.checklists = merged_checklist
        dossier.historique.append(transition)
        self.dossiers[dossier.id] = dossier
        return transition


repo = InMemoryRepository()

__all__ = ["repo", "InMemoryRepository", "TransitionError"]
