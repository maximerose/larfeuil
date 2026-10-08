import datetime
import random
import string
from decimal import Decimal
from typing import ClassVar

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, Value, When
from django.utils import timezone

from core.models import BaseModel, SoftDeleteModel, Visibility


def generate_short_token():
    """Génère un code alphanumérique de 6 caractères (ex: A7B9X2)."""
    return "".join(random.choices(string.ascii_uppercase + string.digits, k=6))


class Household(BaseModel, SoftDeleteModel):
    name = models.CharField(
        max_length=100,
        verbose_name="Nom du foyer",
        default="Mon foyer",
    )

    def __str__(self) -> str:
        return self.name

    class Meta(BaseModel.Meta, SoftDeleteModel.Meta):
        verbose_name = ("Foyer",)
        verbose_name_plural = "Foyers"
        ordering: ClassVar[list[str]] = ["name"]


class HouseholdMember(BaseModel, SoftDeleteModel):
    name = models.CharField(max_length=100)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="%(class)s_user",
    )
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="members",
        null=True,
        blank=True,
        verbose_name="Foyer",
    )

    def __str__(self) -> str:
        if self.user:
            return f"{self.name} (@{self.user.username})"
        return self.name

    class Meta(BaseModel.Meta, SoftDeleteModel.Meta):
        verbose_name = "Membre du foyer"
        verbose_name_plural = "Membres du foyer"
        ordering: ClassVar[list[str]] = ["name"]


class HouseholdInvitation(BaseModel):
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="invitations",
        verbose_name="Foyer",
    )
    token = models.CharField(
        max_length=10,
        default=generate_short_token,
        editable=False,
        unique=True,
        verbose_name="Code Foyer",
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="accepted_invitations",
        verbose_name="Accepté par",
    )

    @property
    def is_valid(self) -> bool:
        """Une invitation est valide 48h et si elle n'a pas encore été acceptée."""
        if self.accepted_by is not None:
            return False

        expiration_date = self.created_at + datetime.timedelta(hours=48)

        return timezone.now() <= expiration_date

    def __str__(self) -> str:
        status = "Acceptée" if self.accepted_by else "En attente"

        return f"Invitation pour {self.household.name} ({status})"


class AccountType(models.TextChoices):
    CHECKING = "CHECKING", "Compte courant"
    SAVINGS = "SAVINGS", "Compte épargne"
    CASH = "CASH", "Espèces"
    BUSINESS = "BUSINESS", "Compte pro"
    MEAL_VOUCHER = "MEAL_VOUCHER", "Tickets resto"
    OTHER = "OTHER", "Autre"


class BankAccount(BaseModel, SoftDeleteModel):
    name = models.CharField(max_length=100, verbose_name="Nom du compte")
    account_type = models.CharField(
        max_length=20,
        choices=AccountType.choices,
        default=AccountType.CHECKING,
        verbose_name="Type de compte",
    )
    owner = models.ForeignKey(
        HouseholdMember,
        on_delete=models.CASCADE,
        related_name="bank_accounts",
        verbose_name="Propriétaire du compte",
    )
    visibility = models.CharField(
        max_length=20,
        choices=Visibility.choices,
        default=Visibility.SHARED,
        verbose_name="Visibilité",
        help_text="Un compte privé ne sera visible que par son propriétaire.",
    )
    current_balance = models.DecimalField(
        max_digits=15,
        decimal_places=2,
        default=Decimal("0.0"),
        verbose_name="Solde actuel",
    )
    daily_meal_voucher_limit = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        verbose_name="Limite quotidienne de tickets resto",
        help_text="Si c'est un compte Tickets Resto, renseignez la limite quotidienne (ex : 25€)",
    )
    is_default = models.BooleanField(default=False, verbose_name="Compte par défaut")
    fallback_account = models.ForeignKey(
        "self",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="fallback_for",
        verbose_name="Compte relais",
        help_text="Si ce compte est un compte Tickets Resto, alors vous pouvez renseigner un autre compte qui fait la bascule lors d'un paiement d'un montant supérieur à la limite quotidienne",
    )
    is_joint = models.BooleanField(
        default=False,
        verbose_name="Compte joint",
        help_text="Cochez si ce compte est co-détenu par le foyer.",
    )

    def __str__(self) -> str:
        account_type_label = AccountType(self.account_type).label
        owner_display = (
            f"(@{self.owner.user.username})" if self.owner.user else self.owner.name
        )
        return f"{self.name} ({account_type_label}) {owner_display}"

    def clean(self) -> None:
        super().clean()
        if self.account_type == AccountType.MEAL_VOUCHER:
            if not self.daily_meal_voucher_limit:
                self.daily_meal_voucher_limit = Decimal("25.00")
        else:
            self.daily_meal_voucher_limit = None

        if self.is_default and self.account_type != AccountType.CHECKING:
            raise ValidationError(
                {
                    "is_default": "Seul un compte courant peur être défini comme compte par défaut",
                }
            )

    def save(self, *args, **kwargs) -> None:
        self.full_clean()
        super().save(*args, **kwargs)

        #  Si ce compte est défini par défaut, on retire le flag aux autres comptes du même propriétaire
        if self.is_default:
            BankAccount.objects.filter(owner=self.owner, is_default=True).exclude(
                pk=self.pk
            ).update(is_default=False)

    class Meta(BaseModel.Meta, SoftDeleteModel.Meta):
        verbose_name = "Compte bancaire"
        verbose_name_plural = "Comptes bancaires"

        # Le tri natif en base de données géré par Django !
        ordering: ClassVar[list] = [
            Case(
                When(account_type=AccountType.CHECKING, then=Value(1)),
                When(account_type=AccountType.MEAL_VOUCHER, then=Value(2)),
                When(account_type=AccountType.SAVINGS, then=Value(3)),
                When(account_type=AccountType.BUSINESS, then=Value(4)),
                default=Value(5),
            ),
            "-is_default",  # Entre deux comptes courants, le "par défaut" gagne
            "name",  # Et enfin on trie par ordre alphabétique
        ]


class AccountSnapshot(BaseModel):
    bank_account = models.ForeignKey(
        BankAccount,
        on_delete=models.CASCADE,
        related_name="snapshots",
        verbose_name="Compte associé",
    )
    balance = models.DecimalField(max_digits=15, decimal_places=2, verbose_name="Solde")
    date = models.DateField(default=timezone.localdate, verbose_name="Date")

    def __str__(self) -> str:
        return f"{self.bank_account.name} - {self.balance} € au {self.date}"

    class Meta(BaseModel.Meta):
        verbose_name = "Relevé de compte (Snapshot)"
        verbose_name_plural = "Relevés de comptes (Snapshots)"
        ordering: ClassVar[list[str]] = ["-date"]
        constraints: ClassVar[list[models.UniqueConstraint]] = [
            models.UniqueConstraint(
                fields=["bank_account", "date"], name="unique_daily_account_snapshot"
            )
        ]
