import os
import logging
import requests
import csv
import json
from datetime import datetime, timedelta
from dotenv import load_dotenv
import anthropic
from tenacity import retry, stop_after_attempt, wait_fixed

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

CSV_FILENAME = "candidatures.csv"
EXPECTED_HEADERS = ["Date Découverte", "Type", "Source", "Entreprise", "Titre", "Lieu", "Statut", "Lien", "Contact", "Date Relance", "Date Candidature", "Notes"]

def init_csv_and_load_memory() -> set:
    seen_links = set()
    file_exists = os.path.isfile(CSV_FILENAME)
    
    if file_exists:
        with open(CSV_FILENAME, mode='r', encoding='utf-8-sig') as file:
            reader = csv.DictReader(file, delimiter=';')
            headers = reader.fieldnames
            rows = list(reader)
            
        # MIGRATION AUTOMATIQUE DES ANCIENNES DONNÉES
        if headers != EXPECTED_HEADERS:
            logging.info("Mise à jour de l'ancien fichier CSV vers le nouveau format sans perte de données...")
            with open(CSV_FILENAME, mode='w', encoding='utf-8-sig', newline='') as file:
                writer = csv.DictWriter(file, fieldnames=EXPECTED_HEADERS, delimiter=';')
                writer.writeheader()
                for row in rows:
                    new_row = {
                        "Date Découverte": row.get("Date Découverte", row.get("Date", "")),
                        "Type": row.get("Type", "Offre"),
                        "Source": row.get("Source", "Inconnue"),
                        "Entreprise": row.get("Entreprise", ""),
                        "Titre": row.get("Titre", ""),
                        "Lieu": row.get("Lieu", "Non précisé"),
                        "Statut": row.get("Statut", ""),
                        "Lien": row.get("Lien", ""),
                        "Contact": row.get("Contact", ""),
                        "Date Relance": row.get("Date Relance", ""),
                        "Date Candidature": row.get("Date Candidature", ""),
                        "Notes": row.get("Notes", "")
                    }
                    writer.writerow(new_row)
                    seen_links.add(new_row["Lien"])
            logging.info("Migration terminée avec succès !")
        else:
            for row in rows:
                seen_links.add(row.get("Lien", ""))
            logging.info(f"Mémoire chargée : {len(seen_links)} offres déjà traitées.")
    else:
        with open(CSV_FILENAME, mode='w', encoding='utf-8-sig', newline='') as file:
            writer = csv.writer(file, delimiter=';')
            writer.writerow(EXPECTED_HEADERS)
        logging.info("Nouveau fichier candidatures.csv créé.")
            
    return seen_links

def save_to_csv(company: str, title: str, status: str, link: str, candidature_type: str, source: str, location: str):
    date_decouverte = datetime.now().strftime("%Y-%m-%d")
    date_relance = (datetime.now() + timedelta(days=7)).strftime("%Y-%m-%d")
    
    with open(CSV_FILENAME, mode='a', encoding='utf-8-sig', newline='') as file:
        writer = csv.writer(file, delimiter=';')
        writer.writerow([date_decouverte, candidature_type, source, company, title, location, status, link, "", date_relance, "", ""])

def read_candidate_profile() -> str:
    try:
        with open("candidate.md", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        logging.error("ÉCHEC FATAL : Le fichier candidate.md est introuvable.")
        return ""

# --- LOGIQUE FRANCE TRAVAIL ---
def get_ft_token(client_id, client_secret):
    # Ajout de ?realm=%2Fpartenaire essentiel pour se connecter à l'API
    url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token?realm=%2Fpartenaire"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "api_offresdemploiv2 o2dsoffre"  # CORRECTION DU SCOPE ICI
    }
    response = requests.post(url, data=data)
    
    # Si ça échoue, on affiche le message de refus exact de France Travail
    if response.status_code != 200:
        logging.error(f"Détail de l'erreur d'authentification FT : {response.text}")
        
    response.raise_for_status()
    return response.json()["access_token"]

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def fetch_jobs_via_ft(token, keyword: str, seen_links: set) -> list[dict]:
    logging.info("Recherche via API France Travail V2...")
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    
    # La pagination (range) doit être passée en header, pas en paramètre d'URL
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Range": "items=0-19" 
    }
    
    # Paramètres de recherche (motsCles et typeContrat sont corrects)
    params = {
        "motsCles": keyword,
    #    "natureContrat": "E2",
        "publieeDepuis": 1
    }
    
    response = requests.get(url, headers=headers, params=params)

    if response.status_code == 204:
        logging.info("France Travail : Aucune nouvelle offre publiée ces dernières 24h")
        return []
    
    # Si erreur 400, on affiche le détail renvoyé par FT pour debugger
    if response.status_code == 400:
        logging.error(f"Détail erreur FT : {response.text}")
        
    response.raise_for_status()
    jobs = response.json().get("resultats", [])
    
    results = []
    for job in jobs:
        link = job.get("origineOffre", {}).get("urlOrigine", "")
        if link and link not in seen_links:
            results.append({
                "texte_pour_ia": f"Titre : {job.get('intitule')}\nEntreprise : {(job.get('entreprise') or {}).get('nom', 'Inconnue')}\nDescription : {job.get('description')}",
                "lien_direct": link,
                "titre": job.get('intitule'),
                "entreprise": job.get('entreprise', {}).get('nom', 'Inconnue')
            })
    return results

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def fetch_jobs_via_adzuna(app_id: str, app_key: str, seen_links: set) -> list[dict]:
    logging.info("Étape 1a : Recherche d'offres sur Adzuna...")
    url = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
    search_keywords = "devops alternance OR devops stage OR cloud alternance OR cloud stage OR infrastructure alternance OR infrastructure stage OR kubernetes alternance OR kubernetes stage OR automatisation alternance OR automatisation stage"
    params = {
        'app_id': app_id,
        'app_key': app_key,
        'results_per_page': 20,
        'what': search_keywords,
        'where': 'france',
        'sort_by': 'date',
        'max_days_old': 1,
        'content-type': 'application/json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status() 
        data = response.json()
    except requests.exceptions.RequestException as e:
        logging.warning(f"Erreur réseau Adzuna : {e}")
        raise 

    real_jobs = []
    mots_interdits = [
        "école", "ecole", "formation", "campus", "bootcamp", "organisme de formation",
        "iscod", "openclassrooms", "simplon", "epitech", "my digital school", 
        "alternance ingénieur infrastructure", "cfa"
    ]
    
    for job in data.get('results', []):
        job_link = job.get('redirect_url', 'Lien non disponible') 
        if job_link in seen_links:
            continue
            
        job_title = job.get('title', '')
        job_summary = job.get('description', '')
        company = job.get('company', {}).get('display_name', 'Inconnue')
        lieu = job.get('location', {}).get('display_name', 'Non précisé')
        
        texte_a_verifier = f"{job_title} {job_summary} {company}".lower()
        if any(mot in texte_a_verifier for mot in mots_interdits):
            logging.info(f"Filtre Anti-École : {company} ignorée.")
            continue 
            
        real_jobs.append({
            "texte_pour_ia": f"Titre : {job_title}\nEntreprise : {company}\nLieu : {lieu}\nDescription : {job_summary}",
            "lien_direct": job_link,
            "titre": job_title,
            "entreprise": company,
            "source": "Adzuna",
            "lieu": lieu
        })
    return real_jobs

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def analyze_with_ai(job_data: dict, candidate_profile: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    
    system_prompt = """Tu es un expert en recrutement DevOps. 
    1. Calcule un score de matching (0-100%).
    2. Si < 70%, réponds "STATUT: REJETE".
    3. Si >= 70%, réponds "STATUT: VALIDE".
    """

    user_prompt = f"CV DU CANDIDAT:\n{candidate_profile}\n\nOFFRE:\n{job_data['texte_pour_ia']}"

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        return response.content[0].text
    except Exception as e:
        logging.warning(f"Erreur IA : {e}")
        raise

def send_slack_notification(message: str):
    # Récupération de l'URL depuis les variables d'environnement
    webhook_url = os.getenv("SLACK_WEBHOOK_URL")
    if not webhook_url:
        return

    slack_data = {'text': message}
    try:
        response = requests.post(
            webhook_url, 
            data=json.dumps(slack_data),
            headers={'Content-Type': 'application/json'}
        )
        response.raise_for_status()
    except Exception as e:
        logging.error(f"Erreur lors de l'envoi Slack : {e}")

def main():
    logging.info("Démarrage du pipeline de stockage des offres.")
    load_dotenv()
    
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    adzuna_id = os.getenv("ADZUNA_APP_ID")
    adzuna_key = os.getenv("ADZUNA_APP_KEY")
    ft_id = os.getenv("FT_CLIENT_ID")
    ft_secret = os.getenv("FT_CLIENT_SECRET")
    
    candidate_profile = read_candidate_profile()
    seen_links = init_csv_and_load_memory()

    jobs_to_process = []
    
    # Récupération Adzuna
    if adzuna_id and adzuna_key:
        try:
            jobs_to_process.extend(fetch_jobs_via_adzuna(adzuna_id, adzuna_key, seen_links))
        except Exception:
            logging.error("Échec récupération Adzuna.")

    # Récupération France Travail
    if ft_id and ft_secret:
        # On définit uniquement les "racines" des métiers
        base_keywords = [
            "DevOps", 
            "Ingénieur Cloud", 
            "Systèmes et Réseaux", 
            "Data Engineer",
            "Automatisation",
            "Infrastructure",
            "Kubernetes",
            "Industrialisation"
        ]
        
        # Le script va générer automatiquement la liste complète (stage + alternance)
        keywords_list = []
        for kw in base_keywords:
            keywords_list.append(f"{kw} alternance")
            keywords_list.append(f"{kw} stage")
            
        try:
            token = get_ft_token(ft_id, ft_secret)
            for kw in keywords_list:
                jobs_to_process.extend(fetch_jobs_via_ft(token, kw, seen_links))
        except Exception as e:
            logging.error(f"Échec récupération France Travail : {e}")

    # Élimination des doublons potentiels récoltés par les différents mots-clés
    unique_jobs = {job['lien_direct']: job for job in jobs_to_process}.values()
    jobs_to_process = list(unique_jobs)[:20] # On garde les 20 premières meilleures offres
    
    # 1. Traitement des OFFRES (avec IA)
    for job_data in jobs_to_process:
        logging.info(f"Traitement IA : {job_data['titre']}")
        
        try:
            result = analyze_with_ai(job_data, candidate_profile, anthropic_key)
        except Exception:
            result = "STATUT: REJETE"

        is_valid = "STATUT: VALIDE" in result
        if is_valid:
            status = "En attente"
            send_slack_notification(f"Nouvelle opportunité DevOps : *{job_data['titre']}* chez *{job_data['entreprise']}*!\nLien : {job_data['lien_direct']}")
        else:
            status = "Refusé"
        
        save_to_csv(
            company=job_data['entreprise'],
            title=job_data['titre'],
            status=status,
            link=job_data['lien_direct'],
            candidature_type="Offre",
            source=job_data.get("source", "Inconnue"),
            location=job_data.get("lieu", "Non précisé")
        )
        logging.info(f"Offre stockée : {job_data['entreprise']} (Statut: {status})")

    # 2. Traitement des CANDIDATURES SPONTANÉES (Lecture depuis le fichier externe)
    companies_file = "entreprises_cibles.txt"
    if os.path.exists(companies_file):
        with open(companies_file, "r", encoding="utf-8") as f:
            # On nettoie la ligne et on exclut les commentaires
            spontaneous_companies = [line.strip() for line in f if line.strip() and not line.startswith('#')]
            
        for company in spontaneous_companies:
            fake_link = f"Spontanée - {company}"
            if fake_link not in seen_links:
                save_to_csv(
                    company=company,
                    title="Candidature Spontanée DevOps",
                    status="À postuler",
                    link=fake_link,
                    candidature_type="Spontanée",
                    source="Ciblage direct",
                    location="À définir"
                )
                seen_links.add(fake_link)
                logging.info(f"Entreprise cible stockée : {company}")
    else:
        logging.warning("Fichier entreprises_cibles.txt introuvable, étape spontanée ignorée")

    logging.info("Pipeline terminé avec succès.")

if __name__ == "__main__":
    main()