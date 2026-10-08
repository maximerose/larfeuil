import datetime
from typing import Any

from django.http import HttpRequest
from django.utils import timezone

from budget.utils import get_target_month_from_request


def global_budget_context(request: HttpRequest) -> dict[str, Any]:
    selected_date = get_target_month_from_request(request)
    today = timezone.localdate().replace(day=1)

    # Génération d'une fenêtre glissante autour du mois sélectionné (-6 mois à +6 mois)
    months_list = []
    months_names = [
        "Jan",
        "Fév",
        "Mar",
        "Avr",
        "Mai",
        "Juin",
        "Juil",
        "Août",
        "Sep",
        "Oct",
        "Nov",
        "Déc",
    ]

    for i in range(-6, 7):
        m = selected_date.month - 1 + i
        y = selected_date.year + m // 12
        m = m % 12 + 1
        dt = datetime.date(y, m, 1)

        months_list.append(
            {
                "url_value": f"{y}-{m:02d}",
                "label": f"{months_names[m - 1]} {y}",
                "is_active": (dt == selected_date),
                "is_current": (dt == today),
            }
        )

    resolver_match = getattr(request, "resolver_match", None)
    current_url_name = getattr(resolver_match, "url_name", "") if resolver_match else ""

    main_menu = [
        {
            "label": "Accueil",
            "url_name": "dashboard",
            "is_active": current_url_name == "dashboard",
            "icon": "home",
        },
        {
            "label": "Historique",
            "url_name": "monthly_history",
            "is_active": current_url_name == "monthly_history",
            "icon": "clipboard-document-list",
        },
        {
            "is_button": True,
            "icon": "plus",
        },
        {
            "label": "Prévisions",
            "url_name": "forecast_list",
            "is_active": current_url_name == "forecast_list",
            "icon": "chart-bar",
        },
        {
            "label": "Statistiques",
            "url_name": "statistics",
            "is_active": current_url_name == "statistics",
            "icon": "chart-pie",
        },
    ]

    return {
        "selected_month": selected_date,
        "budget_months_list": months_list,
        "main_menu": main_menu,
    }


def current_member(request: HttpRequest) -> dict[str, Any | None]:
    return {
        "current_member": getattr(request, "member", None),
        "household": getattr(request, "household", None),
    }
