from decimal import Decimal
from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from core.models import BaseModel

from .account import BankAccount
from .category import Category


class TransactionType(models.TextChoices):
    INCOME = "INCOME", "Revenu"
    EXPENSE = "EXPENSE", "Dépense"


class Transaction(BaseModel):
    transaction_date = models.DateField(default=timezone.localdate, verbose_name="Date")
    transaction_type = models.CharField(
        max_length=20,
        choices=TransactionType.choices,
        default=TransactionType.EXPENSE,
        verbose_name="Type",
    )
    budget_month = models.DateField(
        default=timezone.localdate,
        verbose_name="Mois associé",
        help_text="A renseigner si une transaction habituelle pour un mois a été reçue sur un autre mois (ex : le salaire qui tombe sur le mois d'après, un abonnement qui doit tomber le 1er et qui tombe le 30 du mois précédent)",
    )
    total_amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant"
    )

    label = models.CharField(
        max_length=100, blank=True, default="", verbose_name="Libellé"
    )
    comment = models.CharField(
        max_length=255, blank=True, default="", verbose_name="Commentaire"
    )
    category = models.ForeignKey(
        Category,
        on_delete=models.PROTECT,
        related_name="transactions",
        verbose_name="Catégorie",
        null=True,
        blank=True,
    )
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name="transactions",
        verbose_name="Compte associé",
    )
    recurring_expense = models.ForeignKey(
        "budget.RecurringExpense",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="transactions",
        verbose_name="Charge fixe",
    )
    meal_voucher_bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="meal_voucher_transactions",
        verbose_name="Compte Tickets Resto associé",
    )
    meal_voucher_amount = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.00"),
        verbose_name="Montant en Tickets Resto",
    )

    @property
    def fallback_amount(self) -> Decimal:
        """Retourne le montant réel débité du compte bancaire principal (hors Tickets Resto)."""
        return self.total_amount - self.meal_voucher_amount

    def get_transaction_type_display(self) -> str:
        """Implémentation explicite pour Pylance."""
        # On crée un dictionnaire purement textuel dict[str, str] à partir des choix
        choices_dict = {str(k): str(v) for k, v in TransactionType.choices}
        tx_value = str(self.transaction_type)

        return choices_dict.get(tx_value, tx_value)

    def __str__(self) -> str:
        sign = "+" if self.transaction_type == TransactionType.INCOME else "-"

        # On gère le cas où la catégorie est nulle
        if self.category:
            target_name = self.category.name
        elif self.recurring_expense:
            target_name = self.recurring_expense.label
        else:
            target_name = "Sans catégorie"

        return f"[{self.get_transaction_type_display()}] {self.transaction_date} - {target_name}: {sign}{self.total_amount} € ({self.label})"

    def clean(self) -> None:
        super().clean()
        # Règle métier : une transaction doit avoir une catégorie OU une charge fixe
        if not self.category and not self.recurring_expense:
            raise ValidationError(
                "Une transaction doit obligatoirement être rattachée à une catégorie ou à une charge fixe."
            )

    def save(self, *args, **kwargs) -> None:
        is_new = self._state.adding

        # Si la transaction existe déjà, on doit d'abord restaurer les anciens soldes
        if not is_new:
            old_self = Transaction.objects.get(pk=self.pk)

            if old_self.transaction_type == TransactionType.EXPENSE:
                old_self.bank_account.current_balance += (
                    old_self.total_amount - old_self.meal_voucher_amount
                )
                if (
                    old_self.meal_voucher_amount > 0
                    and hasattr(old_self, "meal_voucher_bank_account")
                    and old_self.meal_voucher_bank_account
                ):
                    old_self.meal_voucher_bank_account.current_balance += (
                        old_self.meal_voucher_amount
                    )
                    old_self.meal_voucher_bank_account.save(
                        update_fields=["current_balance"]
                    )
            elif old_self.transaction_type == TransactionType.INCOME:
                old_self.bank_account.current_balance -= old_self.total_amount

            old_self.bank_account.save(update_fields=["current_balance"])

        super().save(*args, **kwargs)

        # Application des nouveaux montants sur les comptes
        if self.transaction_type == TransactionType.EXPENSE:
            cash_amount = self.total_amount - self.meal_voucher_amount
            self.bank_account.current_balance -= cash_amount
            if (
                self.meal_voucher_amount > 0
                and hasattr(self, "meal_voucher_bank_account")
                and self.meal_voucher_bank_account
            ):
                self.meal_voucher_bank_account.current_balance -= (
                    self.meal_voucher_amount
                )
                self.meal_voucher_bank_account.save(update_fields=["current_balance"])
        elif self.transaction_type == TransactionType.INCOME:
            self.bank_account.current_balance += self.total_amount

        self.bank_account.save(update_fields=["current_balance"])

    def delete(self, *args, **kwargs):
        """Réajuste le solde du compte lors de la suppression d'une transaction."""
        if self.transaction_type == TransactionType.EXPENSE:
            self.bank_account.current_balance += (
                self.total_amount - self.meal_voucher_amount
            )

            # Stockage dans une variable locale pour que Pylance comprenne que ce n'est pas None
            mv_account = self.meal_voucher_bank_account
            if self.meal_voucher_amount > 0 and mv_account is not None:
                mv_account.current_balance += self.meal_voucher_amount
                mv_account.save(update_fields=["current_balance"])

        elif self.transaction_type == TransactionType.INCOME:
            self.bank_account.current_balance -= self.total_amount

        self.bank_account.save(update_fields=["current_balance"])
        super().delete(*args, **kwargs)

    class Meta(BaseModel.Meta):
        verbose_name = "Transaction"
        verbose_name_plural = "Transactions"
        ordering: ClassVar[list[str]] = ["-transaction_date", "-created_at"]


class Transfer(BaseModel):
    source_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="transfers_sent",
        verbose_name="Compte émetteur",
    )
    destination_account = models.ForeignKey(
        BankAccount,
        on_delete=models.PROTECT,
        related_name="transfers_received",
        verbose_name="Compte récepteur",
    )
    amount = models.DecimalField(
        max_digits=15, decimal_places=2, verbose_name="Montant"
    )
    date = models.DateField(default=timezone.localdate, verbose_name="Date")

    def __str__(self) -> str:
        return f"Transfert de {self.amount} € ({self.source_account.name} -> {self.destination_account.name})"

    def clean(self) -> None:
        super().clean()

        source_id = getattr(self, "source_account_id", None)
        dest_id = getattr(self, "destination_account_id", None)

        if source_id and source_id == dest_id:
            raise ValidationError(
                "Le compte source et le compte destination doivent être différents."
            )

    def save(self, *args, **kwargs) -> None:
        is_new = self._state.adding

        super().save(*args, **kwargs)

        if is_new:
            # Débiter le compte source
            self.source_account.current_balance -= self.amount
            self.source_account.save(update_fields=["current_balance"])

            # Créditer le compte destination
            self.destination_account.current_balance += self.amount
            self.destination_account.save(update_fields=["current_balance"])

    def delete(self, *args, **kwargs):
        """Réajuste les soldes lors de la suppression d'un transfert."""
        self.source_account.current_balance += self.amount
        self.source_account.save(update_fields=["current_balance"])

        self.destination_account.current_balance -= self.amount
        self.destination_account.save(update_fields=["current_balance"])

        super().delete(*args, **kwargs)

    class Meta(BaseModel.Meta):
        verbose_name = "Transfert"
        verbose_name_plural = "Transferts"
        ordering: ClassVar[list[str]] = ["-date", "-created_at"]
