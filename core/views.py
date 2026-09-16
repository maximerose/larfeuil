import subprocess

from django.conf import settings
from django.http import HttpResponse, HttpResponseForbidden
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def deploy_webhook(request):
    token = request.GET.get("token")
    # Vérification du token secret via la SECRET_KEY Django
    if not token or token != settings.SECRET_KEY:
        return HttpResponseForbidden("Accès refusé")

    try:
        # Répertoire du projet
        project_dir = "/home2/yehe6737/larfeuil.maximerose.com"

        # Commandes exécutées localement sur o2switch
        subprocess.run(["git", "pull", "origin", "main"], cwd=project_dir, check=True)
        subprocess.run(
            [
                "/home2/yehe6737/virtualenv/larfeuil.maximerose.com/3.11/bin/python",
                "manage.py",
                "migrate",
                "--noinput",
            ],
            cwd=project_dir,
            check=True,
        )
        subprocess.run(
            [
                "/home2/yehe6737/virtualenv/larfeuil.maximerose.com/3.11/bin/python",
                "manage.py",
                "collectstatic",
                "--noinput",
            ],
            cwd=project_dir,
            check=True,
        )

        # Redémarrage de l'application Python Passenger
        subprocess.run(["touch", "tmp/restart.txt"], cwd=project_dir, check=True)

        return HttpResponse("Déploiement réussi !")
    except subprocess.CalledProcessError as e:
        return HttpResponse(
            f"Erreur lors de l'exécution de la commande : {e}", status=500
        )
