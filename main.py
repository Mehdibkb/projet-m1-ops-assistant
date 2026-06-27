import os
import logging
import requests
import csv
from datetime import datetime
from dotenv import load_dotenv
import anthropic
# NOUVEL IMPORT POUR LA RÉSILIENCE
from tenacity import retry, stop_after_attempt, wait_fixed

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

CSV_FILENAME = "candidatures.csv"

def init_csv_and_load_memory() -> set:
    """Crée le fichier CSV s'il n'existe pas et charge en mémoire les liens déjà traités."""
    seen_links = set()
    file_exists = os.path.isfile(CSV_FILENAME)
    
    if file_exists:
        with open(CSV_FILENAME, mode='r', encoding='utf-8') as file:
            reader = csv.DictReader(file)
            for row in reader:
                seen_links.add(row.get("Lien", ""))
        logging.info(f"Mémoire chargée : {len(seen_links)} offres déjà traitées dans le passé.")
    else:
        with open(CSV_FILENAME, mode='w', encoding='utf-8', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Date", "Entreprise", "Titre", "Statut", "Lien", "Email_Genere"])
        logging.info("Nouveau fichier candidatures.csv créé.")
            
    return seen_links

def save_to_csv(company: str, title: str, status: str, link: str, email_text: str):
    """Sauvegarde une offre validée et son e-mail dans le fichier CSV."""
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

# RÉSILIENCE : Si la fonction "raise" une erreur, elle attend 5 secondes et réessaie (max 3 fois)
@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def fetch_jobs_via_api(app_id: str, app_key: str, seen_links: set) -> list[dict]:
    """Récupère jusqu'à 10 offres NOUVELLES via l'API Adzuna avec système Anti-Crash."""
    logging.info("Étape 1 : Recherche d'offres fraîches sur Adzuna...")
    
    url = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
    
    params = {
        'app_id': app_id,
        'app_key': app_key,
        'results_per_page': 30,
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
        logging.warning(f"Bégaiement du réseau (API Adzuna). Tentative de reconnexion... Erreur: {e}")
        raise # Cela déclenche le @retry de tenacity

    real_jobs = []
    mots_interdits = ["école", "ecole", "formation", "campus", "bootcamp", "organisme de formation"]
    results = data.get('results', [])
    
    for job in results:
        if len(real_jobs) >= 10:
            break
            
        job_title = job.get('title', '')
        job_summary = job.get('description', '')
        job_link = job.get('redirect_url', 'Lien non disponible') 
        company = job.get('company', {}).get('display_name', 'Inconnue')
        
        if job_link in seen_links:
            continue
            
        texte_a_verifier = f"{job_title} {job_summary}".lower()
        if any(mot in texte_a_verifier for mot in mots_interdits):
            continue 
            
        formatted_job = f"""
        Titre : {job_title}
        Entreprise : {company}
        Description : {job_summary}
        """
        
        real_jobs.append({
            "texte_pour_ia": formatted_job,
            "lien_direct": job_link,
            "titre": job_title,
            "entreprise": company
        })
        
    return real_jobs

# RÉSILIENCE : Protège contre les micro-coupures de l'API Anthropic
@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def analyze_with_ai(job_data: dict, candidate_profile: str, api_key: str) -> str:
    client = anthropic.Anthropic(api_key=api_key)
    
    # OPTIMISATION CLAUDE : Séparation du SYSTEM (Les règles) et du USER (La donnée)
    system_prompt = """Tu es un expert implacable en recrutement DevOps.
    Règles strictes :
    1. Calcule un pourcentage de matching réel entre le CV et l'offre.
    2. Si < 70%, écris UNIQUEMENT "STATUT: REJETE".
    3. Si >= 70%, écris "STATUT: VALIDE". 
    4. Rédige ensuite un e-mail de motivation court (3-4 phrases MAX) très percutant. 
    5. INSTRUCTION CRUCIALE : Tu dois obligatoirement mentionner le rythme "3 semaines en entreprise et 1 semaine à l'école".
    6. Termine l'e-mail par : "Vous trouverez mon CV détaillé en pièce jointe."
    """

    user_prompt = f"""
    PROFIL DU CANDIDAT :
    {candidate_profile}
    
    OFFRE D'EMPLOI :
    {job_data['texte_pour_ia']}
    """

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_prompt, # Injection du comportement global ici
            messages=[{"role": "user", "content": user_prompt}] # Données brutes ici
        )
        return response.content[0].text
    except Exception as e:
        logging.warning(f"Bégaiement de l'IA (API Anthropic). Tentative de reconnexion... Erreur: {e}")
        raise # Déclenche le @retry

def main():
    logging.info("Démarrage du pipeline de recherche automatisé.")
    load_dotenv()
    
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    adzuna_id = os.getenv("ADZUNA_APP_ID")
    adzuna_key = os.getenv("ADZUNA_APP_KEY")
    
    if not all([anthropic_key, adzuna_id, adzuna_key]):
        logging.error("ÉCHEC FATAL : Il manque une ou plusieurs clés dans le fichier .env.")
        return
        
    candidate_profile = read_candidate_profile()
    if not candidate_profile:
        return

    seen_links = init_csv_and_load_memory()

    try:
        jobs = fetch_jobs_via_api(adzuna_id, adzuna_key, seen_links)
    except Exception as e:
        logging.error("Échec définitif de la récupération des offres après 3 tentatives.")
        return
    
    if jobs:
        for index, job_data in enumerate(jobs):
            logging.info(f"\n{'='*50}\n🔎 OFFRE {index + 1} : {job_data['titre']} ({job_data['entreprise']})")
            
            try:
                result = analyze_with_ai(job_data, candidate_profile, anthropic_key)
            except Exception as e:
                logging.error(f"Échec définitif de l'analyse pour cette offre après 3 tentatives.")
                continue

            logging.info(f"\n{result}\n")
            
            if result and "STATUT: VALIDE" in result:
                try:
                    email_only = result.split("STATUT: VALIDE")[1].strip()
                except IndexError:
                    email_only = result
                    
                save_to_csv(job_data['entreprise'], job_data['titre'], "VALIDE", job_data['lien_direct'], email_only)
                logging.info(f" Candidature sauvegardée dans {CSV_FILENAME}")
            else:
                logging.info(f" Offre rejetée par l'IA.")
                save_to_csv(job_data['entreprise'], job_data['titre'], "REJETE", job_data['lien_direct'], "")
                
            logging.info("-" * 50)
    else:
        logging.info("Aucune nouvelle offre d'entreprise à traiter.")

if __name__ == "__main__":
    main()