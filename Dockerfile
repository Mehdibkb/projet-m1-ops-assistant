# Image de base allégée
FROM python:3.12.3-slim

# Création de l'utilisateur non-root en premier
# -m : create home directory
RUN useradd -m mehdi

# Définition du répertoire de travail
WORKDIR /usr/local/mon_script/src

# Installation des dépendances
# On copie d'abord SEULEMENT le requirements.txt pour optimiser le cache Docker
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Création du dossier src et attribution des droits
# Il faut que le dossier LUI-MÊME appartienne à mehdi pour qu'il puisse y créer des fichiers (comme le CSV)
RUN mkdir -p src && chown mehdi:mehdi src

# Copie du code source avec attribution des droits à notre utilisateur
# -chown=mehdi:mehdi : on donne la propriété des fichiers à "mehdi"
COPY --chown=mehdi:mehdi main.py candidate.md ./

# On crée un dossier isolé uniquement pour la donnée persistante
RUN mkdir -p /data && chown mehdi:mehdi /data

# lien symbolique : quand Python lira/écrira candidatures.csv, 
# il sera redirigé silencieusement vers le dossier /data
RUN ln -s /data/candidatures.csv /usr/local/mon_script/src/candidatures.csv

# On bascule sur l'utilisateur sécurisé
USER mehdi

# Lancement du script

CMD ["python", "main.py"]

# Build the image

## docker build -t assistant-recherche-alternance:latest .

# Run the container with the volume candidatures.csv (to save the CSV file)

## docker run --rm --env-file .env -v $(pwd)/candidatures.csv:/usr/local/mon_script/src/candidatures.csv assistant-recherche-alternance:latest