from decimal import Decimal

from django.core.exceptions import ValidationError
from django.test import TestCase

from budget.models import AccountType, BankAccount, HouseholdMember
from budget.models.account import Household
from core.models import Visibility


class AccountModelsTestCase(TestCase):
    def setUp(self) -> None:
        self.household = Household.objects.create(name="Foyer Test")
        self.member = HouseholdMember.objects.create(
            name="Maxime",
            household=self.household,
        )
        self.partner = HouseholdMember.objects.create(
            name="Laurie",
            household=self.household,
        )

        self.bank_account = BankAccount.objects.create(
            name="Compte courant",
            account_type=AccountType.CHECKING,
            owner=self.member,
            current_balance=Decimal("1000.00"),
            is_default=True,
        )

    def test_household_and_members_relationship(self) -> None:
        """Vérifie la relation One-to-Many entre un foyer et ses membres."""
        self.assertEqual(str(self.household), "Foyer Test")
        self.assertEqual(self.member.household, self.household)
        self.assertEqual(self.partner.household, self.household)

        # Vérifie qu'on peut récpérer tous les membres depuis le foyer
        self.assertEqual(
            HouseholdMember.objects.filter(household=self.household).count(), 2
        )

    def test_bank_account_str(self) -> None:
        self.assertEqual(
            str(self.bank_account), "Compte courant (Compte courant) Maxime"
        )

    def test_bank_account_visibility_default_and_custom(self) -> None:
        """Vérifie la gestion de la visibilité SHARED et PRIVATE."""
        self.assertEqual(self.bank_account.visibility, Visibility.SHARED)

        private_account = BankAccount.objects.create(
            name="Compte Secret",
            account_type=AccountType.CHECKING,
            owner=self.member,
            visibility=Visibility.PRIVATE,
        )
        self.assertEqual(private_account.visibility, Visibility.PRIVATE)

    def test_meal_voucher_account_default_limit(self) -> None:
        # Un compte TR sans limite spécifiée doit recevoir 25.00 par défaut via clean()
        tr_account = BankAccount.objects.create(
            name="Swile",
            account_type=AccountType.MEAL_VOUCHER,
            owner=self.member,
        )
        self.assertEqual(tr_account.daily_meal_voucher_limit, Decimal("25.00"))

    def test_checking_account_only_can_be_default(self) -> None:
        """Vérifie que seul un compte courant peut être défini comme compte par défaut."""
        savings_account = BankAccount(
            name="Livret A",
            account_type=AccountType.SAVINGS,
            owner=self.member,
            is_default=True,
        )
        with self.assertRaises(ValidationError):
            savings_account.full_clean()

    def test_checking_account_forces_null_limit(self) -> None:
        # Un compte courant ne doit jamais avoir de limite TR, même si on tente de lui en assigner une
        checking_account = BankAccount.objects.create(
            name="Compte sans TR",
            account_type=AccountType.CHECKING,
            owner=self.member,
            daily_meal_voucher_limit=Decimal("50.00"),
        )
        self.assertIsNone(checking_account.daily_meal_voucher_limit)
