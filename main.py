import os
import logging
import requests
from dotenv import load_dotenv
import anthropic

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def read_candidate_profile():
    try:
        with open("candidate.md", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        logging.error("ÉCHEC FATAL : Le fichier candidate.md est introuvable.")
        return None

def fetch_jobs_via_api(app_id, app_key):
    """Récupère des offres d'emploi françaises via l'API REST officielle d'Adzuna."""
    logging.info("Étape 1 : Interrogation de l'API Adzuna (100% Fiable)...")
    
    # Endpoint officiel pour la France (fr)
    url = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
    
    # Les paramètres précis de ta recherche métier
    params = {
        'app_id': app_id,
        'app_key': app_key,
        'results_per_page': 5,      # On limite à 5 offres pour tester
        'what': 'devops alternance', # Les mots clés
        'where': 'france',          # Le pays
        'content-type': 'application/json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        # Si Adzuna renvoie une erreur (ex: mauvaises clés), le script l'attrape ici
        response.raise_for_status() 
        data = response.json()
    except Exception as e:
        logging.error(f"Erreur de connexion à l'API Adzuna : {e}")
        return []

    real_jobs = []
    mots_interdits = ["école", "ecole", "formation", "campus", "bootcamp", "organisme de formation"]
    
    results = data.get('results', [])
    logging.info(f"Nombre d'offres renvoyées par l'API : {len(results)}")
    
    for job in results:
        job_title = job.get('title', '')
        job_summary = job.get('description', '')
        job_link = job.get('redirect_url', '')
        company = job.get('company', {}).get('display_name', 'Inconnue')
        
        texte_a_verifier = f"{job_title} {job_summary}".lower()
        
        # Filtre anti-écoles conservé
        if any(mot in texte_a_verifier for mot in mots_interdits):
            logging.warning(f"Offre ignorée (Détection école) : {job_title} chez {company}")
            continue 
            
        formatted_job = f"""
        Titre : {job_title}
        Entreprise : {company}
        Lien pour postuler : {job_link}
        Description : {job_summary}
        """
        real_jobs.append(formatted_job)
        logging.info(f" Offre VALIDE conservée : {job_title} ({company})")
        
    return real_jobs

def analyze_with_ai(job_description, candidate_profile, api_key):
    logging.info("Étape 2 : Analyse et rédaction par Claude...")
    client = anthropic.Anthropic(api_key=api_key)
    
    prompt = f"""
    Tu es un assistant IA de recherche d'emploi.
    
    PROFIL DU CANDIDAT :
    {candidate_profile}
    
    OFFRE D'EMPLOI :
    {job_description}
    
    Mission :
    1. Calcule un pourcentage de matching.
    2. Si < 70%, écris juste "STATUT: REJETE".
    3. Si >= 70%, écris "STATUT: VALIDE". Puis, rédige un court e-mail de motivation (3 phrases max) très percutant que le candidat pourra copier-coller pour postuler à cette offre, en mettant en avant ses compétences Cloud/DevOps.
    """

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=400,
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        logging.error(f"Erreur Anthropic : {e}")
        return None

def main():
    logging.info("Démarrage du pipeline de recherche automatisé.")
    load_dotenv()
    
    # Récupération des 3 clés sécurisées
    anthropic_key = os.getenv("ANTHROPIC_API_KEY")
    adzuna_id = os.getenv("ADZUNA_APP_ID")
    adzuna_key = os.getenv("ADZUNA_APP_KEY")
    
    if not all([anthropic_key, adzuna_id, adzuna_key]):
        logging.error("ÉCHEC FATAL : Il manque une ou plusieurs clés dans le fichier .env.")
        return
        
    candidate_profile = read_candidate_profile()
    if not candidate_profile:
        return

    jobs = fetch_jobs_via_api(adzuna_id, adzuna_key)
    
    if jobs:
        for index, job in enumerate(jobs):
            logging.info(f"--- ANALYSE DE L'OFFRE {index + 1} ---")
            result = analyze_with_ai(job, candidate_profile, anthropic_key)
            logging.info(f"\n{result}\n")
            logging.info("-" * 30)

if __name__ == "__main__":
    main()