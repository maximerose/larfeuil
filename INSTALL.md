# 🚀 Guide d'installation (Nouveau poste de développement)

Ce guide détaille les étapes pour configurer l'environnement de développement local du projet **Larfeuil** sur une nouvelle machine. Il est optimisé pour les environnements Linux (Ubuntu/Mint) tout en restant applicable à macOS et Windows.

## 1. Prérequis Système
Assurez-vous d'avoir installé les outils suivants sur votre machine locale :
* **Git**
* **Docker** & **Docker Compose**
* **Python 3.11+** (nécessaire pour l'environnement virtuel de l'IDE)
* **Node.js 22+** et **npm** (nécessaires pour la compilation Tailwind CSS)

> **Note pour les utilisateurs Linux :** Ajoutez votre utilisateur au groupe `docker` pour éviter d'utiliser `sudo` à chaque commande (`sudo usermod -aG docker $USER`, puis redémarrez votre session).

## 2. Configuration du Projet & Docker
L'application principale et la base de données s'exécutent de manière isolée via Docker.

1. **Cloner le dépôt :**
   ```bash
   git clone https://github.com/maximerose/larfeuil.git
   cd larfeuil
   ```
2. **Configurer les variables d'environnement :**
   ```bash
   cp .env.example .env
   ```
   Ouvrez le fichier `.env` et complétez les valeurs manquantes (notamment `DJANGO_SUPERUSER_PASSWORD` et `DJANGO_LAURIE_PASSWORD`).
   *Sous Linux, ajoutez votre UID/GID pour garantir que les fichiers générés par Docker vous appartiennent :*
   ```bash
   echo "UID=$(id -u)" >> .env
   echo "GID=$(id -g)" >> .env
   ```
3. **Lancer les conteneurs et initialiser la base de données :**
   ```bash
   docker compose up -d --build
   docker compose exec app python manage.py migrate
   ```
4. **Importer les données initiales (optionnel) :**
   ```bash
   docker compose exec app python manage.py import_history_csv
   ```

## 3. Configuration de l'IDE (VS Code) & Pre-commit
Bien que l'application s'exécute dans Docker, un environnement Python local est indispensable pour l'autocomplétion (Pylance) et le formatage automatique.

1. **Créer et activer l'environnement virtuel local :**
   ```bash
   python3 -m venv .venv
   source .venv/bin/activate
   ```
2. **Installer les dépendances locales :**
   ```bash
   pip install -r requirements.txt
   pip install pre-commit
   ```
3. **Activer les hooks Git :**
   ```bash
   pre-commit install
   ```
4. **Connecter VS Code :** Faites `Ctrl+Shift+P` > *Python: Select Interpreter* > Choisissez l'interpréteur situé dans `./.venv/bin/python`.

## 4. Front-end (Tailwind CSS) & Outils NPM
La compilation des fichiers CSS (Tailwind) est gérée localement par Node.js pour assurer un rechargement rapide pendant le développement.

1. **Installer les dépendances Node du projet :**
   ```bash
   npm install
   ```
2. **Lancer le watcher Tailwind en tâche de fond :**
   ```bash
   npm run tailwind:watch
   ```

**Dépannage NPM (Erreurs `EACCES` sous Linux) :**
Pour installer des outils globaux (comme `repomix` ou `tailwindcss`) sans utiliser `sudo`, configurez un répertoire NPM local à votre utilisateur :
```bash
mkdir ~/.npm-global
npm config set prefix '~/.npm-global'
echo 'export PATH=~/.npm-global/bin:$PATH' >> ~/.bashrc
source ~/.bashrc
```
*(Si une installation NPM reste bloquée sur `idealTree`, désactivez l'IPv6 temporairement avec `npm config set registry http://registry.npmjs.org/`)*.
