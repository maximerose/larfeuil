from typing import ClassVar

from django import forms

from budget.models.account import BankAccount


class BankAccountForm(forms.ModelForm):
    class Meta:
        model = BankAccount
        fields: ClassVar[str] = [
            "name",
            "account_type",
            "current_balance",
            "visibility",
            "is_default",
            "daily_meal_voucher_limit",
            "fallback_account",
        ]

    def __init__(self, *args, household, **kwargs):
        self.household = household
        super().__init__(*args, **kwargs)

        # On limite le compte relais aux autres comptes du même foyer
        if "fallback_account" in self.fields:
            self.fields["fallback_account"].queryset = BankAccount.objects.filter(
                owner__household=household,
                is_active=True,
            ).select_related("owner")

            # On empêche un compte d'être son propre relais en modification
            if self.instance and self.instance.pk:
                self.fields["fallback_account"].queryset = self.fields[
                    "fallback_account"
                ].queryset.exclude(pk=self.instance.pk)

    def clean_name(self):
        """Validation personnalisée du champ 'name'."""
        name = self.cleaned_data.get("name")
        if not name:
            return name

        name = name.strip()

        existing_accounts = BankAccount.objects.filter(
            owner__household=self.household, name__iexact=name
        )

        if self.instance and self.instance.pk:
            existing_accounts = existing_accounts.exclude(pk=self.instance.pk)

        existing = existing_accounts.first()

        if existing:
            if existing.is_active:
                raise forms.ValidationError(
                    "Un compte bancaire avec ce nom existe déjà dans votre foyer."
                )
            else:
                raise forms.ValidationError(
                    "Ce compte existe déjà mais a été supprimé. Choisissez un autre nom ou modifiez l'ancien."
                )

        return name
