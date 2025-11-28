from __future__ import annotations

from typing import Dict, List, Optional

from .models import (
    ChecklistState,
    Dossier,
    DossierStatus,
    Message,
    Patient,
    Role,
    Transition,
    TransitionRequest,
)
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
        engine.reset()

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

    def get_history(self, dossier_id: str) -> List[Transition]:
        dossier = self.get_dossier(dossier_id)
        return dossier.historique

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

    def list_messages(self, dossier_id: str) -> List[Message]:
        if dossier_id not in self.dossiers:
            raise KeyError("Dossier introuvable")
        return self.messages.get(dossier_id, [])

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

    def get_checklist_fields(self):
        return ChecklistState.model_fields.keys()

    def list_dossiers_grouped(self):
        grouped: Dict[str, List[dict]] = {
            status.value: [] for status in DossierStatus
        }
        for dossier in self.dossiers.values():
            patient = self.patients.get(dossier.patient_id)
            grouped[dossier.statut.value].append(
                {
                    "id": dossier.id,
                    "statut": dossier.statut.value,
                    "patient": f"{patient.prenom} {patient.nom}" if patient else "",
                    "machine": dossier.machine,
                    "protocole": dossier.protocole,
                    "priorite": dossier.priorite,
                    "etiquettes": dossier.etiquettes,
                    "checklists": dossier.checklists.model_dump(),
                    "historique": [
                        t.model_dump(mode="json") for t in dossier.historique
                    ],
                }
            )
        return grouped

    def seed_demo(self):
        self.reset()
        alice = self.create_patient("Durand", "Alice", pathologie="sein")
        bob = self.create_patient("Martin", "Bob", pathologie="poumon")
        clara = self.create_patient("Bernard", "Clara", pathologie="ORL")

        dossiers = [
            self.create_dossier(alice.id, machine="Linac A", priorite="haute"),
            self.create_dossier(bob.id, machine="CyberKnife", priorite="standard"),
            self.create_dossier(clara.id, machine="Linac B", priorite="basse"),
        ]

        transitions: List[TransitionRequest] = [
            TransitionRequest(
                cible=DossierStatus.PRESCRIPTION_VALIDEE,
                contexte={"identity_validated": True},
                acteur="dr onco",
                role=Role.ONCOLOGUE,
            ),
            TransitionRequest(
                cible=DossierStatus.CONTOURS_VALIDES,
                contexte={"prescription_signed": True},
                acteur="dr onco",
                role=Role.ONCOLOGUE,
            ),
            TransitionRequest(
                cible=DossierStatus.PLAN_EN_REVUE,
                contexte={"contours_locked": True},
                acteur="dosimetrist",
                role=Role.DOSIMETRISTE,
            ),
            TransitionRequest(
                cible=DossierStatus.PLAN_VALIDE,
                contexte={"qa_dosimetrie": True},
                acteur="physicien",
                role=Role.PHYSICIEN,
            ),
            TransitionRequest(
                cible=DossierStatus.PRET_POUR_TRAITEMENT,
                contexte={"signature_oncologue": True},
                acteur="dr onco",
                role=Role.ONCOLOGUE,
            ),
            TransitionRequest(
                cible=DossierStatus.EN_TRAITEMENT,
                contexte={"qa_machine_jour": True},
                acteur="manip",
                role=Role.MANIPULATEUR,
            ),
        ]

        targets = [
            [],
            [transitions[0]],
            transitions[:3],
        ]

        for dossier, steps in zip(dossiers, targets):
            for transition in steps:
                self.apply_transition(dossier.id, transition)

        return dossiers


repo = InMemoryRepository()

__all__ = ["repo", "InMemoryRepository", "TransitionError"]
