import datetime
from decimal import Decimal, DecimalException
from urllib.request import Request

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from budget.models import (
    BankAccount,
    Category,
    MonthlyForecast,
    RecurringExpense,
)
from budget.models.account import AccountType
from budget.models.category import CategoryType
from core.models import Visibility


@login_required
def forecast_list_view(request: Request) -> HttpResponse:
    member = request.member
    household = request.household

    month_str = request.GET.get("month")
    selected_date = timezone.localdate().replace(day=1)

    if month_str:
        try:
            selected_date = datetime.date.fromisoformat(f"{month_str}-01")
        except ValueError:
            pass

    # Récupération de toutes les charges fixes (sans masquer celles qui ne sont pas dues)
    recurring_items = RecurringExpense.objects.filter(
        Q(owner=member) | Q(visibility=Visibility.SHARED),
        household=household,
        is_active=True,
    )

    # Calcul des montants par défaut attendus pour le mois sélectionné
    default_rec_amounts = {}
    for r in recurring_items:
        is_due = False
        if r.frequency_months == 1:
            is_due = True
        elif r.usual_due_day:
            start_month = r.usual_due_day.replace(day=1)
            if selected_date >= start_month:
                diff_months = (selected_date.year - start_month.year) * 12 + (
                    selected_date.month - start_month.month
                )
                if diff_months % r.frequency_months == 0:
                    is_due = True

        default_rec_amounts[str(r.id)] = r.total_amount if is_due else Decimal("0.00")

    # 1. Sauvegarde des prévisions (POST)
    if request.method == "POST":
        action = request.POST.get("action", "save")

        with transaction.atomic():
            if action == "save":
                for key, value in request.POST.items():
                    if not key.startswith(
                        ("forecast_cat_", "forecast_acc_", "forecast_rec_")
                    ):
                        continue

                    if value.strip() == "":
                        amount = Decimal("0.00")
                    else:
                        try:
                            amount = Decimal(value.replace(",", "."))
                        except (ValueError, TypeError, DecimalException):
                            continue

                    if key.startswith("forecast_cat_"):
                        cat_id = key.replace("forecast_cat_", "")
                        if amount == Decimal("0.00"):
                            MonthlyForecast.objects.filter(
                                month=selected_date, member=member, category_id=cat_id
                            ).delete()
                        else:
                            MonthlyForecast.objects.update_or_create(
                                month=selected_date,
                                member=member,
                                category_id=cat_id,
                                defaults={"amount": amount},
                            )

                    elif key.startswith("forecast_acc_"):
                        acc_id = key.replace("forecast_acc_", "")
                        if amount == Decimal("0.00"):
                            MonthlyForecast.objects.filter(
                                month=selected_date,
                                member=member,
                                bank_account_id=acc_id,
                            ).delete()
                        else:
                            MonthlyForecast.objects.update_or_create(
                                month=selected_date,
                                member=member,
                                bank_account_id=acc_id,
                                defaults={"amount": amount},
                            )

                    elif key.startswith("forecast_rec_"):
                        rec_id = key.replace("forecast_rec_", "")
                        default_val = default_rec_amounts.get(rec_id, Decimal("0.00"))

                        # Si on valide le montant exact prévu par défaut, on nettoie la base (pas besoin d'exception)
                        if amount == default_val:
                            MonthlyForecast.objects.filter(
                                month=selected_date,
                                member=member,
                                recurring_expense_id=rec_id,
                            ).delete()
                        else:
                            MonthlyForecast.objects.update_or_create(
                                month=selected_date,
                                member=member,
                                recurring_expense_id=rec_id,
                                defaults={"amount": amount},
                            )

            elif action == "replicate":
                try:
                    months_count = int(request.POST.get("replicate_months", 1))
                except ValueError:
                    months_count = 1

                current_forecasts = MonthlyForecast.objects.filter(
                    member=member, month=selected_date, is_active=True
                )

                for i in range(1, months_count + 1):
                    month_offset = selected_date.month - 1 + i
                    new_year = selected_date.year + month_offset // 12
                    new_month = month_offset % 12 + 1
                    target_month = datetime.date(new_year, new_month, 1)

                    for f in current_forecasts:
                        MonthlyForecast.objects.update_or_create(
                            month=target_month,
                            member=f.member,
                            category=f.category,
                            bank_account=f.bank_account,
                            recurring_expense=f.recurring_expense,
                            defaults={"amount": f.amount, "visibility": f.visibility},
                        )

        return redirect(f"{request.path}?month={selected_date.strftime('%Y-%m')}")

    # 2. Chargement des données existantes (Filtrées sur le membre actif)
    existing_forecasts = MonthlyForecast.objects.filter(
        member=member, month=selected_date, is_active=True
    )

    cat_map = {f.category_id: f.amount for f in existing_forecasts if f.category_id}
    acc_map = {
        f.bank_account_id: f.amount for f in existing_forecasts if f.bank_account_id
    }
    rec_map = {
        f.recurring_expense_id: f.amount
        for f in existing_forecasts
        if f.recurring_expense_id
    }

    # --- SECTION 1 : Catégories Variables ---
    var_categories = Category.objects.filter(
        household=household, type=CategoryType.VARIABLE, is_active=True
    )
    var_data = [
        {"id": c.id, "name": c.name, "amount": cat_map.get(c.id, Decimal("0.00"))}
        for c in var_categories
    ]

    # --- SECTION 2 : Charges Fixes (Toutes affichées avec leur montant dynamique) ---
    fix_data = []
    for r in recurring_items:
        # Soit on a une exception en base, soit on prend le montant calculé par défaut
        allocated = rec_map.get(r.id, default_rec_amounts[str(r.id)])

        fix_data.append(
            {
                "id": r.id,
                "name": r.label,
                "amount": allocated,
                "default_amount": r.total_amount,
            }
        )

    # --- SECTION 3 : Épargne ---
    savings_accounts = BankAccount.objects.filter(
        Q(owner=member) | Q(visibility=Visibility.SHARED),
        owner__household=household,
        account_type=AccountType.SAVINGS,
        is_active=True,
    )
    savings_data = [
        {"id": a.id, "name": a.name, "amount": acc_map.get(a.id, Decimal("0.00"))}
        for a in savings_accounts
    ]

    # --- SECTION 4 : Revenus ---
    income_categories = Category.objects.filter(
        household=household, type=CategoryType.INCOME, is_active=True
    )
    income_data = [
        {"id": c.id, "name": c.name, "amount": cat_map.get(c.id, Decimal("0.00"))}
        for c in income_categories
    ]

    return render(
        request,
        "budget/forecast/forecast_list.html",
        {
            "selected_month": selected_date,
            "var_data": var_data,
            "fix_data": fix_data,
            "savings_data": savings_data,
            "income_data": income_data,
            "breadcrumbs": ["Prévisions budgétaires"],
        },
    )


@login_required
def quick_forecast_override(request, expense_id):
    expense = get_object_or_404(
        RecurringExpense, id=expense_id, household=request.household
    )

    # On récupère le mois actif depuis l'URL (ex: ?month=2026-09) sinon mois courant
    month_str = request.GET.get("month")
    current_month = timezone.localdate().replace(day=1)
    if month_str:
        try:
            current_month = datetime.date.fromisoformat(f"{month_str}-01")
        except ValueError:
            pass

    if request.method == "POST":
        amount = Decimal(request.POST.get("amount", "0").replace(",", "."))
        update_default = request.POST.get("update_default") == "on"

        if update_default:
            # 1. On modifie le contrat de base définitivement
            expense.total_amount = amount
            expense.save(update_fields=["total_amount"])
            # 2. On nettoie l'éventuelle exception qui ne sert plus à rien
            MonthlyForecast.objects.filter(
                month=current_month, member=request.member, recurring_expense=expense
            ).delete()
        else:
            # 1. On enregistre une exception juste pour ce mois-ci
            MonthlyForecast.objects.update_or_create(
                month=current_month,
                member=request.member,
                recurring_expense=expense,
                defaults={"amount": amount},
            )

        return HttpResponse(status=200, headers={"HX-Refresh": "true"})

    # Pour l'affichage de la modale en GET
    existing_forecast = MonthlyForecast.objects.filter(
        month=current_month, member=request.member, recurring_expense=expense
    ).first()

    current_forecast_amount = (
        existing_forecast.amount if existing_forecast else expense.total_amount
    )

    return render(
        request,
        "budget/partials/forecast/_modal_quick_override.html",
        {
            "expense": expense,
            "current_forecast_amount": current_forecast_amount,
            "selected_month": current_month,
        },
    )
