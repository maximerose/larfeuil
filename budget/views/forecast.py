import datetime
from collections import defaultdict
from decimal import Decimal, DecimalException

from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Q
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from budget.models import (
    BankAccount,
    Category,
    Household,
    HouseholdMember,
    MonthlyForecast,
    RecurringExpense,
)
from budget.models.account import AccountType
from budget.models.category import CategoryType
from budget.utils import advance_date
from core.models import Visibility


class AuthenticatedHttpRequest(HttpRequest):
    member: HouseholdMember
    household: Household


@login_required
def forecast_list_view(request: AuthenticatedHttpRequest) -> HttpResponse:
    member = request.member
    household = request.household

    month_str = request.GET.get("month")
    selected_date = timezone.localdate().replace(day=1)

    if month_str:
        try:
            selected_date = datetime.date.fromisoformat(f"{month_str}-01")
        except ValueError:
            pass

    # Récupération des charges fixes
    recurring_items = RecurringExpense.objects.filter(
        Q(owner=member) | Q(visibility=Visibility.SHARED),
        household=household,
        is_active=True,
    )

    # Calcul des montants par défaut attendus
    default_rec_amounts = {}
    due_status_map = {}
    next_date_map = {}

    for r in recurring_items:
        is_due = False
        next_date = None

        if r.frequency_months == 1:
            is_due = True
        elif r.usual_due_day:
            next_date = r.usual_due_day
            if next_date.replace(day=1) <= selected_date:
                while next_date.replace(day=1) < selected_date:
                    next_date = advance_date(next_date, r.frequency_months)
                is_due = (
                    next_date.year == selected_date.year
                    and next_date.month == selected_date.month
                )

        default_rec_amounts[str(r.id)] = r.total_amount if is_due else Decimal("0.00")
        due_status_map[str(r.id)] = is_due
        next_date_map[str(r.id)] = next_date

    # 1. Sauvegarde / Modification / Suppression (POST)
    if request.method == "POST":
        action = request.POST.get("action", "save")

        with transaction.atomic():
            if action == "save":
                for key in request.POST:
                    if not key.startswith(
                        ("forecast_cat_", "forecast_acc_", "forecast_rec_")
                    ):
                        continue

                    # Clé sous forme : forecast_<type>_<item_id>_<line_id>
                    parts = key.split("_")
                    if len(parts) < 4:
                        continue

                    p_type = parts[1]
                    item_id = parts[2]
                    line_id = "_".join(parts[3:])

                    # Ignore la ligne de modèle de clonage HTML
                    if line_id == "template":
                        continue

                    raw_val = str(request.POST.get(key, "")).strip()
                    try:
                        amount = (
                            Decimal("0.00")
                            if raw_val == ""
                            else Decimal(raw_val.replace(",", "."))
                        )
                    except (ValueError, TypeError, DecimalException):
                        continue

                    tx_acc_id = (
                        request.POST.get(
                            f"forecast_tx_acc_{p_type}_{item_id}_{line_id}"
                        )
                        or None
                    )

                    lookup = {"month": selected_date, "member": member}
                    if p_type == "cat":
                        lookup["category_id"] = item_id
                    elif p_type == "acc":
                        lookup["bank_account_id"] = item_id
                    elif p_type == "rec":
                        lookup["recurring_expense_id"] = item_id

                    # Détection d'une charge fixe laissée par défaut sans forçage de compte
                    is_default = False
                    if p_type == "rec":
                        is_default = (
                            amount == default_rec_amounts.get(item_id, Decimal("0.00"))
                            and not tx_acc_id
                        )

                    # Suppression si montant à 0 OU si c'est la valeur par défaut d'une charge fixe
                    if amount == Decimal("0.00") or is_default:
                        if not line_id.startswith("new"):
                            MonthlyForecast.objects.filter(
                                id=line_id, member=member
                            ).delete()
                    else:
                        # Création ou Mise à jour
                        if line_id.startswith("new"):
                            MonthlyForecast.objects.create(
                                amount=amount,
                                transaction_account_id=tx_acc_id,
                                **lookup,
                            )
                        else:
                            MonthlyForecast.objects.filter(
                                id=line_id, member=member
                            ).update(amount=amount, transaction_account_id=tx_acc_id)

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
                            transaction_account=f.transaction_account,
                            defaults={
                                "amount": f.amount,
                                "visibility": f.visibility,
                            },
                        )

        return redirect(f"{request.path}?month={selected_date.strftime('%Y-%m')}")

    # 2. Options de comptes bancaires pour les sélecteurs
    accounts = (
        BankAccount.objects.filter(
            Q(owner=member)
            | Q(owner__household=household, visibility=Visibility.SHARED),
            is_active=True,
        )
        .select_related("owner")
        .distinct()
    )

    default_account = next(
        (
            acc
            for acc in accounts
            if acc.is_default and getattr(acc, "owner_id", None) == member.id
        ),
        None,
    )
    if not default_account:
        default_account = next(
            (
                acc
                for acc in accounts
                if acc.account_type == AccountType.CHECKING
                and getattr(acc, "owner_id", None) == member.id
            ),
            None,
        )

    global_default_acc_id = str(default_account.id) if default_account else ""
    global_default_acc_name = (
        default_account.name if default_account else "Aucun compte"
    )

    account_options = [
        {
            "id": str(acc.id),
            "name": f"{acc.name} ({acc.owner.name})"
            if getattr(acc, "owner_id", None) != member.id
            else acc.name,
        }
        for acc in accounts
    ]

    # 3. Chargement des prévisions existantes
    existing_forecasts = MonthlyForecast.objects.filter(
        member=member, month=selected_date, is_active=True
    )

    cat_map = defaultdict(list)
    acc_map = defaultdict(list)
    rec_map = defaultdict(list)

    for f in existing_forecasts:
        c_id = getattr(f, "category_id", None)
        b_id = getattr(f, "bank_account_id", None)
        r_id = getattr(f, "recurring_expense_id", None)
        t_id = getattr(f, "transaction_account_id", None)

        if c_id:
            cat_map[str(c_id)].append(
                {"id": str(f.id), "amount": f.amount, "acc_id": str(t_id or "")}
            )
        if b_id:
            acc_map[str(b_id)].append(
                {"id": str(f.id), "amount": f.amount, "acc_id": str(t_id or "")}
            )
        if r_id:
            rec_map[str(r_id)].append(
                {"id": str(f.id), "amount": f.amount, "acc_id": str(t_id or "")}
            )

    def get_lines(mapping, item_id):
        # Renvoie uniquement les lignes existantes en BDD (liste vide si aucune prévision)
        return mapping.get(str(item_id), [])

    # Dépenses variables
    var_categories = Category.objects.filter(
        household=household, type=CategoryType.VARIABLE, is_active=True
    )
    var_data = [
        {
            "id": str(c.id),
            "name": c.name,
            "lines": get_lines(cat_map, c.id),
            "default_acc_id": global_default_acc_id,
            "placeholder": f"Par défaut ({global_default_acc_name})",
        }
        for c in var_categories
    ]

    # Charges fixes
    fix_data = []
    for r in recurring_items:
        def_acc = r.default_bank_account or default_account
        fix_data.append(
            {
                "id": str(r.id),
                "name": r.label,
                "lines": get_lines(rec_map, r.id),
                "default_amount": r.total_amount,
                "default_acc_id": str(def_acc.id) if def_acc else "",
                "placeholder": f"Par défaut ({def_acc.name if def_acc else 'Aucun compte'})",
                "is_due_this_month": due_status_map[str(r.id)],
                "next_date": next_date_map[str(r.id)],
                "frequency_months": r.frequency_months,
                "due_day": r.usual_due_day.day if r.usual_due_day else None,
            }
        )
    fix_data.sort(
        key=lambda x: (
            not (x["is_due_this_month"] and x["frequency_months"] > 1),
            x["name"].lower(),
        )
    )

    # Épargne
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
            "lines": get_lines(acc_map, a.id),
            "default_acc_id": global_default_acc_id,
            "placeholder": f"Par défaut ({global_default_acc_name})",
        }
        for a in savings_accounts
    ]

    # Revenus
    income_categories = Category.objects.filter(
        household=household, type=CategoryType.INCOME, is_active=True
    )
    income_data = [
        {
            "id": str(c.id),
            "name": c.name,
            "lines": get_lines(cat_map, c.id),
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
def quick_forecast_override(
    request: AuthenticatedHttpRequest, expense_id: str
) -> HttpResponse:
    expense = get_object_or_404(
        RecurringExpense, id=expense_id, household=request.household
    )

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
            expense.total_amount = amount
            expense.save(update_fields=["total_amount"])
            MonthlyForecast.objects.filter(
                month=current_month, member=request.member, recurring_expense=expense
            ).delete()
        else:
            MonthlyForecast.objects.update_or_create(
                month=current_month,
                member=request.member,
                recurring_expense=expense,
                defaults={"amount": amount},
            )

        return HttpResponse(status=200, headers={"HX-Refresh": "true"})

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
