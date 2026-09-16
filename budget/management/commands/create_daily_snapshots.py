from django.core.management.base import BaseCommand
from django.utils import timezone

from budget.models import AccountSnapshot, BankAccount


class Command(BaseCommand):
    help = (
        "Crée un snapshot journalier du solde pour tous les comptes bancaires actifs."
    )

    def handle(self, *args, **options) -> None:
        today = timezone.localdate()
        active_accounts = BankAccount.objects.filter(is_active=True)
        created_count = 0

        for account in active_accounts:
            # update_or_create permet d'éviter les doublons si la commande est lancée plusieurs fois le même jour
            _, created = AccountSnapshot.objects.update_or_create(
                bank_account=account,
                date=today,
                defaults={"balance": account.current_balance},
            )
            if created:
                created_count += 1

        self.stdout.write(
            self.style.SUCCESS(
                f"Succès : {created_count} snapshot(s) créé(s) pour la date du {today}."
            )
        )
