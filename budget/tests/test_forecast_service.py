from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from budget.models import (
    AccountType,
    BankAccount,
    Category,
    HouseholdMember,
    MonthlyForecast,
    RecurringExpense,
    RecurringExpenseShare,
    Transaction,
    TransactionType,
    Transfer,
)
from budget.models.account import Household
from budget.models.category import CategoryType
from budget.models.recurring import RecurringExpenseStatus
from budget.services.forecast import (
    calculate_monthly_projected_balances,
    get_recurring_expenses_with_status,
)


class ForecastServiceTestCase(TestCase):
    def setUp(self) -> None:
        self.household = Household.objects.create(name="Foyer Test")
        self.member = HouseholdMember.objects.create(
            name="Maxime", household=self.household
        )
        self.today = timezone.localdate().replace(day=1)

        self.checking_account = BankAccount.objects.create(
            name="Compte courant",
            account_type=AccountType.CHECKING,
            owner=self.member,
            current_balance=Decimal("1500.00"),
            is_default=True,
        )
        self.savings_account = BankAccount.objects.create(
            name="Livret A",
            account_type=AccountType.SAVINGS,
            owner=self.member,
            current_balance=Decimal("5000.00"),
        )
        self.tr_account = BankAccount.objects.create(
            name="Swile",
            account_type=AccountType.MEAL_VOUCHER,
            owner=self.member,
            current_balance=Decimal("100.00"),
            fallback_account=self.checking_account,
        )

        self.cat_housing = Category.objects.create(
            name="Logement",
            type=CategoryType.RECURRING,
            household=self.household,
        )
        self.cat_groceries = Category.objects.create(
            name="Courses",
            type=CategoryType.VARIABLE,
            is_meal_voucher_eligible=True,
            household=self.household,
        )
        self.cat_salary = Category.objects.create(
            name="Salaire",
            type=CategoryType.INCOME,
            household=self.household,
        )
        self.cat_savings = Category.objects.create(
            name="Intérêts ou Plum",
            type=CategoryType.SAVINGS,
            household=self.household,
        )

    def test_calculate_monthly_projected_balances_complete_cascade(self) -> None:
        rent = RecurringExpense.objects.create(
            label="Loyer",
            total_amount=Decimal("600.00"),
            category=self.cat_housing,
            household=self.household,
        )
        RecurringExpenseShare.objects.create(
            recurring_expense=rent,
            bank_account=self.checking_account,
            amount=Decimal("600.00"),
        )

        # On ne définit pas transaction_account pour tester le fallback automatique (TR -> Compte Courant)
        MonthlyForecast.objects.create(
            month=self.today,
            category=self.cat_groceries,
            member=self.member,
            amount=Decimal("300.00"),
        )

        MonthlyForecast.objects.create(
            month=self.today,
            bank_account=self.savings_account,
            member=self.member,
            amount=Decimal("200.00"),
        )

        MonthlyForecast.objects.create(
            month=self.today,
            category=self.cat_salary,
            member=self.member,
            amount=Decimal("2500.00"),
        )

        steps = calculate_monthly_projected_balances(
            member=self.member, month=self.today
        )

        self.assertEqual(steps["initial"][self.checking_account.id], Decimal("1500.00"))
        self.assertEqual(
            steps["after_recurring"][self.checking_account.id], Decimal("900.00")
        )
        # 100.00€ pris sur Swile (tr_account) et 200.00€ restants sur le compte courant : 900 - 200 = 700
        self.assertEqual(
            steps["after_variables"][self.checking_account.id], Decimal("700.00")
        )
        self.assertEqual(steps["after_variables"][self.tr_account.id], Decimal("0.00"))
        self.assertEqual(
            steps["after_savings"][self.checking_account.id], Decimal("500.00")
        )
        self.assertEqual(
            steps["after_savings"][self.savings_account.id], Decimal("5200.00")
        )
        self.assertEqual(
            steps["after_incomes"][self.checking_account.id], Decimal("3000.00")
        )

    def test_savings_forecast_with_transfers_and_incomes(self) -> None:
        """Vérifie que les transferts manuels et les arrondis automatiques réduisent la prévision d'épargne."""
        MonthlyForecast.objects.create(
            month=self.today,
            bank_account=self.savings_account,
            member=self.member,
            amount=Decimal("200.00"),
        )

        # 1. Transfert manuel (50€)
        Transfer.objects.create(
            source_account=self.checking_account,
            destination_account=self.savings_account,
            amount=Decimal("50.00"),
            date=self.today,
        )

        # 2. Arrondis Plum simulés via Transaction INCOME (30€)
        Transaction.objects.create(
            total_amount=Decimal("30.00"),
            label="Plum",
            category=self.cat_savings,
            bank_account=self.savings_account,
            transaction_date=self.today,
            budget_month=self.today,
            transaction_type=TransactionType.INCOME,
        )

        steps = calculate_monthly_projected_balances(self.member, self.today)

        # Le solde DB a changé à cause des signaux : Checking=1450, Savings=5080.
        self.assertEqual(steps["initial"][self.checking_account.id], Decimal("1450.00"))
        self.assertEqual(steps["initial"][self.savings_account.id], Decimal("5080.00"))

        # Reste à projeter : 200 - (50 + 30) = 120. Checking = 1450 - 120 = 1330.
        self.assertEqual(
            steps["after_savings"][self.checking_account.id], Decimal("1330.00")
        )
        self.assertEqual(
            steps["after_savings"][self.savings_account.id], Decimal("5200.00")
        )

    def test_calculate_monthly_projected_balances_temporal_logic(self) -> None:
        current_month = self.today
        past_month = (current_month - timedelta(days=1)).replace(day=1)
        future_month = (current_month.replace(day=28) + timedelta(days=5)).replace(
            day=1
        )

        rent = RecurringExpense.objects.create(
            label="Loyer",
            total_amount=Decimal("600.00"),
            category=self.cat_housing,
            household=self.household,
        )
        RecurringExpenseShare.objects.create(
            recurring_expense=rent,
            bank_account=self.checking_account,
            amount=Decimal("600.00"),
        )

        Transaction.objects.create(
            transaction_date=past_month,
            budget_month=past_month,
            total_amount=Decimal("580.00"),
            category=self.cat_housing,
            bank_account=self.checking_account,
            transaction_type=TransactionType.EXPENSE,
            recurring_expense=rent,
        )

        past_steps = calculate_monthly_projected_balances(
            member=self.member, month=past_month
        )
        self.assertEqual(
            past_steps["after_recurring"][self.checking_account.id], Decimal("920.00")
        )

        future_steps = calculate_monthly_projected_balances(
            member=self.member, month=future_month
        )
        self.assertEqual(
            future_steps["after_recurring"][self.checking_account.id], Decimal("320.00")
        )

        Transaction.objects.create(
            transaction_date=current_month,
            budget_month=current_month,
            total_amount=Decimal("600.00"),
            category=self.cat_housing,
            bank_account=self.checking_account,
            transaction_type=TransactionType.EXPENSE,
            recurring_expense=rent,
        )
        current_steps = calculate_monthly_projected_balances(
            member=self.member, month=current_month
        )
        self.assertEqual(
            current_steps["after_recurring"][self.checking_account.id],
            Decimal("320.00"),
        )

    def test_get_recurring_expenses_with_status(self) -> None:
        rent = RecurringExpense.objects.create(
            label="Loyer",
            total_amount=Decimal("600.00"),
            category=self.cat_housing,
            household=self.household,
        )
        RecurringExpenseShare.objects.create(
            recurring_expense=rent,
            bank_account=self.checking_account,
            amount=Decimal("600.00"),
        )

        result = get_recurring_expenses_with_status(self.member, self.today)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], RecurringExpenseStatus.WAITING)

        Transaction.objects.create(
            transaction_date=self.today,
            budget_month=self.today,
            total_amount=Decimal("300.00"),
            category=self.cat_housing,
            bank_account=self.checking_account,
            transaction_type=TransactionType.EXPENSE,
            recurring_expense=rent,
        )
        result_partial = get_recurring_expenses_with_status(self.member, self.today)
        self.assertEqual(result_partial[0]["status"], RecurringExpenseStatus.PARTIAL)

        Transaction.objects.create(
            transaction_date=self.today,
            budget_month=self.today,
            total_amount=Decimal("300.00"),
            category=self.cat_housing,
            bank_account=self.checking_account,
            transaction_type=TransactionType.EXPENSE,
            recurring_expense=rent,
        )
        result_completed = get_recurring_expenses_with_status(self.member, self.today)
        self.assertEqual(
            result_completed[0]["status"], RecurringExpenseStatus.COMPLETED
        )

    def test_recurring_expense_without_share(self) -> None:
        internet = RecurringExpense.objects.create(
            label="Internet",
            total_amount=Decimal("40.00"),
            category=self.cat_housing,
            default_bank_account=self.checking_account,
            household=self.household,
        )

        steps = calculate_monthly_projected_balances(self.member, self.today)
        self.assertEqual(
            steps["after_recurring"][self.checking_account.id], Decimal("1460.00")
        )

        status_list = get_recurring_expenses_with_status(self.member, self.today)
        self.assertEqual(len(status_list), 1)
        self.assertEqual(status_list[0]["expense"], internet)
        self.assertEqual(status_list[0]["status"], RecurringExpenseStatus.WAITING)

    def test_recurring_expense_override_and_prorata(self) -> None:
        """Vérifie qu'un override mensuel modifie bien la projection et le statut au prorata."""
        rent = RecurringExpense.objects.create(
            label="Loyer",
            total_amount=Decimal("1000.00"),
            category=self.cat_housing,
            household=self.household,
        )
        # Part théorique de 500€ (soit 50% de la charge globale)
        RecurringExpenseShare.objects.create(
            recurring_expense=rent,
            bank_account=self.checking_account,
            amount=Decimal("500.00"),
        )

        # Override de 1200€ ce mois-ci !
        MonthlyForecast.objects.create(
            month=self.today,
            recurring_expense=rent,
            member=self.member,
            amount=Decimal("1200.00"),
        )

        # 1. Test de la projection (prorata: 50% de 1200€ = 600€)
        steps = calculate_monthly_projected_balances(self.member, self.today)
        # Compte courant initial : 1500€. Moins 600€ = 900€
        self.assertEqual(
            steps["after_recurring"][self.checking_account.id], Decimal("900.00")
        )

        # 2. Test des statuts (l'interface doit afficher la charge Globale du foyer)
        status_list = get_recurring_expenses_with_status(self.member, self.today)
        self.assertEqual(status_list[0]["expected_amount"], Decimal("1200.00"))
