from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from budget.models.account import AccountType, BankAccount, Household, HouseholdMember
from budget.models.category import Category, CategoryType

User = get_user_model()


class SettingsCategoriesTestCase(TestCase):
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
            name="Courses",
            type=CategoryType.VARIABLE,
            household=self.household,
        )

    def test_category_list_view(self) -> None:
        """Vérifie l'affichage de la liste des catégories."""
        url = reverse("settings_categories")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "budget/settings/category_list.html")
        self.assertIn("categories", response.context)

    def test_category_create_get(self) -> None:
        """Vérifie l'affichage du formulaire de création de catégorie."""
        url = reverse("settings_category_create")
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "budget/partials/settings/_modal_category_form.html"
        )

    def test_category_create_post(self) -> None:
        """Vérifie la création d'une nouvelle catégorie via POST."""
        url = reverse("settings_category_create")
        data = {
            "name": "Salaire",
            "type": CategoryType.INCOME,
            "is_meal_voucher_eligible": False,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.assertEqual(Category.objects.count(), 2)
        new_category = Category.objects.get(name="Salaire")
        self.assertEqual(new_category.household, self.household)

    def test_category_update_get(self) -> None:
        """Vérifie l'affichage du formulaire de modification."""
        url = reverse("settings_category_update", args=[self.category.id])
        response = self.client.get(url)

        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(
            response, "budget/partials/settings/_modal_category_form.html"
        )
        self.assertEqual(response.context["category"], self.category)

    def test_category_update_post(self) -> None:
        """Vérifie la modification d'une catégorie existante."""
        url = reverse("settings_category_update", args=[self.category.id])
        data = {
            "name": "Courses Modifiées",
            "type": CategoryType.VARIABLE,
            "is_meal_voucher_eligible": True,
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.category.refresh_from_db()
        self.assertEqual(self.category.name, "Courses Modifiées")
        self.assertTrue(self.category.is_meal_voucher_eligible)

    def test_category_delete_post(self) -> None:
        """Vérifie le soft-delete d'une catégorie."""
        url = reverse("settings_category_delete", args=[self.category.id])
        response = self.client.post(url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.headers.get("HX-Refresh"), "true")

        self.category.refresh_from_db()
        self.assertFalse(self.category.is_active)
