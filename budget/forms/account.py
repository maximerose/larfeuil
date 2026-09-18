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

        # 1. Coupe-circuit : on ne valide pas si le nom n'a pas été modifié
        if self.instance and self.instance.pk and self.instance.name == name:
            return name

        # 2. Récupération sécurisée de l'ID du propriétaire (inexistant lors d'une création pure)
        owner_id = getattr(self.instance, "owner_id", None)

        # 3. Validation de l'unicité ciblée sur le membre
        if owner_id:
            existing = (
                BankAccount.objects.filter(owner_id=owner_id, name__iexact=name)
                .exclude(pk=self.instance.pk)
                .first()
            )

            if existing:
                if existing.is_active:
                    raise forms.ValidationError(
                        "Vous possédez déjà un compte bancaire avec ce nom."
                    )
                else:
                    raise forms.ValidationError(
                        "Ce compte existe déjà mais a été supprimé. Choisissez un autre nom ou modifiez l'ancien."
                    )

        return name
