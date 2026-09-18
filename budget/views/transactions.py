import datetime
import json
from decimal import Decimal
from itertools import chain
from urllib.request import Request

from django.contrib import messages
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from budget.models import (
    BankAccount,
    Category,
    Transaction,
    TransactionType,
)
from budget.models.account import AccountType, Visibility
from budget.models.category import CategoryType
from budget.models.transaction import Transfer
from budget.utils import (
    advance_date,
    calculate_budget_month,
    get_remaining_meal_voucher_ceiling,
    get_target_month_from_request,
    htmx_login_required,
)


@htmx_login_required
def adjust_account_balance_view(
    request: Request, account_id: str
) -> HttpResponse | None:
    account = get_object_or_404(BankAccount, id=account_id)

    if request.method == "POST":
        new_balance = Decimal(request.POST.get("new_balance", "0.00"))

        account.current_balance = new_balance
        account.save()

        messages.success(request, "Solde ajusté")

        response = HttpResponse("")
        response["HX-Refresh"] = "true"

        return response

    return render(
        request,
        "budget/partials/accounts/_modal_adjust_balance.html",
        {"account": account},
    )


@htmx_login_required
@require_http_methods(["GET", "POST"])
def quick_transaction_form_view(request: Request) -> HttpResponse:
    current_member = request.member
    household = request.household

    if request.method == "POST":
        tx_type = request.POST.get("tx_type", "EXPENSE")
        total_amount = Decimal(request.POST.get("total_amount", "0.00"))
        label = request.POST.get("label", "")
        transaction_date_str = request.POST.get("transaction_date")
        transaction_date = (
            datetime.date.fromisoformat(transaction_date_str)
            if transaction_date_str
            else timezone.localdate()
        )

        shift = int(request.POST.get("budget_shift", "0"))

        if shift != 0:
            target_date = advance_date(transaction_date, shift)
            budget_month = calculate_budget_month(
                transaction_date, target_date.year, target_date.month
            )
        else:
            budget_month = transaction_date

        if tx_type == "TRANSFER":
            source_id = request.POST.get("source_account")
            dest_id = request.POST.get("destination_account")
            transfer_category_id = request.POST.get("transfer_category")

            if transfer_category_id:
                # Remboursement "Catégorisé"
                Transaction.objects.create(
                    total_amount=total_amount,
                    label=label or "Remboursement envoyé",
                    category_id=transfer_category_id,
                    bank_account_id=source_id,
                    transaction_date=transaction_date,
                    budget_month=budget_month,
                    transaction_type=TransactionType.EXPENSE,
                )
                Transaction.objects.create(
                    total_amount=-total_amount,
                    label=label or "Remboursement reçu",
                    category_id=transfer_category_id,
                    bank_account_id=dest_id,
                    transaction_date=transaction_date,
                    budget_month=budget_month,
                    transaction_type=TransactionType.EXPENSE,
                )
            else:
                # Transfert simple
                Transfer.objects.create(
                    source_account_id=source_id,
                    destination_account_id=dest_id,
                    amount=total_amount,
                    date=transaction_date,
                )
        else:
            if tx_type == TransactionType.EXPENSE:
                category_id = request.POST.get("expense_category")
                bank_account_id = request.POST.get("expense_account")
                db_tx_type = TransactionType.EXPENSE
            else:
                category_id = request.POST.get("income_category")
                bank_account_id = request.POST.get("income_account")
                db_tx_type = TransactionType.INCOME

            meal_voucher_amount = Decimal(
                request.POST.get("meal_voucher_amount") or "0.00"
            )
            meal_voucher_account_id = request.POST.get("meal_voucher_account_id")

            Transaction.objects.create(
                total_amount=total_amount,
                label=label,
                category_id=category_id,
                bank_account_id=bank_account_id,
                transaction_date=transaction_date,
                budget_month=budget_month,
                transaction_type=db_tx_type,
                meal_voucher_amount=meal_voucher_amount
                if db_tx_type == TransactionType.EXPENSE
                else Decimal("0.00"),
                meal_voucher_bank_account_id=meal_voucher_account_id
                if meal_voucher_amount > 0 and db_tx_type == TransactionType.EXPENSE
                else None,
            )

        messages.success(request, "Opération ajoutée")

        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    # --- GET ---
    categories_expense = list(
        Category.objects.filter(is_active=True, household=household)
        .exclude(type__in=[CategoryType.INCOME, CategoryType.SAVINGS])
        .only("id", "name", "is_meal_voucher_eligible")
    )

    categories_income = list(
        Category.objects.filter(
            is_active=True, household=household, type=CategoryType.INCOME
        )
        .exclude(type=CategoryType.SAVINGS)
        .only("id", "name")
    )

    accounts = list(
        BankAccount.objects.filter(
            Q(owner=current_member)
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
            if acc.owner_id == current_member.id and acc.is_default
        ),
        next(
            (
                acc
                for acc in accounts
                if acc.owner_id == current_member.id
                and acc.account_type == AccountType.CHECKING
            ),
            None,
        ),
    )
    selected_account_id = default_account.id if default_account else None

    account_options = [
        {
            "id": acc.id,
            "name": f"{acc.name} ({acc.owner.name})"
            if acc.owner_id != current_member.id
            else acc.name,
        }
        for acc in accounts
    ]

    today = timezone.localdate()

    tr_accounts = [
        acc for acc in accounts if acc.account_type == AccountType.MEAL_VOUCHER
    ]
    tr_accounts_info = []

    if tr_accounts:
        today_txs = list(
            Transaction.objects.filter(
                transaction_date=today,
                transaction_type=TransactionType.EXPENSE,
            ).only(
                "bank_account_id",
                "meal_voucher_bank_account_id",
                "total_amount",
                "meal_voucher_amount",
            )
        )

        for tr in tr_accounts:
            limit = tr.daily_meal_voucher_limit or Decimal("25.00")

            spent_as_tr = sum(
                tx.meal_voucher_amount
                for tx in today_txs
                if tx.meal_voucher_bank_account_id == tr.id
            )
            spent_as_main = sum(
                (tx.total_amount - tx.meal_voucher_amount)
                for tx in today_txs
                if tx.bank_account_id == tr.id
            )

            remaining = max(Decimal("0.00"), limit - (spent_as_tr + spent_as_main))

            tr_accounts_info.append(
                {
                    "id": str(tr.id),
                    "name": tr.name,
                    "remaining": float(remaining),
                    "fallback_id": str(tr.fallback_account_id)
                    if tr.fallback_account_id
                    else "",
                }
            )

    cat_tr_map = {str(c.id): c.is_meal_voucher_eligible for c in categories_expense}

    return render(
        request,
        "budget/partials/transactions/_modal_quick_transaction.html",
        {
            "categories_expense": categories_expense,
            "categories_income": categories_income,
            "accounts": account_options,
            "selected_account_id": selected_account_id,
            "today": today,
            "tr_accounts_info": tr_accounts_info,
            "tr_accounts_info_json": json.dumps(tr_accounts_info),
            "cat_tr_map": json.dumps(cat_tr_map),
        },
    )


@htmx_login_required
@require_http_methods(["GET", "POST"])
def transaction_update_view(request: Request, transaction_id: str) -> HttpResponse:
    current_member = request.member
    household = request.household

    tx = get_object_or_404(
        Transaction,
        id=transaction_id,
        bank_account__owner=current_member,
    )

    if request.method == "POST":
        tx_type = request.POST.get("tx_type", "EXPENSE")
        total_amount = Decimal(request.POST.get("total_amount", "0.00"))
        label = request.POST.get("label", "")
        transaction_date_str = request.POST.get("transaction_date")
        transaction_date = (
            datetime.date.fromisoformat(transaction_date_str)
            if transaction_date_str
            else tx.transaction_date
        )

        shift = int(request.POST.get("budget_shift", "0"))
        if shift != 0:
            target_date = advance_date(transaction_date, shift)
            budget_month = calculate_budget_month(
                transaction_date, target_date.year, target_date.month
            )
        else:
            budget_month = transaction_date

        if tx_type == "TRANSFER":
            source_id = request.POST.get("source_account")
            dest_id = request.POST.get("destination_account")

            tx.delete()
            Transfer.objects.create(
                source_account_id=source_id,
                destination_account_id=dest_id,
                amount=total_amount,
                date=transaction_date,
            )
        else:
            if tx_type == TransactionType.EXPENSE:
                category_id = request.POST.get("expense_category")
                bank_account_id = request.POST.get("expense_account")
                db_tx_type = TransactionType.EXPENSE
            else:
                category_id = request.POST.get("income_category")
                bank_account_id = request.POST.get("income_account")
                db_tx_type = TransactionType.INCOME

            meal_voucher_amount = Decimal(
                request.POST.get("meal_voucher_amount") or "0.00"
            )
            meal_voucher_account_id = request.POST.get("meal_voucher_account_id")

            tx.transaction_type = db_tx_type
            tx.total_amount = total_amount
            tx.label = label
            tx.category_id = category_id
            tx.bank_account_id = bank_account_id
            tx.transaction_date = transaction_date
            tx.budget_month = budget_month
            tx.meal_voucher_amount = (
                meal_voucher_amount
                if db_tx_type == TransactionType.EXPENSE
                else Decimal("0.00")
            )
            tx.meal_voucher_bank_account_id = (
                meal_voucher_account_id
                if meal_voucher_amount > 0 and db_tx_type == TransactionType.EXPENSE
                else None
            )

            tx.save()

        messages.success(request, "Transaction modifiée")

        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    categories_expense = Category.objects.filter(
        is_active=True, household=household
    ).exclude(type__in=[CategoryType.INCOME, CategoryType.SAVINGS])

    categories_income = Category.objects.filter(
        is_active=True, household=household, type=CategoryType.INCOME
    ).exclude(type=CategoryType.SAVINGS)

    accounts = (
        BankAccount.objects.filter(
            Q(owner=current_member)
            | Q(owner__household=household, visibility=Visibility.SHARED),
            is_active=True,
        )
        .select_related("owner")
        .distinct()
    )

    account_options = [
        {
            "id": acc.id,
            "name": f"{acc.name} ({acc.owner.name})"
            if acc.owner_id != current_member.id
            else acc.name,
        }
        for acc in accounts
    ]

    tr_accounts = [
        acc for acc in accounts if acc.account_type == AccountType.MEAL_VOUCHER
    ]
    tr_accounts_info = [
        {
            "id": str(tr.id),
            "name": tr.name,
            "remaining": float(
                get_remaining_meal_voucher_ceiling(
                    tx.transaction_date, tr, exclude_transaction_pk=tx.pk
                )
                or Decimal("0.00")
            ),
            "fallback_id": str(tr.fallback_account_id)
            if tr.fallback_account_id
            else "",
        }
        for tr in tr_accounts
    ]

    cat_tr_map = {str(c.id): c.is_meal_voucher_eligible for c in categories_expense}

    shift = 0
    if tx.budget_month and tx.transaction_date:
        tx_m = (tx.transaction_date.year, tx.transaction_date.month)
        bg_m = (tx.budget_month.year, tx.budget_month.month)

        if bg_m < tx_m:
            shift = -1
        elif bg_m > tx_m:
            shift = 1

    return render(
        request,
        "budget/partials/transactions/_modal_quick_transaction.html",
        {
            "transaction": tx,
            "budget_shift": shift,
            "selected_category_id": tx.category_id,
            "categories_expense": categories_expense,
            "categories_income": categories_income,
            "accounts": account_options,
            "selected_account_id": tx.bank_account_id,
            "today": tx.transaction_date,
            "tr_accounts_info": tr_accounts_info,
            "tr_accounts_info_json": json.dumps(tr_accounts_info),
            "cat_tr_map": json.dumps(cat_tr_map),
        },
    )


@htmx_login_required
def transaction_delete_view(request: Request, transaction_id: str) -> HttpResponse:
    member = request.member
    tx = get_object_or_404(
        Transaction,
        id=transaction_id,
        bank_account__owner=member,
    )

    if request.method == "POST":
        tx.delete()
        messages.success(request, "Transaction supprimée")
        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    return HttpResponse("Méthode non autorisée", status=405)


@htmx_login_required
@require_http_methods(["GET", "POST"])
def transfer_update_view(request: Request, transfer_id: str) -> HttpResponse:
    current_member = request.member
    household = request.household

    transfer = get_object_or_404(
        Transfer,
        id=transfer_id,
        source_account__owner__household=household,
    )

    if request.method == "POST":
        source_id = request.POST.get("source_account")
        dest_id = request.POST.get("destination_account")
        amount = Decimal(request.POST.get("total_amount", "0.00"))
        date_str = request.POST.get("transaction_date")

        transfer.source_account_id = source_id
        transfer.destination_account_id = dest_id
        transfer.amount = amount
        if date_str:
            transfer.date = datetime.date.fromisoformat(date_str)
        transfer.save()

        messages.success(request, "Transfert modifié")
        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    categories_expense = Category.objects.filter(
        is_active=True, household=household
    ).exclude(type__in=[CategoryType.INCOME, CategoryType.SAVINGS])

    categories_income = Category.objects.filter(
        is_active=True, household=household, type=CategoryType.INCOME
    ).exclude(type=CategoryType.SAVINGS)

    accounts = list(
        BankAccount.objects.filter(
            Q(owner=current_member)
            | Q(owner__household=household, visibility=Visibility.SHARED),
            is_active=True,
        )
        .select_related("owner")
        .distinct()
    )

    account_options = [
        {
            "id": acc.id,
            "name": f"{acc.name} ({acc.owner.name})"
            if acc.owner_id != current_member.id
            else acc.name,
        }
        for acc in accounts
    ]

    tr_accounts = [
        acc for acc in accounts if acc.account_type == AccountType.MEAL_VOUCHER
    ]
    tr_accounts_info = [
        {
            "id": str(tr.id),
            "name": tr.name,
            "remaining": float(
                get_remaining_meal_voucher_ceiling(transfer.date, tr) or Decimal("0.00")
            ),
            "fallback_id": str(tr.fallback_account_id)
            if tr.fallback_account_id
            else "",
        }
        for tr in tr_accounts
    ]

    cat_tr_map = {str(c.id): c.is_meal_voucher_eligible for c in categories_expense}

    return render(
        request,
        "budget/partials/transactions/_modal_quick_transaction.html",
        {
            "transfer": transfer,
            "selected_account_id": transfer.source_account_id,
            "selected_category_id": None,
            "categories_expense": categories_expense,
            "categories_income": categories_income,
            "accounts": account_options,
            "today": transfer.date,
            "tr_accounts_info": tr_accounts_info,
            "tr_accounts_info_json": json.dumps(tr_accounts_info),
            "cat_tr_map": json.dumps(cat_tr_map),
        },
    )


@htmx_login_required
def transfer_delete_view(request: Request, transfer_id: str) -> HttpResponse:
    member = request.member
    transfer = get_object_or_404(
        Transfer,
        id=transfer_id,
    )
    if (
        transfer.source_account.owner_id == member.id
        or transfer.destination_account.owner_id == member.id
    ) and request.method == "POST":
        transfer.delete()
        messages.success(request, "Transfert supprimé")
        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    return HttpResponse("Méthode non autorisée", status=405)


@htmx_login_required
def monthly_history_view(request):
    member = request.member
    household = request.household

    target_month = get_target_month_from_request(request)

    accounts = BankAccount.objects.filter(
        Q(owner=member) | Q(owner__household=household, visibility=Visibility.SHARED),
        is_active=True,
    ).distinct()

    recent_txs = list(
        Transaction.objects.filter(
            bank_account__in=accounts,
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
        ).select_related(
            "category",
            "bank_account",
            "bank_account__owner",
            "meal_voucher_bank_account",
            "recurring_expense",
        )
    )

    recent_transfers = list(
        Transfer.objects.filter(
            Q(source_account__in=accounts) | Q(destination_account__in=accounts),
            date__year=target_month.year,
            date__month=target_month.month,
        ).select_related("source_account", "destination_account")
    )

    all_activity = sorted(
        chain(recent_txs, recent_transfers),
        key=lambda x: getattr(
            x, "transaction_date", getattr(x, "date", datetime.date.min)
        ),
        reverse=True,
    )

    total_income = sum(
        tx.total_amount for tx in recent_txs if tx.transaction_type == "INCOME"
    )
    total_expense = sum(
        tx.total_amount for tx in recent_txs if tx.transaction_type == "EXPENSE"
    )
    net_balance = total_income - total_expense

    return render(
        request,
        "budget/transactions/history_list.html",
        {
            "selected_month": target_month,
            "member": member,
            "transactions": all_activity,
            "total_income": total_income,
            "total_expense": total_expense,
            "net_balance": net_balance,
            "breadcrumbs": ["Historique des transactions"],
        },
    )
