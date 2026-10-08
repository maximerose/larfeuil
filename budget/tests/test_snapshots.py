from decimal import Decimal

from django.core.management import call_command
from django.db import IntegrityError
from django.test import TestCase
from django.utils import timezone

from budget.models.account import (
    AccountSnapshot,
    AccountType,
    BankAccount,
    HouseholdMember,
)


class AccountSnapshotTestCase(TestCase):
    def setUp(self) -> None:
        self.member = HouseholdMember.objects.create(name="Maxime")
        self.bank_account = BankAccount.objects.create(
            name="Compte courant",
            account_type=AccountType.CHECKING,
            owner=self.member,
            current_balance=Decimal("1500.00"),
        )

    def test_snapshop_str_and_creation(self) -> None:
        today = timezone.localdate()
        snapshot = AccountSnapshot.objects.create(
            bank_account=self.bank_account,
            balance=Decimal("1500.00"),
            date=today,
        )
        self.assertEqual(str(snapshot), f"Compte courant - 1500.00 € au {today}")

    def test_unique_daily_snapshot_constraint(self) -> None:
        today = timezone.localdate()
        AccountSnapshot.objects.create(
            bank_account=self.bank_account,
            balance=Decimal("1500.00"),
            date=today,
        )

        # Tenter de créer un deuxième snapshot le même jour pour le même compte doit échouer
        with self.assertRaises(IntegrityError):
            AccountSnapshot.objects.create(
                bank_account=self.bank_account,
                balance=Decimal("1500.00"),
                date=today,
            )

    def test_management_command_multiple_accounts(self) -> None:
        # Création d'un second compte actif et d'un compte inactif
        BankAccount.objects.create(
            name="Livret A",
            account_type=AccountType.SAVINGS,
            owner=self.member,
            current_balance=Decimal("3000.00"),
        )
        BankAccount.objects.create(
            name="Vieux compte",
            account_type=AccountType.CHECKING,
            owner=self.member,
            current_balance=Decimal("0.00"),
            is_active=False,
        )

        call_command("create_daily_snapshots")

        # Doit créer un snapshot uniquement pour les 2 comptes actifs, pas pour l'inactif
        self.assertEqual(AccountSnapshot.objects.count(), 2)

        livret_snapshot = AccountSnapshot.objects.filter(
            bank_account__name="Livret A"
        ).first()
        assert livret_snapshot is not None
        self.assertEqual(livret_snapshot.balance, Decimal("3000.00"))

    def test_management_command_create_daily_snapshot(self) -> None:
        # Exécution de la commande custom
        call_command("create_daily_snapshots")

        snapshots = AccountSnapshot.objects.all()
        self.assertEqual(snapshots.count(), 1)

        first_snapshot = snapshots.first()
        assert first_snapshot is not None
        self.assertEqual(first_snapshot.balance, Decimal("1500.00"))
