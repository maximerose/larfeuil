from decimal import Decimal
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models

from core.models import BaseModel, SoftDeleteModel, Visibility

from .account import BankAccount, Household, HouseholdMember
from .category import Category


class RecurringExpenseStatus(models.TextChoices):
    WAITING = "WAITING", "En attente"
    PARTIAL = "PARTIAL", "Partiellement payé"
    COMPLETED = "COMPLETED", "Soldé"


class RecurringExpense(BaseModel, SoftDeleteModel):
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="recurring_expenses",
        null=True,
        blank=True,
        verbose_name="Foyer",
    )
    owner = models.ForeignKey(
        HouseholdMember,
        on_delete=models.CASCADE,
        related_name="personal_recurring_expenses",
        null=True,
        blank=True,
        verbose_name="Propriétaire (Laisser vide si charge commune)",
    )
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.SHARED,
        verbose_name="Visibilité",
        help_text="Une charge privée ne sera visible que par son propriétaire.",
    )
    label = models.CharField(max_length=100, verbose_name="Nom")
    total_amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant"
    )
    usual_due_day = models.DateField(
        null=True, blank=True, verbose_name="Date de prélèvement"
    )
    frequency_months = models.PositiveIntegerField(
        default=1, verbose_name="Fréquence (tous les X mois)"
    )
    is_variable = models.BooleanField(
        default=False,
        verbose_name="Variable",
        help_text="Le montant peut-il varier d'un mois à l'autre ? (ex : Facture d'éléctricité)",
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recurring_expenses",
        verbose_name="Catégorie",
    )
    default_bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="recurring_expenses",
        verbose_name="Compte prélevé par défaut",
    )

    def __str__(self) -> str:
        return f"{self.label} ({self.total_amount} €)"

    def get_remaining_amount_to_split(self) -> Decimal:
        """Calcule le montant qu'il reste à assigner parmi les parts."""
        # Résolution propre sans passer par le reverse accessor magique
        allocated = RecurringExpenseShare.objects.filter(
            recurring_expense=self
        ).aggregate(models.Sum("amount"))["amount__sum"] or Decimal("0.00")
        return self.total_amount - allocated

    class Meta(BaseModel.Meta, SoftDeleteModel.Meta):
        verbose_name = "Charge récurrente"
        verbose_name_plural = "Charges récurrentes"
        ordering: ClassVar[list[str]] = ["label"]


class RecurringExpenseShare(BaseModel, SoftDeleteModel):
    recurring_expense = models.ForeignKey(
        RecurringExpense,
        on_delete=models.CASCADE,
        related_name="shares",
        verbose_name="Charge fixe",
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name="expense_shares",
        verbose_name="Compte associé",
    )
    amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant"
    )

    def __str__(self) -> str:
        return f"{self.recurring_expense.label} - {self.bank_account.name}: {self.amount} €"

    def clean(self) -> None:
        super().clean()

        # Validation propre via getattr pour éviter l'alerte Pylance
        if getattr(self, "recurring_expense_id", None) is None:
            return

        existing_shares_sum = RecurringExpenseShare.objects.filter(
            recurring_expense=self.recurring_expense
        ).exclude(pk=self.pk).aggregate(models.Sum("amount"))["amount__sum"] or Decimal(
            "0.00"
        )

        total_with_this_share = existing_shares_sum + self.amount

        if total_with_this_share > self.recurring_expense.total_amount:
            raise ValidationError(
                f"La somme des parts ({total_with_this_share} €) dépasse le montant total de la charge ({self.recurring_expense.total_amount} €)."
            )

    class Meta(BaseModel.Meta, SoftDeleteModel.Meta):
        verbose_name = "Répartition de dépense"
        verbose_name_plural = "Répartitions de dépenses"
