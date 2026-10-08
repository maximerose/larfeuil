import calendar
import datetime
from decimal import Decimal
from functools import wraps

from django.db.models import F, Sum
from django.http import HttpResponse
from django.utils import timezone

from budget.models.account import AccountType
from budget.models.category import Category
from budget.models.forecast import MonthlyForecast
from budget.models.recurring import RecurringExpense
from budget.models.transaction import Transaction, TransactionType


def htmx_login_required(view_func):
    """Décorateur pour bloquer l'accès aux vues HTMX si non connecté."""

    @wraps(view_func)
    def _wrapped_view(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return HttpResponse("Non autorisé", status=401)
        return view_func(request, *args, **kwargs)

    return _wrapped_view


def calculate_budget_month(
    ref_date: datetime.date, target_year: int, target_month: int
) -> datetime.date:
    """Calcule le budget_month selon que le mois cible est antérieur, égal ou postérieur"""
    ref_key = (ref_date.year, ref_date.month)
    target_key = (target_year, target_month)

    if target_key < ref_key:
        last_day = calendar.monthrange(target_year, target_month)[1]
        return datetime.date(target_year, target_month, last_day)
    elif target_key > ref_key:
        return datetime.date(target_year, target_month, 1)
    else:
        return ref_date


def get_remaining_meal_voucher_ceiling(
    transaction_date: datetime.date, bank_account, exclude_transaction_pk=None
) -> Decimal | None:
    """
    Calcule le plafond journalier des tickets resto restant pour un membre.
    """
    if bank_account.account_type != AccountType.MEAL_VOUCHER:
        return None

    limit = bank_account.daily_meal_voucher_limit or Decimal("25.00")

    # On ne regarde QUE les dépenses du jour (les revenus ne comptent pas dans le plafond)
    qs = Transaction.objects.filter(
        transaction_date=transaction_date, transaction_type=TransactionType.EXPENSE
    )

    if exclude_transaction_pk:
        qs = qs.exclude(pk=exclude_transaction_pk)

    # 1. Montant déduit via l'encart Tickets Resto
    spent_as_tr = qs.filter(meal_voucher_bank_account=bank_account).aggregate(
        total=Sum("meal_voucher_amount")
    )["total"] or Decimal("0.00")

    # 2. Montant déduit si le compte TR est sélectionné en compte principal
    spent_as_main = qs.filter(bank_account=bank_account).aggregate(
        total=Sum(F("total_amount") - F("meal_voucher_amount"))
    )["total"] or Decimal("0.00")

    spent_today = spent_as_tr + spent_as_main

    return max(Decimal("0.00"), limit - spent_today)


def advance_date(start_date: datetime.date, months_to_add: int) -> datetime.date:
    """Fait avancer une date d'un certain nombre de mois en gérant les fins de mois."""
    month_zero_indexed = start_date.month - 1 + months_to_add
    new_year = start_date.year + month_zero_indexed // 12
    new_month = month_zero_indexed % 12 + 1
    last_day = calendar.monthrange(new_year, new_month)[1]
    return datetime.date(new_year, new_month, min(start_date.day, last_day))


def get_target_month_from_request(request) -> datetime.date:
    """Extrait le mois ciblé depuis l'URL (?month=YYYY-MM) ou renvoie le mois courant."""
    month_str = request.GET.get("month")
    if month_str:
        try:
            year, month = map(int, month_str.split("-"))
            return datetime.date(year, month, 1)
        except (ValueError, TypeError):
            pass

    return timezone.localdate().replace(day=1)


def merge_categories(source_category: Category, target_category: Category) -> None:
    """Réassigne les données de la catégorie source vers la cible, puis désactive la source."""
    Transaction.objects.filter(category=source_category).update(
        category=target_category
    )
    MonthlyForecast.objects.filter(category=source_category).update(
        category=target_category
    )
    RecurringExpense.objects.filter(category=source_category).update(
        category=target_category
    )

    source_category.is_active = False
    source_category.save(update_fields=["is_active"])


def remove_accents(text):
    if not text:
        return ""
    return str(text).lower().translate(str.maketrans("éèêëàâäôöûüç", "eeeeaaaoouuc"))
