from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from budget.models.account import AccountType, BankAccount, Household, HouseholdMember
from budget.models.category import Category, CategoryType
from budget.models.transaction import Transaction

User = get_user_model()


class TransactionViewsTestCase(TestCase):
    def setUp(self) -> None:
        self.user = User.objects.create_user(username="maxime", password="password123")
        self.household = Household.objects.create(name="Foyer Test")
        self.member = HouseholdMember.objects.create(
            name="Maxime", household=self.household, user=self.user
        )
        self.client.force_login(self.user)

        self.account = BankAccount.objects.create(
            name="Compte Courant",
            account_type=AccountType.CHECKING,
            owner=self.member,
            current_balance=Decimal("1000.00"),
        )

        self.category = Category.objects.create(
            name="Alimentation",
            type=CategoryType.VARIABLE,
            household=self.household,
        )

    def test_quick_transaction_get(self) -> None:
        url = reverse("quick_transaction_form")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "budget/partials/transactions/_modal_quick_transaction.html"
        )

    def test_quick_transaction_post(self) -> None:
        url = reverse("quick_transaction_form")
        today = timezone.localdate()

        data = {
            "total_amount": "45.50",
            "label": "Boulangerie",
            "category": str(self.category.id),
            "bank_account": str(self.account.id),
            "expense_category": str(self.category.id),
            "expense_account": str(self.account.id),
            "transaction_date": today.strftime("%Y-%m-%d"),
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.assertEqual(Transaction.objects.count(), 1)
        transaction = Transaction.objects.first()

        assert transaction is not None

        self.assertEqual(transaction.total_amount, Decimal("45.50"))
        self.assertEqual(transaction.label, "Boulangerie")
        self.assertEqual(transaction.category, self.category)

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("954.50"))

    def test_adjust_balance_get(self) -> None:
        url = reverse("adjust_account_balance", args=[self.account.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "budget/partials/accounts/_modal_adjust_balance.html"
        )

    def test_adjust_balance_post(self) -> None:
        url = reverse("adjust_account_balance", args=[self.account.id])

        data = {"new_balance": "1250.00"}

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("1250.00"))

    def test_categorized_transfer_creates_two_transactions(self) -> None:
        """Vérifie qu'un transfert avec catégorie crée bien 2 transactions opposées et aucun Transfer."""
        dest_account = BankAccount.objects.create(
            name="Livret A",
            account_type=AccountType.SAVINGS,
            owner=self.member,
            current_balance=Decimal("0.00"),
        )

        url = reverse("quick_transaction_form")
        today = timezone.localdate()

        data = {
            "tx_type": "TRANSFER",
            "source_account": str(self.account.id),
            "destination_account": str(dest_account.id),
            "transfer_category": str(self.category.id),
            "total_amount": "50.00",
            "transaction_date": today.strftime("%Y-%m-%d"),
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        # Vérification : 2 Transactions ont été créées (et 0 objet Transfer)
        from budget.models.transaction import Transfer

        self.assertEqual(Transaction.objects.count(), 2)
        self.assertEqual(Transfer.objects.count(), 0)

        # Vérification des soldes
        self.account.refresh_from_db()
        dest_account.refresh_from_db()
        self.assertEqual(self.account.current_balance, Decimal("950.00"))  # -50
        self.assertEqual(dest_account.current_balance, Decimal("50.00"))  # +50
