from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from budget.models.recurring import RecurringExpense
from core.models import BaseModel, SoftDeleteModel, Visibility

from .account import AccountType, BankAccount, HouseholdMember
from .category import Category, CategoryType


class MonthlyForecast(BaseModel, SoftDeleteModel):
    month = models.DateField(
        default=timezone.localdate,
        verbose_name="Mois",
    )
    member = models.ForeignKey(
        HouseholdMember,
        on_delete=models.CASCADE,
        related_name="forecasts",
        verbose_name="Utilisateur associé",
    )
    amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        verbose_name="Montant de la prévision",
    )

    # Option A : Pour les dépenses et les revenus
    category = models.ForeignKey(
        Category,
        on_delete=models.CASCADE,
        related_name="forecasts",
        null=True,
        blank=True,
        verbose_name="Catégorie (Dépenses / Revenus)",
        limit_choices_to={"type__in": [CategoryType.VARIABLE, CategoryType.INCOME]},
    )

    # Option B : Pour l'épargne
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name="savings_forecasts",
        null=True,
        blank=True,
        verbose_name="Compte cible (Épargne)",
        limit_choices_to={"account_type": AccountType.SAVINGS},
    )

    # Option C : Override d'une charge récurrente
    recurring_expense = models.ForeignKey(
        RecurringExpense,
        on_delete=models.CASCADE,
        related_name="forecast_overrides",
        null=True,
        blank=True,
        verbose_name="Charge fixe (Exception mensuelle)",
    )

    # Compte sur lequel l'opération (débit ou crédit) va se réaliser ce mois-ci
    transaction_account = models.ForeignKey(
        "BankAccount",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="forecast_transactions",
        verbose_name="Compte ciblé (Optionnel)",
    )
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.SHARED,
        verbose_name="Visibilité",
    )

    def __str__(self) -> str:
        if self.category:
            target = self.category.name
        elif self.bank_account:
            target = self.bank_account.name
        elif self.recurring_expense:
            target = self.recurring_expense.label
        else:
            target = "Non défini"

        return f"{self.member.name} - {target} ({self.month.strftime('%m/%Y')}): {self.amount} €"

    def clean(self) -> None:
        super().clean()
        # On vérifie qu'exactement UN SEUL des trois champs est rempli
        filled_fields = sum(
            [bool(self.category), bool(self.bank_account), bool(self.recurring_expense)]
        )

        if filled_fields != 1:
            raise ValidationError(
                "Une prévision doit cibler EXACTEMENT UNE de ces options : Catégorie, Compte bancaire, ou Charge fixe."
            )

    class Meta(BaseModel.Meta, SoftDeleteModel.Meta):
        verbose_name = "Prévision mensuelle"
        verbose_name_plural = "Prévisions mensuelles"
        constraints: ClassVar[list[models.UniqueConstraint]] = [
            models.UniqueConstraint(
                fields=["month", "category", "member"],
                name="unique_monthly_category_forecast_per_member",
            )
        ]
        ordering: ClassVar[list[str]] = [
            "-month",
            "category__name",
            "bank_account__name",
        ]
