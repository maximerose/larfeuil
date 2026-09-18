from typing import ClassVar

from django import forms

from budget.models import BankAccount, Category, RecurringExpense
from budget.models.account import Household, HouseholdMember
from budget.models.category import CategoryType
from budget.models.recurring import RecurringExpenseShare


class RecurringExpenseForm(forms.ModelForm):
    class Meta:
        model = RecurringExpense
        fields: ClassVar[list[str]] = [
            "label",
            "total_amount",
            "category",
            "default_bank_account",
            "visibility",
            "is_variable",
            "frequency_months",
            "usual_due_day",
        ]

    def __init__(
        self, *args, household: Household, member: HouseholdMember, **kwargs
    ) -> None:
        self.household = household
        self.member = member
        super().__init__(*args, **kwargs)

        # Restreindre aux catégories "Récurrentes" du foyer
        if "category" in self.fields:
            self.fields["category"].queryset = Category.objects.filter(
                household=household,
                type=CategoryType.RECURRING,
                is_active=True,
            )

        # Restreindre aux comptes du foyer
        if "default_bank_account" in self.fields:
            self.fields["default_bank_account"].queryset = BankAccount.objects.filter(
                owner__household=household,
                is_active=True,
            )

    def clean_label(self):
        """Validation personnalisée du champ 'label'."""
        label = self.cleaned_data.get("label")
        if not label:
            return label

        label = label.strip()

        existing_expenses = RecurringExpense.objects.filter(
            household=self.household,
            owner=self.member,
            label__iexact=label,
        )

        if self.instance and self.instance.pk:
            existing_expenses = existing_expenses.exclude(pk=self.instance.pk)

        existing = existing_expenses.first()

        if existing:
            if existing.is_active:
                raise forms.ValidationError(
                    "Vous avez déjà une charge fixe avec ce nom."
                )
            else:
                raise forms.ValidationError(
                    "Cette charge fixe existe déjà mais a été supprimée. Choisissez un autre nom ou réactivez l'ancienne."
                )

        return label


class RecurringExpenseShareForm(forms.ModelForm):
    class Meta:
        model = RecurringExpenseShare
        fields: ClassVar[list[str]] = ["bank_account", "amount"]

    def __init__(self, *args, household: Household, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        # Rend le champ catégorie optionnel
        if "category" in self.fields:
            self.fields["category"].required = False
            self.fields["category"].queryset = Category.objects.filter(
                household=household,
                type=CategoryType.RECURRING,
                is_active=True,
            )

        # Restreindre aux comptes du foyer
        if "default_bank_account" in self.fields:
            self.fields["default_bank_account"].queryset = BankAccount.objects.filter(
                owner__household=household,
                is_active=True,
            )
