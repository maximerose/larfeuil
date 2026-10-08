from django.contrib.auth import get_user_model
from django.forms import BaseForm
from django.test import TestCase
from django.urls import reverse

from budget.models.account import HouseholdMember

User = get_user_model()


class AuthenticationTestCase(TestCase):
    def test_login_page_renders(self) -> None:
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/login.html")

    def test_register_page_renders(self) -> None:
        response = self.client.get(reverse("register"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/register.html")

    def test_successful_registration_creates_household_and_member(self) -> None:
        url = reverse("register")
        data = {
            "username": "nouveau_testeur",
            "display_name": "Nouveau Testeur",
            "email": "testeur@budget.local",
            "password": "SuperPassword123!",
            "password_confirm": "SuperPassword123!",
        }

        response = self.client.post(url, data)
        self.assertRedirects(response, reverse("dashboard"))

        self.assertTrue(User.objects.filter(username="nouveau_testeur").exists())
        new_user = User.objects.get(username="nouveau_testeur")

        self.assertTrue(HouseholdMember.objects.filter(user=new_user).exists())
        new_member = HouseholdMember.objects.get(user=new_user)
        self.assertEqual(new_member.name, "Nouveau Testeur")
        self.assertIsNotNone(new_member.household)

    def test_register_password_mismatch(self) -> None:
        url = reverse("register")
        data = {
            "username": "testeur2",
            "email": "testeur2@budget.local",
            "password": "SuperPassword123!",
            "password_confirm": "DifferentPassword123!",
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        assert response.context is not None
        form = response.context["form"]
        assert isinstance(form, BaseForm)

        self.assertEqual(
            form.errors.get("password_confirm"),
            ["Les deux mots de passe ne correspondent pas."],
        )
        self.assertFalse(User.objects.filter(username="testeur2").exists())

    def test_register_invalid_email(self) -> None:
        url = reverse("register")
        data = {
            "username": "testeur3",
            "email": "not-an-email",
            "password": "SuperPassword123!",
            "password_confirm": "SuperPassword123!",
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        assert response.context is not None
        form = response.context["form"]
        assert isinstance(form, BaseForm)

        self.assertEqual(
            form.errors.get("email"),
            ["Saisissez une adresse e-mail valide."],
        )

    def test_register_duplicate_email_raises_error(self) -> None:
        """Vérifie qu'on ne peut pas créer deux comptes avec la même adresse mail."""
        from budget.forms import RegisterForm

        # 1. Création explicite d'un utilisateur existant
        existing_email = "duplicate@larfeuil.app"
        User.objects.create_user(
            username="existing_user",
            email=existing_email,
            password="Password123!",
        )

        # 2. Tentative d'inscription avec la même adresse mail
        form_data = {
            "username": "new_unique_user",
            "email": existing_email,
            "password": "ComplexPassword123!",
            "password_confirm": "ComplexPassword123!",
            "display_name": "New User",
        }
        form = RegisterForm(data=form_data)

        self.assertFalse(form.is_valid())
        self.assertIn("email", form.errors)
        self.assertEqual(
            form.errors["email"], ["Un compte existe déjà avec cette adresse e-mail."]
        )

    def test_register_duplicate_username(self) -> None:
        User.objects.create_user(username="existant", password="password123")
        url = reverse("register")
        data = {
            "username": "existant",
            "email": "nouveau@budget.local",
            "password": "SuperPassword123!",
            "password_confirm": "SuperPassword123!",
        }
        response = self.client.post(url, data)

        self.assertEqual(response.status_code, 200)
        assert response.context is not None
        form = response.context["form"]
        assert isinstance(form, BaseForm)

        self.assertEqual(
            form.errors.get("username"),
            ["Un utilisateur avec ce nom d'utilisateur existe déjà."],
        )

    def test_user_login_redirects_to_dashboard(self) -> None:
        user = User.objects.create_user(username="maxime", password="password123")
        HouseholdMember.objects.create(name="Maxime", user=user)

        url = reverse("login")
        response = self.client.post(
            url, {"username": "maxime", "password": "password123"}
        )
        self.assertRedirects(response, reverse("dashboard"))

    def test_dashboard_displays_correct_logged_in_user(self) -> None:
        user1 = User.objects.create_user(username="maxime", password="password123")
        member1 = HouseholdMember.objects.create(name="Maxime", user=user1)

        user2 = User.objects.create_user(username="laurie", password="password123")
        member2 = HouseholdMember.objects.create(name="Laurie", user=user2)

        self.client.login(username="laurie", password="password123")
        response = self.client.get(reverse("dashboard"))

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context["member"], member2)
        self.assertNotEqual(response.context["member"], member1)
