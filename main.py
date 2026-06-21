import os
import logging
from dotenv import load_dotenv
import anthropic

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
    """Simule la récupération d'une offre pour tester la logique de l'IA (Mocking)"""
    logging.info("Étape 1 : Récupération des offres (Mode Simulation activé)...")
    
    # Fausse offre d'emploi parfaitement taillée pour tester mon profil
    dummy_job = """
    Titre : Alternance Ingénieur DevOps (H/F)
    Entreprise : TechCorp France
    Description : Nous recherchons un alternant pour rejoindre notre équipe infrastructure.
    Missions : Déploiement de pipelines CI/CD, conteneurisation des applications.
    Stack requise : Docker, Kubernetes, Jenkins, GitLab CI, AWS, Terraform.
    Rythme souhaité : 3 semaines entreprise / 1 semaine école.
    """
    return [dummy_job]

def analyze_with_ai(job_description, candidate_profile, api_key):
    """Envoie l'offre et le profil à Claude pour validation."""
    logging.info("Étape 2 : Analyse de l'offre par Claude...")
    
    # Initialisation du client Anthropic
    client = anthropic.Anthropic(api_key=api_key)
    
    # Le Prompt (Les instructions strictes de l'agent)
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
    Sois concis et direct.
    """

    try:
        # Appel à l'API (Utilisation du modèle successeur)
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
        
    # 1. Lecture du profil
    candidate_profile = read_candidate_profile()
    if not candidate_profile:
        return

    # 2. Récupération des offres (fausses pour le moment)
    jobs = fetch_jobs()
    
    # 3. Analyse
    for job in jobs:
        result = analyze_with_ai(job, candidate_profile, api_key)
        logging.info(f"--- RÉSULTAT DE L'ANALYSE ---\n{result}\n-----------------------------")

if __name__ == "__main__":
    main()