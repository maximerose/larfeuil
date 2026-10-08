from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from budget.models import BankAccount, HouseholdMember, Transaction, TransactionType
from budget.models.account import Household
from budget.models.category import Category, CategoryType
from budget.models.forecast import MonthlyForecast
from budget.models.recurring import RecurringExpense

User = get_user_model()


class CategoryMergeTestCase(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="maxime", password="password123")
        self.household = Household.objects.create(name="Foyer Test")
        self.member = HouseholdMember.objects.create(
            name="Maxime",
            household=self.household,
            user=self.user,
        )
        self.client.force_login(self.user)

        # Catégorie cible (celle qu'on garde)
        self.cat_target = Category.objects.create(
            name="Alimentation",
            type=CategoryType.VARIABLE,
            household=self.household,
        )

        # Catégorie source (celle qu'on va fusionner et supprimer)
        self.cat_source = Category.objects.create(
            name="Courses",
            type=CategoryType.VARIABLE,
            household=self.household,
        )

        today = timezone.localdate()

        account = BankAccount.objects.create(name="Compte", owner=self.member)

        # On attache des données à la catégorie source
        self.transaction = Transaction.objects.create(
            total_amount=Decimal("50.00"),
            category=self.cat_source,
            bank_account=account,
            transaction_type=TransactionType.EXPENSE,
        )
        self.forecast = MonthlyForecast.objects.create(
            month=today.replace(day=1),
            category=self.cat_source,
            member=self.member,
            amount=Decimal("200.00"),
        )
        self.recurring = RecurringExpense.objects.create(
            label="Panier Légumes",
            total_amount=Decimal("20.00"),
            category=self.cat_source,
            household=self.household,
        )

    def test_manual_category_merge(self) -> None:
        """Vérifie que la fusion réassigne toutes les données et désactive la catégorie source."""
        url = reverse("settings_category_merge", args=[self.cat_source.id])
        data = {"target_category": str(self.cat_target.id)}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        # Vérification 1 : La catégorie source est supprimée (soft-delete)
        self.cat_source.refresh_from_db()
        self.assertFalse(self.cat_source.is_active)

        # Vérification 2 : Les données ont été transférées vers la cible
        self.transaction.refresh_from_db()
        self.assertEqual(self.transaction.category, self.cat_target)

        self.forecast.refresh_from_db()
        self.assertEqual(self.forecast.category, self.cat_target)

        self.recurring.refresh_from_db()
        self.assertEqual(self.recurring.category, self.cat_target)
