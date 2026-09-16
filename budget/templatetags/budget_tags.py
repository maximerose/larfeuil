from decimal import Decimal

from django import template

register = template.Library()


@register.simple_tag
def build_progress_data(spent, allocated):
    try:
        spent_dec = Decimal(str(spent or 0))
        alloc_dec = Decimal(str(allocated or 0))
    except (ValueError, TypeError):
        spent_dec = Decimal("0.00")
        alloc_dec = Decimal("0.00")

    if alloc_dec <= 0:
        ratio = 100 if spent_dec > 0 else 0
    else:
        ratio = float((spent_dec / alloc_dec) * 100)

    percentage = min(100.0, max(0.0, ratio))

    # Couleur dynamique : Vert < 80%, Orange 80-100%, Rouge > 100%
    if ratio < 80:
        bg_color = "bg-action-primary"
        text_color = "text-action-primary"
    elif ratio <= 100:
        bg_color = "bg-action-warning"
        text_color = "text-action-warning"
    else:
        bg_color = "bg-action-danger"
        text_color = "text-action-danger"

    return {
        "percentage": round(percentage, 1),
        "ratio_raw": round(ratio, 1),
        "bg_color": bg_color,
        "text_color": text_color,
    }


@register.simple_tag
def get_badge_classes(variant: str) -> str:
    variant = (variant or "").lower()
    base = (
        "inline-flex items-center rounded-full border px-2.5 py-1 text-xs font-semibold"
    )

    styles = {
        "success": "border-budget-income/20 bg-budget-income/10 text-budget-income",
        "income": "border-budget-income/20 bg-budget-income/10 text-budget-income",
        "danger": "border-budget-recurring/20 bg-budget-recurring/10 text-budget-recurring",
        "expense": "border-budget-recurring/20 bg-budget-recurring/10 text-budget-recurring",
        "recurring": "border-budget-recurring/20 bg-budget-recurring/10 text-budget-recurring",
        "warning": "border-budget-variable/20 bg-budget-variable/10 text-budget-variable",
        "variable": "border-budget-variable/20 bg-budget-variable/10 text-budget-variable",
        "checking": "border-account-checking/20 bg-account-checking/10 text-account-checking",
        "savings": "border-account-savings/20 bg-account-savings/10 text-account-savings",
        "business": "border-account-business/20 bg-account-business/10 text-account-business",
        "meal_voucher": "border-account-meal/20 bg-account-meal/10 text-account-meal",
        "other": "border-account-other/20 bg-account-other/10 text-account-other",
    }

    color = styles.get(variant, "border-brand-border bg-brand-border/50 text-slate-300")
    return f"{base} {color}"
