from typing import ClassVar

from django import forms
from django.forms import ModelChoiceField

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
        self,
        *args,
        household: Household,
        member: HouseholdMember | None = None,
        **kwargs,
    ) -> None:
        self.household = household
        self.member = member
        super().__init__(*args, **kwargs)

        # Restreindre aux catégories "Récurrentes" du foyer
        cat_field = self.fields.get("category")
        if isinstance(cat_field, ModelChoiceField):
            cat_field.queryset = Category.objects.filter(
                household=household,
                type=CategoryType.RECURRING,
                is_active=True,
            )

        # Restreindre aux comptes du foyer
        acc_field = self.fields.get("default_bank_account")
        if isinstance(acc_field, ModelChoiceField):
            acc_field.queryset = BankAccount.objects.filter(
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


class RecurringExpenseUpdateForm(RecurringExpenseForm):
    """Formulaire allégé pour l'édition : hérite du formulaire principal et restreint les champs."""

    class Meta(RecurringExpenseForm.Meta):
        fields: ClassVar[list[str]] = [
            "label",
            "total_amount",
            "default_bank_account",
            "usual_due_day",
        ]


class RecurringExpenseShareForm(forms.ModelForm):
    class Meta:
        model = RecurringExpenseShare
        fields: ClassVar[list[str]] = ["bank_account", "amount"]

    def __init__(self, *args, household: Household, **kwargs) -> None:
        super().__init__(*args, **kwargs)

        cat_field = self.fields.get("category")
        if isinstance(cat_field, ModelChoiceField):
            cat_field.required = False
            cat_field.queryset = Category.objects.filter(
                household=household,
                type=CategoryType.RECURRING,
                is_active=True,
            )

        acc_field = self.fields.get("default_bank_account")
        if isinstance(acc_field, ModelChoiceField):
            acc_field.queryset = BankAccount.objects.filter(
                owner__household=household,
                is_active=True,
            )
