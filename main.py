import os
import logging
import requests
import csv
from datetime import datetime
from dotenv import load_dotenv
import anthropic
from tenacity import retry, stop_after_attempt, wait_fixed

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

CSV_FILENAME = "candidatures.csv"

def init_csv_and_load_memory() -> set:
    seen_links = set()
    file_exists = os.path.isfile(CSV_FILENAME)
    
    if file_exists:
        with open(CSV_FILENAME, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                seen_links.add(row.get("Lien", ""))
        logging.info(f"Mémoire chargée : {len(seen_links)} offres déjà traitées.")
    else:
        with open(CSV_FILENAME, mode='w', encoding='utf-8', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Date", "Entreprise", "Titre", "Statut", "Lien", "Email_Genere"])
        logging.info("Nouveau fichier candidatures.csv créé.")
            
    return seen_links

def save_to_csv(company: str, title: str, status: str, link: str, email_text: str):
    date_du_jour = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(CSV_FILENAME, mode='a', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([date_du_jour, company, title, status, link, email_text])

def read_candidate_profile() -> str:
    try:
        with open("candidate.md", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        logging.error("ÉCHEC FATAL : Le fichier candidate.md est introuvable.")
        return ""

# --- NOUVELLE LOGIQUE FRANCE TRAVAIL ---
def get_ft_token(client_id, client_secret):
    url = "https://entreprise.francetravail.fr/connexion/oauth2/access_token"
    data = {
        "grant_type": "client_credentials",
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "api_offresdemploi_v2f rechercheroffresdemploi"
    }
    response = requests.post(url, data=data)
    response.raise_for_status()
    return response.json()["access_token"]

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def fetch_jobs_via_ft(token, seen_links: set) -> list[dict]:
    logging.info("Recherche via API France Travail V2...")
    url = "https://api.francetravail.io/partenaire/offresdemploi/v2/offres/search"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    params = {"motsCles": "DevOps", "typeContrat": "ALT", "range": "0-19"}
    
    response = requests.get(url, headers=headers, params=params)
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
    logging.info("Étape 1 : Recherche d'offres sur Adzuna...")
    url = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
    params = {
        'app_id': app_id,
        'app_key': app_key,
        'results_per_page': 20,
        'what': 'devops alternance',
        'where': 'france',
        'sort_by': 'date',
        'max_days_old': 3,
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
        
        texte_a_verifier = f"{job_title} {job_summary} {company}".lower()
        if any(mot in texte_a_verifier for mot in mots_interdits):
            logging.info(f"Filtre Anti-École : {company} ignorée.")
            continue 
            
        real_jobs.append({
            "texte_pour_ia": f"Titre : {job_title}\nEntreprise : {company}\nDescription : {job_summary}",
            "lien_direct": job_link,
            "titre": job_title,
            "entreprise": company
        })
    return real_jobs

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def analyze_with_ai(job_data: dict, candidate_profile: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    
    system_prompt = """Tu es un expert en recrutement DevOps. 
    1. Calcule un score de matching (0-100%).
    2. Si < 70%, réponds "STATUT: REJETE".
    3. Si >= 70%, réponds "STATUT: VALIDE" suivi d'un email de motivation pro.
    4. INSTRUCTION : Mentionne impérativement le rythme "3 semaines en entreprise et 1 semaine à l'école".
    5. Termine par : "Vous trouverez mon CV détaillé en pièce jointe."
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
        try:
            token = get_ft_token(ft_id, ft_secret)
            jobs_to_process.extend(fetch_jobs_via_ft(token, seen_links))
        except Exception as e:
            logging.error(f"Échec récupération France Travail : {e}")
    
    jobs_to_process = jobs_to_process[:20] # Augmenté à 20 pour intégrer 2 sources
    
    for job_data in jobs_to_process:
        logging.info(f"Traitement : {job_data['titre']}")
        
        try:
            result = analyze_with_ai(job_data, candidate_profile, anthropic_key)
        except Exception:
            result = "STATUT: REJETE"

        is_valid = "STATUT: VALIDE" in result
        email_content = result.split("STATUT: VALIDE")[1].strip() if is_valid else ""
        
        save_to_csv(
            company=job_data['entreprise'],
            title=job_data['titre'],
            status="VALIDE" if is_valid else "REJETE",
            link=job_data['lien_direct'],
            email_text=email_content
        )
        logging.info(f"Stockage réussi : {job_data['entreprise']}")

    logging.info("Pipeline terminé.")

if __name__ == "__main__":
    main()