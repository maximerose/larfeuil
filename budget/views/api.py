import json

from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.db import Error as DatabaseError
from django.http import JsonResponse

from budget.models import Category
from budget.models.category import CategoryType


@login_required
def api_create_element_view(request):
    if request.method == "POST":
        try:
            data = json.loads(request.body)
            elem_type = data.get("type")
            value = data.get("value")

            if not elem_type or not value:
                return JsonResponse({"error": "Données invalides"}, status=400)

            # --- CRÉATION DE CATÉGORIE À LA VOLÉE ---
            if elem_type == "category":
                name_clean = value.strip()

                # Sécurité anti-doublon
                if Category.objects.filter(
                    household=request.household, name__iexact=name_clean
                ).exists():
                    return JsonResponse(
                        {"error": "Cette catégorie existe déjà."}, status=400
                    )

                # L'utilisateur pourra toujours la requalifier dans ses paramètres
                category = Category.objects.create(
                    name=value.strip(),
                    type=CategoryType.VARIABLE,
                    household=request.household,
                    created_by=request.user,
                )
                return JsonResponse({"id": str(category.id), "text": category.name})

            return JsonResponse({"error": "Type inconnu"}, status=400)

        except json.JSONDecodeError:
            return JsonResponse({"error": "Format JSON invalide"}, status=400)
        except ValidationError as e:
            # e.messages est une liste des erreurs de validation
            return JsonResponse(
                {"error": f"Erreur de validation: {', '.join(e.messages)}"}, status=400
            )
        except DatabaseError:
            return JsonResponse(
                {"error": "Erreur lors de l'enregistrement en base de données"},
                status=500,
            )

    return JsonResponse({"error": "Méthode non autorisée"}, status=405)
