# Pipeline DevOps : Assistant de Recherche d'Alternance

> **Automatisation de bout en bout de ma recherche d'entreprise pour mon Mastère DevOps**

## Problème

Chercher une alternance est chronophage et répétitif (parcourir les mêmes sites, filtrer les écoles déguisées en entreprises, lire des dizaines d'offres non pertinentes). En tant que futur Ingénieur DevOps, mon réflexe a été d'automatiser ce flux et d'en profiter en même temps comme terrain d'entraînement pour manipuler une chaîne d'outils DevOps réelle (conteneurisation, CI, orchestration)

## 🛠️ Solution (V1 - Actuelle)

J'ai conçu un pipeline en Python qui :

1. **S'authentifie & interroge** les API REST de France Travail (OAuth2) et d'Adzuna
2. **Filtre** intelligemment les résultats (système anti-écoles de formation)
3. **Analyse via l'IA** (Anthropic Claude 3.5 Haiku) pour évaluer la pertinence de l'offre par rapport à mon CV (`candidate.md`)
4. **Alimente une base de données** (CSV) servant de tableau de bord, tout en gérant les candidatures spontanées ciblées (OVH, Scaleway, etc.)

### Stack technique (V1)

- **Langage :** Python 3
- **Librairies :** `requests`, `tenacity` (gestion de la résilience réseau), `anthropic`
- **Architecture :** Gestion des secrets via `.env`, persistance des données via CSV

---

## 🚀 Évolution DevOps (V2 - En cours)

Le script fonctionne, mais nécessite encore une action manuelle pour être lancé. L'objectif de la V2 n'est pas seulement de l'automatiser, mais de m'en servir comme **projet vitrine** pour manipuler une chaîne d'outils DevOps de bout en bout — de la conteneurisation à l'orchestration.

**Note d'architecture :** pour un simple cron quotidien, un `cron` classique ou un GitHub Actions `schedule` suffiraient largement. Je choisis volontairement une stack plus complète (Docker → CI → Kubernetes) à des fins d'apprentissage et de démonstration de compétences, pas parce que le besoin fonctionnel l'exige. Je l'assume et le documente ici pour que ce soit explicite

### Étapes, dans l'ordre logique

- [ ] **Conteneurisation (Docker)**
  Packaging de l'application dans une image Docker (script + dépendances figées via `requirements.txt`), pour garantir sa portabilité et l'isoler de l'environnement hôte. C'est le socle : tout ce qui suit s'appuie sur cette image

- [ ] **Intégration Continue (CI) avec Jenkins**
  Un job Jenkins déclenché à chaque `push` sur le dépôt :
  - lint + tests unitaires du script Python,
  - build de l'image Docker,
  - push de l'image vers un registre (Docker Hub ou registre privé).
  *(C'est ici qu'intervient le vrai sens du mot "CI" : validation automatique du code à chaque changement, pas juste une exécution planifiée)*

- [ ] **3. Déploiement serveur**
  Hébergement sur un VPS, qui exécute l'image Docker construite à l'étape précédente (via un simple `docker run` en cron, en attendant l'étape K8s)

- [ ] **4. Orchestration (Kubernetes - initiation)**
  Objectif d'apprentissage à moyen terme : déployer ce service dans un cluster local (Minikube ou K3s) sous forme de **CronJob** Kubernetes, pour manipuler manifests, Secrets et ConfigMaps

- [ ] **5. Notifications**
  Envoi des offres "Validées par l'IA" par mail ou notification mobile, une fois le pipeline exécuté

### Points d'architecture à ne pas négliger

- **Secrets :** migration progressive du `.env` local vers Jenkins Credentials (étape CI), puis vers Kubernetes Secrets (étape orchestration) — pas de `.env` en clair transporté d'un environnement à l'autre
- **Persistance des données :** le CSV convient en V1 (exécution unique, séquentielle), mais n'est pas adapté à des exécutions concurrentes en environnement orchestré. Passage prévu à **SQLite** (voire PostgreSQL si le projet grandit) au moment du passage en Kubernetes
