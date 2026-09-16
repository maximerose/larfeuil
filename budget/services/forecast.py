import calendar
import datetime
from collections import defaultdict
from decimal import Decimal

from django.db.models import Case, F, Q, Sum, Value, When
from django.utils import timezone

from budget.models import (
    AccountType,
    BankAccount,
    HouseholdMember,
    Transaction,
    TransactionType,
)
from budget.models.category import CategoryType
from budget.models.forecast import MonthlyForecast
from budget.models.recurring import RecurringExpense, RecurringExpenseStatus
from budget.models.transaction import Transfer
from budget.utils import advance_date, remove_accents
from core.models import Visibility


def get_target_account_for_expense(
    expense: RecurringExpense, member: HouseholdMember
) -> BankAccount | None:
    if expense.default_bank_account:
        return expense.default_bank_account
    if expense.category and expense.category.default_bank_account:
        return expense.category.default_bank_account

    owner = expense.owner or member
    return BankAccount.objects.filter(
        owner=owner, is_default=True, is_active=True
    ).first()


def calculate_monthly_projected_balances(
    member: HouseholdMember, month: datetime.date
) -> dict[str, dict[str, Decimal]]:
    household = member.household
    accounts = BankAccount.objects.filter(
        Q(owner=member) | Q(owner__household=household, visibility=Visibility.SHARED),
        is_active=True,
    ).distinct()

    today = timezone.localdate().replace(day=1)
    target_month = month.replace(day=1)

    initial = {acc.id: acc.current_balance for acc in accounts}

    if target_month < today:
        return {
            "initial": initial,
            "after_recurring": initial.copy(),
            "after_variables": initial.copy(),
            "after_savings": initial.copy(),
            "after_incomes": initial.copy(),
        }

    recurring_overrides = {
        f.recurring_expense_id: f.amount
        for f in MonthlyForecast.objects.filter(
            member__household=household,
            month__year=target_month.year,
            month__month=target_month.month,
            recurring_expense__isnull=False,
            is_active=True,
        )
    }

    # 1. Charges Fixes
    after_recurring = initial.copy()
    recurring_expenses = RecurringExpense.objects.filter(
        Q(owner=member)
        | Q(owner__isnull=True, household=household)
        | Q(owner__household=household, visibility=Visibility.SHARED),
        is_active=True,
    ).select_related("category", "default_bank_account")

    for expense in recurring_expenses:
        has_override = expense.id in recurring_overrides
        is_due_this_month = False

        if expense.frequency_months == 1:
            is_due_this_month = True
        elif expense.usual_due_day:
            next_date = expense.usual_due_day
            if next_date.replace(day=1) <= target_month:
                while next_date.replace(day=1) < target_month:
                    next_date = advance_date(next_date, expense.frequency_months)
                is_due_this_month = (
                    next_date.year == target_month.year
                    and next_date.month == target_month.month
                )

        if not is_due_this_month and not has_override:
            continue

        expected_amount = recurring_overrides.get(expense.id, expense.total_amount)
        shares = expense.shares.filter(is_active=True)

        if shares.exists():
            for share in shares:
                if share.bank_account_id not in after_recurring:
                    continue
                real_transactions = Transaction.objects.filter(
                    bank_account_id=share.bank_account_id,
                    recurring_expense=expense,
                    budget_month__year=target_month.year,
                    budget_month__month=target_month.month,
                    transaction_type=TransactionType.EXPENSE,
                )
                if not real_transactions.exists():
                    ratio = (
                        share.amount / expense.total_amount
                        if expense.total_amount > Decimal("0.00")
                        else Decimal("1.00")
                    )
                    adjusted_share_amount = round(expected_amount * ratio, 2)
                    after_recurring[share.bank_account_id] -= adjusted_share_amount
        else:
            target_account = get_target_account_for_expense(expense, member)
            if target_account and target_account.id in after_recurring:
                real_transactions = Transaction.objects.filter(
                    bank_account_id=target_account.id,
                    recurring_expense=expense,
                    budget_month__year=target_month.year,
                    budget_month__month=target_month.month,
                    transaction_type=TransactionType.EXPENSE,
                )
                if not real_transactions.exists():
                    after_recurring[target_account.id] -= expected_amount

    # 2. Charges Variables
    after_variables = after_recurring.copy()
    tr_accounts = [
        acc for acc in accounts if acc.account_type == AccountType.MEAL_VOUCHER
    ]

    # Recherche robuste du compte par défaut
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

    category_forecasts = defaultdict(Decimal)
    for f in MonthlyForecast.objects.filter(
        member__household=household,
        month__year=target_month.year,
        month__month=target_month.month,
        category__isnull=False,
        is_active=True,
    ).select_related("category"):
        category_forecasts[f.category] += f.amount

    for category, total_amount in category_forecasts.items():
        if category.type in [CategoryType.INCOME, CategoryType.SAVINGS]:
            continue

        # Prise en compte des remboursements (Dépenses - Revenus de la même catégorie)
        realized_data = Transaction.objects.filter(
            bank_account__in=accounts,
            category=category,
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
        ).aggregate(
            net_spent=Sum(
                Case(
                    When(
                        transaction_type=TransactionType.EXPENSE, then=F("total_amount")
                    ),
                    When(
                        transaction_type=TransactionType.INCOME, then=-F("total_amount")
                    ),
                    default=Value(Decimal("0.00")),
                )
            )
        )
        realized = realized_data["net_spent"] or Decimal("0.00")
        remaining = max(Decimal("0.00"), total_amount - realized)

        if remaining > Decimal("0.00"):
            target_acc = category.default_bank_account

            if target_acc and target_acc.id in after_variables:
                after_variables[target_acc.id] -= remaining
            else:
                # Priorité au compte Tickets Resto si éligible
                if category.is_meal_voucher_eligible and tr_accounts:
                    for tr_acc in tr_accounts:
                        if remaining <= Decimal("0.00"):
                            break
                        available_tr = max(
                            Decimal("0.00"),
                            after_variables.get(tr_acc.id, Decimal("0.00")),
                        )
                        if available_tr > Decimal("0.00"):
                            tr_deduction = min(remaining, available_tr)
                            after_variables[tr_acc.id] -= tr_deduction
                            remaining -= tr_deduction

                # Le reste s'impute sur le compte courant
                if remaining > Decimal("0.00") and default_account:
                    after_variables[default_account.id] -= remaining

    # 3. Épargne
    after_savings = after_variables.copy()
    savings_totals = defaultdict(Decimal)

    for f in MonthlyForecast.objects.filter(
        member__household=household,
        month__year=target_month.year,
        month__month=target_month.month,
        bank_account__isnull=False,
        bank_account__account_type=AccountType.SAVINGS,
        is_active=True,
    ).select_related("bank_account"):
        savings_totals[f.bank_account] += f.amount

    for target_account, total_amount in savings_totals.items():
        realized_transfers = Transfer.objects.filter(
            destination_account=target_account,
            source_account__in=accounts,
            date__year=target_month.year,
            date__month=target_month.month,
        ).aggregate(Sum("amount"))["amount__sum"] or Decimal("0.00")

        realized_transactions = Transaction.objects.filter(
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
            bank_account=target_account,
            transaction_type=TransactionType.INCOME,
        ).aggregate(Sum("total_amount"))["total_amount__sum"] or Decimal("0.00")

        remaining = max(
            Decimal("0.00"), total_amount - realized_transfers - realized_transactions
        )

        if remaining > Decimal("0.00"):
            if default_account:
                after_savings[default_account.id] -= remaining
            if target_account.id in after_savings:
                after_savings[target_account.id] += remaining

    # 4. Revenus
    after_incomes = after_savings.copy()
    for category, total_amount in category_forecasts.items():
        if category.type != CategoryType.INCOME:
            continue

        realized_data = Transaction.objects.filter(
            bank_account__in=accounts,
            category=category,
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
        ).aggregate(
            net_income=Sum(
                Case(
                    When(
                        transaction_type=TransactionType.INCOME, then=F("total_amount")
                    ),
                    When(
                        transaction_type=TransactionType.EXPENSE,
                        then=-F("total_amount"),
                    ),
                    default=Value(Decimal("0.00")),
                )
            )
        )
        realized = realized_data["net_income"] or Decimal("0.00")

        remaining_to_receive = max(Decimal("0.00"), total_amount - realized)

        if remaining_to_receive > Decimal("0.00"):
            target_acc = category.default_bank_account or default_account
            if target_acc and target_acc.id in after_incomes:
                after_incomes[target_acc.id] += remaining_to_receive

    return {
        "initial": initial,
        "after_recurring": after_recurring,
        "after_variables": after_variables,
        "after_savings": after_savings,
        "after_incomes": after_incomes,
    }


def get_recurring_expenses_with_status(
    member: HouseholdMember, month: datetime.date
) -> list[dict]:
    household = member.household
    target_month = month.replace(day=1)
    today = timezone.localdate()

    expenses = RecurringExpense.objects.filter(
        Q(owner=member)
        | Q(owner__isnull=True, household=household)
        | Q(owner__household=household, visibility=Visibility.SHARED),
        is_active=True,
    ).select_related("category", "default_bank_account")

    recurring_overrides = {
        f.recurring_expense_id: f.amount
        for f in MonthlyForecast.objects.filter(
            member__household=household,
            month__year=target_month.year,
            month__month=target_month.month,
            recurring_expense__isnull=False,
            is_active=True,
        )
    }

    member_accounts_ids = list(
        BankAccount.objects.filter(owner=member, is_active=True).values_list(
            "id", flat=True
        )
    )

    results = []
    for expense in expenses:
        expected_total = recurring_overrides.get(expense.id, expense.total_amount)
        has_override = expense.id in recurring_overrides

        transactions = Transaction.objects.filter(
            recurring_expense=expense,
            budget_month__year=target_month.year,
            budget_month__month=target_month.month,
            transaction_type=TransactionType.EXPENSE,
        ).select_related("bank_account", "bank_account__owner")

        realized = sum(t.total_amount for t in transactions) or Decimal("0.00")

        next_date = None
        is_overdue = False
        is_due_this_month = False

        if expense.frequency_months == 1:
            is_due_this_month = True
            if expense.usual_due_day:
                last_day = calendar.monthrange(target_month.year, target_month.month)[1]
                day = min(expense.usual_due_day.day, last_day)
                next_date = datetime.date(target_month.year, target_month.month, day)
        elif expense.usual_due_day:
            start_month = expense.usual_due_day.replace(day=1)
            if target_month >= start_month:
                diff_months = (target_month.year - start_month.year) * 12 + (
                    target_month.month - start_month.month
                )
                if diff_months % expense.frequency_months == 0:
                    is_due_this_month = True
                    last_day = calendar.monthrange(
                        target_month.year, target_month.month
                    )[1]
                    day = min(expense.usual_due_day.day, last_day)
                    next_date = datetime.date(
                        target_month.year, target_month.month, day
                    )

        if not is_due_this_month and not has_override:
            continue

        if expected_total <= Decimal("0.00") and realized == Decimal("0.00"):
            continue

        is_past_month = target_month < today.replace(day=1)

        if is_past_month:
            status = (
                RecurringExpenseStatus.COMPLETED
                if realized > Decimal("0.00")
                else RecurringExpenseStatus.WAITING
            )
        else:
            status = (
                RecurringExpenseStatus.WAITING
                if realized == Decimal("0.00")
                else (
                    RecurringExpenseStatus.PARTIAL
                    if realized < expected_total
                    else RecurringExpenseStatus.COMPLETED
                )
            )

        if (
            next_date
            and not is_past_month
            and status != RecurringExpenseStatus.COMPLETED
            and today > next_date
        ):
            is_overdue = True

        my_expected_share = expected_total
        shares = expense.shares.filter(is_active=True)
        if shares.exists():
            my_share = shares.filter(bank_account_id__in=member_accounts_ids).first()
            if my_share:
                ratio = (
                    my_share.amount / expense.total_amount
                    if expense.total_amount > Decimal("0.00")
                    else Decimal("1.00")
                )
                my_expected_share = round(expected_total * ratio, 2)
            else:
                my_expected_share = Decimal("0.00")

        my_realized = sum(
            t.total_amount
            for t in transactions
            if t.bank_account_id in member_accounts_ids
        ) or Decimal("0.00")

        my_remaining = max(Decimal("0.00"), my_expected_share - my_realized)
        global_remaining = max(Decimal("0.00"), expected_total - realized)

        if shares.exists():
            account_name = "Multiples comptes"
            acc_type = "OTHER"
        else:
            target_account = get_target_account_for_expense(expense, member)
            if target_account:
                acc_type = target_account.account_type
                if target_account.owner_id != member.id:
                    account_name = (
                        f"{target_account.name} ({target_account.owner.name})"
                    )
                else:
                    account_name = target_account.name
            else:
                account_name = "Aucun compte configuré"
                acc_type = "OTHER"

        results.append(
            {
                "expense": expense,
                "bank_account_name": account_name,
                "account_type": acc_type,
                "expected_amount": expected_total,
                "realized_amount": realized,
                "status": status,
                "next_date": next_date,
                "is_overdue": is_overdue,
                "my_expected_share": my_expected_share,
                "my_remaining": my_remaining,
                "global_remaining": global_remaining,
                "transactions": transactions,
            }
        )

    results.sort(key=lambda x: remove_accents(x["expense"].label))

    return results


def create_transaction_from_recurring_expense(
    expense: RecurringExpense,
    bank_account: BankAccount,
    amount: Decimal | None = None,
    budget_month: datetime.date | None = None,
    label: str | None = None,
) -> Transaction:
    today = timezone.localdate()
    month = budget_month.replace(day=1) if budget_month else today.replace(day=1)

    return Transaction.objects.create(
        bank_account=bank_account,
        category=expense.category,
        recurring_expense=expense,
        total_amount=amount if amount is not None else expense.total_amount,
        label=label or expense.label,
        transaction_date=today,
        budget_month=month,
        transaction_type=TransactionType.EXPENSE,
    )
