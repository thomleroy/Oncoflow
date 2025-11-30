import pytest
from fastapi.testclient import TestClient

from oncoflow.app import app
from oncoflow.models import DossierStatus, Patient, Role
from oncoflow.repository import repo

client = TestClient(app)


def setup_function(_function):
    repo.reset()


def create_patient_and_dossier():
    patient_resp = client.post(
        "/patients",
        json={"nom": "Doe", "prenom": "Jane", "pathologie": "sein"},
    )
    patient = Patient(**patient_resp.json())
    dossier_resp = client.post(
        "/dossiers",
        json={"patient_id": patient.id, "machine": "Linac A"},
    )
    dossier = dossier_resp.json()
    return patient, dossier


def test_happy_path_forward_transitions():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    transitions = [
        (DossierStatus.PRESCRIPTION_VALIDEE, {"identity_validated": True}),
        (DossierStatus.CONTOURS_VALIDES, {"prescription_signed": True}),
        (DossierStatus.PLAN_EN_REVUE, {"contours_locked": True}),
        (DossierStatus.PLAN_VALIDE, {"qa_dosimetrie": True}),
        (DossierStatus.PRET_POUR_TRAITEMENT, {"signature_oncologue": True}),
        (DossierStatus.EN_TRAITEMENT, {"qa_machine_jour": True}),
        (DossierStatus.CLOTURE, {}),
    ]

    for target, context in transitions:
        response = client.post(
            f"/dossiers/{dossier_id}/transition",
            json={
                "cible": target.value,
                "contexte": context,
                "acteur": "bot",
                "role": "physicien",
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["statut"] == target.value


def test_missing_checklist_block_transition():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    response = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.PRESCRIPTION_VALIDEE.value,
            "contexte": {},
            "acteur": "bot",
            "role": "physicien",
        },
    )
    assert response.status_code == 400
    assert "identity_validated" in response.json()["detail"]


def test_backward_requires_comment():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    forward = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.PRESCRIPTION_VALIDEE.value,
            "contexte": {"identity_validated": True},
            "acteur": "bot",
            "role": "physicien",
        },
    )
    assert forward.status_code == 200

    backward = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.A_PREPARER.value,
            "contexte": {},
            "acteur": "bot",
            "role": "physicien",
        },
    )
    assert backward.status_code == 400
    assert "commentaire" in backward.json()["detail"].lower()


@pytest.mark.parametrize(
    "target",
    [
        DossierStatus.CONTOURS_VALIDES,
        DossierStatus.PLAN_EN_REVUE,
        DossierStatus.PLAN_VALIDE,
    ],
)
def test_invalid_target_from_start(target):
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    response = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": target.value,
            "contexte": {"identity_validated": True},
            "acteur": "bot",
            "role": "physicien",
        },
    )
    assert response.status_code == 400
    assert "non autorisee" in response.json()["detail"]


def test_messages_threading():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    message_response = client.post(
        f"/dossiers/{dossier_id}/messages",
        json={
            "dossier_id": dossier_id,
            "auteur": "bot",
            "role": "coordination",
            "texte": "Plan pret pour revue",
            "mentions": ["physicien"],
            "pieces_jointes": ["capture.png"],
            "visibilite": "equipe",
        },
    )

    assert message_response.status_code == 200
    body = message_response.json()
    assert body["dossier_id"] == dossier_id
    assert body["texte"] == "Plan pret pour revue"


def test_admin_transition_and_role_controls():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    update_transitions = client.put(
        "/admin/workflow/transitions",
        json={
            "source": DossierStatus.A_PREPARER.value,
            "targets": [DossierStatus.CONTOURS_VALIDES.value],
        },
    )
    assert update_transitions.status_code == 200

    response = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.PRESCRIPTION_VALIDEE.value,
            "contexte": {"identity_validated": True},
            "acteur": "bot",
            "role": Role.PHYSICIEN.value,
        },
    )
    assert response.status_code == 400

    update_roles = client.put(
        "/admin/workflow/roles",
        json={
            "status": DossierStatus.CONTOURS_VALIDES.value,
            "roles": [Role.ONCOLOGUE.value],
        },
    )
    assert update_roles.status_code == 200

    response_bis = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.CONTOURS_VALIDES.value,
            "contexte": {"prescription_signed": True},
            "acteur": "bot",
            "role": Role.PHYSICIEN.value,
        },
    )
    assert response_bis.status_code == 400

    oncologue = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.CONTOURS_VALIDES.value,
            "contexte": {"prescription_signed": True},
            "acteur": "dr aude",
            "role": Role.ONCOLOGUE.value,
        },
    )
    assert oncologue.status_code == 200
