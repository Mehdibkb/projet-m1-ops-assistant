import os
import logging
import requests
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
    """Récupère de VÉRITABLES offres d'emploi en contournant les anti-bots et en filtrant les écoles."""
    logging.info("Étape 1 : Récupération des offres en temps réel...")
    
    reliable_rss = "https://weworkremotely.com/categories/remote-devops-sysadmin-jobs.rss"
    
    # 1. Le déguisement (Spoofing du User-Agent) pour passer le pare-feu
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        # On télécharge le flux avec requests, puis on le donne à feedparser
        response = requests.get(reliable_rss, headers=headers, timeout=10)
        feed = feedparser.parse(response.content)

        # --- DEBUGGAGE ADZUNA ---
        logging.info(f"Code HTTP de la réponse Adzuna : {response.status_code}")
        logging.info(f"Nombre total d'offres trouvées dans le flux : {len(feed.entries)}")
        # -----------------------------
    except Exception as e:
        logging.error(f"Erreur lors de la connexion au flux RSS : {e}")
        return []

    real_jobs = []
    
    # 2. Le filtre anti-écoles (Mots-clés à exclure pour économiser les tokens API)
    mots_interdits = ["école", "ecole", "formation", "campus", "bootcamp", "étudiant recherché pour notre formation", "rejoins notre école"]

    # 3. Le filtre pro-alternance (Ce qu'on exige)
    mots_requis = ["alternance", "apprenti", "apprentissage", "professionnalisation", "france", "rennes", "paris"]
    
    # On parcourt les 10 premières offres
    for entry in feed.entries[:10]:
        job_title = entry.title
        job_summary = entry.summary
        job_link = entry.link
        
        # Vérification des mots interdits (en minuscules pour ne rien rater)
        texte_a_verifier = f"{job_title} {job_summary}".lower()
        if any(mot in texte_a_verifier for mot in mots_interdits):
            logging.warning(f"Offre ignorée (Détection d'école/formation) : {job_title}")
            continue # On passe directement à l'offre suivante

        # Filtre 2 : Est-ce bien une alternance ou en France ?
        # Si AUCUN des mots requis n'est dans le texte, on rejette l'offre.
        if not any(mot in texte_a_verifier for mot in mots_requis):
            logging.warning(f"Offre ignorée (Hors scope / Pas d'alternance) : {job_title}")
            continue
        
        # Formatage de l'offre propre
        formatted_job = f"""
        Titre : {job_title}
        Lien : {job_link}
        Description courte : {job_summary}
        """
        real_jobs.append(formatted_job)
        logging.info(f"Offre valide trouvée et conservée : {job_title}")
        
    if not real_jobs:
        logging.warning("Aucune offre d'entreprise pure trouvée dans le flux RSS actuel après filtrage.")
        
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

    jobs = fetch_jobs()
    
    if jobs:
        for index, job in enumerate(jobs):
            logging.info(f"--- DÉBUT DE L'ANALYSE DE L'OFFRE {index + 1} ---")
            result = analyze_with_ai(job, candidate_profile, api_key)
            logging.info(f"\n{result}\n")
            logging.info(f"--- FIN DE L'ANALYSE DE L'OFFRE {index + 1} ---")

if __name__ == "__main__":
    main()