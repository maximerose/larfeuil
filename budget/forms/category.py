from typing import ClassVar

from django import forms

from budget.models import Category


class CategoryForm(forms.ModelForm):
    class Meta:
        model = Category
        fields: ClassVar[list[str]] = [
            "name",
            "type",
            "is_meal_voucher_eligible",
        ]

    def __init__(self, *args, household, member=None, **kwargs) -> None:
        self.household = household
        self.member = member
        super().__init__(*args, **kwargs)

    def clean_name(self):
        """Validation personnalisée du champ 'name'."""
        name = self.cleaned_data.get("name")
        if not name:
            return name

        # On enlève les espaces superflus avant et après
        name = name.strip()

        # On cherche une catégorie avec ce nom exact (insensible à la casse) dans le même foyer
        existing_categories = Category.objects.filter(
            household=self.household, name__iexact=name
        )

        # Si on est en train de modifier une catégorie existante, on s'exclut de la recherche
        if self.instance and self.instance.pk:
            existing_categories = existing_categories.exclude(pk=self.instance.pk)

        existing = existing_categories.first()

        if existing:
            if existing.is_active:
                raise forms.ValidationError(
                    "Une catégorie avec ce nom existe déjà dans votre foyer."
                )
            else:
                raise forms.ValidationError(
                    "Cette catégorie existe déjà mais a été supprimée. Choisissez un autre nom ou modifiez l'ancienne."
                )

        return name
