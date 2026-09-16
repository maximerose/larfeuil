import os
import subprocess

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def deploy_webhook(request):
    token = request.GET.get("token")
    if token != os.environ.get("SECRET_KEY"):
        return HttpResponseForbidden("Token invalide.")

    base_dir = settings.BASE_DIR
    # Chemin absolu vers le python du venv o2switch
    python_bin = "/home2/yehe6737/virtualenv/larfeuil.maximerose.com/3.11/bin/python"

    try:
        # 1. Pull le dernier code
        subprocess.run(["git", "pull", "origin", "main"], cwd=base_dir, check=True)

        # 2. Installer d'éventuelles nouvelles dépendances
        subprocess.run(
            [python_bin, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=base_dir,
            check=True,
        )

        # 3. Exécuter les migrations MySQL
        subprocess.run(
            [python_bin, "manage.py", "migrate", "--noinput"],
            cwd=base_dir,
            check=True,
        )

        # 4. Recharger Phusion Passenger
        subprocess.run(["touch", "tmp/restart.txt"], cwd=base_dir, check=True)

        return HttpResponse("Déploiement réussi !", status=200)

    except subprocess.CalledProcessError as e:
        return HttpResponse(f"Erreur lors du déploiement : {e}", status=500)
