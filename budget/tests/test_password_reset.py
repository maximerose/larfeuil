from django.contrib.auth.models import User
from django.core import mail
from django.test import TestCase
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode


class PasswordResetTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username="testuser",
            email="testuser@larfeuil.app",
            password="old_secure_password123",
        )

    def test_password_reset_form_view(self):
        """Vérifie que la page de demande de réinitialisation s'affiche correctement."""
        response = self.client.get(reverse("password_reset"))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/password_reset_form.html")

    def test_password_reset_successful_email_sent(self):
        """Vérifie le submit du formulaire et l'envoi de l'e-mail dans la boîte mail virtuelle."""
        response = self.client.post(
            reverse("password_reset"),
            {"email": "testuser@larfeuil.app"},
            follow=True,
        )
        self.assertRedirects(response, reverse("password_reset_done"))
        self.assertTemplateUsed(response, "registration/password_reset_done.html")

        # Vérification qu'un mail a bien été intercepté
        self.assertEqual(len(mail.outbox), 1)
        sent_email = mail.outbox[0]
        self.assertIn("testuser@larfeuil.app", sent_email.to)
        self.assertIn("Réinitialisation", sent_email.subject)

    def test_password_reset_invalid_email_does_not_send_mail(self):
        """Vérifie qu'aucun mail n'est envoyé si l'adresse e-mail n'existe pas."""
        response = self.client.post(
            reverse("password_reset"),
            {"email": "unknown@larfeuil.app"},
            follow=True,
        )
        # Par sécurité UX/anti-enumeration, Django redirige tout de même vers 'done'
        self.assertRedirects(response, reverse("password_reset_done"))
        # Mais aucun e-mail n'est généré
        self.assertEqual(len(mail.outbox), 0)

    def test_password_reset_confirm_invalid_token(self):
        """Vérifie le comportement si le token dans l'URL est corrompu ou expiré."""
        # On génère un UID valide en base64 pour l'utilisateur
        valid_uidb64 = urlsafe_base64_encode(force_bytes(self.user.pk))

        # On teste avec un token délibérément invalide
        url = reverse(
            "password_reset_confirm",
            kwargs={"uidb64": valid_uidb64, "token": "invalid-token-123"},
        )
        response = self.client.get(url)
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, "registration/password_reset_confirm.html")
        # Le template personnalisé s'affiche et contient notre message d'erreur
        self.assertContains(
            response, "Ce lien de réinitialisation est invalide ou a expiré."
        )
