from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path, reverse_lazy

from budget.forms.auth import CustomSetPasswordForm
from budget.views import dashboard_view, quick_transaction_form_view
from budget.views.accounts import (
    settings_account_delete_view,
    settings_account_form_view,
    settings_accounts_list_view,
)
from budget.views.api import api_create_element_view
from budget.views.auth import join_household_view, register_view
from budget.views.categories import (
    settings_categories_list_view,
    settings_category_delete_view,
    settings_category_form_view,
    settings_category_merge_view,
)
from budget.views.dashboard import pay_recurring_expense_view
from budget.views.forecast import forecast_list_view, quick_forecast_override
from budget.views.profile import (
    settings_generate_invite,
    settings_household_update,
    settings_profile_update,
    settings_profile_view,
)
from budget.views.recurring import (
    settings_recurring_delete_view,
    settings_recurring_form_view,
    settings_recurring_list_view,
    settings_recurring_share_delete_view,
    settings_recurring_shares_view,
)
from budget.views.statistics import statistics_view
from budget.views.transactions import (
    adjust_account_balance_view,
    monthly_history_view,
    transaction_delete_view,
    transaction_update_view,
    transfer_delete_view,
    transfer_update_view,
)
from core.views import deploy_webhook

urlpatterns = [
    path("admin/", admin.site.urls),
    path("api/deploy-webhook/", deploy_webhook, name="deploy_webhook"),
    # --- Authentification ---
    path(
        "login/",
        auth_views.LoginView.as_view(redirect_authenticated_user=True),
        name="login",
    ),
    path(
        "logout/",
        auth_views.LogoutView.as_view(),
        name="logout",
    ),
    path(
        "register/",
        register_view,
        name="register",
    ),
    path(
        "join/<str:token>/",
        join_household_view,
        name="join_household",
    ),
    # Réinitialisation de mot de passe
    path(
        "password-reset/",
        auth_views.PasswordResetView.as_view(
            template_name="registration/password_reset_form.html",
            email_template_name="registration/password_reset_email.html",
            subject_template_name="registration/password_reset_subject.txt",
        ),
        name="password_reset",
    ),
    path(
        "password-reset/done/",
        auth_views.PasswordResetDoneView.as_view(
            template_name="registration/password_reset_done.html"
        ),
        name="password_reset_done",
    ),
    path(
        "password-reset-confirm/<uidb64>/<token>/",
        auth_views.PasswordResetConfirmView.as_view(
            template_name="registration/password_reset_confirm.html",
            success_url=reverse_lazy("password_reset_complete"),
            form_class=CustomSetPasswordForm,
        ),
        name="password_reset_confirm",
    ),
    path(
        "password-reset-complete/",
        auth_views.PasswordResetCompleteView.as_view(
            template_name="registration/password_reset_complete.html"
        ),
        name="password_reset_complete",
    ),
    # --- Application ---
    path(
        "",
        dashboard_view,
        name="dashboard",
    ),
    path(
        "quick-transaction/",
        quick_transaction_form_view,
        name="quick_transaction_form",
    ),
    path(
        "forecast/quick-override/<uuid:expense_id>/",
        quick_forecast_override,
        name="quick_forecast_override",
    ),
    path(
        "account/<str:account_id>/adjust/",
        adjust_account_balance_view,
        name="adjust_account_balance",
    ),
    path(
        "recurring/<str:expense_id>/pay/",
        pay_recurring_expense_view,
        name="pay_recurring_expense",
    ),
    path(
        "transactions/<uuid:transaction_id>/update/",
        transaction_update_view,
        name="transaction_update",
    ),
    path(
        "transactions/<uuid:transaction_id>/delete/",
        transaction_delete_view,
        name="transaction_delete",
    ),
    path(
        "transfers/<uuid:transfer_id>/update/",
        transfer_update_view,
        name="transfer_update",
    ),
    path(
        "transfers/<uuid:transfer_id>/delete/",
        transfer_delete_view,
        name="transfer_delete",
    ),
    path(
        "transactions/history/",
        monthly_history_view,
        name="monthly_history",
    ),
    path(
        "forecasts/",
        forecast_list_view,
        name="forecast_list",
    ),
    path(
        "statistics/",
        statistics_view,
        name="statistics",
    ),
    # --- Paramètres & Configuration ---
    path(
        "settings/accounts/",
        settings_accounts_list_view,
        name="settings_accounts",
    ),
    path(
        "settings/accounts/create/",
        settings_account_form_view,
        name="settings_account_create",
    ),
    path(
        "settings/accounts/<uuid:account_id>/update/",
        settings_account_form_view,
        name="settings_account_update",
    ),
    path(
        "settings/accounts/<uuid:account_id>/delete/",
        settings_account_delete_view,
        name="settings_account_delete",
    ),
    path(
        "settings/categories/",
        settings_categories_list_view,
        name="settings_categories",
    ),
    path(
        "settings/categories/create/",
        settings_category_form_view,
        name="settings_category_create",
    ),
    path(
        "settings/categories/<uuid:category_id>/update/",
        settings_category_form_view,
        name="settings_category_update",
    ),
    path(
        "settings/categories/<uuid:category_id>/delete/",
        settings_category_delete_view,
        name="settings_category_delete",
    ),
    path(
        "settings/categories/<uuid:category_id>/merge/",
        settings_category_merge_view,
        name="settings_category_merge",
    ),
    path(
        "settings/recurring/",
        settings_recurring_list_view,
        name="settings_recurring",
    ),
    path(
        "settings/recurring/create/",
        settings_recurring_form_view,
        name="settings_recurring_create",
    ),
    path(
        "settings/recurring/<uuid:expense_id>/update/",
        settings_recurring_form_view,
        name="settings_recurring_update",
    ),
    path(
        "settings/recurring/<uuid:expense_id>/delete/",
        settings_recurring_delete_view,
        name="settings_recurring_delete",
    ),
    path(
        "settings/recurring/<uuid:expense_id>/shares/",
        settings_recurring_shares_view,
        name="settings_recurring_shares",
    ),
    path(
        "settings/recurring/<uuid:expense_id>/shares/<uuid:share_id>/delete/",
        settings_recurring_share_delete_view,
        name="settings_recurring_share_delete",
    ),
    path(
        "settings/profile/",
        settings_profile_view,
        name="settings_profile",
    ),
    path(
        "settings/profile/update/",
        settings_profile_update,
        name="settings_profile_update",
    ),
    path(
        "settings/household/update/",
        settings_household_update,
        name="settings_household_update",
    ),
    path(
        "settings/household/invite/",
        settings_generate_invite,
        name="settings_generate_invite",
    ),
    # API TomSelect
    path("api/create/", api_create_element_view, name="api_create_element"),
]
