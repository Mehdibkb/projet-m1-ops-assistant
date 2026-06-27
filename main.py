import os
import logging
import requests
import csv
from datetime import datetime
from dotenv import load_dotenv
import anthropic

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

CSV_FILENAME = "candidatures.csv"

def init_csv_and_load_memory():
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
        # Création du fichier et de l'en-tête (colonnes)
        with open(CSV_FILENAME, mode='w', encoding='utf-8', newline='') as file:
            writer = csv.writer(file)
            writer.writerow(["Date", "Entreprise", "Titre", "Statut", "Lien", "Email_Genere"])
        logging.info("Nouveau fichier candidatures.csv créé.")
            
    return seen_links

def save_to_csv(company, title, status, link, email_text):
    """Sauvegarde une offre validée et son e-mail dans le fichier CSV."""
    date_du_jour = datetime.now().strftime("%Y-%m-%d %H:%M")
    with open(CSV_FILENAME, mode='a', encoding='utf-8', newline='') as file:
        writer = csv.writer(file)
        writer.writerow([date_du_jour, company, title, status, link, email_text])

def read_candidate_profile():
    try:
        with open("candidate.md", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        logging.error("ÉCHEC FATAL : Le fichier candidate.md est introuvable.")
        return None

def fetch_jobs_via_api(app_id: str, app_key: str, seen_links: set) -> list[dict]:
    """Récupère jusqu'à 10 offres NOUVELLES via l'API Adzuna."""
    logging.info("Étape 1 : Recherche d'offres fraîches (Anti-doublons activé)...")
    
    url = "https://api.adzuna.com/v1/api/jobs/fr/search/1"
    
    # On demande 30 offres pour avoir un "buffer" et être sûr d'en trouver 10 nouvelles après filtrage
    params = {
        'app_id': app_id,
        'app_key': app_key,
        'results_per_page': 30,
        'what': 'devops alternance',
        'where': 'france',
        'sort_by': 'date',
        'max_days_old': 3, # On élargit un peu à 3 jours au cas où
        'content-type': 'application/json'
    }
    
    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status() 
        data = response.json()
    except Exception as e:
        logging.error(f"Erreur de connexion à l'API Adzuna : {e}")
        return []

    real_jobs = []
    mots_interdits = ["école", "ecole", "formation", "campus", "bootcamp", "organisme de formation"]
    results = data.get('results', [])
    
    for job in results:
        # Si on a trouvé nos 10 nouvelles offres, on arrête de chercher
        if len(real_jobs) >= 10:
            break
            
        job_title = job.get('title', '')
        job_summary = job.get('description', '')
        job_link = job.get('redirect_url', 'Lien non disponible') 
        company = job.get('company', {}).get('display_name', 'Inconnue')
        
        # Filtre Anti-Doublon (Est-ce que l'offre est déjà dans le CSV ?)
        if job_link in seen_links:
            continue
            
        # Filtre Anti-École
        texte_a_verifier = f"{job_title} {job_summary}".lower()
        if any(mot in texte_a_verifier for mot in mots_interdits):
            continue 
            
        formatted_job = f"""
        Titre : {job_title}
        Entreprise : {company}
        Lien pour postuler : {job_link}
        Description : {job_summary}
        """
        
        real_jobs.append({
            "texte_pour_ia": formatted_job,
            "lien_direct": job_link,
            "titre": job_title,
            "entreprise": company
        })
        
    logging.info(f"Nombre de NOUVELLES offres retenues pour analyse IA : {len(real_jobs)}")
    return real_jobs

def analyze_with_ai(job_data, candidate_profile, api_key):
    client = anthropic.Anthropic(api_key=api_key)
    
    # Prompt mis à jour avec la consigne stricte sur le rythme d'alternance
    prompt = f"""
    Tu es un assistant IA de recherche d'emploi.
    
    PROFIL DU CANDIDAT :
    {candidate_profile}
    
    OFFRE D'EMPLOI :
    {job_data['texte_pour_ia']}
    
    Mission :
    1. Calcule un pourcentage de matching (sois strict).
    2. Si < 70%, écris juste "STATUT: REJETE".
    3. Si >= 70%, écris "STATUT: VALIDE". 
    4. Rédige un e-mail de motivation court (3-4 phrases MAX) mettant en avant les outils DevOps du CV. 
    5. INSTRUCTION CRUCIALE : Tu dois obligatoirement mentionner mon rythme d'alternance ("3 semaines en entreprise et 1 semaine à l'école") dans l'e-mail.
    6. Termine obligatoirement l'e-mail par : "Vous trouverez mon CV détaillé en pièce jointe."
    """

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=600, # Augmenté pour éviter toute coupure
            messages=[{"role": "user", "content": prompt}]
        )
        return response.content[0].text
    except Exception as e:
        logging.error(f"Erreur Anthropic : {e}")
        return None

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

    # 1. Initialisation de la base de données CSV et lecture de la mémoire
    seen_links = init_csv_and_load_memory()

    # 2. Récupération des offres en filtrant les doublons
    jobs = fetch_jobs_via_api(adzuna_id, adzuna_key, seen_links)
    
    if jobs:
        for index, job_data in enumerate(jobs):
            logging.info(f"\n{'='*50}\n🔎 OFFRE {index + 1} : {job_data['titre']} ({job_data['entreprise']})")
            
            # 3. Analyse par l'IA
            result = analyze_with_ai(job_data, candidate_profile, anthropic_key)
            logging.info(f"\n{result}\n")
            
            # 4. Sauvegarde dans le CSV
            if result and "STATUT: VALIDE" in result:
                # Extraction basique de l'email pour le fichier CSV (on enlève l'en-tête de l'IA)
                try:
                    email_only = result.split("STATUT: VALIDE")[1].strip()
                except IndexError:
                    email_only = result
                    
                save_to_csv(
                    company=job_data['entreprise'],
                    title=job_data['titre'],
                    status="VALIDE",
                    link=job_data['lien_direct'],
                    email_text=email_only
                )
                logging.info(f"💾 Candidature sauvegardée dans {CSV_FILENAME}")
            else:
                logging.info(f"❌ Offre rejetée par l'IA, non sauvegardée.")
                # On sauvegarde quand même le lien pour ne pas la re-tester demain
                save_to_csv(job_data['entreprise'], job_data['titre'], "REJETE", job_data['lien_direct'], "")
                
            logging.info("-" * 50)
    else:
        logging.info("Aucune nouvelle offre d'entreprise à traiter.")

if __name__ == "__main__":
    main()