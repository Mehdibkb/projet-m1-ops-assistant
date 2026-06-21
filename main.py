import os
import logging
from dotenv import load_dotenv
import anthropic
import feedparser

# Configuration des logs
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

def read_candidate_profile():
    """Lit le contenu du candidate.md"""
    try:
        with open("candidate.md", "r", encoding="utf-8") as file:
            return file.read()
    except FileNotFoundError:
        logging.error("ÉCHEC FATAL : Le fichier candidate.md est introuvable.")
        return None

def fetch_jobs():
    """Récupère de VÉRITABLES offres d'emploi via un flux RSS public"""
    logging.info("Étape 1 : Récupération des offres en temps réel (via Flux RSS)...")
    
    # URL d'un flux RSS d'offres d'emploi. 
    # On utilise un flux public pour contourner les protections anti-bot complexes
    rss_url = "https://www.wizbii.com/company/wizbii/jobs.rss" # Exemple de flux (à remplacer par la suite par un plus spécifique si besoin)
    
    # Pour un test DevOps pertinent, simulons la recherche sur un agrégateur orienté tech ou alternance.
    # Adzuna propose des flux RSS très propres. Cherchons "DevOps Alternance"
    adzuna_rss = "https://www.adzuna.fr/search/jobs.rss?q=devops+alternance"
    
    feed = feedparser.parse(adzuna_rss)
    real_jobs = []
    
    # On limite à 3 offres pour ne pas exploser la consommation de l'API Anthropic lors des tests
    for entry in feed.entries[:3]:
        job_title = entry.title
        job_summary = entry.summary
        job_link = entry.link
        
        # On formate l'offre pour que Claude puisse la lire facilement
        formatted_job = f"""
        Titre : {job_title}
        Lien : {job_link}
        Description courte : {job_summary}
        """
        real_jobs.append(formatted_job)
        logging.info(f"Offre trouvée : {job_title}")
        
    if not real_jobs:
        logging.warning("Aucune offre trouvée dans le flux RSS actuel.")
        
    return real_jobs

def analyze_with_ai(job_description, candidate_profile, api_key):
    """Envoie l'offre et le profil à Claude pour validation."""
    logging.info("Étape 2 : Analyse de l'offre par Claude...")
    
    client = anthropic.Anthropic(api_key=api_key)
    
    prompt = f"""
    Tu es un expert en recrutement IT. Ton rôle est d'analyser une offre d'emploi et de déterminer si elle correspond au profil du candidat.
    
    PROFIL DU CANDIDAT :
    {candidate_profile}
    
    OFFRE D'EMPLOI :
    {job_description}
    
    Règles de sortie obligatoires :
    1. Calcule un pourcentage de correspondance (matching).
    2. Si le matching est supérieur ou égal à 70%, écris "STATUT: VALIDE". Sinon, écris "STATUT: REJETE".
    3. Résume l'analyse avec 2 points de correspondances forts et 1 point d'attention éventuel.
    Sois concis et direct. Ne donne pas de conseils généraux.
    """

    try:
        response = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            messages=[
                {"role": "user", "content": prompt}
            ]
        )
        return response.content[0].text
    except Exception as e:
        logging.error(f"Erreur lors de l'appel à l'API Anthropic : {e}")
        return None

def main():
    logging.info("Démarrage du pipeline de recherche automatisé.")
    
    load_dotenv()
    api_key = os.getenv("ANTHROPIC_API_KEY")
    
    if not api_key or api_key == "ma-cle-secrete":
        logging.error("ÉCHEC FATAL : Clé API Anthropic introuvable ou non configurée.")
        return
        
    candidate_profile = read_candidate_profile()
    if not candidate_profile:
        return

    # Récupération des VRAIES offres
    jobs = fetch_jobs()
    
    if jobs:
        # Analyse de chaque vraie offre trouvée
        for index, job in enumerate(jobs):
            logging.info(f"--- DÉBUT DE L'ANALYSE DE L'OFFRE {index + 1} ---")
            result = analyze_with_ai(job, candidate_profile, api_key)
            logging.info(f"\n{result}\n")
            logging.info(f"--- FIN DE L'ANALYSE DE L'OFFRE {index + 1} ---")

if __name__ == "__main__":
    main()