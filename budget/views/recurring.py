from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, render
from django.views.decorators.http import require_GET, require_http_methods

from budget.forms.recurring import (
    RecurringExpenseForm,
    RecurringExpenseShareForm,
    RecurringExpenseUpdateForm,
)
from budget.models import Household, HouseholdMember, RecurringExpense
from budget.models.account import BankAccount
from budget.models.recurring import RecurringExpenseShare
from budget.services.forecast import get_recurring_expenses_with_status
from budget.utils import get_target_month_from_request, htmx_login_required
from core.models import Visibility


class AuthenticatedHttpRequest(HttpRequest):
    member: HouseholdMember
    household: Household


@login_required
@require_GET
def settings_recurring_list_view(request: AuthenticatedHttpRequest) -> HttpResponse:
    member = request.member
    household = request.household
    today = get_target_month_from_request(request)

    recurring_expenses = get_recurring_expenses_with_status(
        member, today, include_all=True
    )

    has_multiple_members = (
        HouseholdMember.objects.filter(household=household, is_active=True).count() > 1
    )

    return render(
        request,
        "budget/settings/recurring_list.html",
        {
            "recurring_expenses": recurring_expenses,
            "has_multiple_members": has_multiple_members,
            "member": member,
            "breadcrumbs": ["Paramètres", "Charges fixes"],
        },
    )


@htmx_login_required
@require_http_methods(["GET", "POST"])
def settings_recurring_form_view(
    request: AuthenticatedHttpRequest, expense_id: str | None = None
) -> HttpResponse:
    member = request.member
    household = request.household
    expense = None

    if expense_id:
        expense = get_object_or_404(
            RecurringExpense, id=expense_id, household=household, is_active=True
        )

    form_class = RecurringExpenseUpdateForm if expense else RecurringExpenseForm

    if request.method == "POST":
        form = form_class(
            request.POST, instance=expense, household=household, member=member
        )
        if form.is_valid():
            rec = form.save(commit=False)
            if not expense:
                rec.household = household
                rec.owner = member if rec.visibility == Visibility.PRIVATE else None
            rec.save()

            messages.success(request, "Charge fixe enregistrée")
            response = HttpResponse("")
            response["HX-Refresh"] = "true"
            return response
    else:
        form = form_class(instance=expense, household=household, member=member)

    return render(
        request,
        "budget/components/modal.html",
        {
            "modal_title": "Modifier la charge" if expense else "Nouvelle charge fixe",
            "modal_icon": "calendar",
            "has_cancel": True,
            "has_save": True,
            "form_id": "recurring-form",
            "modal_content_template": "budget/partials/settings/_modal_recurring_form.html",
            "form": form,
            "expense": expense,
        },
    )


@htmx_login_required
def settings_recurring_delete_view(
    request: AuthenticatedHttpRequest, expense_id: str
) -> HttpResponse:
    household = request.household
    expense = get_object_or_404(
        RecurringExpense, id=expense_id, household=household, is_active=True
    )

    if request.method == "POST":
        expense.is_active = False
        expense.save(update_fields=["is_active"])

        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    return HttpResponse("Méthode non autorisée", status=405)


@htmx_login_required
def settings_recurring_shares_view(
    request: AuthenticatedHttpRequest, expense_id: str
) -> HttpResponse:
    member = request.member
    household = request.household
    expense = get_object_or_404(
        RecurringExpense,
        id=expense_id,
        household=household,
        is_active=True,
    )
    shares = RecurringExpenseShare.objects.filter(
        recurring_expense=expense, is_active=True
    )
    remaining = expense.get_remaining_amount_to_split()

    accounts = BankAccount.objects.filter(owner__household=household, is_active=True)
    account_options = [
        {
            "id": acc.id,
            "name": f"{acc.name} ({acc.owner.name})"
            if getattr(acc, "owner_id", None) != member.id
            else acc.name,
        }
        for acc in accounts
    ]

    if request.method == "POST":
        form = RecurringExpenseShareForm(request.POST, household=household)

        if form.is_valid():
            share = form.save(commit=False)
            share.recurring_expense = expense

            try:
                share.full_clean()
                share.save()

                if expense.visibility == Visibility.PRIVATE:
                    expense.visibility = Visibility.SHARED
                    expense.save(update_fields=["visibility"])

                response = HttpResponse("")
                response["HX-Refresh"] = "true"

                return response
            except ValidationError as e:
                form.add_error(None, e)
    else:
        form = RecurringExpenseShareForm(household=household)

    members_count = HouseholdMember.objects.filter(
        household=household, is_active=True
    ).count()
    if members_count > 0:
        ideal_share = Decimal(str(round(expense.total_amount / members_count, 2)))
    else:
        ideal_share = expense.total_amount

    suggested_amount = min(ideal_share, remaining)

    return render(
        request,
        "budget/components/modal.html",
        {
            "modal_title": f"Répartition : {expense.label}",
            "modal_icon": "arrows-right-left",
            "has_cancel": True,
            "has_save": False,
            "modal_content_template": "budget/partials/settings/_modal_recurring_shares.html",
            "form": form,
            "expense": expense,
            "shares": shares,
            "remaining": remaining,
            "suggested_amount": suggested_amount,
            "member": member,
            "account_options": account_options,
        },
    )


@htmx_login_required
def settings_recurring_share_delete_view(
    request: AuthenticatedHttpRequest, expense_id: str, share_id: str
) -> HttpResponse:
    household = request.household
    expense = get_object_or_404(
        RecurringExpense, id=expense_id, household=household, is_active=True
    )
    share = get_object_or_404(
        RecurringExpenseShare, id=share_id, recurring_expense=expense, is_active=True
    )

    if request.method == "POST":
        share.is_active = False
        share.save(update_fields=["is_active"])
        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    return HttpResponse("Méthode non autorisée", status=405)
