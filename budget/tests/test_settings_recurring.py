from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget.models.account import (
    AccountType,
    BankAccount,
    Household,
    HouseholdMember,
)
from budget.models.category import Category, CategoryType
from budget.models.recurring import RecurringExpense
from core.models import Visibility

User = get_user_model()


class SettingsRecurringTestCase(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="maxime", password="password123")
        self.household = Household.objects.create(name="Foyer Test")
        self.member = HouseholdMember.objects.create(
            name="Maxime",
            household=self.household,
            user=self.user,
        )
        self.client.force_login(self.user)

        self.account = BankAccount.objects.create(
            name="Compte Courant",
            account_type=AccountType.CHECKING,
            owner=self.member,
        )

        self.category = Category.objects.create(
            name="Logement",
            type=CategoryType.RECURRING,
            household=self.household,
        )

        self.expense = RecurringExpense.objects.create(
            label="Assurance Habitation",
            total_amount=Decimal("25.00"),
            frequency_months=1,
            category=self.category,
            default_bank_account=self.account,
            household=self.household,
            visibility=Visibility.SHARED,
        )

    def test_recurring_list_view(self) -> None:
        """Vérifie l'affichage de la liste des charges fixes."""
        url = reverse("settings_recurring")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "budget/settings/recurring_list.html")
        self.assertIn("recurring_expenses", response.context)

    def test_recurring_create_get(self) -> None:
        """Vérifie l'affichage du formulaire de création de charge fixe."""
        url = reverse("settings_recurring_create")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "budget/partials/settings/_modal_recurring_form.html"
        )

    def test_recurring_create_post(self) -> None:
        """Vérifie la création d'une nouvelle charge fixe via POST."""
        url = reverse("settings_recurring_create")
        data = {
            "label": "Abonnement Internet",
            "total_amount": "30.00",
            "frequency_months": 1,
            "category": self.category.id,
            "default_bank_account": self.account.id,
            "visibility": Visibility.SHARED,
            "is_variable": False,
        }
        response = self.client.post(url, data)

        # HTMX doit nous renvoyer un header de rafraîchissement
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        # La charge doit bien avoir été créée et rattachée au foyer
        self.assertEqual(RecurringExpense.objects.count(), 2)
        new_expense = RecurringExpense.objects.get(label="Abonnement Internet")
        self.assertEqual(new_expense.total_amount, Decimal("30.00"))
        self.assertEqual(new_expense.household, self.household)

    def test_recurring_update_get(self) -> None:
        """Vérifie l'affichage du formulaire de modification."""
        url = reverse("settings_recurring_update", args=[self.expense.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "budget/partials/settings/_modal_recurring_form.html"
        )
        self.assertEqual(response.context["expense"], self.expense)

    def test_recurring_update_post(self) -> None:
        """Vérifie la modification d'une charge existante via le formulaire allégé."""
        url = reverse("settings_recurring_update", args=[self.expense.id])
        data = {
            "label": "Assurance Auto",
            "total_amount": "45.00",
            "default_bank_account": self.account.id,
            "usual_due_day": "2026-10-15",
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.expense.refresh_from_db()
        self.assertEqual(self.expense.label, "Assurance Auto")
        self.assertEqual(self.expense.total_amount, Decimal("45.00"))

    def test_recurring_delete_post(self) -> None:
        """Vérifie le soft-delete d'une charge fixe."""
        url = reverse("settings_recurring_delete", args=[self.expense.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.expense.refresh_from_db()
        self.assertFalse(self.expense.is_active)


def test_recurring_shares_view_get(self) -> None:
    """Vérifie l'affichage de la modale de répartition."""
    url = reverse("settings_recurring_shares", args=[self.expense.id])
    response = self.client.get(url)

    self.assertEqual(response.status_code, 200)
    self.assertTemplateUsed(
        response, "budget/partials/settings/_modal_recurring_shares.html"
    )
    self.assertEqual(response.context["expense"], self.expense)


def test_recurring_shares_view_post_valid(self) -> None:
    """Vérifie l'ajout d'une nouvelle part de répartition."""
    url = reverse("settings_recurring_shares", args=[self.expense.id])
    data = {
        "bank_account": self.account.id,
        "amount": "15.00",
    }
    response = self.client.post(url, data)

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.headers.get("HX-Refresh"), "true")
    self.assertEqual(self.expense.shares.count(), 1)
    self.assertEqual(self.expense.shares.first().amount, Decimal("15.00"))


def test_recurring_shares_view_post_invalid_exceeds_total(self) -> None:
    """Vérifie qu'on ne peut pas répartir plus que le montant total de la charge."""
    url = reverse("settings_recurring_shares", args=[self.expense.id])
    # La charge totale est de 25.00, on essaie d'attribuer 30.00
    data = {
        "bank_account": self.account.id,
        "amount": "30.00",
    }
    response = self.client.post(url, data)

    self.assertEqual(response.status_code, 200)
    self.assertFalse(response.headers.get("HX-Refresh"))
    self.assertIn("dépasse le montant total", response.content.decode())
    self.assertEqual(self.expense.shares.count(), 0)


def test_recurring_share_delete_post(self) -> None:
    """Vérifie la suppression (soft-delete) d'une part de répartition."""
    from budget.models.recurring import RecurringExpenseShare

    share = RecurringExpenseShare.objects.create(
        recurring_expense=self.expense,
        bank_account=self.account,
        amount=Decimal("10.00"),
    )

    url = reverse("settings_recurring_share_delete", args=[self.expense.id, share.id])
    response = self.client.post(url)

    self.assertEqual(response.status_code, 200)
    self.assertEqual(response.headers.get("HX-Refresh"), "true")

    share.refresh_from_db()
    self.assertFalse(share.is_active)
