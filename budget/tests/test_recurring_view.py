from decimal import Decimal

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget.models.account import AccountType, BankAccount, Household, HouseholdMember
from budget.models.category import Category, CategoryType
from budget.models.recurring import RecurringExpense
from budget.models.transaction import Transaction

User = get_user_model()


class RecurringViewTestCase(TestCase):
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
            name="Abonnements",
            type=CategoryType.RECURRING,
            household=self.household,
        )

        self.expense = RecurringExpense.objects.create(
            label="Internet",
            total_amount=Decimal("30.00"),
            category=self.category,
            default_bank_account=self.account,
        )

    def test_pay_recurring_expense_get(self) -> None:
        url = reverse("pay_recurring_expense", args=[self.expense.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "budget/partials/recurring/_modal_pay_recurring.html"
        )
        self.assertEqual(response.context["expense"], self.expense)

    def test_pay_recurring_expense_post(self) -> None:
        url = reverse("pay_recurring_expense", args=[self.expense.id])
        data = {
            "amount": "30.00",
            "account_id": str(self.account.id),
        }

        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.assertEqual(Transaction.objects.count(), 1)
        tx = Transaction.objects.first()

        assert tx is not None

        self.assertEqual(tx.total_amount, Decimal("30.00"))
        self.assertEqual(tx.recurring_expense, self.expense)
        self.assertEqual(tx.bank_account, self.account)
