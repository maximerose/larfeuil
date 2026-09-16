import csv
import datetime
import os
import re
import statistics
import xml.etree.ElementTree as ET
import zipfile
from collections import defaultdict

from django.conf import settings
from django.core.management.base import BaseCommand


def parse_excel_date(val):
    if val is None:
        return None
    if isinstance(val, (int, float)):
        try:
            dt = datetime.date(1899, 12, 30) + datetime.timedelta(days=int(val))
            return dt.strftime("%Y-%m-%d")
        except (ValueError, OverflowError, TypeError):
            return None

    val_str = str(val).strip()
    if len(val_str) >= 10:
        return val_str[:10]
    return None


def read_xlsx_sheet(zip_ref, sheet_path, shared_strings):
    try:
        sheet_xml = zip_ref.read(sheet_path)
    except KeyError:
        return []
    root = ET.fromstring(sheet_xml)
    ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
    rows_data = []
    sheet_data = root.find("s:sheetData", ns)
    if sheet_data is None:
        return []
    for row in sheet_data.findall("s:row", ns):
        row_cells = {}
        for c in row.findall("s:c", ns):
            cell_ref = c.get("r")
            cell_type = c.get("t")
            v_tag = c.find("s:v", ns)
            val = None
            if v_tag is not None and v_tag.text is not None:
                raw_val = v_tag.text
                if cell_type == "s":
                    try:
                        val = shared_strings[int(raw_val)]
                    except (IndexError, ValueError):
                        val = raw_val
                elif cell_type == "b":
                    val = raw_val == "1"
                else:
                    try:
                        val = float(raw_val) if "." in raw_val else int(raw_val)
                    except ValueError:
                        val = raw_val

            col_str = "".join([char for char in cell_ref if char.isalpha()])
            col_idx = 0
            for char in col_str:
                col_idx = col_idx * 26 + (ord(char.upper()) - ord("A") + 1)
            col_idx -= 1
            row_cells[col_idx] = val

        if row_cells:
            max_col = max(row_cells.keys())
            row_list = [row_cells.get(i, None) for i in range(max_col + 1)]
            rows_data.append(row_list)
        else:
            rows_data.append([])
    return rows_data


def parse_xlsx(file_path):
    if not os.path.exists(file_path):
        return {}
    with zipfile.ZipFile(file_path, "r") as z:
        shared_strings = []
        if "xl/sharedStrings.xml" in z.namelist():
            ss_xml = z.read("xl/sharedStrings.xml")
            ss_root = ET.fromstring(ss_xml)
            ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
            for si in ss_root.findall("s:si", ns):
                t_el = si.find("s:t", ns)
                if t_el is not None and t_el.text is not None:
                    shared_strings.append(t_el.text)
                else:
                    text_parts = [t.text for t in si.findall(".//s:t", ns) if t.text]
                    shared_strings.append("".join(text_parts))

        wb_xml = z.read("xl/workbook.xml")
        wb_root = ET.fromstring(wb_xml)
        ns = {"s": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
        rels_xml = z.read("xl/_rels/workbook.xml.rels")
        rels_root = ET.fromstring(rels_xml)
        rel_ns = {"r": "http://schemas.openxmlformats.org/package/2006/relationships"}
        rel_map = {
            rel.get("Id"): rel.get("Target")
            for rel in rels_root.findall("r:Relationship", rel_ns)
        }

        sheets = {}
        sheets_el = wb_root.find("s:sheets", ns)
        if sheets_el is not None:
            for sheet in sheets_el.findall("s:sheet", ns):
                name = sheet.get("name")
                r_id = sheet.get(
                    "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
                )
                target = rel_map.get(r_id, "")
                sheet_path = f"xl/{target}" if not target.startswith("xl/") else target
                sheets[name] = read_xlsx_sheet(z, sheet_path, shared_strings)
        return sheets


class Command(BaseCommand):
    help = "Extrait intelligemment l'historique et les prévisions en distinguant les charges par utilisateur."

    def add_arguments(self, parser):
        parser.add_argument(
            "--files", nargs="+", default=["Budget_2025.xlsx", "Budget_2026.xlsx"]
        )

    def handle(self, *args, **options):
        file_paths = options["files"]

        # --- A. COMPTES BANCAIRES ---
        accounts_records = []
        for file_path in file_paths:
            full_path = os.path.join(settings.BASE_DIR, file_path)
            sheets = parse_xlsx(full_path)
            if "Situation des comptes" in sheets:
                rows = sheets["Situation des comptes"]
                for row in rows[2:]:
                    acc_type_str, maxime_bal, laurie_bal = (
                        row[0] if len(row) > 0 else None,
                        row[2] if len(row) > 2 else None,
                        row[4] if len(row) > 4 else None,
                    )
                    if acc_type_str is not None and str(acc_type_str).strip():
                        acc_name = str(acc_type_str).strip()
                        if maxime_bal is not None:
                            try:
                                accounts_records.append(
                                    {
                                        "owner": "Maxime",
                                        "account_name": acc_name,
                                        "last_balance": float(maxime_bal),
                                        "source_file": file_path,
                                    }
                                )
                            except (ValueError, TypeError):
                                pass
                        if laurie_bal is not None:
                            try:
                                accounts_records.append(
                                    {
                                        "owner": "Laurie",
                                        "account_name": acc_name,
                                        "last_balance": float(laurie_bal),
                                        "source_file": file_path,
                                    }
                                )
                            except (ValueError, TypeError):
                                pass

        unique_accounts = {
            (rec["owner"], rec["account_name"]): rec for rec in accounts_records
        }
        with open(
            os.path.join(settings.BASE_DIR, "accounts_init.csv"),
            mode="w",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            writer = csv.DictWriter(
                f, fieldnames=["owner", "account_name", "last_balance", "source_file"]
            )
            writer.writeheader()
            writer.writerows(unique_accounts.values())

        # --- B. CHARGES FIXES & HISTORIQUE & PRÉVISIONS ---
        month_names = {
            "janvier": 1,
            "février": 2,
            "mars": 3,
            "avril": 4,
            "mai": 5,
            "juin": 6,
            "juillet": 7,
            "août": 8,
            "septembre": 9,
            "octobre": 10,
            "novembre": 11,
            "décembre": 12,
        }

        param_info = {}
        category_records = {}  # <-- NOUVEAU : Sauvegarde des catégories et du statut Swilable
        observed_txs = defaultdict(list)
        tx_records = []

        # Passe 1 : Récupération des Paramètres
        for file_path in file_paths:
            full_path = os.path.join(settings.BASE_DIR, file_path)
            sheets = parse_xlsx(full_path)
            if "Paramètres" in sheets:
                for row in sheets["Paramètres"][1:]:
                    label, freq, due_date, amount, is_pro = (
                        row[4] if len(row) > 4 else None,
                        row[5] if len(row) > 5 else None,
                        row[6] if len(row) > 6 else None,
                        row[7] if len(row) > 7 else None,
                        row[8] if len(row) > 8 else None,
                    )
                    if (
                        label is not None
                        and str(label).strip()
                        and str(label).strip() != "None"
                    ):
                        lbl_clean = str(label).strip()
                        if lbl_clean.lower() in [
                            "la bellenergie",
                            "energie",
                            "énergie",
                            "électricité",
                            "electricite",
                        ]:
                            lbl_clean = "Électricité"

                        try:
                            freq_val = int(float(freq)) if freq is not None else 1
                        except (ValueError, TypeError):
                            freq_val = 1

                        try:
                            amt_val = float(amount) if amount is not None else 0.0
                        except (ValueError, TypeError):
                            amt_val = 0.0

                        param_info[lbl_clean.lower()] = {
                            "display": lbl_clean,
                            "freq": freq_val,
                            "amount": amt_val,
                            "is_pro": bool(is_pro) if is_pro is not None else False,
                            "due_date": parse_excel_date(due_date) or "",
                        }

                    # NOUVEAU : Lecture des catégories variables et du statut Swilable
                    cat_name = row[10] if len(row) > 10 else None
                    swilable = row[11] if len(row) > 11 else False

                    if (
                        cat_name is not None
                        and str(cat_name).strip()
                        and str(cat_name).strip() != "None"
                        and str(cat_name).strip().lower() != "nan"
                    ):
                        cat_clean = str(cat_name).strip()
                        if cat_clean.lower() in ["aménagement", "aménagement / maison"]:
                            cat_clean = "Aménagement / Maison"

                        swilable_bool = (
                            str(swilable).strip().lower() in ["true", "1", "oui", "yes"]
                            or swilable is True
                        )

                        category_records[cat_clean.lower()] = {
                            "name": cat_clean,
                            "is_meal_voucher_eligible": swilable_bool,
                        }

        # Passe 2 : Historique des paiements mensuels ET PRÉVISIONS
        for file_path in file_paths:
            full_path = os.path.join(settings.BASE_DIR, file_path)
            year_match = re.search(r"20\d\d", file_path)
            default_year = int(year_match.group(0)) if year_match else 2025
            sheets = parse_xlsx(full_path)

            for sheet_name, rows in sheets.items():
                if sheet_name.strip().lower() not in month_names:
                    continue
                month_num = month_names[sheet_name.strip().lower()]

                # === EXTRACTION SÉCURISÉE DES PRÉVISIONS (Colonnes AA à AD) ===
                current_forecast_section = None
                for r_idx, row in enumerate(rows):
                    if len(row) > 26 and row[26] is not None and str(row[26]).strip():
                        cell_26_str = str(row[26]).lower().strip()

                        if (
                            "répartition revenus" in cell_26_str
                            or "prévisions revenus" in cell_26_str
                        ):
                            current_forecast_section = "INCOME"
                        elif (
                            "répartition charges fixes" in cell_26_str
                            or "prévisions charges fixes" in cell_26_str
                        ):
                            current_forecast_section = "RECURRING"
                        elif (
                            "répartition charges variables" in cell_26_str
                            or "prévisions charges variables" in cell_26_str
                        ):
                            current_forecast_section = "VARIABLE"
                        elif (
                            "répartition épargne" in cell_26_str
                            or "prévisions épargne" in cell_26_str
                        ):
                            current_forecast_section = "SAVINGS"

                        elif current_forecast_section:
                            if "total" in cell_26_str:
                                current_forecast_section = None
                            elif cell_26_str != "type":
                                cat_name = str(row[26]).strip()

                                if cat_name.lower() in [
                                    "la bellenergie",
                                    "energie",
                                    "énergie",
                                    "électricité",
                                    "electricite",
                                ]:
                                    cat_name = "Électricité"

                                # Maxime (Col AB = 27)
                                if len(row) > 27 and row[27] is not None:
                                    raw_val = str(row[27]).strip()
                                    if raw_val != "" and raw_val.lower() != "nan":
                                        try:
                                            amt = float(raw_val)
                                            if (
                                                current_forecast_section == "RECURRING"
                                                or amt != 0
                                            ):
                                                tx_records.append(
                                                    {
                                                        "source_file": file_path,
                                                        "year": default_year,
                                                        "month": month_num,
                                                        "section": f"FORECAST_{current_forecast_section}",
                                                        "label_or_category": cat_name,
                                                        "amount": amt,
                                                        "user": "Maxime",
                                                        "date": f"{default_year}-{month_num:02d}-01",
                                                        "comment": "",
                                                        "meal_voucher_amount": 0.0,
                                                    }
                                                )
                                        except (ValueError, TypeError):
                                            pass

                                # Laurie (Col AC = 28)
                                if len(row) > 28 and row[28] is not None:
                                    raw_val = str(row[28]).strip()
                                    if raw_val != "" and raw_val.lower() != "nan":
                                        try:
                                            amt = float(raw_val)
                                            if (
                                                current_forecast_section == "RECURRING"
                                                or amt != 0
                                            ):
                                                tx_records.append(
                                                    {
                                                        "source_file": file_path,
                                                        "year": default_year,
                                                        "month": month_num,
                                                        "section": f"FORECAST_{current_forecast_section}",
                                                        "label_or_category": cat_name,
                                                        "amount": amt,
                                                        "user": "Laurie",
                                                        "date": f"{default_year}-{month_num:02d}-01",
                                                        "comment": "",
                                                        "meal_voucher_amount": 0.0,
                                                    }
                                                )
                                        except (ValueError, TypeError):
                                            pass

                                # Pro (Col AD = 29)
                                if len(row) > 29 and row[29] is not None:
                                    raw_val = str(row[29]).strip()
                                    if raw_val != "" and raw_val.lower() != "nan":
                                        try:
                                            amt = float(raw_val)
                                            if (
                                                current_forecast_section == "RECURRING"
                                                or amt != 0
                                            ):
                                                tx_records.append(
                                                    {
                                                        "source_file": file_path,
                                                        "year": default_year,
                                                        "month": month_num,
                                                        "section": f"FORECAST_{current_forecast_section}",
                                                        "label_or_category": cat_name,
                                                        "amount": amt,
                                                        "user": "Pro",
                                                        "date": f"{default_year}-{month_num:02d}-01",
                                                        "comment": "",
                                                        "meal_voucher_amount": 0.0,
                                                    }
                                                )
                                        except (ValueError, TypeError):
                                            pass
                    else:
                        current_forecast_section = None
                # === FIN EXTRACTION DES PRÉVISIONS ===

                # === RÉCUPÉRATION CLASSIQUE (Transactions réelles) ===
                header_row = 28
                for r_idx in range(15, min(40, len(rows))):
                    if any(
                        "Charges variables" in str(v)
                        for v in rows[r_idx]
                        if v is not None
                    ):
                        header_row = r_idx
                        break

                # Charges fixes
                for r_idx in range(header_row + 2, len(rows)):
                    row = rows[r_idx]
                    label, amount, user, raw_date, comment = (
                        row[7] if len(row) > 7 else None,
                        row[8] if len(row) > 8 else None,
                        row[9] if len(row) > 9 else None,
                        row[10] if len(row) > 10 else None,
                        row[11] if len(row) > 11 else None,
                    )

                    if (
                        label is None
                        or not str(label).strip()
                        or str(label).strip() == "None"
                    ):
                        continue

                    if amount is not None:
                        try:
                            amt_f = float(amount)
                            if amt_f != 0 and (
                                user is not None or raw_date is not None
                            ):
                                lbl_clean = str(label).strip()
                                if lbl_clean.lower() in [
                                    "la bellenergie",
                                    "energie",
                                    "énergie",
                                    "électricité",
                                    "electricite",
                                ]:
                                    lbl_clean = "Électricité"

                                usr_str = (
                                    str(user).strip().lower()
                                    if user is not None
                                    else ""
                                )
                                if "pro" in usr_str:
                                    owner = "Pro"
                                elif "laurie" in usr_str:
                                    owner = "Laurie"
                                else:
                                    owner = "Maxime"

                                dt_str = parse_excel_date(raw_date)
                                observed_txs[lbl_clean.lower()].append(
                                    {"owner": owner, "amount": amt_f, "date": dt_str}
                                )

                                tx_records.append(
                                    {
                                        "source_file": file_path,
                                        "year": default_year,
                                        "month": month_num,
                                        "section": "RECURRING",
                                        "label_or_category": lbl_clean,
                                        "amount": amt_f,
                                        "user": owner,
                                        "date": dt_str
                                        if dt_str
                                        else f"{default_year}-{month_num:02d}-01",
                                        "comment": str(comment).strip()
                                        if comment is not None
                                        else "",
                                        "meal_voucher_amount": 0.0,
                                    }
                                )
                        except (ValueError, TypeError):
                            pass

                # Revenus
                for r_idx in range(header_row + 2, len(rows)):
                    row = rows[r_idx]
                    cat, amount, user, raw_date, comment = (
                        row[1] if len(row) > 1 else None,
                        row[2] if len(row) > 2 else None,
                        row[3] if len(row) > 3 else None,
                        row[4] if len(row) > 4 else None,
                        row[5] if len(row) > 5 else None,
                    )
                    if cat is not None and amount is not None:
                        try:
                            amt_f = float(amount)
                            if amt_f != 0:
                                dt_str = parse_excel_date(raw_date)
                                tx_records.append(
                                    {
                                        "source_file": file_path,
                                        "year": default_year,
                                        "month": month_num,
                                        "section": "INCOME",
                                        "label_or_category": str(cat).strip(),
                                        "amount": amt_f,
                                        "user": str(user).strip()
                                        if user is not None
                                        else "",
                                        "date": dt_str
                                        if dt_str
                                        else f"{default_year}-{month_num:02d}-01",
                                        "comment": str(comment).strip()
                                        if comment is not None
                                        else "",
                                        "meal_voucher_amount": 0.0,
                                    }
                                )
                        except (ValueError, TypeError):
                            pass

                # Variables
                for r_idx in range(header_row + 2, len(rows)):
                    row = rows[r_idx]
                    cat, amount, user, raw_date, comment, swile_amt = (
                        row[12] if len(row) > 12 else None,
                        row[13] if len(row) > 13 else None,
                        row[14] if len(row) > 14 else None,
                        row[15] if len(row) > 15 else None,
                        row[16] if len(row) > 16 else None,
                        row[18] if len(row) > 18 else None,
                    )
                    if cat is not None and amount is not None:
                        try:
                            amt_f = float(amount)
                            if amt_f != 0:
                                dt_str = parse_excel_date(raw_date)
                                mv_f = 0.0
                                if swile_amt is not None:
                                    try:
                                        mv_f = float(swile_amt)
                                    except (ValueError, TypeError):
                                        pass
                                tx_records.append(
                                    {
                                        "source_file": file_path,
                                        "year": default_year,
                                        "month": month_num,
                                        "section": "VARIABLE",
                                        "label_or_category": str(cat).strip(),
                                        "amount": amt_f,
                                        "user": str(user).strip()
                                        if user is not None
                                        else "",
                                        "date": dt_str
                                        if dt_str
                                        else f"{default_year}-{month_num:02d}-01",
                                        "comment": str(comment).strip()
                                        if comment is not None
                                        else "",
                                        "meal_voucher_amount": mv_f,
                                    }
                                )
                        except (ValueError, TypeError):
                            pass

                # Épargne
                for r_idx in range(header_row + 2, len(rows)):
                    row = rows[r_idx]
                    acc, amount, user, raw_date, comment = (
                        row[20] if len(row) > 20 else None,
                        row[21] if len(row) > 21 else None,
                        row[22] if len(row) > 22 else None,
                        row[23] if len(row) > 23 else None,
                        row[24] if len(row) > 24 else None,
                    )
                    if acc is not None and amount is not None:
                        try:
                            amt_f = float(amount)
                            if amt_f != 0:
                                dt_str = parse_excel_date(raw_date)
                                tx_records.append(
                                    {
                                        "source_file": file_path,
                                        "year": default_year,
                                        "month": month_num,
                                        "section": "SAVINGS",
                                        "label_or_category": str(acc).strip(),
                                        "amount": amt_f,
                                        "user": str(user).strip()
                                        if user is not None
                                        else "",
                                        "date": dt_str
                                        if dt_str
                                        else f"{default_year}-{month_num:02d}-01",
                                        "comment": str(comment).strip()
                                        if comment is not None
                                        else "",
                                        "meal_voucher_amount": 0.0,
                                    }
                                )
                        except (ValueError, TypeError):
                            pass

        # Passe 3 : Résolution Finale (Dédoublonnage Intelligent)
        recurring_records = []
        all_labels = set(param_info.keys()).union(set(observed_txs.keys()))

        for lbl_lower in all_labels:
            p_info = param_info.get(
                lbl_lower,
                {
                    "display": lbl_lower.title(),
                    "freq": 1,
                    "amount": 0.0,
                    "is_pro": False,
                    "due_date": "",
                },
            )
            txs = observed_txs.get(lbl_lower, [])
            lbl_display = p_info["display"]

            if p_info["is_pro"]:
                true_owners = ["Pro"]
            else:
                if any(
                    x in lbl_lower for x in ["salle de sport", "bestrong", "icloud"]
                ):
                    true_owners = ["Laurie"]
                elif "viacham" in lbl_lower:
                    true_owners = ["Maxime", "Laurie"]
                elif not txs:
                    true_owners = ["Maxime"]
                else:
                    owner_counts = defaultdict(int)
                    for tx in txs:
                        owner_counts[tx["owner"]] += 1
                    valid_owners = [o for o, c in owner_counts.items() if c >= 2]
                    if not valid_owners:
                        top_owner = max(owner_counts, key=owner_counts.get)
                        true_owners = [top_owner]
                    else:
                        true_owners = valid_owners

            for owner in true_owners:
                if owner == "Pro":
                    o_txs = txs
                else:
                    o_txs = [tx for tx in txs if tx["owner"] == owner]

                dates = [tx["date"] for tx in o_txs if tx["date"]]
                amts = [tx["amount"] for tx in o_txs if tx["amount"] > 0]

                final_due_date_str = ""
                if p_info["freq"] > 1:
                    if p_info["due_date"]:
                        final_due_date_str = p_info["due_date"]
                    elif dates:
                        final_due_date_str = max(dates)
                    else:
                        final_due_date_str = "2026-01-01"
                else:
                    if dates:
                        days = []
                        for d in dates:
                            try:
                                days.append(datetime.date.fromisoformat(d).day)
                            except ValueError:
                                pass
                        final_due_date_str = (
                            f"2026-01-{round(statistics.median(days)):02d}"
                            if days
                            else "2026-01-01"
                        )
                    elif p_info["due_date"]:
                        try:
                            final_due_date_str = f"2026-01-{datetime.date.fromisoformat(p_info['due_date']).day:02d}"
                        except ValueError:
                            final_due_date_str = "2026-01-01"
                    else:
                        final_due_date_str = "2026-01-01"

                final_amount = amts[-1] if amts else p_info["amount"]

                recurring_records.append(
                    {
                        "label": lbl_display,
                        "owner": owner,
                        "frequency_months": p_info["freq"],
                        "total_amount": final_amount,
                        "usual_due_day": final_due_date_str,
                        "is_variable": lbl_lower in ["électricité", "urssaf", "impôts"],
                    }
                )

        # NOUVEAU : Sauvegarde des catégories et de leur éligibilité Tickets Resto
        with open(
            os.path.join(settings.BASE_DIR, "categories_init.csv"),
            mode="w",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "name",
                    "is_meal_voucher_eligible",
                ],
            )
            writer.writeheader()
            writer.writerows(category_records.values())

        with open(
            os.path.join(settings.BASE_DIR, "recurring_expenses_init.csv"),
            mode="w",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            writer = csv.DictWriter(
                f,
                fieldnames=[
                    "label",
                    "owner",
                    "frequency_months",
                    "total_amount",
                    "usual_due_day",
                    "is_variable",
                ],
            )
            writer.writeheader()
            writer.writerows(recurring_records)

        with open(
            os.path.join(settings.BASE_DIR, "transactions_history.csv"),
            mode="w",
            encoding="utf-8-sig",
            newline="",
        ) as f:
            fieldnames = [
                "source_file",
                "year",
                "month",
                "section",
                "label_or_category",
                "amount",
                "user",
                "date",
                "comment",
                "meal_voucher_amount",
            ]
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(tx_records)

        self.stdout.write(
            self.style.SUCCESS("Extraction terminée, lancez import_history_csv")
        )
