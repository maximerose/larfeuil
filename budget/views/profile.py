from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpRequest, HttpResponse
from django.shortcuts import render
from django.urls import reverse

from budget.models import Household, HouseholdMember
from budget.models.account import HouseholdInvitation
from budget.utils import htmx_login_required


class AuthenticatedHttpRequest(HttpRequest):
    member: HouseholdMember
    household: Household


@login_required
def settings_profile_view(request: AuthenticatedHttpRequest) -> HttpResponse:
    member = request.member
    household = request.household

    invitations = HouseholdInvitation.objects.filter(
        household=household,
        accepted_by__isnull=True,
    ).order_by("-created_at")

    valid_invitation = next((inv for inv in invitations if inv.is_valid), None)

    invite_url = None
    invite_code = None

    if valid_invitation:
        invite_code = valid_invitation.token
        invite_url = request.build_absolute_uri(
            reverse("join_household", args=[valid_invitation.token])
        )

    return render(
        request,
        "budget/settings/profile_list.html",
        {
            "member": member,
            "household": household,
            "invite_url": invite_url,
            "invite_code": invite_code,
            "breadcrumbs": ["Paramètres", "Foyer & profil"],
        },
    )


@htmx_login_required
def settings_profile_update(request: AuthenticatedHttpRequest) -> HttpResponse:
    member = request.member

    if request.method == "POST":
        name = request.POST.get("name")
        email = request.POST.get("email")

        with transaction.atomic():
            if name:
                member.name = name
                member.save(update_fields=["name"])

            # Utilisation directe de member.user pour garantir le type User auprès de Pylance
            if email and member.user:
                user = member.user
                user.email = email
                user.save(update_fields=["email"])

        response = HttpResponse("")
        response["HX-Refresh"] = "true"

        return response

    return HttpResponse("Méthode non autorisée", status=405)


@htmx_login_required
def settings_household_update(request: AuthenticatedHttpRequest) -> HttpResponse:
    member = request.member

    if request.method == "POST":
        name = request.POST.get("name")
        if name and member.household:
            member.household.name = name
            member.household.save(update_fields=["name"])

        response = HttpResponse("")
        response["HX-Refresh"] = "true"
        return response

    return HttpResponse("Méthode non autorisée", status=405)


@htmx_login_required
def settings_generate_invite(request: AuthenticatedHttpRequest) -> HttpResponse:
    member = request.member

    if request.method == "POST":
        user = member.user or (request.user if request.user.is_authenticated else None)
        HouseholdInvitation.objects.create(
            household=member.household,
            created_by=user,
        )

        response = HttpResponse("")
        response["HX-Refresh"] = "true"

        return response

    return HttpResponse("Méthode non autorisée", status=405)
