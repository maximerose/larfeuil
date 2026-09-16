import os
import sys

# Ajout du dossier du projet au path
sys.path.insert(0, os.path.dirname(__file__))

# Remplace "config" par le nom du dossier de ton projet Django s'il s'appelle autrement (ex: budget.settings)
os.environ["DJANGO_SETTINGS_MODULE"] = "config.settings"
