from django.contrib.auth import login
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render

from budget.forms import RegisterForm
from budget.models.account import Household, HouseholdInvitation, HouseholdMember
from budget.models.category import Category
from budget.models.recurring import RecurringExpense
from budget.utils import merge_categories


class AuthenticatedHttpRequest(HttpRequest):
    member: HouseholdMember | None


def join_household_view(request: AuthenticatedHttpRequest, token: str) -> HttpResponse:
    """Gère le clic sur un lien magique d'invitation."""
    invitation = get_object_or_404(HouseholdInvitation, token=token)

    if not invitation.is_valid:
        return render(request, "registration/invite_error.html", status=400)

    if request.user.is_authenticated:
        if request.method == "POST":
            member = request.member
            if member:
                with transaction.atomic():
                    old_household = member.household
                    new_household = invitation.household

                    if old_household and old_household != new_household:
                        # 1. Traitement des catégories (auto-merge)
                        old_categories = Category.objects.filter(
                            household=old_household, is_active=True
                        )

                        for old_cat in old_categories:
                            new_cat = Category.objects.filter(
                                household=new_household,
                                name__iexact=old_cat.name,
                                is_active=True,
                            ).first()

                            if new_cat:
                                merge_categories(old_cat, new_cat)
                            else:
                                old_cat.household = new_household
                                old_cat.save(update_fields=["household"])

                        # 2. Transfert des charges fixes
                        RecurringExpense.objects.filter(household=old_household).update(
                            household=new_household
                        )

                        # 3. Désactivation de l'ancien foyer s'il se retrouve vide
                        if (
                            not HouseholdMember.objects.filter(
                                household=old_household, is_active=True
                            )
                            .exclude(id=member.id)
                            .exists()
                        ):
                            old_household.is_active = False
                            old_household.save(update_fields=["is_active"])

                    # 4. Assigner le membre au nouveau foyer
                    member.household = new_household
                    member.save(update_fields=["household"])

                    invitation.accepted_by = request.user
                    invitation.save(update_fields=["accepted_by"])

                return redirect("dashboard")

        return render(
            request, "registration/invite_confirm.html", {"invitation": invitation}
        )

    request.session["invite_token"] = str(invitation.token)
    return redirect("register")


def register_view(request: HttpRequest) -> HttpResponse:
    if request.user.is_authenticated:
        return redirect("dashboard")

    if request.method == "POST":
        form = RegisterForm(request.POST)
        if form.is_valid():
            with transaction.atomic():
                user = form.save()
                display_name = form.cleaned_data.get("display_name")

                invitation = form.cleaned_data.get("valid_invitation")

                if not invitation:
                    token = request.session.get("invite_token")
                    if token:
                        invitation = HouseholdInvitation.objects.filter(
                            token=token, accepted_by__isnull=True
                        ).first()

                if invitation and invitation.is_valid:
                    household = invitation.household
                    invitation.accepted_by = user
                    invitation.save()
                    if "invite_token" in request.session:
                        del request.session["invite_token"]
                else:
                    household = Household.objects.create(
                        name=f"Foyer de {display_name}"
                    )

                HouseholdMember.objects.create(
                    name=display_name,
                    user=user,
                    household=household,
                )

            login(request, user)
            return redirect("dashboard")
    else:
        form = RegisterForm()

    return render(request, "registration/register.html", {"form": form})
