from __future__ import annotations

from typing import Dict, List

from .models import ChecklistState, DossierStatus, Role, Transition, WorkflowSnapshot


class TransitionError(ValueError):
    pass


class WorkflowEngine:
    order: List[DossierStatus] = [
        DossierStatus.A_PREPARER,
        DossierStatus.PRESCRIPTION_VALIDEE,
        DossierStatus.CONTOURS_VALIDES,
        DossierStatus.PLAN_EN_REVUE,
        DossierStatus.A_REPRENDRE_CONTOURAGE,
        DossierStatus.PLAN_VALIDE,
        DossierStatus.PRET_POUR_TRAITEMENT,
        DossierStatus.EN_TRAITEMENT,
        DossierStatus.CLOTURE,
    ]

    base_forward_rules: Dict[DossierStatus, List[DossierStatus]] = {
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

    base_allowed_roles: Dict[DossierStatus, List[Role]] = {
        status: [
            Role.MANIPULATEUR,
            Role.PHYSICIEN,
            Role.ONCOLOGUE,
            Role.DOSIMETRISTE,
            Role.COORDINATION,
        ]
        for status in DossierStatus
    }

    base_checklist_requirements: Dict[DossierStatus, str] = {
        DossierStatus.PRESCRIPTION_VALIDEE: "identity_validated",
        DossierStatus.CONTOURS_VALIDES: "prescription_signed",
        DossierStatus.PLAN_EN_REVUE: "contours_locked",
        DossierStatus.PLAN_VALIDE: "qa_dosimetrie",
        DossierStatus.PRET_POUR_TRAITEMENT: "signature_oncologue",
        DossierStatus.EN_TRAITEMENT: "qa_machine_jour",
    }

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.forward_rules = {
            status: list(targets) for status, targets in self.base_forward_rules.items()
        }
        self.allowed_roles = {
            status: list(roles) for status, roles in self.base_allowed_roles.items()
        }
        self.checklist_requirements = dict(self.base_checklist_requirements)

    def validate_transition(
        self,
        current: DossierStatus,
        target: DossierStatus,
        checklist: ChecklistState,
        commentaire: str | None = None,
        role: Role | None = None,
    ) -> None:
        allowed_targets = self.forward_rules.get(current, [])
        if target not in allowed_targets:
            raise TransitionError(
                f"Transition {current.value} -> {target.value} non autorisee"
            )

        if role:
            authorized_roles = self.allowed_roles.get(target, [])
            if authorized_roles and role not in authorized_roles:
                raise TransitionError(
                    f"Le role {role.value} n'est pas autorise pour atteindre {target.value}"
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
        self.validate_transition(current, target, checklist, commentaire, role)
        return Transition(
            dossier_id=dossier_id,
            ancien_statut=current,
            nouveau_statut=target,
            auteur=auteur,
            role=role,
            commentaire=commentaire,
        )

    def update_transitions(
        self, source: DossierStatus, targets: List[DossierStatus]
    ) -> None:
        invalid_targets = [t for t in targets if t not in DossierStatus]
        if invalid_targets:
            raise TransitionError(
                f"Cibles invalides: {', '.join([t.value for t in invalid_targets])}"
            )
        self.forward_rules[source] = targets

    def update_allowed_roles(self, status: DossierStatus, roles: List[Role]) -> None:
        self.allowed_roles[status] = roles

    def update_checklist_requirement(
        self, status: DossierStatus, requirement: str | None
    ) -> None:
        if requirement and requirement not in ChecklistState.model_fields:
            raise TransitionError(
                f"Le pre-requis {requirement} n'existe pas dans la checklist"
            )
        if requirement:
            self.checklist_requirements[status] = requirement
        elif status in self.checklist_requirements:
            del self.checklist_requirements[status]

    def snapshot(self) -> WorkflowSnapshot:
        return WorkflowSnapshot(
            transitions=self.forward_rules,
            checklist_requirements=self.checklist_requirements,
            allowed_roles=self.allowed_roles,
            status_order=self.order,
        )


engine = WorkflowEngine()
