import re
from typing import ClassVar

from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.forms import SetPasswordForm

from budget.models.account import HouseholdInvitation

User = get_user_model()


class RegisterForm(forms.ModelForm):
    display_name = forms.CharField(
        required=True,
        label="Nom d'affichage",
    )
    email = forms.EmailField(
        required=True,
        error_messages={"invalid": "Saisissez une adresse e-mail valide."},
    )
    password = forms.CharField(widget=forms.PasswordInput)
    password_confirm = forms.CharField(widget=forms.PasswordInput)
    household_code = forms.CharField(
        required=False,
        help_text="Optionnel : Saisissez le code fourni par un membre de votre foyer.",
    )

    class Meta:
        model = User
        fields: ClassVar[list[str]] = ["username", "email"]
        error_messages: ClassVar[dict[str, dict[str, str]]] = {
            "username": {
                "unique": "Un utilisateur avec ce nom d'utilisateur existe déjà."
            }
        }

    def clean_username(self):
        username = self.cleaned_data.get("username", "")
        username = username.strip().lower()
        if not re.match(r"^[a-z0-9-_]+$", username):
            raise forms.ValidationError(
                "Le pseudo ne doit contenir que des lettres minuscules, des chiffres et des tirets."
            )
        return username

    def clean_display_name(self):
        name = self.cleaned_data.get("display_name", "")
        return name.strip().title()

    def clean_email(self):
        email = self.cleaned_data.get("email", "").strip().lower()
        if User.objects.filter(email__iexact=email).exists():
            raise forms.ValidationError(
                "Un compte existe déjà avec cette adresse e-mail."
            )
        return email

    def clean(self):
        cleaned_data = super().clean()
        p1 = cleaned_data.get("password")
        p2 = cleaned_data.get("password_confirm")

        # 1. Validation de la robustesse du mot de passe (Même logique que le Front-end)
        if p1:
            if len(p1) < 8:
                self.add_error(
                    "password", "Le mot de passe doit contenir au moins 8 caractères."
                )
            if not re.search(r"[A-Z]", p1):
                self.add_error(
                    "password", "Le mot de passe doit contenir au moins une majuscule."
                )
            if not re.search(r"[0-9]", p1):
                self.add_error(
                    "password", "Le mot de passe doit contenir au moins un chiffre."
                )
            if not re.search(r"[^A-Za-z0-9]", p1) and len(p1) < 12:
                self.add_error(
                    "password",
                    "Le mot de passe doit contenir un symbole ou faire plus de 12 caractères.",
                )

        # 2. Validation de la correspondance
        if p1 and p2 and p1 != p2:
            self.add_error(
                "password_confirm", "Les deux mots de passe ne correspondent pas."
            )

        # 3. Validation de l'invitation (Code Foyer)
        code = cleaned_data.get("household_code")
        if code:
            code = code.strip().upper()
            invitation = HouseholdInvitation.objects.filter(
                token=code, accepted_by__isnull=True
            ).first()

            if not invitation or not invitation.is_valid:
                self.add_error(
                    "household_code", "Ce Code Foyer est invalide ou a expiré."
                )
            else:
                cleaned_data["valid_invitation"] = invitation

        return cleaned_data

    def save(self, commit=True):
        user = super().save(commit=False)
        user.set_password(self.cleaned_data["password"])
        if commit:
            user.save()
        return user


class CustomSetPasswordForm(SetPasswordForm):
    def clean_new_password1(self):
        p1 = self.cleaned_data.get("new_password1")
        if p1:
            if len(p1) < 8:
                raise forms.ValidationError(
                    "Le mot de passe doit contenir au moins 8 caractères."
                )
            if not re.search(r"[A-Z]", p1):
                raise forms.ValidationError(
                    "Le mot de passe doit contenir au moins une majuscule."
                )
            if not re.search(r"[0-9]", p1):
                raise forms.ValidationError(
                    "Le mot de passe doit contenir au moins un chiffre."
                )
            if not re.search(r"[^A-Za-z0-9]", p1) and len(p1) < 12:
                raise forms.ValidationError(
                    "Le mot de passe doit contenir un symbole ou faire plus de 12 caractères."
                )
        return p1
