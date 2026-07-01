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

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def fetch_jobs_via_adzuna(app_id: str, app_key: str, seen_links: set) -> list[dict]:
    logging.info("Étape 1a : Recherche d'offres sur Adzuna...")
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
        logging.warning(f"Bégaiement du réseau (API Adzuna). Erreur: {e}")
        raise 

    real_jobs = []
    mots_interdits = ["école", "ecole", "formation", "campus", "bootcamp", "organisme de formation"]
    
    for job in data.get('results', []):
        job_link = job.get('redirect_url', 'Lien non disponible') 
        if job_link in seen_links:
            continue
            
        job_title = job.get('title', '')
        job_summary = job.get('description', '')
        company = job.get('company', {}).get('display_name', 'Inconnue')
        
        texte_a_verifier = f"{job_title} {job_summary}".lower()
        if any(mot in texte_a_verifier for mot in mots_interdits):
            continue 
            
        real_jobs.append({
            "texte_pour_ia": f"Titre : {job_title}\nEntreprise : {company}\nDescription : {job_summary}",
            "lien_direct": job_link,
            "titre": job_title,
            "entreprise": company
        })
    return real_jobs

@retry(stop=stop_after_attempt(3), wait=wait_fixed(5), reraise=True)
def fetch_jobs_via_lba(seen_links: set) -> list[dict]:
    logging.info("Étape 1b : Recherche d'offres sur La Bonne Alternance (API État)...")
    url = "https://labonnealternance.apprentissage.beta.gouv.fr/api/v1/jobs"
    
    # Codes ROME pour l'IT/DevOps, et géolocalisation autour de Rennes (100km)
    params = {
        "romes": "M1810,M1805", # Production SI et Développement
        "caller": "assistant-devops-mehdi",
        "latitude": 48.117266,  # Latitude Rennes
        "longitude": -1.677792, # Longitude Rennes
        "radius": 100,          # Rayon de 100km
        "sources": "matcha,offres" # Offres LBA + France Travail
    }
    
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logging.warning(f"Bégaiement du réseau (API LBA). Erreur: {e}")
        raise

    real_jobs = []
    mots_interdits = ["école", "ecole", "formation", "campus", "bootcamp", "organisme de formation"]
    
    # LBA renvoie deux listes : peJobs (France Travail) et matchas (LBA natif)
    all_results = data.get('peJobs', {}).get('results', []) + data.get('matchas', {}).get('results', [])
    
    for job in all_results:
        job_link = job.get('url', 'Lien non disponible')
        if job_link in seen_links or job_link == 'Lien non disponible':
            continue
            
        job_title = job.get('title', '')
        company = job.get('company', {}).get('name', 'Inconnue')
        
        # LBA structure parfois la description différemment selon la source
        job_summary = job.get('description', '')
        if not job_summary and 'job' in job:
            job_summary = job['job'].get('description', '')

        texte_a_verifier = f"{job_title} {job_summary}".lower()
        if any(mot in texte_a_verifier for mot in mots_interdits):
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
    
    system_prompt = """Tu es un expert implacable en recrutement DevOps.
    Règles strictes :
    1. Calcule un pourcentage de matching réel entre le CV et l'offre.
    2. Si < 70%, écris UNIQUEMENT "STATUT: REJETE".
    3. Si >= 70%, écris "STATUT: VALIDE". 
    4. Rédige ensuite un e-mail de motivation court (3-4 phrases MAX) très percutant. 
    5. INSTRUCTION CRUCIALE : Tu dois obligatoirement mentionner le rythme "3 semaines en entreprise et 1 semaine à l'école".
    6. Termine l'e-mail par : "Vous trouverez mon CV détaillé en pièce jointe."
    """

    user_prompt = f"PROFIL DU CANDIDAT :\n{candidate_profile}\n\nOFFRE D'EMPLOI :\n{job_data['texte_pour_ia']}"

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}]
        )
        return response.content[0].text
    except Exception as e:
        logging.warning(f"Bégaiement de l'IA. Erreur: {e}")
        raise

def main():
    logging.info("Démarrage du Super-Pipeline (Adzuna + La Bonne Alternance).")
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

    # 1. Collecte Multi-Sources
    jobs_to_process = []
    try:
        jobs_to_process.extend(fetch_jobs_via_adzuna(adzuna_id, adzuna_key, seen_links))
        jobs_to_process.extend(fetch_jobs_via_lba(seen_links))
    except Exception:
        logging.error("Échec de la récupération sur l'une des APIs.")
    
    # 2. Gestion FinOps : On limite à 10 nouvelles offres max par exécution
    jobs_to_process = jobs_to_process[:10]
    logging.info(f"Nombre total de nouvelles offres à analyser par l'IA : {len(jobs_to_process)}")
    
    if jobs_to_process:
        for index, job_data in enumerate(jobs_to_process):
            logging.info(f"\n{'='*50}\n🔎 OFFRE {index + 1} : {job_data['titre']} ({job_data['entreprise']})")
            
            try:
                result = analyze_with_ai(job_data, candidate_profile, anthropic_key)
            except Exception:
                logging.error(f"Échec de l'analyse IA pour cette offre.")
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
        logging.info("Aucune nouvelle offre à traiter. Ton pipeline est à jour !")

if __name__ == "__main__":
    main()