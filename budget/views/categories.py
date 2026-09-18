from urllib.request import Request

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, render

from budget.forms.category import CategoryForm
from budget.models import Category
from budget.utils import htmx_login_required, merge_categories


@login_required
def settings_categories_list_view(request: Request) -> HttpResponse:
    member = request.member
    categories = Category.objects.filter(household=member.household, is_active=True)

    return render(
        request,
        "budget/settings/category_list.html",
        {
            "categories": categories,
            "member": member,
            "breadcrumbs": ["Paramètres", "Catégories"],
        },
    )


@htmx_login_required
def settings_category_form_view(
    request: Request, category_id: str | None = None
) -> HttpResponse:
    member = request.member
    category = None

    if category_id:
        category = get_object_or_404(
            Category, id=category_id, household=member.household, is_active=True
        )

    if request.method == "POST":
        form = CategoryForm(
            request.POST,
            instance=category,
            household=member.household,
            member=member,
        )
        if form.is_valid():
            new_category = form.save(commit=False)
            if not category_id:
                new_category.household = member.household
                if member.user:
                    new_category.created_by = member.user
            new_category.save()

            messages.success(
                request, "Catégorie créée" if not category_id else "Catégorie modifiée"
            )

            response = HttpResponse("")
            response["HX-Refresh"] = "true"

            return response
    else:
        form = CategoryForm(
            instance=category,
            household=member.household,
            member=member,
        )

    return render(
        request,
        "budget/components/modal.html",
        {
            "modal_title": "Modifier la catégorie"
            if category
            else "Nouvelle catégorie",
            "modal_icon": "tag",
            "has_cancel": True,
            "has_save": True,
            "form_id": "category-form",
            "modal_content_template": "budget/partials/settings/_modal_category_form.html",
            "form": form,
            "category": category,
        },
    )


@htmx_login_required
def settings_category_delete_view(request: Request, category_id: str) -> HttpResponse:
    member = request.member
    category = get_object_or_404(
        Category, id=category_id, household=member.household, is_active=True
    )

    if request.method == "POST":
        category.is_active = False
        category.save(update_fields=["is_active"])

        messages.success(request, "Catégorie supprimée")

        response = HttpResponse("")
        response["HX-Refresh"] = "true"

        return response

    return HttpResponse("Méthode non autorisée", status=405)


@htmx_login_required
def settings_category_merge_view(request: Request, category_id: str) -> HttpResponse:
    member = request.member
    source_category = get_object_or_404(
        Category,
        id=category_id,
        household=member.household,
        is_active=True,
    )

    if request.method == "POST":
        target_id = request.POST.get("target_category")
        target_category = get_object_or_404(
            Category,
            id=target_id,
            household=member.household,
            is_active=True,
        )

        if source_category.id == target_category.id:
            return HttpResponse(
                "Impossible de fusionner une catégorie avec elle-même", status=400
            )

        with transaction.atomic():
            merge_categories(source_category, target_category)

        response = HttpResponse("")
        response["HX-Refresh"] = "true"

        return response

    categories = Category.objects.filter(
        household=member.household, is_active=True
    ).exclude(id=source_category.id)

    return render(
        request,
        "budget/components/modal.html",
        {
            "modal_title": f"Fusionner '{source_category.name}'",
            "modal_icon": "link",
            "has_cancel": True,
            "has_save": True,
            "save_text": "Fusionner",
            "form_id": "category-merge-form",
            "modal_content_template": "budget/partials/settings/_modal_category_merge.html",
            "source_category": source_category,
            "categories": categories,
        },
    )
