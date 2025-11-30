import pytest
from fastapi.testclient import TestClient

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from oncoflow.app import app
from oncoflow.models import DossierStatus, Patient, Role
from oncoflow.repository import FileBackedRepository, SQLiteRepository, repo

client = TestClient(app)
ADMIN_HEADERS = {"X-API-Key": "devkey"}


def auth_headers(user: str = "bot", role: Role = Role.PHYSICIEN):
    return {"X-User": user, "X-Role": role.value}


def setup_function(_function):
    repo.reset()


def create_patient_and_dossier():
    patient_resp = client.post(
        "/patients",
        json={"nom": "Doe", "prenom": "Jane", "pathologie": "sein"},
        headers=auth_headers(),
    )
    patient = Patient(**patient_resp.json())
    dossier_resp = client.post(
        "/dossiers",
        json={"patient_id": patient.id, "machine": "Linac A"},
        headers=auth_headers(),
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
            headers=auth_headers(),
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
        headers=auth_headers(),
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
        headers=auth_headers(),
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
        headers=auth_headers(),
    )
    assert backward.status_code == 400
    assert "commentaire" in backward.json()["detail"].lower()


def test_transition_requires_identity_headers():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    unauthorized = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.PRESCRIPTION_VALIDEE.value,
            "contexte": {"identity_validated": True},
            "acteur": "ghost",
            "role": Role.PHYSICIEN.value,
        },
    )
    assert unauthorized.status_code == 401

    authorized = client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.PRESCRIPTION_VALIDEE.value,
            "contexte": {"identity_validated": True},
            "acteur": "bot",
            "role": Role.PHYSICIEN.value,
        },
        headers=auth_headers(),
    )
    assert authorized.status_code == 200


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
        headers=auth_headers(),
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
        headers=auth_headers(role=Role.COORDINATION),
    )

    assert message_response.status_code == 200
    body = message_response.json()
    assert body["dossier_id"] == dossier_id
    assert body["texte"] == "Plan pret pour revue"


def test_message_identity_must_match_headers():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    forbidden = client.post(
        f"/dossiers/{dossier_id}/messages",
        json={
            "dossier_id": dossier_id,
            "auteur": "intrus",
            "role": "coordination",
            "texte": "Plan pret",
        },
        headers=auth_headers(role=Role.COORDINATION),
    )
    assert forbidden.status_code in {401, 403}

    allowed = client.post(
        f"/dossiers/{dossier_id}/messages",
        json={
            "dossier_id": dossier_id,
            "auteur": "bot",
            "role": "coordination",
            "texte": "Plan pret",
        },
        headers=auth_headers(role=Role.COORDINATION),
    )
    assert allowed.status_code == 200


def test_list_messages_endpoint():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    client.post(
        f"/dossiers/{dossier_id}/messages",
        json={
            "dossier_id": dossier_id,
            "auteur": "bot",
            "role": "coordination",
            "texte": "Prêt",
        },
        headers=auth_headers(role=Role.COORDINATION),
    )

    listing = client.get(f"/dossiers/{dossier_id}/messages")
    assert listing.status_code == 200
    assert len(listing.json()) == 1


def test_admin_transition_and_role_controls():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    update_transitions = client.put(
        "/admin/workflow/transitions",
        json={
            "source": DossierStatus.A_PREPARER.value,
            "targets": [DossierStatus.CONTOURS_VALIDES.value],
        },
        headers=ADMIN_HEADERS,
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
        headers=auth_headers(),
    )
    assert response.status_code == 400

    update_roles = client.put(
        "/admin/workflow/roles",
        json={
            "status": DossierStatus.CONTOURS_VALIDES.value,
            "roles": [Role.ONCOLOGUE.value],
        },
        headers=ADMIN_HEADERS,
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
        headers=auth_headers(),
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
        headers=auth_headers(user="dr aude", role=Role.ONCOLOGUE),
    )
    assert oncologue.status_code == 200


def test_board_grouping_and_seed():
    seed = client.post("/admin/demo/seed", headers=ADMIN_HEADERS)
    assert seed.status_code == 200
    data = seed.json()
    assert "A_PREPARER" in data

    board_data = client.get("/ui/dossiers")
    assert board_data.status_code == 200
    board_json = board_data.json()
    assert isinstance(board_json.get("A_PREPARER"), list)


def test_admin_requires_api_key():
    response = client.post("/admin/demo/seed")
    assert response.status_code == 401


def test_notifications_are_exposed():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    client.post(
        f"/dossiers/{dossier_id}/messages",
        json={
            "dossier_id": dossier_id,
            "auteur": "bot",
            "role": "coordination",
            "texte": "Bonjour",
        },
        headers=auth_headers(role=Role.COORDINATION),
    )

    notif_resp = client.get("/notifications")
    assert notif_resp.status_code == 200
    assert any("message" in n["type"] for n in notif_resp.json())


def test_file_backed_repository_persists(tmp_path):
    path = tmp_path / "state.json"
    file_repo = FileBackedRepository(path)
    patient = file_repo.create_patient("Test", "User")
    dossier = file_repo.create_dossier(patient.id, machine="Linac")
    assert path.exists()

    restored = FileBackedRepository(path)
    assert restored.get_dossier(dossier.id).machine == "Linac"


def test_sqlite_repository_persists_and_logs(tmp_path):
    path = tmp_path / "state.db"
    sqlite_repo = SQLiteRepository(path)
    patient = sqlite_repo.create_patient("Test", "User")
    dossier = sqlite_repo.create_dossier(patient.id, machine="Linac")
    sqlite_repo.add_message(dossier.id, "bot", Role.COORDINATION, "Note")

    restored = SQLiteRepository(path)
    assert restored.get_dossier(dossier.id).machine == "Linac"
    assert len(restored.list_notifications()) >= 1


def test_admin_audit_endpoint_requires_key():
    patient, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    client.post(
        f"/dossiers/{dossier_id}/transition",
        json={
            "cible": DossierStatus.PRESCRIPTION_VALIDEE.value,
            "contexte": {"identity_validated": True},
            "acteur": "bot",
            "role": Role.ONCOLOGUE.value,
        },
        headers=auth_headers(role=Role.ONCOLOGUE),
    )

    unauthorized = client.get("/admin/audit")
    assert unauthorized.status_code == 401

    authorized = client.get("/admin/audit", headers=ADMIN_HEADERS)
    assert authorized.status_code == 200
    assert any(entry["dossier_id"] == dossier_id for entry in authorized.json())


def test_fhir_projection():
    _, dossier = create_patient_and_dossier()
    dossier_id = dossier["id"]

    response = client.get(f"/dossiers/{dossier_id}/fhir")
    assert response.status_code == 200
    body = response.json()
    assert body["resourceType"] == "Bundle"
    assert body["entry"][0]["resource"]["resourceType"] == "Patient"
