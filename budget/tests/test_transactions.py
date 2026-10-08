import datetime
from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase
from django.utils import timezone

from budget.models import (
    AccountType,
    BankAccount,
    Category,
    HouseholdMember,
    Transaction,
    TransactionType,
    Transfer,
)
from budget.models.account import Household
from budget.models.category import CategoryType
from budget.utils import calculate_budget_month, get_remaining_meal_voucher_ceiling


class TransactionAndTransferTestCase(TestCase):
    def setUp(self) -> None:
        self.household = Household.objects.create(name="Foyer Test")
        self.member = HouseholdMember.objects.create(
            name="Maxime", household=self.household
        )
        self.category = Category.objects.create(
            name="Loyer",
            type=CategoryType.RECURRING,
            household=self.household,
        )
        self.bank_account = BankAccount.objects.create(
            name="Compte courant",
            account_type=AccountType.CHECKING,
            owner=self.member,
            current_balance=Decimal("1000.00"),
        )

    def test_transaction_creation_and_defaults(self) -> None:
        expense_tx = Transaction.objects.create(
            total_amount=Decimal("45.50"),
            meal_voucher_amount=Decimal("15.00"),
            label="Courses Leclerc",
            comment="Matelas trek Laurie",
            category=self.category,
            bank_account=self.bank_account,
            transaction_type=TransactionType.EXPENSE,
        )

        self.assertEqual(expense_tx.transaction_type, TransactionType.EXPENSE)
        self.assertEqual(expense_tx.total_amount, Decimal("45.50"))
        self.assertEqual(expense_tx.meal_voucher_amount, Decimal("15.00"))
        self.assertEqual(expense_tx.label, "Courses Leclerc")
        self.assertEqual(expense_tx.comment, "Matelas trek Laurie")
        self.assertIsNotNone(expense_tx.transaction_date)

        income_category = Category.objects.create(
            name="Salaire", type=CategoryType.INCOME, household=self.household
        )
        income_tx = Transaction.objects.create(
            total_amount=Decimal("2500.00"),
            label="Salaire",
            category=income_category,
            bank_account=self.bank_account,
            transaction_type=TransactionType.INCOME,
        )

        self.assertEqual(income_tx.transaction_type, TransactionType.INCOME)
        self.assertEqual(income_tx.comment, "")

    def test_transaction_delete_readjusts_balance(self) -> None:
        initial_balance = self.bank_account.current_balance
        tx = Transaction.objects.create(
            total_amount=Decimal("50.00"),
            category=self.category,
            bank_account=self.bank_account,
            transaction_type=TransactionType.EXPENSE,
        )
        self.bank_account.refresh_from_db()
        self.assertEqual(
            self.bank_account.current_balance, initial_balance - Decimal("50.00")
        )

        tx.delete()
        self.bank_account.refresh_from_db()
        self.assertEqual(self.bank_account.current_balance, initial_balance)

    def test_transfer_creation_and_str(self) -> None:
        destination_account = BankAccount.objects.create(
            name="Livret A",
            account_type=AccountType.SAVINGS,
            owner=self.member,
            current_balance=Decimal("500.00"),
        )

        initial_source_balance = self.bank_account.current_balance
        initial_destination_balance = destination_account.current_balance

        transfer_date = timezone.localdate()
        transfer = Transfer.objects.create(
            source_account=self.bank_account,
            destination_account=destination_account,
            amount=Decimal("150.00"),
            date=transfer_date,
        )

        self.assertEqual(transfer.source_account, self.bank_account)
        self.assertEqual(transfer.destination_account, destination_account)
        self.assertEqual(transfer.amount, Decimal("150.00"))
        self.assertEqual(transfer.date, transfer_date)

        expected_str = "Transfert de 150.00 € (Compte courant -> Livret A)"
        self.assertEqual(str(transfer), expected_str)

        self.bank_account.refresh_from_db()
        destination_account.refresh_from_db()
        self.assertEqual(
            self.bank_account.current_balance,
            initial_source_balance - Decimal("150.00"),
        )
        self.assertEqual(
            destination_account.current_balance,
            initial_destination_balance + Decimal("150.00"),
        )

    def test_transfer_same_account_validation(self) -> None:
        transfer = Transfer(
            source_account=self.bank_account,
            destination_account=self.bank_account,
            amount=Decimal("50.0"),
        )

        with self.assertRaises(ValidationError):
            transfer.full_clean()

    def test_transaction_budget_month_default_and_custom(self) -> None:
        tx_default = Transaction.objects.create(
            total_amount=Decimal("20.00"),
            label="Achat standard",
            category=self.category,
            bank_account=self.bank_account,
        )
        self.assertEqual(tx_default.budget_month, timezone.localdate())

        last_day_prev_month = timezone.localdate().replace(day=1) - timedelta(days=1)
        tx_custom = Transaction.objects.create(
            total_amount=Decimal("2500.00"),
            label="Salaire mois précédent",
            category=self.category,
            bank_account=self.bank_account,
            transaction_date=timezone.localdate(),
            budget_month=last_day_prev_month,
        )
        self.assertEqual(tx_custom.budget_month, last_day_prev_month)

    def test_calculate_budget_month_logic(self) -> None:
        ref_date = datetime.date(2026, 9, 4)

        # 1. Mois antérieur -> Dernier jour
        past_budget_month = calculate_budget_month(ref_date, 2026, 8)
        self.assertEqual(past_budget_month, datetime.date(2026, 8, 31))

        # 2. Mois postérieur -> Premier jour
        next_budget_month = calculate_budget_month(ref_date, 2026, 10)
        self.assertEqual(next_budget_month, datetime.date(2026, 10, 1))

        # 3. Même mois -> Date de référence
        current_budget_month = calculate_budget_month(ref_date, 2026, 9)
        self.assertEqual(current_budget_month, ref_date)

    def test_get_remaining_meal_voucher_ceiling_per_account(self) -> None:
        # Création d'un compte Swile dédié pour le test
        tr_account = BankAccount.objects.create(
            name="Swile Principal",
            account_type=AccountType.MEAL_VOUCHER,
            owner=self.member,
            daily_meal_voucher_limit=Decimal("25.00"),
        )

        eligible_cat = Category.objects.create(
            name="Courses",
            type=CategoryType.VARIABLE,
            is_meal_voucher_eligible=True,
            household=self.household,
        )
        today = timezone.localdate()

        # Le plafond initial sur ce compte est de 25.00€
        self.assertEqual(
            get_remaining_meal_voucher_ceiling(today, tr_account),
            Decimal("25.00"),
        )

        # Si on passe un compte courant classique, la fonction retourne None
        self.assertIsNone(get_remaining_meal_voucher_ceiling(today, self.bank_account))

        # Achat de 10.00€ payé via ce compte TR
        Transaction.objects.create(
            total_amount=Decimal("30.00"),
            meal_voucher_amount=Decimal("10.00"),
            category=eligible_cat,
            bank_account=self.bank_account,
            meal_voucher_bank_account=tr_account,
            transaction_date=today,
            transaction_type=TransactionType.EXPENSE,
        )

        # Il reste 15.00€ sur ce compte TR
        self.assertEqual(
            get_remaining_meal_voucher_ceiling(today, tr_account),
            Decimal("15.00"),
        )

    def test_transaction_expense_with_meal_voucher_updates_balances(self) -> None:
        tr_account = BankAccount.objects.create(
            name="Swile Principal",
            account_type=AccountType.MEAL_VOUCHER,
            owner=self.member,
            current_balance=Decimal("100.00"),
        )
        initial_checking_balance = self.bank_account.current_balance
        initial_tr_balance = tr_account.current_balance

        eligible_cat = Category.objects.create(
            name="Courses",
            type=CategoryType.VARIABLE,
            is_meal_voucher_eligible=True,
            household=self.household,
        )

        Transaction.objects.create(
            total_amount=Decimal("50.00"),
            meal_voucher_amount=Decimal("20.00"),
            meal_voucher_bank_account=tr_account,
            label="Supermarché",
            category=eligible_cat,
            bank_account=self.bank_account,
            transaction_type=TransactionType.EXPENSE,
        )

        self.bank_account.refresh_from_db()
        tr_account.refresh_from_db()

        # Compte courant débité de total - meal_voucher (50 - 20 = 30)
        self.assertEqual(
            self.bank_account.current_balance,
            initial_checking_balance - Decimal("30.00"),
        )
        # Compte TR débité du montant TR (20)
        self.assertEqual(
            tr_account.current_balance,
            initial_tr_balance - Decimal("20.00"),
        )
