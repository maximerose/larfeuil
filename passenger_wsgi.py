import os
import sys

from django.core.wsgi import get_wsgi_application
from dotenv import load_dotenv

# 1. Chemins du projet et du virtualenv
project_dir = "/home2/yehe6737/larfeuil.maximerose.com"
venv_site_packages = "/home2/yehe6737/virtualenv/larfeuil.maximerose.com/3.11/lib/python3.11/site-packages"

# Inscription des dossiers dans le sys.path de Python
if project_dir not in sys.path:
    sys.path.insert(0, project_dir)
if venv_site_packages not in sys.path:
    sys.path.insert(0, venv_site_packages)

# 2. Chargement des variables d'environnement du .env
load_dotenv(os.path.join(project_dir, ".env"))

# 3. Déclaration du module de configuration Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")

# 4. Chargement de l'application WSGI
application = get_wsgi_application()
