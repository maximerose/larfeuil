import os
import subprocess
import threading

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt


def run_deployment(base_dir, python_bin):
    """Exécute le déploiement en tâche de fond pour ne pas bloquer HTTP."""
    try:
        # 1. Pull le dernier code
        subprocess.run(["git", "pull", "origin", "main"], cwd=base_dir, check=True)

        # 2. Installer les dépendances
        subprocess.run(
            [python_bin, "-m", "pip", "install", "-r", "requirements.txt"],
            cwd=base_dir,
            check=True,
        )

        # 3. Exécuter les migrations
        subprocess.run(
            [python_bin, "manage.py", "migrate", "--noinput"],
            cwd=base_dir,
            check=True,
        )

        # 4. Rassembler les fichiers statiques (Tailwind)
        subprocess.run(
            [
                python_bin,
                "manage.py",
                "collectstatic",
                "--noinput",
                "--ignore",
                "input.css",
            ],
            cwd=base_dir,
            check=True,
        )

        # 5. Recharger Passenger
        subprocess.run(["touch", "tmp/restart.txt"], cwd=base_dir, check=True)

    except (subprocess.CalledProcessError, OSError) as e:
        print(f"Erreur lors du déploiement en tâche de fond : {e}")


@csrf_exempt
def deploy_webhook(request):
    token = request.GET.get("token")
    if token != os.environ.get("SECRET_KEY"):
        return HttpResponseForbidden("Token invalide.")

    base_dir = settings.BASE_DIR
    python_bin = "/home2/yehe6737/virtualenv/larfeuil.maximerose.com/3.11/bin/python"

    # Lance le processus dans un thread séparé
    thread = threading.Thread(target=run_deployment, args=(base_dir, python_bin))
    thread.start()

    # Répond immédiatement à GitHub (évite la 503 pour timeout)
    return HttpResponse("Déploiement initialisé avec succès !", status=200)
