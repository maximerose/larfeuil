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

    # Récupération de toutes les charges fixes
    recurring_items = RecurringExpense.objects.filter(
        Q(owner=member) | Q(visibility=Visibility.SHARED),
        household=household,
        is_active=True,
    )

    # Calcul des montants par défaut attendus pour le mois sélectionné
    default_rec_amounts = {}
    due_status_map = {}

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
        due_status_map[str(r.id)] = is_due

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
                        tx_acc_id = (
                            request.POST.get(f"forecast_tx_acc_cat_{cat_id}") or None
                        )

                        if amount == Decimal("0.00"):
                            MonthlyForecast.objects.filter(
                                month=selected_date, member=member, category_id=cat_id
                            ).delete()
                        else:
                            MonthlyForecast.objects.update_or_create(
                                month=selected_date,
                                member=member,
                                category_id=cat_id,
                                defaults={
                                    "amount": amount,
                                    "transaction_account_id": tx_acc_id,
                                },
                            )

                    elif key.startswith("forecast_acc_"):
                        acc_id = key.replace("forecast_acc_", "")
                        tx_acc_id = (
                            request.POST.get(f"forecast_tx_acc_acc_{acc_id}") or None
                        )

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
                                defaults={
                                    "amount": amount,
                                    "transaction_account_id": tx_acc_id,
                                },
                            )

                    elif key.startswith("forecast_rec_"):
                        rec_id = key.replace("forecast_rec_", "")
                        tx_acc_id = (
                            request.POST.get(f"forecast_tx_acc_rec_{rec_id}") or None
                        )
                        default_val = default_rec_amounts.get(rec_id, Decimal("0.00"))

                        # Si on valide le montant exact prévu par défaut et aucun compte d'exception, on nettoie
                        if amount == default_val and not tx_acc_id:
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
                                defaults={
                                    "amount": amount,
                                    "transaction_account_id": tx_acc_id,
                                },
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
                            defaults={
                                "amount": f.amount,
                                "visibility": f.visibility,
                                "transaction_account": f.transaction_account,
                            },
                        )

        return redirect(f"{request.path}?month={selected_date.strftime('%Y-%m')}")

    # 2. Options de sélection pour les menus déroulants de comptes
    accounts = (
        BankAccount.objects.filter(
            Q(owner=member)
            | Q(owner__household=household, visibility=Visibility.SHARED),
            is_active=True,
        )
        .select_related("owner")
        .distinct()
    )

    # Détermination du compte de repli global pour l'utilisateur
    default_account = next(
        (acc for acc in accounts if acc.is_default and acc.owner_id == member.id), None
    )
    if not default_account:
        default_account = next(
            (
                acc
                for acc in accounts
                if acc.account_type == AccountType.CHECKING
                and acc.owner_id == member.id
            ),
            None,
        )
    if not default_account:
        default_account = next(
            (acc for acc in accounts if acc.owner_id == member.id), None
        )

    global_default_acc_id = str(default_account.id) if default_account else ""
    global_default_acc_name = (
        default_account.name if default_account else "Aucun compte"
    )

    account_options = [
        {
            "id": str(acc.id),
            "name": f"{acc.name} ({acc.owner.name})"
            if acc.owner_id != member.id
            else acc.name,
        }
        for acc in accounts
    ]

    # 3. Chargement des données existantes
    existing_forecasts = MonthlyForecast.objects.filter(
        member=member, month=selected_date, is_active=True
    )

    cat_map = {
        f.category_id: {"amount": f.amount, "acc_id": f.transaction_account_id}
        for f in existing_forecasts
        if f.category_id
    }
    acc_map = {
        f.bank_account_id: {"amount": f.amount, "acc_id": f.transaction_account_id}
        for f in existing_forecasts
        if f.bank_account_id
    }
    rec_map = {
        f.recurring_expense_id: {"amount": f.amount, "acc_id": f.transaction_account_id}
        for f in existing_forecasts
        if f.recurring_expense_id
    }

    # --- SECTION 1 : Catégories Variables ---
    var_categories = Category.objects.filter(
        household=household, type=CategoryType.VARIABLE, is_active=True
    )
    var_data = [
        {
            "id": str(c.id),
            "name": c.name,
            "amount": cat_map.get(c.id, {}).get("amount", Decimal("0.00")),
            "acc_id": str(cat_map.get(c.id, {}).get("acc_id") or ""),
            "default_acc_id": global_default_acc_id,
            "placeholder": f"Par défaut ({global_default_acc_name})",
        }
        for c in var_categories
    ]

    # --- SECTION 2 : Charges Fixes ---
    fix_data = []
    for r in recurring_items:
        allocated = rec_map.get(r.id, {}).get("amount", default_rec_amounts[str(r.id)])
        # Pour les charges fixes, on conserve le compte par défaut lié à la charge, sinon on retombe sur le compte global
        def_acc = r.default_bank_account or default_account
        def_acc_id = str(def_acc.id) if def_acc else ""
        def_acc_name = def_acc.name if def_acc else "Aucun compte"

        fix_data.append(
            {
                "id": str(r.id),
                "name": r.label,
                "amount": allocated,
                "acc_id": str(rec_map.get(r.id, {}).get("acc_id") or ""),
                "default_amount": r.total_amount,
                "default_acc_id": def_acc_id,
                "placeholder": f"Par défaut ({def_acc_name})",
                "is_due_this_month": due_status_map[str(r.id)],
                "frequency_months": r.frequency_months,
            }
        )

    fix_data.sort(
        key=lambda x: (
            not (x["is_due_this_month"] and x["frequency_months"] > 1),
            x["name"].lower(),
        )
    )

    # --- SECTION 3 : Épargne ---
    savings_accounts = BankAccount.objects.filter(
        Q(owner=member) | Q(visibility=Visibility.SHARED),
        owner__household=household,
        account_type=AccountType.SAVINGS,
        is_active=True,
    )
    savings_data = [
        {
            "id": str(a.id),
            "name": a.name,
            "amount": acc_map.get(a.id, {}).get("amount", Decimal("0.00")),
            "acc_id": str(acc_map.get(a.id, {}).get("acc_id") or ""),
            "default_acc_id": global_default_acc_id,
            "placeholder": f"Par défaut ({global_default_acc_name})",
        }
        for a in savings_accounts
    ]

    # --- SECTION 4 : Revenus ---
    income_categories = Category.objects.filter(
        household=household, type=CategoryType.INCOME, is_active=True
    )
    income_data = [
        {
            "id": str(c.id),
            "name": c.name,
            "amount": cat_map.get(c.id, {}).get("amount", Decimal("0.00")),
            "acc_id": str(cat_map.get(c.id, {}).get("acc_id") or ""),
            "default_acc_id": global_default_acc_id,
            "placeholder": f"Par défaut ({global_default_acc_name})",
        }
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
            "account_options": account_options,
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
