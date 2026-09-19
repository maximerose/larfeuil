import datetime
import json
from decimal import Decimal
from urllib.request import Request

from django.contrib import messages
from django.db.models import Q
from django.db.models.aggregates import Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render
from django.utils import timezone
from django.views.decorators.http import require_GET, require_http_methods

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

    all_household_accounts = (
        BankAccount.objects.filter(owner__household=household, is_active=True)
        .select_related("owner")
        .order_by("name")
    )

    household_account_options = [
        {
            "id": str(acc.id),
            "name": f"{acc.name} ({acc.owner.name})"
            if acc.owner_id != current_member.id
            else acc.name,
        }
        for acc in all_household_accounts
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
            "household_account_options": household_account_options,
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

    all_household_accounts = (
        BankAccount.objects.filter(owner__household=household, is_active=True)
        .select_related("owner")
        .order_by("name")
    )

    household_account_options = [
        {
            "id": str(acc.id),
            "name": f"{acc.name} ({acc.owner.name})"
            if acc.owner_id != current_member.id
            else acc.name,
        }
        for acc in all_household_accounts
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
            "household_account_options": household_account_options,
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

    all_household_accounts = (
        BankAccount.objects.filter(owner__household=household, is_active=True)
        .select_related("owner")
        .order_by("name")
    )

    household_account_options = [
        {
            "id": str(acc.id),
            "name": f"{acc.name} ({acc.owner.name})"
            if acc.owner_id != current_member.id
            else acc.name,
        }
        for acc in all_household_accounts
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
            "household_account_options": household_account_options,
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
@require_GET
def monthly_history_view(request: Request) -> HttpResponse:
    member = request.member
    household = member.household

    # --- 1. GESTION DES FILTRES ---
    month_str = request.GET.get("month")
    if month_str:
        try:
            target_month = datetime.date.fromisoformat(f"{month_str}-01")
        except ValueError:
            target_month = timezone.localdate().replace(day=1)
    else:
        target_month = timezone.localdate().replace(day=1)

    selected_member_id = request.GET.get("member", "")
    selected_category_id = request.GET.get("category", "")
    selected_account_id = request.GET.get("account", "")
    selected_tx_type = request.GET.get("tx_type", "")

    # --- 2. REQUÊTE DE BASE (SÉCURISÉE) ---
    base_txs = Transaction.objects.filter(
        Q(bank_account__owner=member) | Q(bank_account__visibility=Visibility.SHARED),
        bank_account__owner__household=household,
        budget_month__year=target_month.year,
        budget_month__month=target_month.month,
    ).select_related(
        "category", "bank_account", "bank_account__owner", "recurring_expense"
    )

    if selected_member_id:
        base_txs = base_txs.filter(bank_account__owner_id=selected_member_id)
    if selected_account_id:
        base_txs = base_txs.filter(bank_account_id=selected_account_id)

    # --- 3. CALCUL SÉCURISÉ DES KPIS ---
    income_kpi = base_txs.filter(transaction_type="INCOME").aggregate(
        s=Sum("total_amount")
    )["s"] or Decimal("0.00")

    fixed_kpi = base_txs.filter(transaction_type="EXPENSE").filter(
        Q(category__type="RECURRING") | Q(recurring_expense__isnull=False)
    ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0.00")

    savings_kpi = base_txs.filter(
        transaction_type="EXPENSE", category__type="SAVINGS"
    ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0.00")

    variable_kpi = base_txs.filter(transaction_type="EXPENSE").exclude(
        Q(category__type="RECURRING")
        | Q(recurring_expense__isnull=False)
        | Q(category__type="SAVINGS")
    ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0.00")

    # --- 4. RÉPARTITION (GRAPHIQUE DOUGHNUT) ---
    breakdown_qs = (
        base_txs.filter(transaction_type="EXPENSE")
        .exclude(category__type="SAVINGS")
        .values("category__name")
        .annotate(total=Sum("total_amount"))
        .order_by("-total")
    )

    chart_labels = []
    chart_data = []

    for b in breakdown_qs:
        cat_name = b["category__name"] or "Sans catégorie"
        chart_labels.append(cat_name)
        chart_data.append(float(b["total"]))

    chart_dict = {"labels": chart_labels, "data": chart_data} if chart_labels else None

    # --- 5. APPLICATION DES FILTRES À LA LISTE ---
    txs = base_txs
    if selected_category_id == "none":
        txs = txs.filter(category__isnull=True)
    elif selected_category_id:
        txs = txs.filter(category_id=selected_category_id)

    if selected_tx_type == "VARIABLE":
        txs = txs.filter(transaction_type="EXPENSE").exclude(
            Q(category__type="RECURRING")
            | Q(recurring_expense__isnull=False)
            | Q(category__type="SAVINGS")
        )
    elif selected_tx_type == "RECURRING":
        txs = txs.filter(transaction_type="EXPENSE").filter(
            Q(category__type="RECURRING") | Q(recurring_expense__isnull=False)
        )
    elif selected_tx_type == "INCOME":
        txs = txs.filter(transaction_type="INCOME")
    elif selected_tx_type == "SAVINGS":
        txs = txs.filter(transaction_type="EXPENSE", category__type="SAVINGS")

    txs = txs.order_by("-transaction_date", "-created_at")

    # --- 6. FORMATAGE DES COMPTES POUR LE SÉLECTEUR ---
    visible_accounts = (
        BankAccount.objects.filter(
            Q(owner=member) | Q(visibility=Visibility.SHARED),
            owner__household=household,
            is_active=True,
        )
        .select_related("owner")
        .order_by("name")
    )

    account_options = [
        {
            "id": str(acc.id),
            "name": f"{acc.name} ({acc.owner.name})"
            if acc.owner_id != member.id
            else acc.name,
        }
        for acc in visible_accounts
    ]

    # --- 7. PRÉPARATION DU CONTEXTE ---
    context = {
        "member": member,
        "transactions": txs,
        "target_month": target_month,
        "income_kpi": income_kpi,
        "fixed_kpi": fixed_kpi,
        "variable_kpi": variable_kpi,
        "savings_kpi": savings_kpi,
        "chart_json": chart_dict,
        "members": household.members.filter(is_active=True),
        "categories": Category.objects.filter(
            household=household, is_active=True
        ).order_by("name"),
        "accounts": account_options,
        "selected_member": selected_member_id,
        "selected_category": selected_category_id,
        "selected_account": selected_account_id,
        "selected_tx_type": selected_tx_type,
    }

    if request.headers.get("HX-Target") == "history-results":
        return render(request, "budget/transactions/_history_results.html", context)

    return render(request, "budget/transactions/history_list.html", context)
