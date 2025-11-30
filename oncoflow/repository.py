from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Dict, Iterable, List, Optional
from urllib.parse import urlparse

from .models import (
    ChecklistState,
    Dossier,
    DossierStatus,
    Message,
    Notification,
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
        self.notifications: List[Notification] = []

    def reset(self) -> None:
        self.patients.clear()
        self.dossiers.clear()
        self.messages.clear()
        self.notifications.clear()
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

    def list_patients(self) -> List[Patient]:
        return list(self.patients.values())

    def get_patient(self, patient_id: str) -> Patient:
        patient = self.patients.get(patient_id)
        if not patient:
            raise KeyError("Patient introuvable")
        return patient

    def patient_exists(self, patient_id: str) -> bool:
        return patient_id in self.patients

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
        self.notifications.append(
            Notification(
                type="message",
                message=f"Nouveau message sur le dossier {dossier_id} par {auteur}",
                severity="info",
                dossier_id=dossier_id,
            )
        )
        return message

    def list_messages(self, dossier_id: str) -> List[Message]:
        if dossier_id not in self.dossiers:
            raise KeyError("Dossier introuvable")
        return self.messages.get(dossier_id, [])

    def apply_transition(self, dossier_id: str, request: TransitionRequest) -> Transition:
        dossier = self.get_dossier(dossier_id)
        merged_checklist = dossier.checklists.model_copy(update=request.contexte)
        if not request.acteur or not request.role:
            raise TransitionError("Identite (acteur/role) manquante pour la transition")
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
        self.notifications.append(
            Notification(
                type="transition",
                message=(
                    f"{request.acteur} ({request.role}) : {dossier.statut.value} -> "
                    f"{request.cible.value}"
                ),
                severity="info",
                dossier_id=dossier_id,
            )
        )
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
                    "messages": [
                        m.model_dump(mode="json")
                        for m in self.messages.get(dossier.id, [])
                    ],
                }
            )
        return grouped

    def list_notifications(self) -> List[Notification]:
        return list(self.notifications)

    def list_audit_log(self) -> List[Transition]:
        events: List[Transition] = []
        for dossier in self.dossiers.values():
            events.extend(dossier.historique)
        return sorted(events, key=lambda t: t.horodatage, reverse=True)

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


class FileBackedRepository(InMemoryRepository):
    def __init__(self, path: Path) -> None:
        super().__init__()
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists():
            self._load()

    def reset(self) -> None:
        super().reset()
        self._save()

    def create_patient(self, *args, **kwargs):
        patient = super().create_patient(*args, **kwargs)
        self._save()
        return patient

    def create_dossier(self, *args, **kwargs):
        dossier = super().create_dossier(*args, **kwargs)
        self._save()
        return dossier

    def add_message(self, *args, **kwargs):
        message = super().add_message(*args, **kwargs)
        self._save()
        return message

    def apply_transition(self, *args, **kwargs):
        transition = super().apply_transition(*args, **kwargs)
        self._save()
        return transition

    def _save(self) -> None:
        snapshot = {
            "patients": [p.model_dump(mode="json") for p in self.patients.values()],
            "dossiers": [d.model_dump(mode="json") for d in self.dossiers.values()],
            "messages": {
                key: [m.model_dump(mode="json") for m in value]
                for key, value in self.messages.items()
            },
            "notifications": [n.model_dump(mode="json") for n in self.notifications],
        }
        self.path.write_text(json.dumps(snapshot, indent=2), encoding="utf-8")

    def _load(self) -> None:
        data = json.loads(self.path.read_text(encoding="utf-8"))
        self.patients = {
            item["id"]: Patient.model_validate(item) for item in data.get("patients", [])
        }
        self.dossiers = {
            item["id"]: Dossier.model_validate(item) for item in data.get("dossiers", [])
        }
        self.messages = {
            key: [Message.model_validate(m) for m in messages]
            for key, messages in data.get("messages", {}).items()
        }
        self.notifications = [
            Notification.model_validate(n) for n in data.get("notifications", [])
        ]

    def seed_demo(self):
        dossiers = super().seed_demo()
        self._save()
        return dossiers


class SQLiteRepository:
    """Durable repository with normalized schema and lightweight migrations."""

    SCHEMA_VERSION = 1

    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA journal_mode = WAL")
        self._ensure_schema()

    @classmethod
    def from_env(cls) -> "SQLiteRepository":
        url = os.getenv("ONCOFLOW_DATABASE_URL")
        if not url:
            return cls(Path("data/state.db"))
        parsed = urlparse(url)
        if parsed.scheme != "sqlite":
            raise ValueError("Seul sqlite:// est supporté dans ce prototype")
        if parsed.path.startswith("/"):
            db_path = Path(parsed.path)
        else:
            db_path = Path(parsed.netloc) / parsed.path
        return cls(db_path)

    def _ensure_schema(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER NOT NULL
            )
            """
        )
        current = self.conn.execute("SELECT version FROM schema_version").fetchone()
        if current is None:
            self._apply_migration_v1()
            self.conn.execute("INSERT INTO schema_version(version) VALUES (?)", (1,))
            self.conn.commit()

    def _apply_migration_v1(self) -> None:
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY,
                external_id TEXT,
                nom TEXT NOT NULL,
                prenom TEXT NOT NULL,
                pathologie TEXT,
                medecins_referents TEXT
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS dossiers (
                id TEXT PRIMARY KEY,
                patient_id TEXT NOT NULL,
                machine TEXT,
                protocole TEXT,
                statut TEXT NOT NULL,
                priorite TEXT,
                etiquettes TEXT,
                checklists TEXT,
                created_at TEXT,
                FOREIGN KEY(patient_id) REFERENCES patients(id) ON DELETE CASCADE
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS transitions (
                id TEXT PRIMARY KEY,
                dossier_id TEXT NOT NULL,
                ancien_statut TEXT NOT NULL,
                nouveau_statut TEXT NOT NULL,
                horodatage TEXT NOT NULL,
                auteur TEXT NOT NULL,
                role TEXT NOT NULL,
                commentaire TEXT,
                FOREIGN KEY(dossier_id) REFERENCES dossiers(id) ON DELETE CASCADE
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS messages (
                id TEXT PRIMARY KEY,
                dossier_id TEXT NOT NULL,
                auteur TEXT NOT NULL,
                role TEXT NOT NULL,
                texte TEXT NOT NULL,
                mentions TEXT,
                pieces_jointes TEXT,
                visibilite TEXT,
                horodatage TEXT NOT NULL,
                FOREIGN KEY(dossier_id) REFERENCES dossiers(id) ON DELETE CASCADE
            )
            """
        )
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS notifications (
                id TEXT PRIMARY KEY,
                dossier_id TEXT,
                type TEXT NOT NULL,
                message TEXT NOT NULL,
                severity TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY(dossier_id) REFERENCES dossiers(id) ON DELETE CASCADE
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_dossiers_patient ON dossiers(patient_id)")
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_transitions_dossier ON transitions(dossier_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_messages_dossier ON messages(dossier_id)"
        )
        self.conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_notifications_created ON notifications(created_at)"
        )

    def reset(self) -> None:
        for table in ["notifications", "messages", "transitions", "dossiers", "patients"]:
            self.conn.execute(f"DELETE FROM {table}")
        self.conn.commit()
        engine.reset()

    def _json_dump(self, payload: dict | list | None) -> str:
        return json.dumps(payload or {}, ensure_ascii=False)

    def _json_dump_list(self, payload: list | None) -> str:
        return json.dumps(payload or [], ensure_ascii=False)

    def _json_load(self, raw: str | None):
        return json.loads(raw) if raw else {}

    def _json_load_list(self, raw: str | None):
        return json.loads(raw) if raw else []

    def _row_to_patient(self, row: sqlite3.Row) -> Patient:
        return Patient(
            id=row["id"],
            external_id=row["external_id"],
            nom=row["nom"],
            prenom=row["prenom"],
            pathologie=row["pathologie"],
            medecins_referents=self._json_load_list(row["medecins_referents"]),
        )

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
        self.conn.execute(
            """
            INSERT INTO patients(id, external_id, nom, prenom, pathologie, medecins_referents)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                patient.id,
                patient.external_id,
                patient.nom,
                patient.prenom,
                patient.pathologie,
                self._json_dump_list(patient.medecins_referents),
            ),
        )
        self.conn.commit()
        return patient

    def list_patients(self) -> List[Patient]:
        rows = self.conn.execute("SELECT * FROM patients ORDER BY nom, prenom").fetchall()
        return [self._row_to_patient(row) for row in rows]

    def get_patient(self, patient_id: str) -> Patient:
        row = self.conn.execute("SELECT * FROM patients WHERE id = ?", (patient_id,)).fetchone()
        if not row:
            raise KeyError("Patient introuvable")
        return self._row_to_patient(row)

    def patient_exists(self, patient_id: str) -> bool:
        return (
            self.conn.execute("SELECT 1 FROM patients WHERE id = ?", (patient_id,)).fetchone()
            is not None
        )

    def create_dossier(
        self,
        patient_id: str,
        machine: Optional[str] = None,
        protocole: Optional[str] = None,
        priorite: Optional[str] = None,
        etiquettes: Optional[List[str]] = None,
    ) -> Dossier:
        patient = self.conn.execute(
            "SELECT id FROM patients WHERE id = ?", (patient_id,)
        ).fetchone()
        if not patient:
            raise KeyError("Patient introuvable")

        dossier = Dossier(
            patient_id=patient_id,
            machine=machine,
            protocole=protocole,
            priorite=priorite,
            etiquettes=etiquettes or [],
        )
        self.conn.execute(
            """
            INSERT INTO dossiers(id, patient_id, machine, protocole, statut, priorite, etiquettes, checklists, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                dossier.id,
                dossier.patient_id,
                dossier.machine,
                dossier.protocole,
                dossier.statut.value,
                dossier.priorite,
                self._json_dump_list(dossier.etiquettes),
                self._json_dump(dossier.checklists.model_dump()),
                datetime.utcnow().isoformat(),
            ),
        )
        self.conn.commit()
        return dossier

    def list_dossiers(self) -> List[Dossier]:
        rows = self.conn.execute(
            "SELECT * FROM dossiers ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_dossier(row) for row in rows]

    def _row_to_dossier(self, row: sqlite3.Row) -> Dossier:
        dossier = Dossier(
            id=row["id"],
            patient_id=row["patient_id"],
            machine=row["machine"],
            protocole=row["protocole"],
            statut=DossierStatus(row["statut"]),
            priorite=row["priorite"],
            etiquettes=self._json_load_list(row["etiquettes"]),
            checklists=ChecklistState.model_validate(self._json_load(row["checklists"])),
        )
        dossier.historique = self.get_history(dossier.id)
        return dossier

    def get_dossier(self, dossier_id: str) -> Dossier:
        row = self.conn.execute(
            "SELECT * FROM dossiers WHERE id = ?", (dossier_id,)
        ).fetchone()
        if not row:
            raise KeyError("Dossier introuvable")
        return self._row_to_dossier(row)

    def get_history(self, dossier_id: str) -> List[Transition]:
        rows = self.conn.execute(
            "SELECT * FROM transitions WHERE dossier_id = ? ORDER BY horodatage", (dossier_id,)
        ).fetchall()
        return [self._row_to_transition(row) for row in rows]

    def _row_to_transition(self, row: sqlite3.Row) -> Transition:
        return Transition(
            id=row["id"],
            dossier_id=row["dossier_id"],
            ancien_statut=DossierStatus(row["ancien_statut"]),
            nouveau_statut=DossierStatus(row["nouveau_statut"]),
            horodatage=datetime.fromisoformat(row["horodatage"]),
            auteur=row["auteur"],
            role=Role(row["role"]),
            commentaire=row["commentaire"],
        )

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
        if not self.conn.execute("SELECT 1 FROM dossiers WHERE id = ?", (dossier_id,)).fetchone():
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
        self.conn.execute(
            """
            INSERT INTO messages(id, dossier_id, auteur, role, texte, mentions, pieces_jointes, visibilite, horodatage)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message.id,
                message.dossier_id,
                message.auteur,
                message.role.value if isinstance(message.role, Role) else message.role,
                message.texte,
                self._json_dump_list(message.mentions),
                self._json_dump_list(message.pieces_jointes),
                message.visibilite,
                message.horodatage.isoformat(),
            ),
        )
        notification = Notification(
            type="message",
            message=f"Nouveau message sur le dossier {dossier_id} par {auteur}",
            severity="info",
            dossier_id=dossier_id,
        )
        self._insert_notification(notification)
        self.conn.commit()
        return message

    def _insert_notification(self, notification: Notification) -> None:
        self.conn.execute(
            """
            INSERT INTO notifications(id, dossier_id, type, message, severity, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                notification.id,
                notification.dossier_id,
                notification.type,
                notification.message,
                notification.severity,
                notification.created_at.isoformat(),
            ),
        )

    def list_messages(self, dossier_id: str) -> List[Message]:
        if not self.conn.execute("SELECT 1 FROM dossiers WHERE id = ?", (dossier_id,)).fetchone():
            raise KeyError("Dossier introuvable")
        rows = self.conn.execute(
            "SELECT * FROM messages WHERE dossier_id = ? ORDER BY horodatage DESC",
            (dossier_id,),
        ).fetchall()
        return [self._row_to_message(row) for row in rows]

    def _row_to_message(self, row: sqlite3.Row) -> Message:
        return Message(
            id=row["id"],
            dossier_id=row["dossier_id"],
            auteur=row["auteur"],
            role=Role(row["role"]),
            texte=row["texte"],
            mentions=self._json_load_list(row["mentions"]),
            pieces_jointes=self._json_load_list(row["pieces_jointes"]),
            visibilite=row["visibilite"],
            horodatage=datetime.fromisoformat(row["horodatage"]),
        )

    def apply_transition(self, dossier_id: str, request: TransitionRequest) -> Transition:
        dossier = self.get_dossier(dossier_id)
        merged_checklist = dossier.checklists.model_copy(update=request.contexte)
        if not request.acteur or not request.role:
            raise TransitionError("Identite (acteur/role) manquante pour la transition")

        transition = engine.apply_transition(
            dossier_id=dossier.id,
            current=dossier.statut,
            target=request.cible,
            checklist=merged_checklist,
            auteur=request.acteur,
            role=request.role,
            commentaire=request.commentaire,
        )
        self.conn.execute(
            "UPDATE dossiers SET statut = ?, checklists = ? WHERE id = ?",
            (
                request.cible.value,
                self._json_dump(merged_checklist.model_dump()),
                dossier.id,
            ),
        )
        self.conn.execute(
            """
            INSERT INTO transitions(id, dossier_id, ancien_statut, nouveau_statut, horodatage, auteur, role, commentaire)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                transition.id,
                dossier.id,
                transition.ancien_statut.value,
                transition.nouveau_statut.value,
                transition.horodatage.isoformat(),
                transition.auteur,
                transition.role.value,
                transition.commentaire,
            ),
        )
        notification = Notification(
            type="transition",
            message=f"{request.acteur} ({request.role}) : {dossier.statut.value} -> {request.cible.value}",
            severity="info",
            dossier_id=dossier_id,
        )
        self._insert_notification(notification)
        self.conn.commit()
        return transition

    def get_checklist_fields(self):
        return ChecklistState.model_fields.keys()

    def list_dossiers_grouped(self):
        grouped: Dict[str, List[dict]] = {status.value: [] for status in DossierStatus}
        dossiers = self.list_dossiers()
        patients = {
            row["id"]: row for row in self.conn.execute("SELECT * FROM patients").fetchall()
        }
        for dossier in dossiers:
            patient = patients.get(dossier.patient_id)
            grouped[dossier.statut.value].append(
                {
                    "id": dossier.id,
                    "statut": dossier.statut.value,
                    "patient": f"{patient['prenom']} {patient['nom']}" if patient else "",
                    "machine": dossier.machine,
                    "protocole": dossier.protocole,
                    "priorite": dossier.priorite,
                    "etiquettes": dossier.etiquettes,
                    "checklists": dossier.checklists.model_dump(),
                    "historique": [t.model_dump(mode="json") for t in dossier.historique],
                    "messages": [m.model_dump(mode="json") for m in self.list_messages(dossier.id)],
                }
            )
        return grouped

    def list_notifications(self) -> List[Notification]:
        cursor = self.conn.execute(
            "SELECT * FROM notifications ORDER BY datetime(created_at) DESC"
        )
        return [self._row_to_notification(row) for row in cursor.fetchall()]

    def _row_to_notification(self, row: sqlite3.Row) -> Notification:
        return Notification(
            id=row["id"],
            type=row["type"],
            message=row["message"],
            severity=row["severity"],
            dossier_id=row["dossier_id"],
            created_at=datetime.fromisoformat(row["created_at"]),
        )

    def list_audit_log(self) -> List[Transition]:
        cursor = self.conn.execute(
            "SELECT * FROM transitions ORDER BY datetime(horodatage) DESC"
        )
        return [self._row_to_transition(row) for row in cursor.fetchall()]

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


repo = SQLiteRepository.from_env()

__all__ = [
    "repo",
    "InMemoryRepository",
    "FileBackedRepository",
    "SQLiteRepository",
    "TransitionError",
]
