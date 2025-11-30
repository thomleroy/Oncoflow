# Oncoflow : suivi des dossiers patients en radiothérapie

## Objectif
Mettre à disposition une application qui suit l'avancement des dossiers patients en radiothérapie, permet de valider les tâches critiques et de partager des informations entre les équipes tout au long du parcours de soins.

## Rôles et responsabilités
- **Manipulateur / technologue** : saisie du dossier patient, vérification des données d'identité, gestion des documents d'imagerie.
- **Physicien médical** : validation du plan de traitement, contrôle qualité des paramètres machine, validation des QA quotidiennes/hebdomadaires.
- **Oncologue radiothérapeute** : prescription, validation du contourage, acceptation du plan.
- **Dosimétriste** : création et soumission du plan dosimétrique, annotations des contraintes.
- **Chef de service / coordination** : vue globale des files actives, relance des dossiers en retard.

## Flux de travail cible
1. **Création du dossier** (Manipulateur) : identité validée, examens importés, statut `À préparer`.
2. **Prescription** (Oncologue) : ordonnance et protocole ajoutés, statut `Prescription validée`.
3. **Contourage** (Oncologue) : volumes dessinés, statut `Contours validés`.
4. **Planification** (Dosimétriste) : plan calculé, contraintes documentées, statut `Plan en revue`.
5. **Contrôle Physique** (Physicien) : contrôle indépendant, QA machine, statut `Plan validé`.
6. **Signature** (Oncologue) : validation finale clinique, statut `Prêt pour traitement`.
7. **Traitement** (Manipulateur) : séances quotidiennes, check-list pré-séance, statut `En traitement`.
8. **Suivi / clôture** (Oncologue + Physicien) : effets indésirables, comparaisons dosimétriques, statut `Clôturé`.

Les transitions sont auditables avec date, auteur, commentaire obligatoire en cas de retour arrière.

## Fonctionnalités clés
- **Listes de travail** : vue Kanban par statut, filtres par priorité, pathologie, machine, médecin référent.
- **Check-lists et validations** : chaque étape associe une check-list ; certaines cases sont obligatoires avant validation.
- **Commentaires et mentions** : fil de commentaires par dossier avec mentions (@user) et pièces jointes (pdf, captures DICOM anonymisées).
- **Notifications** : rappels pour dossiers bloqués >24h, notifications ciblées par rôle et par dossier.
- **Règles de blocage** : impossibilité de lancer une séance si QA machine/plan non validée ou prescription absente.
- **Traçabilité** : historique horodaté des statuts, validations signées (avec identité et rôle), export PDF.
- **Interopérabilité** : import DICOM depuis PACS, export FHIR pour le DPI, identitovigilance via IHE PIX/PDQ.

## Modèle de données (MVP)
- `Patient` : id externe, identité, pathologie, médecins référents.
- `Dossier` : patient_id, machine, protocole, statut, priorité, dates clés, étiquettes.
- `Tâche` : dossier_id, type (prescription, contourage, QA…), statut, assigné à, échéance, checklist, commentaires.
- `Validation` : tâche_id, validateur, rôle, horodatage, commentaire, pièces jointes.
- `Message` : dossier_id, auteur, texte, mentions, pièces jointes, visibilité (équipe, physiciens, médecins).

## Règles de statut et transitions
| Statut courant | Transitions autorisées | Conditions de validation |
| --- | --- | --- |
| À préparer | Prescription validée | Identité et examens importés |
| Prescription validée | Contours validés | Prescription signée |
| Contours validés | Plan en revue | Contours verrouillés |
| Plan en revue | Plan validé \| À reprendre contourage | QA dosimétrique réalisée |
| Plan validé | Prêt pour traitement \| Plan en revue | Signature oncologue |
| Prêt pour traitement | En traitement | QA machine du jour OK |
| En traitement | Clôturé \| Prêt pour traitement | Séances terminées, compte rendu final |

Toute transition inverse exige un commentaire et génère une notification aux rôles impactés.

## Indicateurs de pilotage
- Temps moyen par étape (prescription → planification → validation → première séance).
- Nombre de dossiers bloqués par rôle et par machine.
- Taux de retours en arrière par étape (ex. plans refusés).
- Respect des délais réglementaires (prescription < 48h, validation physique < 72h...).

## Périmètre MVP technique
- Front web (React ou Vue) : Kanban, détail dossier, check-lists, fil de commentaires.
- API REST/GraphQL (Node/TypeScript ou Python/FastAPI) : endpoints dossiers, tâches, validations, fichiers.
- Base de données relationnelle (PostgreSQL) avec migrations versionnées.
- Authentification SSO (OIDC) et RBAC par rôle.
- Bus d'événements/notifications (ex. webhooks + emails).

## Sécurité et conformité
- Journalisation des actions critiques (validation, modification de prescription).
- Pseudonymisation des données non nécessaires aux affichages courants.
- Traçabilité des accès, conservation des logs selon la politique du service.
- Sauvegardes automatisées et plan de reprise en cas d'incident.
- Conformité RGPD : minimisation, droits d'accès, suppression/archivage sur demande.

## Backlog initial
- [ ] Maquette UX des vues Kanban et fiche dossier.
- [ ] Modélisation BDD détaillée (tables, clés, contraintes, index).
- [ ] Spécification des API et schémas de validation (OpenAPI/JSON Schema).
- [ ] Prototype d'authentification OIDC + RBAC.
- [ ] Connecteur d'import DICOM/PACS (placeholder dans le MVP si non disponible).
- [ ] Mécanisme de notifications (emails internes ou webhook Slack/Teams).

## Installation rapide

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
uvicorn oncoflow.app:app --reload
```

Pour peupler la démo :

```bash
curl -X POST http://localhost:8000/admin/demo/seed -H "X-API-Key: devkey"
```

## Sécurité et administration

Les endpoints `/admin/*` et `/admin/demo/seed` exigent une clé API transmise dans `X-API-Key`. Par défaut la valeur est `devkey`; définissez `ONCOFLOW_API_KEY` pour la modifier.

Toutes les actions d'écriture (patients, dossiers, transitions, messages) nécessitent désormais une identité explicite à fournir via les entêtes `X-User` et `X-Role` (valeurs : `manipulateur`, `physicien`, `oncologue`, `dosimetrist`, `coordination`). Le board conserve ces informations dans le navigateur et les réutilise pour signer chaque validation.

## Persistance

Le stockage par défaut utilise SQLite (`data/state.db`) avec un schéma normalisé (patients, dossiers, messages, transitions, notifications) et des clés étrangères. Les migrations sont versionnées dans `schema_version` et appliquées automatiquement au démarrage ; le mode WAL et les index par dossier renforcent la concurrence et les requêtes de supervision. Un dépôt JSON reste disponible (`FileBackedRepository`) pour les tests hors ligne ou les démos rapides.

Vous pouvez rediriger le fichier de base via `ONCOFLOW_DATABASE_URL=sqlite:///chemin/vers/state.db`.

## Intégrations et notifications

- Export FHIR minimal : `GET /dossiers/{id}/fhir` renvoie un bundle Patient + Procedure pour faciliter les échanges DPI/FHIR.
- Flux de notifications : `GET /notifications` expose les derniers événements (messages, transitions) pour alimenter un webhook ou un centre de supervision.
- [ ] Rapports d'activité et exports PDF.

## Démarrer l'API de prototype

Ce dépôt contient une première API FastAPI avec stockage en mémoire pour enchaîner les statuts, poster des messages et créer des patients/dossiers.

1. Créer un environnement virtuel Python 3.11+ puis installer les dépendances :

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

2. Lancer le serveur de développement :

```bash
uvicorn oncoflow.app:app --reload
```

3. Explorer la documentation OpenAPI générée automatiquement : http://localhost:8000/docs.

4. Ouvrir la console d'administration : http://localhost:8000/. Elle permet d'éditer en direct les transitions autorisées,
   les rôles pouvant atteindre une étape et les prérequis de checklist. Les mises à jour se propagent immédiatement aux
   validations côté API.

5. Afficher le board opérationnel : http://localhost:8000/board. Il regroupe les dossiers par statut avec des boutons de
   transition tenant compte des prérequis et permet d'injecter des données de démonstration en un clic.

5. Lancer les tests automatisés :

```bash
pytest
```

### Endpoints d'administration

- `GET /admin/workflow` : récupérer la configuration courante (transitions, prérequis, rôles).
- `PUT /admin/workflow/transitions` : modifier les cibles autorisées pour un statut source.
- `PUT /admin/workflow/roles` : restreindre ou élargir les rôles autorisés pour un statut cible.
- `PUT /admin/workflow/checklist` : définir ou retirer un prérequis de checklist pour un statut.
- `GET /admin/audit` : récupérer le journal horodaté des transitions (clé API requise).
