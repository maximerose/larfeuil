from typing import ClassVar

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Case, Value, When

from budget.models.account import Household
from core.models import BaseModel, SoftDeleteModel


class CategoryType(models.TextChoices):
    RECURRING = "RECURRING", "Charge fixe"
    VARIABLE = "VARIABLE", "Charge variable"
    SAVINGS = "SAVINGS", "Épargne"
    INCOME = "INCOME", "Revenu"


class Category(BaseModel, SoftDeleteModel):
    household = models.ForeignKey(
        Household,
        on_delete=models.CASCADE,
        related_name="categories",
        null=True,
        blank=True,
        verbose_name="Foyer associé",
    )
    name = models.CharField(max_length=100, verbose_name="Nom de la catégorie")
    type = models.CharField(
        max_length=20,
        choices=CategoryType.choices,
        default=CategoryType.VARIABLE,
        verbose_name="Type de catégorie",
    )
    is_meal_voucher_eligible = models.BooleanField(
        default=False, verbose_name="Éligible aux Tickets Resto"
    )

    def __str__(self) -> str:
        return self.name

    def clean(self) -> None:
        super().clean()

        # Règle métier : Un revenu ou une épargne ne peut pas être éligible aux Tickets Resto
        if (
            self.type in [CategoryType.INCOME, CategoryType.SAVINGS]
            and self.is_meal_voucher_eligible
        ):
            raise ValidationError(
                "Un revenu ou une épargne ne peut pas être éligible aux tickets resto."
            )

    def save(self, *args, **kwargs) -> None:
        # Force l'appel de clean() lors d'un .save() programmatique si besoin
        self.full_clean()
        super().save(*args, **kwargs)

    class Meta(BaseModel.Meta, SoftDeleteModel.Meta):
        verbose_name = "Catégorie"
        verbose_name_plural = "Catégories"
        ordering: ClassVar[list] = [
            Case(
                When(type=CategoryType.RECURRING, then=Value(1)),
                When(type=CategoryType.VARIABLE, then=Value(2)),
                When(type=CategoryType.SAVINGS, then=Value(3)),
                When(type=CategoryType.INCOME, then=Value(4)),
                default=Value(5),
            ),
            "name",
        ]
