import datetime
import json
from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.db.models import Min, Q, Sum
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.utils import timezone

from budget.models import (
    BankAccount,
    Household,
    HouseholdMember,
    RecurringExpense,
    Transaction,
    Transfer,
)
from budget.models.account import AccountType
from budget.models.category import CategoryType
from budget.utils import advance_date, remove_accents


class AuthenticatedHttpRequest(HttpRequest):
    member: HouseholdMember
    household: Household


@login_required
def statistics_view(request: AuthenticatedHttpRequest) -> HttpResponse:
    household = request.household
    today = timezone.localdate().replace(day=1)

    min_tx_date = Transaction.objects.filter(
        bank_account__owner__household=household
    ).aggregate(m=Min("budget_month"))["m"]

    start_boundary = min_tx_date.replace(day=1) if min_tx_date else today
    end_boundary = today

    current_year_start = datetime.date(today.year, 1, 1)

    start_str = request.GET.get("start_month")
    end_str = request.GET.get("end_month")

    try:
        start_date = (
            datetime.date.fromisoformat(f"{start_str}-01")
            if start_str
            else current_year_start
        )
    except ValueError:
        start_date = current_year_start

    try:
        end_date = (
            datetime.date.fromisoformat(f"{end_str}-01") if end_str else end_boundary
        )
    except ValueError:
        end_date = end_boundary

    if start_date > end_date:
        start_date, end_date = end_date, start_date

    selected_months = []
    curr = start_date
    while curr <= end_date:
        selected_months.append(curr)
        curr = advance_date(curr, 1)

    nb_period_months = len(selected_months) or 1
    next_month_after_end = advance_date(end_date, 1)

    range_txs = Transaction.objects.filter(
        bank_account__owner__household=household,
        budget_month__gte=start_date,
        budget_month__lt=next_month_after_end,
    )

    range_transfers = Transfer.objects.filter(
        Q(source_account__owner__household=household)
        | Q(destination_account__owner__household=household),
        date__gte=start_date,
        date__lt=next_month_after_end,
    ).select_related("source_account", "destination_account")

    rec_expenses = RecurringExpense.objects.filter(household=household, is_active=True)

    savings_accounts = BankAccount.objects.filter(
        owner__household=household,
        account_type=AccountType.SAVINGS,
        is_active=True,
    ).select_related("owner")

    category_types = [
        (CategoryType.INCOME, "Revenus", "#10b981", "rgba(16, 185, 129, 0.1)"),
        (CategoryType.RECURRING, "Charges fixes", "#f43f5e", "rgba(244, 63, 94, 0.1)"),
        (
            CategoryType.VARIABLE,
            "Charges variables",
            "#f59e0b",
            "rgba(245, 158, 11, 0.1)",
        ),
        (CategoryType.SAVINGS, "Épargne", "#8b5cf6", "rgba(139, 92, 246, 0.1)"),
    ]

    FRENCH_MONTHS = [
        "Janv.",
        "Fév.",
        "Mars",
        "Avr.",
        "Mai",
        "Juin",
        "Juil.",
        "Août",
        "Sept.",
        "Oct.",
        "Nov.",
        "Déc.",
    ]
    chart_labels = [f"{FRENCH_MONTHS[m.month - 1]} {m.year}" for m in selected_months]

    chart_data_combined = {"labels": chart_labels, "datasets": []}
    individual_charts = {}
    period_summary = []

    colors_palette = [
        "#3b82f6",
        "#f43f5e",
        "#f59e0b",
        "#10b981",
        "#8b5cf6",
        "#14b8a6",
        "#ec4899",
        "#06b6d4",
    ]

    def get_net_amount(qs, expected_type):
        inc = qs.filter(transaction_type="INCOME").aggregate(s=Sum("total_amount"))[
            "s"
        ] or Decimal("0.00")
        exp = qs.filter(transaction_type="EXPENSE").aggregate(s=Sum("total_amount"))[
            "s"
        ] or Decimal("0.00")
        return (inc - exp) if expected_type == "INCOME" else (exp - inc)

    def get_savings_month_amount(target_acc_id, m_date):
        m_transfers_in = sum(
            tr.amount
            for tr in range_transfers
            if str(getattr(tr, "destination_account_id", "")) == target_acc_id
            and tr.date.year == m_date.year
            and tr.date.month == m_date.month
        ) or Decimal("0.00")
        m_transfers_out = sum(
            tr.amount
            for tr in range_transfers
            if str(getattr(tr, "source_account_id", "")) == target_acc_id
            and tr.date.year == m_date.year
            and tr.date.month == m_date.month
        ) or Decimal("0.00")
        m_txs_inc = range_txs.filter(
            bank_account_id=target_acc_id,
            transaction_type="INCOME",
            budget_month__year=m_date.year,
            budget_month__month=m_date.month,
        ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0.00")
        m_txs_exp = range_txs.filter(
            bank_account_id=target_acc_id,
            transaction_type="EXPENSE",
            budget_month__year=m_date.year,
            budget_month__month=m_date.month,
        ).aggregate(s=Sum("total_amount"))["s"] or Decimal("0.00")
        return (m_transfers_in - m_transfers_out) + (m_txs_inc - m_txs_exp)

    TOP_LIMIT = 5

    for cat_type_key, cat_type_label, border_color, bg_color in category_types:
        categories_data = []
        type_total_period = Decimal("0.00")
        type_monthly_totals = [0.0] * len(selected_months)
        expected_type = "INCOME" if cat_type_key == CategoryType.INCOME else "EXPENSE"

        # --- CAS 1 : REVENUS & CHARGES VARIABLES ---
        if cat_type_key in [CategoryType.INCOME, CategoryType.VARIABLE]:
            type_txs = range_txs.filter(category__type=cat_type_key)
            cats = (
                type_txs.values("category__id", "category__name")
                .distinct()
                .order_by("category__name")
            )

            for c in cats:
                c_id = c["category__id"]
                c_name = c["category__name"]
                cat_txs = type_txs.filter(category_id=c_id)
                total_period = get_net_amount(cat_txs, expected_type)

                monthly_breakdown = []
                active_months_count = 0

                prev_month_date = start_date.replace(day=1) - datetime.timedelta(days=1)
                prev_qs = cat_txs.filter(
                    budget_month__year=prev_month_date.year,
                    budget_month__month=prev_month_date.month,
                )
                prev_amount = get_net_amount(prev_qs, expected_type)

                for m_idx, m_date in enumerate(selected_months):
                    curr_qs = cat_txs.filter(
                        budget_month__year=m_date.year,
                        budget_month__month=m_date.month,
                    )
                    m_amount = get_net_amount(curr_qs, expected_type)

                    if m_amount != 0:
                        active_months_count += 1

                    if m_amount > prev_amount:
                        evo = "up"
                    elif m_amount < prev_amount:
                        evo = "down"
                    else:
                        evo = "same"

                    monthly_breakdown.append(
                        {"date": m_date, "amount": m_amount, "evolution": evo}
                    )
                    type_monthly_totals[m_idx] += float(m_amount)
                    prev_amount = m_amount

                divisor = Decimal(active_months_count or 1)
                type_total_period += total_period

                categories_data.append(
                    {
                        "id": c_id,
                        "name": c_name,
                        "total_period": total_period,
                        "monthly_avg": total_period / divisor,
                        "active_months": active_months_count,
                        "has_variation": False,
                        "months": monthly_breakdown,
                    }
                )

        # --- CAS 2 : CHARGES FIXES ---
        elif cat_type_key == CategoryType.RECURRING:
            type_txs = range_txs.filter(
                Q(category__type=CategoryType.RECURRING)
                | Q(recurring_expense__isnull=False)
            ).select_related("recurring_expense", "category")

            items_dict = {}
            for r in rec_expenses:
                items_dict[str(r.id)] = r.label

            for tx in type_txs:
                rec_id = getattr(tx, "recurring_expense_id", None)
                if rec_id and tx.recurring_expense:
                    items_dict[str(rec_id)] = tx.recurring_expense.label
                else:
                    lbl = tx.label or (tx.category.name if tx.category else "Autre")
                    items_dict[f"custom_{lbl}"] = lbl

            sorted_items = sorted(
                items_dict.items(), key=lambda x: remove_accents(x[1])
            )

            for item_id, item_name in sorted_items:
                if item_id.startswith("custom_"):
                    item_txs = type_txs.filter(
                        recurring_expense__isnull=True, label=item_name
                    )
                else:
                    item_txs = type_txs.filter(recurring_expense_id=item_id)

                total_period = get_net_amount(item_txs, "EXPENSE")

                monthly_breakdown = []
                active_months_count = 0

                prev_month_date = start_date.replace(day=1) - datetime.timedelta(days=1)
                if item_id.startswith("custom_"):
                    prev_qs = type_txs.filter(
                        recurring_expense__isnull=True,
                        label=item_name,
                        budget_month__year=prev_month_date.year,
                        budget_month__month=prev_month_date.month,
                    )
                else:
                    prev_qs = type_txs.filter(
                        recurring_expense_id=item_id,
                        budget_month__year=prev_month_date.year,
                        budget_month__month=prev_month_date.month,
                    )
                prev_amount = get_net_amount(prev_qs, "EXPENSE")

                for m_idx, m_date in enumerate(selected_months):
                    if item_id.startswith("custom_"):
                        curr_qs = type_txs.filter(
                            recurring_expense__isnull=True,
                            label=item_name,
                            budget_month__year=m_date.year,
                            budget_month__month=m_date.month,
                        )
                    else:
                        curr_qs = type_txs.filter(
                            recurring_expense_id=item_id,
                            budget_month__year=m_date.year,
                            budget_month__month=m_date.month,
                        )
                    m_amount = get_net_amount(curr_qs, "EXPENSE")

                    if m_amount != 0:
                        active_months_count += 1

                    if m_amount > prev_amount:
                        evo = "up"
                    elif m_amount < prev_amount:
                        evo = "down"
                    else:
                        evo = "same"

                    monthly_breakdown.append(
                        {"date": m_date, "amount": m_amount, "evolution": evo}
                    )
                    type_monthly_totals[m_idx] += float(m_amount)
                    prev_amount = m_amount

                if total_period != Decimal("0.00") or active_months_count > 0:
                    divisor = Decimal(active_months_count or 1)
                    type_total_period += total_period

                    active_amounts = [
                        m["amount"] for m in monthly_breakdown if m["amount"] != 0
                    ]
                    has_variation = len(set(active_amounts)) > 1

                    categories_data.append(
                        {
                            "id": item_id,
                            "name": item_name,
                            "total_period": total_period,
                            "monthly_avg": total_period / divisor,
                            "active_months": active_months_count,
                            "has_variation": has_variation,
                            "months": monthly_breakdown,
                        }
                    )

        # --- CAS 3 : ÉPARGNE ---
        elif cat_type_key == CategoryType.SAVINGS:
            savings_acc_dict = {}
            for acc in savings_accounts:
                savings_acc_dict[str(acc.id)] = acc.name

            for tr in range_transfers:
                dest_id = getattr(tr, "destination_account_id", None)
                src_id = getattr(tr, "source_account_id", None)

                if (
                    tr.destination_account
                    and tr.destination_account.account_type == AccountType.SAVINGS
                    and dest_id
                ):
                    savings_acc_dict[str(dest_id)] = tr.destination_account.name
                if (
                    tr.source_account
                    and tr.source_account.account_type == AccountType.SAVINGS
                    and src_id
                ):
                    savings_acc_dict[str(src_id)] = tr.source_account.name

            sorted_accounts = sorted(
                savings_acc_dict.items(), key=lambda x: remove_accents(x[1])
            )

            for acc_id, acc_name in sorted_accounts:
                monthly_breakdown = []
                active_months_count = 0
                total_period = Decimal("0.00")

                prev_month_date = start_date.replace(day=1) - datetime.timedelta(days=1)
                prev_amount = get_savings_month_amount(acc_id, prev_month_date)

                for m_idx, m_date in enumerate(selected_months):
                    m_amount = get_savings_month_amount(acc_id, m_date)

                    if m_amount != 0:
                        active_months_count += 1

                    if m_amount > prev_amount:
                        evo = "up"
                    elif m_amount < prev_amount:
                        evo = "down"
                    else:
                        evo = "same"

                    monthly_breakdown.append(
                        {"date": m_date, "amount": m_amount, "evolution": evo}
                    )
                    total_period += m_amount
                    type_monthly_totals[m_idx] += float(m_amount)
                    prev_amount = m_amount

                if total_period != Decimal("0.00") or active_months_count > 0:
                    divisor = Decimal(active_months_count or 1)
                    type_total_period += total_period

                    categories_data.append(
                        {
                            "id": acc_id,
                            "name": acc_name,
                            "total_period": total_period,
                            "monthly_avg": total_period / divisor,
                            "active_months": active_months_count,
                            "has_variation": False,
                            "months": monthly_breakdown,
                        }
                    )

        # --- TRI & PRÉPARATION DES DATASETS CHART.JS ---
        if cat_type_key == CategoryType.RECURRING:
            sorted_cats_for_chart = sorted(
                categories_data,
                key=lambda item: (
                    not item.get("has_variation", False),
                    -item["total_period"],
                ),
            )
        else:
            sorted_cats_for_chart = sorted(
                categories_data, key=lambda item: item["total_period"], reverse=True
            )

        cat_datasets = []
        has_any_variation = any(c.get("has_variation", False) for c in categories_data)

        for i, c in enumerate(sorted_cats_for_chart):
            cat_monthly_values = [float(m["amount"]) for m in c["months"]]
            has_var = c.get("has_variation", False)

            if cat_type_key == CategoryType.RECURRING and has_any_variation:
                is_hidden_by_default = not has_var
            else:
                is_hidden_by_default = i >= TOP_LIMIT

            cat_datasets.append(
                {
                    "label": f" {c['name']}",
                    "data": cat_monthly_values,
                    "borderColor": colors_palette[i % len(colors_palette)],
                    "backgroundColor": "transparent",
                    "pointBackgroundColor": colors_palette[i % len(colors_palette)],
                    "tension": 0.4,
                    "borderWidth": 2,
                    "pointRadius": 3,
                    "pointHitRadius": 10,
                    "hidden": is_hidden_by_default,
                    "hasVariation": has_var,
                }
            )

        period_summary.append(
            {
                "type_key": cat_type_key,
                "label": cat_type_label,
                "categories": sorted_cats_for_chart,
                "total_period": type_total_period,
                "monthly_avg": type_total_period / Decimal(nb_period_months),
            }
        )

        chart_data_combined["datasets"].append(
            {
                "label": f" {cat_type_label}",
                "data": type_monthly_totals,
                "borderColor": border_color,
                "backgroundColor": bg_color,
                "pointBackgroundColor": border_color,
                "fill": True,
                "tension": 0.4,
                "pointRadius": 3,
                "pointHitRadius": 10,
            }
        )

        individual_charts[cat_type_key] = {
            "labels": chart_labels,
            "datasets": cat_datasets,
        }

    available_months = []
    curr = start_boundary
    while curr <= end_boundary:
        available_months.append(curr)
        curr = advance_date(curr, 1)

    context = {
        "start_date": start_date,
        "end_date": end_date,
        "available_months": available_months,
        "selected_months": selected_months,
        "period_summary": period_summary,
        "chart_data_combined_json": json.dumps(chart_data_combined),
        "individual_charts_json": json.dumps(individual_charts),
        "breadcrumbs": ["Statistiques"],
    }

    return render(request, "budget/statistics/statistics_list.html", context)
