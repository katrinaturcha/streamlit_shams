import io
from datetime import datetime

import pandas as pd


def extract_headers_from_main_table(file_bytes: bytes, sheets=None):
    """
    Извлекает заголовки ТОЛЬКО из строки, где есть:
    Division, Group, Class, Subclass.

    Берёт заголовки начиная с 'Division' и далее.
    """
    bio = io.BytesIO(file_bytes)
    xls = pd.ExcelFile(bio)

    if sheets is None:
        sheets = xls.sheet_names

    unique_headers = []

    for sheet in sheets:
        df = pd.read_excel(xls, sheet_name=sheet, header=None)

        header_row_idx = None
        for i in range(len(df)):
            row = (
                df.iloc[i]
                .astype(str)
                .str.strip()
                .str.lower()
                .tolist()
            )
            if (
                "division" in row
                and "group" in row
                and "class" in row
                and "subclass" in row
            ):
                header_row_idx = i
                break

        if header_row_idx is None:
            continue

        row = df.iloc[header_row_idx].astype(str).str.strip()
        row_lower = row.str.lower().tolist()

        try:
            div_pos = row_lower.index("division")
        except ValueError:
            continue

        for col in row.iloc[div_pos:]:
            if pd.isna(col):
                continue

            col_clean = str(col).strip()
            if not col_clean:
                continue

            if col_clean.lower().startswith("unnamed"):
                continue

            if col_clean not in unique_headers:
                col_clean = str(col).replace("\u00A0", " ").replace("\n", " ").replace("\r", " ")
                col_clean = " ".join(col_clean.split()).strip()

                unique_headers.append(col_clean)

    return unique_headers


def compare_headers(headers_old, headers_new, provider="Shams Provider"):
    """
    Создаёт лог изменений столбцов.

    Возвращает DataFrame с колонками:
    datetime | provider | old | new | action
    """
    now = datetime.now().strftime("%Y-%m-%d %H:%M")

    old_set = set(headers_old)
    new_set = set(headers_new)

    deleted = sorted(old_set - new_set)
    added = sorted(new_set - old_set)
    unchanged = sorted(old_set & new_set)

    rows = []

    for col in deleted:
        rows.append(
            {
                "datetime": now,
                "provider": provider,
                "old": col,
                "new": None,
                "action": "deleted",
            }
        )

    for col in added:
        rows.append(
            {
                "datetime": now,
                "provider": provider,
                "old": None,
                "new": col,
                "action": "added",
            }
        )

    for col in unchanged:
        rows.append(
            {
                "datetime": now,
                "provider": provider,
                "old": col,
                "new": col,
                "action": "unchanged",
            }
        )

    return pd.DataFrame(rows)


def build_header_change_log_from_bytes(
    shams1_bytes: bytes,
    shams2_bytes: bytes,
    sheets,
):
    h1 = extract_headers_from_main_table(shams1_bytes, sheets)
    h2 = extract_headers_from_main_table(shams2_bytes, sheets)

    log_df = compare_headers(h1, h2, provider="Shams Provider")

    return h1, h2, log_df
