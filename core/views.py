import subprocess

from django.conf import settings
from django.http import HttpResponseForbidden, JsonResponse
from django.views.decorators.csrf import csrf_exempt


@csrf_exempt
def deploy_webhook(request):
    # 1. Vérification du token d'accès
    token = request.GET.get("token")
    if not token or token != settings.SECRET_KEY:
        return HttpResponseForbidden("Token invalide ou manquant.")

    # 2. Lancement du script détaché
    try:
        subprocess.Popen(
            ["/bin/bash", "/home2/yehe6737/larfeuil.maximerose.com/deploy.sh"],
            cwd="/home2/yehe6737/larfeuil.maximerose.com",
            start_new_session=True,
        )
        return JsonResponse(
            {"status": "ok", "message": "Déploiement démarré en arrière-plan."},
            status=200,
        )
    except (OSError, subprocess.SubprocessError) as e:
        return JsonResponse({"status": "error", "message": str(e)}, status=500)
