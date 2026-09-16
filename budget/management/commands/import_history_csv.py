import csv
import datetime
import os
from decimal import Decimal

from django.conf import settings
from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from budget.models import (
    BankAccount,
    Category,
    Household,
    HouseholdMember,
    MonthlyForecast,
    RecurringExpense,
    Transaction,
    TransactionType,
    Transfer,
)
from budget.models.account import AccountType
from budget.models.category import CategoryType
from core.models import Visibility

User = get_user_model()


class Command(BaseCommand):
    help = "Importe l'historique et les prévisions en créant les accès utilisateurs."

    def add_arguments(self, parser):
        parser.add_argument("--accounts-file", default="accounts_init.csv")
        parser.add_argument("--recurring-file", default="recurring_expenses_init.csv")
        parser.add_argument("--transactions-file", default="transactions_history.csv")
        parser.add_argument("--categories-file", default="categories_init.csv")

    @transaction.atomic
    def handle(self, *args, **options):
        self.stdout.write("1. Nettoyage de la base de données...")
        Transaction.objects.all().delete()
        Transfer.objects.all().delete()
        MonthlyForecast.objects.all().delete()
        RecurringExpense.objects.all().delete()
        BankAccount.objects.all().delete()
        Category.objects.all().delete()

        accounts_file = os.path.join(settings.BASE_DIR, options["accounts_file"])
        rec_file = os.path.join(settings.BASE_DIR, options["recurring_file"])
        tx_file = os.path.join(settings.BASE_DIR, options["transactions_file"])
        categories_file = os.path.join(settings.BASE_DIR, options["categories_file"])

        if not os.path.exists(tx_file):
            self.stderr.write(self.style.ERROR("Fichiers introuvables."))
            return

        admin_user = os.environ.get("DJANGO_SUPERUSER_USERNAME", "maxime")
        admin_email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "maxime@larfeuil.app")
        admin_pwd = os.environ.get("DJANGO_SUPERUSER_PASSWORD")

        laurie_user = os.environ.get("DJANGO_LAURIE_USERNAME", "laurie")
        laurie_email = os.environ.get("DJANGO_LAURIE_EMAIL", "laurie@larfeuil.app")
        laurie_pwd = os.environ.get("DJANGO_LAURIE_PASSWORD")

        if not admin_pwd or not laurie_pwd:
            self.stderr.write(
                self.style.ERROR("ERREUR : Les mots de passe .env manquent !")
            )
            return

        user_maxime, _ = User.objects.get_or_create(
            username=admin_user, defaults={"is_staff": True, "is_superuser": True}
        )
        user_maxime.email = admin_email
        user_maxime.set_password(admin_pwd)
        user_maxime.save()

        user_laurie, _ = User.objects.get_or_create(
            username=laurie_user, defaults={"is_staff": False, "is_superuser": False}
        )
        user_laurie.email = laurie_email
        user_laurie.set_password(laurie_pwd)
        user_laurie.save()

        household, _ = Household.objects.get_or_create(name="Mon foyer")

        members_map = {}
        accounts_map = {}
        categories_map = {}
        recurring_map = {}

        # NOUVEAU : Chargement de la map des catégories (Swilable)
        meal_voucher_eligible_map = {}
        if os.path.exists(categories_file):
            with open(categories_file, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    meal_voucher_eligible_map[row["name"].lower()] = (
                        row["is_meal_voucher_eligible"] == "True"
                    )

        def get_or_create_member(name_str):
            clean_name = name_str.strip() if name_str else "Maxime"
            if "pro" in clean_name.lower():
                clean_name = "Maxime"

            if clean_name not in members_map:
                linked_user = (
                    user_maxime
                    if clean_name == "Maxime"
                    else (user_laurie if clean_name == "Laurie" else None)
                )

                member, _ = HouseholdMember.objects.get_or_create(
                    household=household,
                    name=clean_name,
                    defaults={"user": linked_user},
                )

                if linked_user and not member.user:
                    member.user = linked_user
                    member.save(update_fields=["user"])

                members_map[clean_name] = member
            return members_map[clean_name]

        def map_account_type(acc_name):
            n = acc_name.lower()
            if "swile" in n or "ticket" in n:
                return AccountType.MEAL_VOUCHER
            elif "pro" in n:
                return AccountType.BUSINESS
            elif any(s in n for s in ["livret", "pel", "lep", "plum", "épargne"]):
                return AccountType.SAVINGS
            return AccountType.CHECKING

        def get_or_create_account(
            member,
            account_name,
            default_type=AccountType.CHECKING,
            visibility=Visibility.PRIVATE,
        ):
            key = (member.id, account_name.lower())
            if key not in accounts_map:
                n_lower = account_name.lower()
                vis = (
                    Visibility.SHARED
                    if "joint" in n_lower or "swile" in n_lower
                    else visibility
                )

                acc, _ = BankAccount.objects.get_or_create(
                    owner=member,
                    name=account_name,
                    defaults={
                        "account_type": default_type,
                        "current_balance": Decimal("0.00"),
                        "visibility": vis,
                    },
                )
                accounts_map[key] = acc
            return accounts_map[key]

        def get_or_create_category(cat_name, cat_type):
            clean_cat = cat_name.strip() or "Divers"
            if clean_cat.lower() in ["aménagement", "aménagement / maison"]:
                clean_cat = "Aménagement / Maison"

            key = (household.id, clean_cat.lower())
            if key not in categories_map:
                cat = Category.objects.filter(
                    household=household, name__iexact=clean_cat
                ).first()

                is_tr = meal_voucher_eligible_map.get(clean_cat.lower(), False)

                if not cat:
                    cat = Category.objects.create(
                        household=household,
                        name=clean_cat,
                        type=cat_type,
                        is_meal_voucher_eligible=is_tr,
                    )
                else:
                    if cat.is_meal_voucher_eligible != is_tr:
                        cat.is_meal_voucher_eligible = is_tr
                        cat.save(update_fields=["is_meal_voucher_eligible"])

                categories_map[key] = cat
            return categories_map[key]

        self.stdout.write("2. Création des comptes...")
        if os.path.exists(accounts_file):
            with open(accounts_file, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    member = get_or_create_member(row["owner"])
                    acc_name = row["account_name"].strip()
                    bal = (
                        Decimal(row["last_balance"])
                        if row["last_balance"]
                        else Decimal("0.00")
                    )
                    acc = get_or_create_account(
                        member, acc_name, map_account_type(acc_name)
                    )
                    acc.current_balance = bal
                    acc.save(update_fields=["current_balance"])

        member_maxime = get_or_create_member("Maxime")
        account_courant = get_or_create_account(
            member_maxime, "Compte courant", AccountType.CHECKING, Visibility.PRIVATE
        )
        account_pro = get_or_create_account(
            member_maxime, "Compte pro", AccountType.BUSINESS, Visibility.PRIVATE
        )

        self.stdout.write("3. Création des charges fixes...")
        if os.path.exists(rec_file):
            with open(rec_file, mode="r", encoding="utf-8-sig") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    label = row["label"].strip()
                    owner_raw = row.get("owner", "Maxime").strip()

                    if owner_raw == "Pro":
                        owner_obj = member_maxime
                        target_account = account_pro
                    elif owner_raw == "Laurie":
                        owner_obj = get_or_create_member("Laurie")
                        target_account = get_or_create_account(
                            owner_obj,
                            "Compte courant",
                            AccountType.CHECKING,
                            Visibility.PRIVATE,
                        )
                    else:
                        owner_obj = member_maxime
                        target_account = account_courant

                    key = (household.id, label.lower(), owner_raw.lower())

                    due_day_raw = row["usual_due_day"].strip()
                    try:
                        due_date = (
                            datetime.date.fromisoformat(due_day_raw[:10])
                            if due_day_raw
                            else None
                        )
                    except ValueError:
                        due_date = None

                    rec, _ = RecurringExpense.objects.update_or_create(
                        household=household,
                        label=label,
                        owner=owner_obj,
                        defaults={
                            "visibility": Visibility.PRIVATE,
                            "total_amount": abs(Decimal(row["total_amount"]))
                            if row["total_amount"]
                            else Decimal("0.00"),
                            "frequency_months": int(row["frequency_months"])
                            if row["frequency_months"]
                            else 1,
                            "is_variable": row["is_variable"] == "True",
                            "default_bank_account": target_account,
                            "usual_due_day": due_date,
                        },
                    )
                    recurring_map[key] = rec

        self.stdout.write("4. Importation des transactions et des prévisions...")
        transactions_to_create = []
        transfers_to_create = []
        forecasts_map = {}
        all_months = set()

        with open(tx_file, mode="r", encoding="utf-8-sig") as f:
            reader = list(csv.DictReader(f))

            for row in reader:
                section = row["section"]
                raw_amount = Decimal(row["amount"])
                user_raw = row.get("user", "Maxime").strip()
                label_or_cat = row["label_or_category"].strip()

                try:
                    tx_date = datetime.date.fromisoformat(row["date"][:10])
                except ValueError:
                    tx_date = datetime.date(int(row["year"]), int(row["month"]), 1)

                budget_month = datetime.date(int(row["year"]), int(row["month"]), 1)
                all_months.add(budget_month)

                comment = row.get("comment", "").strip()
                mv_amount = Decimal(row.get("meal_voucher_amount", "0.0"))

                member = get_or_create_member(user_raw)

                if user_raw == "Pro":
                    base_account = get_or_create_account(
                        member, "Compte pro", AccountType.BUSINESS, Visibility.PRIVATE
                    )
                else:
                    base_account = get_or_create_account(
                        member,
                        "Compte courant",
                        AccountType.CHECKING,
                        Visibility.PRIVATE,
                    )

                # --- TRAITEMENT DES PRÉVISIONS ---
                if section.startswith("FORECAST_"):
                    forecast_type = section.replace("FORECAST_", "")
                    cat_obj = None
                    rec_obj = None
                    acc_obj = None

                    if forecast_type == "INCOME":
                        cat_obj = get_or_create_category(
                            label_or_cat, CategoryType.INCOME
                        )
                    elif forecast_type == "VARIABLE":
                        cat_obj = get_or_create_category(
                            label_or_cat, CategoryType.VARIABLE
                        )
                    elif forecast_type == "RECURRING":
                        lbl_lower = label_or_cat.lower()
                        owner_key = user_raw.lower()

                        if (household.id, lbl_lower, "pro") in recurring_map:
                            rec_obj = recurring_map[(household.id, lbl_lower, "pro")]
                        elif (household.id, lbl_lower, owner_key) in recurring_map:
                            rec_obj = recurring_map[
                                (household.id, lbl_lower, owner_key)
                            ]
                        elif (household.id, lbl_lower, "maxime") in recurring_map:
                            rec_obj = recurring_map[(household.id, lbl_lower, "maxime")]
                        else:
                            rec_obj, _ = RecurringExpense.objects.get_or_create(
                                household=household,
                                label=label_or_cat,
                                owner=member,
                                defaults={
                                    "visibility": Visibility.PRIVATE,
                                    "total_amount": abs(raw_amount),
                                    "default_bank_account": base_account,
                                },
                            )
                            recurring_map[(household.id, lbl_lower, owner_key)] = (
                                rec_obj
                            )

                    elif forecast_type == "SAVINGS":
                        acc_obj = get_or_create_account(
                            member,
                            label_or_cat or "Livret A",
                            map_account_type(label_or_cat),
                            Visibility.PRIVATE,
                        )

                    if cat_obj or rec_obj or acc_obj:
                        key = (
                            budget_month,
                            member.id,
                            cat_obj.id if cat_obj else None,
                            rec_obj.id if rec_obj else None,
                            acc_obj.id if acc_obj else None,
                        )
                        forecasts_map[key] = MonthlyForecast(
                            month=budget_month,
                            member=member,
                            amount=raw_amount,
                            category=cat_obj,
                            recurring_expense=rec_obj,
                            bank_account=acc_obj,
                            visibility=Visibility.PRIVATE,
                        )
                    continue

                # --- TRAITEMENT DES TRANSFERTS ET TRANSACTIONS ---
                if section == "SAVINGS":
                    savings_account = get_or_create_account(
                        member,
                        label_or_cat or "Livret A",
                        map_account_type(label_or_cat),
                        Visibility.PRIVATE,
                    )

                    if raw_amount >= 0:
                        src_acc, dst_acc = base_account, savings_account
                    else:
                        src_acc, dst_acc = savings_account, base_account

                    transfers_to_create.append(
                        Transfer(
                            source_account=src_acc,
                            destination_account=dst_acc,
                            amount=abs(raw_amount),
                            date=tx_date,
                        )
                    )
                    continue

                account = base_account
                recurring_exp = None

                # Conserver le signe !
                final_amount = raw_amount

                if section == "INCOME":
                    tx_type = TransactionType.INCOME
                    category = get_or_create_category(label_or_cat, CategoryType.INCOME)
                elif section == "RECURRING":
                    tx_type = TransactionType.EXPENSE
                    category = None
                    lbl_lower = label_or_cat.lower()
                    owner_key = user_raw.lower()

                    if (household.id, lbl_lower, "pro") in recurring_map:
                        recurring_exp = recurring_map[(household.id, lbl_lower, "pro")]
                    elif (household.id, lbl_lower, owner_key) in recurring_map:
                        recurring_exp = recurring_map[
                            (household.id, lbl_lower, owner_key)
                        ]
                    elif (household.id, lbl_lower, "maxime") in recurring_map:
                        recurring_exp = recurring_map[
                            (household.id, lbl_lower, "maxime")
                        ]
                    else:
                        rec, _ = RecurringExpense.objects.get_or_create(
                            household=household,
                            label=label_or_cat,
                            owner=member,
                            defaults={
                                "visibility": Visibility.PRIVATE,
                                "total_amount": abs(final_amount),
                                "category": category,
                                "default_bank_account": account,
                            },
                        )
                        recurring_map[(household.id, lbl_lower, owner_key)] = rec
                        recurring_exp = rec

                elif section == "VARIABLE":
                    tx_type = TransactionType.EXPENSE
                    category = get_or_create_category(
                        label_or_cat, CategoryType.VARIABLE
                    )

                transactions_to_create.append(
                    Transaction(
                        bank_account=account,
                        category=category,
                        recurring_expense=recurring_exp,
                        transaction_date=tx_date,
                        budget_month=budget_month,
                        transaction_type=tx_type,
                        total_amount=final_amount,
                        meal_voucher_amount=mv_amount,
                        label=label_or_cat
                        if section in ["RECURRING", "INCOME"]
                        else "",
                        comment=comment,
                    )
                )

        Transaction.objects.bulk_create(transactions_to_create, batch_size=500)
        Transfer.objects.bulk_create(transfers_to_create, batch_size=500)

        # --- FORCE LES CHARGES FIXES MANQUANTES À 0€ POUR CE MOIS ---
        all_recurring = RecurringExpense.objects.filter(household=household)
        for budget_month in all_months:
            for rec in all_recurring:
                key = (budget_month, rec.owner.id, None, rec.id, None)
                if key not in forecasts_map:
                    forecasts_map[key] = MonthlyForecast(
                        month=budget_month,
                        member=rec.owner,
                        amount=Decimal("0.00"),
                        recurring_expense=rec,
                        visibility=Visibility.PRIVATE,
                    )

        MonthlyForecast.objects.bulk_create(forecasts_map.values(), batch_size=500)

        self.stdout.write(self.style.SUCCESS("Importation finale réussie !"))
