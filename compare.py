import re
import pandas as pd

from utils import normalize_text_for_compare, normalize_subclass_simple


def compare_shams(
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    column_mapping: dict,
) -> pd.DataFrame:
    """
    Сравнение старого и нового SHAMS-файлов
    с учётом выбранных и сопоставленных столбцов.

    column_mapping:
        {
            <new_col>: <old_col> | None
        }

    Логика:
    - Subclass_en сравнивается ВСЕГДА
    - если old_col != None → сравниваем old vs new
    - если old_col == None → колонка считается новой
      и просто добавляется как <col>_new
    """

    # ==================================================
    # 1. Копии + нормализация ключа
    # ==================================================
    df_old = df_old.copy()
    df_new = df_new.copy()

    df_old["Subclass_code"] = df_old["Subclass"].apply(normalize_subclass_simple)
    df_new["Subclass_code"] = df_new["Subclass"].apply(normalize_subclass_simple)

    df_old = df_old[df_old["Subclass_code"].notna()]
    df_new = df_new[df_new["Subclass_code"].notna()]

    # ==================================================
    # 2. Разделяем выбранные колонки
    # ==================================================
    mapped_pairs = []   # (old_col, new_col)
    new_only_cols = [] # new_col без пары

    for new_col, old_col in column_mapping.items():
        if old_col:
            mapped_pairs.append((old_col, new_col))
        else:
            new_only_cols.append(new_col)

    BASE_COMPARE_COL = "Subclass_en"

    # ==================================================
    # 3. Суффиксы и merge
    # ==================================================
    df_old = df_old.add_suffix("_old")
    df_new = df_new.add_suffix("_new")

    df_old = df_old.rename(columns={"Subclass_code_old": "Subclass_code"})
    df_new = df_new.rename(columns={"Subclass_code_new": "Subclass_code"})

    df = pd.merge(
        df_old,
        df_new,
        on="Subclass_code",
        how="outer",
        indicator=True,
    )

    # ==================================================
    # 4. Первичный статус
    # ==================================================
    def initial_status(row):
        if row["_merge"] == "left_only":
            return "deleted"
        if row["_merge"] == "right_only":
            return "added"
        return "potentially_changed"

    df["status"] = df.apply(initial_status, axis=1)

    # ==================================================
    # 5. Поиск различий
    # ==================================================
    diff_columns = []

    for _, row in df.iterrows():
        diffs = []

        if row["status"] == "potentially_changed":

            # --- Subclass_en (всегда) ---
            old_val = normalize_text_for_compare(row.get("Subclass_en_old", ""))
            new_val = normalize_text_for_compare(row.get("Subclass_en_new", ""))

            if old_val != new_val:
                diffs.append(BASE_COMPARE_COL)

            # --- сопоставленные колонки ---
            for old_col, new_col in mapped_pairs:
                old_v = normalize_text_for_compare(row.get(f"{old_col}_old", ""))
                new_v = normalize_text_for_compare(row.get(f"{new_col}_new", ""))

                if old_v != new_v:
                    diffs.append(new_col)

        diff_columns.append(diffs)

    df["diff_columns"] = diff_columns

    # ==================================================
    # 6. Финальный статус
    # ==================================================
    def final_status(row):
        if row["status"] in ("added", "deleted"):
            return row["status"]
        if len(row["diff_columns"]) > 0:
            return "changed"
        return "not changed"

    df["status"] = df.apply(final_status, axis=1)

    # ==================================================
    # 7. Формирование итоговых колонок
    # ==================================================
    front_cols = [
        "Subclass_code",
        "status",
        "diff_columns",
    ]

    base_cols = [
        "Subclass_en_old",
        "Subclass_en_new",
    ]

    dynamic_cols = []

    # сопоставленные: old + new
    for old_col, new_col in mapped_pairs:
        dynamic_cols.append(f"{old_col}_old")
        dynamic_cols.append(f"{new_col}_new")

    # новые без пары: ТОЛЬКО new
    for new_col in new_only_cols:
        dynamic_cols.append(f"{new_col}_new")

    final_cols = front_cols + base_cols + dynamic_cols
    final_cols = [c for c in final_cols if c in df.columns]

    return df[final_cols]


# ==================================================
# ================== STATS =========================
# ==================================================
def comparison_stats(df_compare: pd.DataFrame) -> pd.DataFrame:
    total_old = df_compare["status"].isin(
        ["not changed", "changed", "deleted"]
    ).sum()
    total_new = df_compare["status"].isin(
        ["not changed", "changed", "added"]
    ).sum()

    added = (df_compare["status"] == "added").sum()
    deleted = (df_compare["status"] == "deleted").sum()
    changed = (df_compare["status"] == "changed").sum()
    not_changed = (df_compare["status"] == "not changed").sum()

    stats = pd.DataFrame(
        {
            "metric": [
                "Количество строк в старом файле",
                "Количество строк в новом файле",
                "Добавлено",
                "Удалено",
                "Изменено (по английским описаниям)",
                "Не изменено",
            ],
            "value": [
                total_old,
                total_new,
                added,
                deleted,
                changed,
                not_changed,
            ],
        }
    )
    return stats


# ==================================================
# ============== JOIN WITH EDIT ====================
# ==================================================
def join_with_edit(
    df_compare: pd.DataFrame,
    df_edit: pd.DataFrame,
) -> pd.DataFrame:
    """
    Присоединяет shams_edit.xlsx к df_compare
    по нормализованному Subclass.

    В df_edit ключевой столбец:
    'Введите код бизнес-деятельности'
    """

    df_compare = df_compare.copy()
    df_compare["Subclass"] = df_compare["Subclass"].astype(str)

    df_edit = df_edit.copy()

    def normalize_subclass(code):
        if pd.isna(code):
            return None
        s = re.sub(r"[^0-9]", "", str(code))
        if len(s) < 5:
            return None
        return f"{s[:4]}.{s[4:].ljust(2, '0')[:2]}"

    df_edit["Subclass"] = df_edit["Введите код бизнес-деятельности"].apply(
        normalize_subclass
    )
    df_edit["Subclass"] = df_edit["Subclass"].astype(str)

    # суффиксы для избежания конфликтов
    df_edit = df_edit.add_suffix("_edit")
    df_edit = df_edit.rename(columns={"Subclass_edit": "Subclass"})

    df_joined = df_compare.merge(df_edit, on="Subclass", how="left")

    return df_joined




# def compare_shams(df_old, df_new):
#
#     df_old = df_old.copy()
#     df_new = df_new.copy()
#
#     # нормализуем ключ
#     df_old["Subclass_norm"] = df_old["Subclass"].apply(normalize_subclass_simple)
#     df_new["Subclass_norm"] = df_new["Subclass"].apply(normalize_subclass_simple)
#
#     df_old = df_old[df_old["Subclass_norm"].notna()]
#     df_new = df_new[df_new["Subclass_norm"].notna()]
#
#     # добавляем суффиксы
#     df_old = df_old.add_suffix("_old")
#     df_new = df_new.add_suffix("_new")
#
#     # вернуть имя ключа
#     df_old = df_old.rename(columns={"Subclass_norm_old": "Subclass_norm"})
#     df_new = df_new.rename(columns={"Subclass_norm_new": "Subclass_norm"})
#
#     # FULL JOIN
#     df = pd.merge(df_old, df_new, on="Subclass_norm", how="outer", indicator=True)
#
#     # -------------------------------
#     # Первичное определение статуса
#     # -------------------------------
#     def classify(row):
#         if row["_merge"] == "left_only":
#             return "deleted"
#         if row["_merge"] == "right_only":
#             return "added"
#         return "potentially_changed"
#
#     df["status"] = df.apply(classify, axis=1)
#
#     # -------------------------------
#     # Сравнение ТОЛЬКО Subclass_en
#     # -------------------------------
#     diff_list = []
#
#     for _, row in df.iterrows():
#         diffs = []
#
#         if row["status"] == "potentially_changed":
#             old_val = normalize_text_for_compare(row.get("Subclass_en_old", ""))
#             new_val = normalize_text_for_compare(row.get("Subclass_en_new", ""))
#
#             if old_val != new_val:
#                 diffs.append("Subclass_en")
#
#         diff_list.append(diffs)
#
#     df["diff_columns"] = diff_list
#
#     # -------------------------------
#     # Финальный статус
#     # -------------------------------
#     def final_status(row):
#         if row["status"] in ("added", "deleted"):
#             return row["status"]
#         if len(row["diff_columns"]) > 0:
#             return "changed"
#         return "not changed"
#
#     df["status"] = df.apply(final_status, axis=1)
#
#     # -------------------------------
#     # Итоговый порядок
#     # -------------------------------
#     front_cols = ["Subclass_norm", "status", "diff_columns"]
#     other = [c for c in df.columns if c not in front_cols and c != "_merge"]
#
#     return df[front_cols + other]


# def comparison_stats(df_compare: pd.DataFrame) -> pd.DataFrame:
#     total_old = df_compare["status"].isin(["not changed", "changed", "deleted"]).sum()
#     total_new = df_compare["status"].isin(["not changed", "changed", "added"]).sum()
#
#     added = (df_compare["status"] == "added").sum()
#     deleted = (df_compare["status"] == "deleted").sum()
#     changed = (df_compare["status"] == "changed").sum()
#     not_changed = (df_compare["status"] == "not changed").sum()
#
#     stats = pd.DataFrame({
#         "metric": [
#             "Количество строк в старом файле",
#             "Количество строк в новом файле",
#             "Добавлено",
#             "Удалено",
#             "Изменено (по английским описаниям)",
#             "Не изменено",
#         ],
#         "value": [
#             total_old,
#             total_new,
#             added,
#             deleted,
#             changed,
#             not_changed,
#         ],
#     })
#     return stats
#
# def join_with_edit(
#     df_compare: pd.DataFrame,
#     df_edit: pd.DataFrame,
#     selected_cols: list[str],
# ) -> pd.DataFrame:
#     """
#     Присоединяет выбранные столбцы из shams_edit.xlsx
#     к df_compare по Subclass_code.
#     """
#
#     df_compare = df_compare.copy()
#     df_edit = df_edit.copy()
#
#     # --- нормализация ключа в edit ---
#     def normalize_subclass(code):
#         if pd.isna(code):
#             return None
#         s = re.sub(r"[^0-9]", "", str(code))
#         if len(s) < 5:
#             return None
#         return f"{s[:4]}.{s[4:].ljust(2, '0')[:2]}"
#
#     df_edit["Subclass_code"] = (
#         df_edit["Введите код бизнес-деятельности"]
#         .apply(normalize_subclass)
#     )
#
#     # --- оставляем только выбранные колонки + ключ ---
#     keep_cols = ["Subclass_code"] + selected_cols
#     df_edit = df_edit[keep_cols]
#
#     # --- суффикс ---
#     df_edit = df_edit.add_suffix("_edit")
#     df_edit = df_edit.rename(columns={"Subclass_code_edit": "Subclass_code"})
#
#     # --- join ---
#     df_joined = df_compare.merge(
#         df_edit,
#         on="Subclass_code",
#         how="left"
#     )
#
#     return df_joined

# def join_with_edit(df_compare: pd.DataFrame, df_edit: pd.DataFrame) -> pd.DataFrame:
#     """
#     Присоединяет shams_edit1 к df_compare по нормализованному Subclass.
#     В df_edit ключевой столбец: 'Введите код бизнес-деятельности'.
#     """
#     df_compare = df_compare.copy()
#     df_compare["Subclass"] = df_compare["Subclass"].astype(str)
#
#     # --- 2. Нормализуем ключ в shams_edit1
#     df_edit = df_edit.copy()
#
#     def normalize_subclass(code):
#         if pd.isna(code):
#             return None
#         s = re.sub(r"[^0-9]", "", str(code))
#         if len(s) < 5:
#             return None
#         return f"{s[:4]}.{s[4:].ljust(2, '0')[:2]}"
#
#     df_edit["Subclass"] = df_edit["Введите код бизнес-деятельности"].apply(normalize_subclass)
#     df_edit["Subclass"] = df_edit["Subclass"].astype(str)
#
#     # --- 3. Добавляем суффиксы, чтобы избежать конфликтов
#     df_edit = df_edit.add_suffix("_edit")
#     df_edit = df_edit.rename(columns={"Subclass_edit": "Subclass"})
#
#     # --- 4. JOIN
#     df_joined = df_compare.merge(df_edit, on="Subclass", how="left")
#
#     return df_joined
