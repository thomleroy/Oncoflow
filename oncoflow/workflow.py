from __future__ import annotations

from typing import Dict, List

from .models import ChecklistState, DossierStatus, Transition


class TransitionError(ValueError):
    pass


class WorkflowEngine:
    order: List[DossierStatus] = [
        DossierStatus.A_PREPARER,
        DossierStatus.PRESCRIPTION_VALIDEE,
        DossierStatus.CONTOURS_VALIDES,
        DossierStatus.PLAN_EN_REVUE,
        DossierStatus.PLAN_VALIDE,
        DossierStatus.PRET_POUR_TRAITEMENT,
        DossierStatus.EN_TRAITEMENT,
        DossierStatus.CLOTURE,
    ]

    forward_rules: Dict[DossierStatus, List[DossierStatus]] = {
        DossierStatus.A_PREPARER: [DossierStatus.PRESCRIPTION_VALIDEE],
        DossierStatus.PRESCRIPTION_VALIDEE: [
            DossierStatus.CONTOURS_VALIDES,
            DossierStatus.A_PREPARER,
        ],
        DossierStatus.CONTOURS_VALIDES: [
            DossierStatus.PLAN_EN_REVUE,
            DossierStatus.PRESCRIPTION_VALIDEE,
        ],
        DossierStatus.PLAN_EN_REVUE: [
            DossierStatus.PLAN_VALIDE,
            DossierStatus.A_REPRENDRE_CONTOURAGE,
            DossierStatus.CONTOURS_VALIDES,
        ],
        DossierStatus.PLAN_VALIDE: [
            DossierStatus.PRET_POUR_TRAITEMENT,
            DossierStatus.PLAN_EN_REVUE,
        ],
        DossierStatus.PRET_POUR_TRAITEMENT: [
            DossierStatus.EN_TRAITEMENT,
            DossierStatus.PLAN_VALIDE,
        ],
        DossierStatus.EN_TRAITEMENT: [
            DossierStatus.CLOTURE,
            DossierStatus.PRET_POUR_TRAITEMENT,
        ],
        DossierStatus.CLOTURE: [],
        DossierStatus.A_REPRENDRE_CONTOURAGE: [DossierStatus.CONTOURS_VALIDES],
    }

    checklist_requirements: Dict[DossierStatus, str] = {
        DossierStatus.PRESCRIPTION_VALIDEE: "identity_validated",
        DossierStatus.CONTOURS_VALIDES: "prescription_signed",
        DossierStatus.PLAN_EN_REVUE: "contours_locked",
        DossierStatus.PLAN_VALIDE: "qa_dosimetrie",
        DossierStatus.PRET_POUR_TRAITEMENT: "signature_oncologue",
        DossierStatus.EN_TRAITEMENT: "qa_machine_jour",
    }

    def validate_transition(
        self,
        current: DossierStatus,
        target: DossierStatus,
        checklist: ChecklistState,
        commentaire: str | None = None,
    ) -> None:
        allowed_targets = self.forward_rules.get(current, [])
        if target not in allowed_targets:
            raise TransitionError(
                f"Transition {current.value} -> {target.value} non autorisee"
            )

        requirement = self.checklist_requirements.get(target)
        if requirement:
            requirement_value = getattr(checklist, requirement)
            if not requirement_value:
                raise TransitionError(
                    f"La condition '{requirement}' doit etre validee pour passer en {target.value}"
                )

        is_backward = self._is_backward(current, target)
        if is_backward and not commentaire:
            raise TransitionError(
                "Un commentaire est obligatoire pour revenir a un statut precedent"
            )

    def _is_backward(self, current: DossierStatus, target: DossierStatus) -> bool:
        try:
            return self.order.index(target) < self.order.index(current)
        except ValueError:
            return False

    def apply_transition(
        self,
        dossier_id: str,
        current: DossierStatus,
        target: DossierStatus,
        checklist: ChecklistState,
        auteur: str,
        role,
        commentaire: str | None = None,
    ) -> Transition:
        self.validate_transition(current, target, checklist, commentaire)
        return Transition(
            dossier_id=dossier_id,
            ancien_statut=current,
            nouveau_statut=target,
            auteur=auteur,
            role=role,
            commentaire=commentaire,
        )


engine = WorkflowEngine()
