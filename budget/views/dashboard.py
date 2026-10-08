import datetime
from decimal import Decimal
from itertools import chain

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.db.models.aggregates import Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from budget.models import (
    BankAccount,
    Household,
    HouseholdMember,
    MonthlyForecast,
    RecurringExpense,
    Transaction,
)
from budget.models.account import AccountType
from budget.models.category import Category, CategoryType
from budget.models.recurring import RecurringExpenseShare
from budget.models.transaction import TransactionType, Transfer
from budget.services.forecast import (
    calculate_monthly_projected_balances,
    create_transaction_from_recurring_expense,
    get_recurring_expenses_with_status,
    get_target_account_for_expense,
)
from budget.utils import get_target_month_from_request, htmx_login_required
from core.models import Visibility


class AuthenticatedHttpRequest(HttpRequest):
    member: HouseholdMember
    household: Household


@login_required
def dashboard_view(request: AuthenticatedHttpRequest) -> HttpResponse:
    member = request.member

    if not member:
        return redirect("/login/")

    accounts_with_projections = []
    recurring_expenses = []
    variable_forecasts = []
    savings_forecasts = []
    income_forecasts = []

    target_month = get_target_month_from_request(request)
    household = request.household

    accounts = BankAccount.objects.filter(
        Q(owner=member) | Q(owner__household=household, visibility=Visibility.SHARED),
        is_active=True,
    ).distinct()

    # 1. 10 Dernières activités (Transactions + Transferts)
    recent_txs = list(
        Transaction.objects.filter(
            bank_account__in=accounts,
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
        )
        .select_related(
            "category",
            "bank_account",
            "bank_account__owner",
            "meal_voucher_bank_account",
            "recurring_expense",
        )
        .order_by("-transaction_date", "-created_at")[:10]
    )

    recent_transfers = list(
        Transfer.objects.filter(
            Q(source_account__in=accounts) | Q(destination_account__in=accounts),
            date__year=target_month.year,
            date__month=target_month.month,
        )
        .select_related("source_account", "destination_account")
        .order_by("-date", "-created_at")[:10]
    )

    # Fusion et tri par date en Python
    recent_activity = sorted(
        chain(recent_txs, recent_transfers),
        key=lambda x: getattr(
            x, "transaction_date", getattr(x, "date", datetime.date.min)
        ),
        reverse=True,
    )[:10]

    # 2. Charges fixes
    recurring_expenses = get_recurring_expenses_with_status(member, target_month)

    # 3. Enveloppes des charges variables restantes par catégorie
    category_forecasts = MonthlyForecast.objects.filter(
        Q(member=member) | Q(visibility=Visibility.SHARED),
        member__household=household,
        month__year=target_month.year,
        month__month=target_month.month,
        category__isnull=False,
        category__type=CategoryType.VARIABLE,
        is_active=True,
    ).select_related("category", "member")

    for forecast in category_forecasts:
        category = forecast.category
        realized = Transaction.objects.filter(
            bank_account__owner=forecast.member,
            bank_account__in=accounts,
            category=category,
            recurring_expense__isnull=True,
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
            transaction_type=TransactionType.EXPENSE,
        ).aggregate(Sum("total_amount"))["total_amount__sum"] or Decimal("0.00")

        remaining = max(Decimal("0.00"), forecast.amount - realized)
        variable_forecasts.append(
            {
                "category": category,
                "member": forecast.member,
                "budget_amount": forecast.amount,
                "realized_amount": realized,
                "remaining_amount": remaining,
            }
        )

    # 4. Enveloppes d'épargne restantes
    savings_qs = MonthlyForecast.objects.filter(
        Q(member=member) | Q(visibility=Visibility.SHARED),
        member__household=household,
        month__year=target_month.year,
        month__month=target_month.month,
        bank_account__isnull=False,
        bank_account__account_type=AccountType.SAVINGS,
        is_active=True,
    ).select_related("bank_account", "member")

    for forecast in savings_qs:
        target_account = forecast.bank_account
        realized_transfers = Transfer.objects.filter(
            source_account__owner=forecast.member,
            destination_account=target_account,
            source_account__in=accounts,
            date__year=target_month.year,
            date__month=target_month.month,
        ).aggregate(Sum("amount"))["amount__sum"] or Decimal("0.00")

        realized_tx = Transaction.objects.filter(
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
            bank_account=target_account,
            transaction_type=TransactionType.INCOME,
        ).aggregate(Sum("total_amount"))["total_amount__sum"] or Decimal("0.00")

        realized = realized_transfers + realized_tx
        remaining = max(Decimal("0.00"), forecast.amount - realized)

        savings_forecasts.append(
            {
                "account": target_account,
                "member": forecast.member,
                "budget_amount": forecast.amount,
                "realized_amount": realized,
                "remaining_amount": remaining,
            }
        )

    income_qs = MonthlyForecast.objects.filter(
        Q(member=member) | Q(visibility=Visibility.SHARED),
        member__household=household,
        month__year=target_month.year,
        month__month=target_month.month,
        category__isnull=False,
        category__type=CategoryType.INCOME,
        is_active=True,
    ).select_related("category", "member")

    for forecast in income_qs:
        category = forecast.category
        realized = Transaction.objects.filter(
            bank_account__owner=forecast.member,
            bank_account__in=accounts,
            category=category,
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
            transaction_type=TransactionType.INCOME,
        ).aggregate(Sum("total_amount"))["total_amount__sum"] or Decimal("0.00")

        remaining = max(Decimal("0.00"), forecast.amount - realized)
        income_forecasts.append(
            {
                "category": category,
                "member": forecast.member,
                "budget_amount": forecast.amount,
                "realized_amount": realized,
                "remaining_amount": remaining,
            }
        )

    # 5. Calcul des prévisions
    projection_steps = calculate_monthly_projected_balances(member, target_month)
    for account in accounts:
        acc_str_id = str(account.id)
        accounts_with_projections.append(
            {
                "account": account,
                "totals": {
                    "initial": round(
                        projection_steps.get("initial", {}).get(
                            acc_str_id, Decimal("0.00")
                        ),
                        2,
                    ),
                    "after_recurring": round(
                        projection_steps.get("after_recurring", {}).get(
                            acc_str_id, Decimal("0.00")
                        ),
                        2,
                    ),
                    "after_variables": round(
                        projection_steps.get("after_variables", {}).get(
                            acc_str_id, Decimal("0.00")
                        ),
                        2,
                    ),
                    "after_savings": round(
                        projection_steps.get("after_savings", {}).get(
                            acc_str_id, Decimal("0.00")
                        ),
                        2,
                    ),
                    "after_incomes": round(
                        projection_steps.get("after_incomes", {}).get(
                            acc_str_id, Decimal("0.00")
                        ),
                        2,
                    ),
                },
            }
        )

    # Calcul de la Checklist d'Onboarding
    has_accounts = len(accounts) > 0
    has_categories = Category.objects.filter(
        household=household, is_active=True
    ).exists()
    has_recurring = RecurringExpense.objects.filter(
        household=household, is_active=True
    ).exists()
    has_transactions = Transaction.objects.filter(bank_account__in=accounts).exists()
    has_forecasts = MonthlyForecast.objects.filter(
        member__household=household, is_active=True
    ).exists()

    onboarding_checklist = {
        "has_accounts": has_accounts,
        "has_categories": has_categories,
        "has_recurring": has_recurring,
        "has_transactions": has_transactions,
        "has_forecasts": has_forecasts,
        "is_complete": all(
            [
                has_accounts,
                has_categories,
                has_recurring,
                has_transactions,
                has_forecasts,
            ]
        ),
    }

    return render(
        request,
        "budget/dashboard.html",
        {
            "member": member,
            "recent_transactions": recent_activity,
            "recurring_expenses": recurring_expenses,
            "variable_forecasts": variable_forecasts,
            "savings_forecasts": savings_forecasts,
            "income_forecasts": income_forecasts,
            "accounts_data": accounts_with_projections,
            "today": target_month,
            "onboarding": onboarding_checklist,
            "breadcrumbs": ["Tableau de bord"],
        },
    )


@htmx_login_required
def pay_recurring_expense_view(
    request: AuthenticatedHttpRequest, expense_id: str
) -> HttpResponse:
    expense = get_object_or_404(RecurringExpense, id=expense_id)
    member = request.member
    target_month = timezone.localdate()

    # 1. On cherche s'il y a DEJA une transaction pour cette charge ce mois-ci
    existing_tx = Transaction.objects.filter(
        recurring_expense=expense,
        budget_month__year=target_month.year,
        budget_month__month=target_month.month,
        transaction_type=TransactionType.EXPENSE,
    ).first()

    accounts = BankAccount.objects.filter(
        Q(owner=member)
        | Q(owner__household=member.household, visibility=Visibility.SHARED),
        is_active=True,
        account_type__in=[AccountType.CHECKING, AccountType.BUSINESS],
    ).distinct()

    account_options = [
        {
            "id": acc.id,
            "name": f"{acc.name} ({acc.owner.name})"
            if getattr(acc, "owner_id", None) != member.id
            else acc.name,
        }
        for acc in accounts
    ]

    target_account = get_target_account_for_expense(expense, member)

    # Récupération de la prévision mensuelle s'il y en a une
    override = MonthlyForecast.objects.filter(
        member__household=member.household,
        month__year=target_month.year,
        month__month=target_month.month,
        recurring_expense=expense,
        is_active=True,
    ).first()

    expected_total = override.amount if override else expense.total_amount

    # Si on édite, le montant et la date par défaut viennent de la transaction existante
    amount_to_pay = existing_tx.total_amount if existing_tx else expected_total
    default_date = existing_tx.transaction_date if existing_tx else timezone.localdate()

    # Le calcul du reste à payer prend en compte le total réalisé.
    # Pour l'UI d'édition, on passe le remaining brut.
    realized_total = Transaction.objects.filter(
        recurring_expense=expense,
        budget_month__year=target_month.year,
        budget_month__month=target_month.month,
        transaction_type=TransactionType.EXPENSE,
    ).aggregate(Sum("total_amount"))["total_amount__sum"] or Decimal("0.00")

    remaining_to_pay = max(Decimal("0.00"), expected_total - realized_total)

    # ... (Logique de répartition partagée / shares_details inchangée) ...
    shares = RecurringExpenseShare.objects.filter(
        recurring_expense=expense, is_active=True
    )
    shares_details = []

    if shares.exists():
        for share in shares:
            ratio = (
                share.amount / expense.total_amount
                if expense.total_amount > Decimal("0.00")
                else Decimal("1.00")
            )
            prorated = round(expected_total * ratio, 2)
            owner_name = (
                share.bank_account.owner.name if share.bank_account.owner else "Foyer"
            )
            shares_details.append({"name": owner_name, "amount": prorated})

        member_share = shares.filter(bank_account__in=accounts).first()
        if member_share and not existing_tx:
            ratio = (
                member_share.amount / expense.total_amount
                if expense.total_amount > Decimal("0.00")
                else Decimal("1.00")
            )
            amount_to_pay = round(expected_total * ratio, 2)
            target_account = member_share.bank_account

    # Surcharge si la transaction existe
    if existing_tx:
        target_account = existing_tx.bank_account

    if request.method == "POST":
        amount = Decimal(request.POST.get("amount", str(amount_to_pay)))
        account_id = request.POST.get("account_id")
        update_default = request.POST.get("update_default") == "on"
        tx_date_str = request.POST.get("transaction_date")

        tx_date = None
        if tx_date_str:
            try:
                tx_date = datetime.date.fromisoformat(tx_date_str)
            except ValueError:
                tx_date = None

        if account_id:
            target_account = get_object_or_404(
                BankAccount,
                id=account_id,
                owner=member,
                is_active=True,
            )

        if target_account is None:
            return HttpResponse("Aucun compte bancaire configuré", status=400)

        # Création ou Mise à jour de la transaction
        if existing_tx:
            existing_tx.total_amount = amount
            existing_tx.bank_account = target_account
            if tx_date:
                existing_tx.transaction_date = tx_date
            existing_tx.save()
        else:
            create_transaction_from_recurring_expense(
                expense=expense,
                bank_account=target_account,
                amount=amount,
                budget_month=target_month.replace(day=1),
                transaction_date=tx_date,
            )

        # ... (Logique update_default inchangée) ...
        if update_default:
            if shares.exists():
                member_share = shares.filter(bank_account__in=accounts).first()
                if member_share:
                    diff = amount - member_share.amount
                    member_share.amount = amount
                    member_share.save()

                    expense.total_amount += diff
                    expense.save()
            else:
                expense.total_amount = amount
                expense.save()

        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    return render(
        request,
        "budget/partials/recurring/_modal_pay_recurring.html",
        {
            "expense": expense,
            "account": target_account,
            "accounts": account_options,
            "amount_to_pay": amount_to_pay,
            "expected_total": expected_total,
            "remaining_to_pay": remaining_to_pay,
            "shares_details": shares_details,
            "today": default_date,
            "is_edit": existing_tx is not None,
        },
    )
