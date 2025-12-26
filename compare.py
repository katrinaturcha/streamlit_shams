import pandas as pd
from utils import normalize_text_for_compare, normalize_subclass_simple


def compare_shams(
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    column_mapping: dict,
) -> pd.DataFrame:
    """
    Сравнивает ТОЛЬКО выбранные и сопоставленные колонки.
    В итоговом df нет лишних столбцов физически.
    """

    # ==================================================
    # 1. Нормализация ключа
    # ==================================================
    df_old = df_old.copy()
    df_new = df_new.copy()

    df_old["Subclass_norm"] = df_old["Subclass"].apply(normalize_subclass_simple)
    df_new["Subclass_norm"] = df_new["Subclass"].apply(normalize_subclass_simple)

    df_old = df_old[df_old["Subclass_norm"].notna()]
    df_new = df_new[df_new["Subclass_norm"].notna()]

    # ==================================================
    # 2. Определяем РАЗРЕШЁННЫЕ колонки
    # ==================================================
    # всегда нужны:
    BASE_COLS = {"Subclass_norm", "Subclass_en"}

    # пары сопоставлений
    compare_pairs = [
        (old_col, new_col)
        for new_col, old_col in column_mapping.items()
        if old_col is not None
    ]

    old_cols_needed = {old for old, _ in compare_pairs}
    new_cols_needed = {new for _, new in compare_pairs}

    # итоговый whitelist
    old_keep = BASE_COLS | old_cols_needed
    new_keep = BASE_COLS | new_cols_needed

    # ==================================================
    # 3. ЖЁСТКАЯ ФИЛЬТРАЦИЯ колонок (КЛЮЧЕВОЙ ШАГ)
    # ==================================================
    df_old = df_old[[c for c in df_old.columns if c in old_keep]]
    df_new = df_new[[c for c in df_new.columns if c in new_keep]]

    # ==================================================
    # 4. Суффиксы и merge
    # ==================================================
    df_old = df_old.add_suffix("_old")
    df_new = df_new.add_suffix("_new")

    df_old = df_old.rename(columns={"Subclass_norm_old": "Subclass_norm"})
    df_new = df_new.rename(columns={"Subclass_norm_new": "Subclass_norm"})

    df = pd.merge(
        df_old,
        df_new,
        on="Subclass_norm",
        how="outer",
        indicator=True,
    )

    # ==================================================
    # 5. Первичный статус
    # ==================================================
    def initial_status(row):
        if row["_merge"] == "left_only":
            return "deleted"
        if row["_merge"] == "right_only":
            return "added"
        return "potentially_changed"

    df["status"] = df.apply(initial_status, axis=1)

    # ==================================================
    # 6. Поиск различий ТОЛЬКО по выбранным колонкам
    # ==================================================
    diff_columns = []

    for _, row in df.iterrows():
        diffs = []

        if row["status"] == "potentially_changed":

            # Subclass_en — всегда
            if (
                normalize_text_for_compare(row.get("Subclass_en_old", ""))
                != normalize_text_for_compare(row.get("Subclass_en_new", ""))
            ):
                diffs.append("Subclass_en")

            # динамика
            for old_col, new_col in compare_pairs:
                old_v = normalize_text_for_compare(row.get(f"{old_col}_old", ""))
                new_v = normalize_text_for_compare(row.get(f"{new_col}_new", ""))
                if old_v != new_v:
                    diffs.append(new_col)

        diff_columns.append(diffs)

    df["diff_columns"] = diff_columns

    # ==================================================
    # 7. Финальный статус
    # ==================================================
    def final_status(row):
        if row["status"] in ("added", "deleted"):
            return row["status"]
        if row["diff_columns"]:
            return "changed"
        return "not changed"

    df["status"] = df.apply(final_status, axis=1)

    # ==================================================
    # 8. ФИНАЛЬНЫЙ набор колонок (и ТОЛЬКО ОН)
    # ==================================================
    final_cols = [
        "Subclass_norm",
        "status",
        "diff_columns",
        "Subclass_en_old",
        "Subclass_en_new",
    ]

    for old_col, new_col in compare_pairs:
        final_cols.append(f"{old_col}_old")
        final_cols.append(f"{new_col}_new")

    final_cols = [c for c in final_cols if c in df.columns]

    return df[final_cols]


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


def comparison_stats(df_compare: pd.DataFrame) -> pd.DataFrame:
    total_old = df_compare["status"].isin(["not changed", "changed", "deleted"]).sum()
    total_new = df_compare["status"].isin(["not changed", "changed", "added"]).sum()

    added = (df_compare["status"] == "added").sum()
    deleted = (df_compare["status"] == "deleted").sum()
    changed = (df_compare["status"] == "changed").sum()
    not_changed = (df_compare["status"] == "not changed").sum()

    stats = pd.DataFrame({
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
    })
    return stats


def join_with_edit(df_compare: pd.DataFrame, df_edit: pd.DataFrame) -> pd.DataFrame:
    """
    Присоединяет shams_edit1 к df_compare по нормализованному Subclass.
    В df_edit ключевой столбец: 'Введите код бизнес-деятельности'.
    """
    df_compare = df_compare.copy()
    df_compare["Subclass"] = df_compare["Subclass"].astype(str)

    # --- 2. Нормализуем ключ в shams_edit1
    df_edit = df_edit.copy()

    def normalize_subclass(code):
        if pd.isna(code):
            return None
        s = re.sub(r"[^0-9]", "", str(code))
        if len(s) < 5:
            return None
        return f"{s[:4]}.{s[4:].ljust(2, '0')[:2]}"

    df_edit["Subclass"] = df_edit["Введите код бизнес-деятельности"].apply(normalize_subclass)
    df_edit["Subclass"] = df_edit["Subclass"].astype(str)

    # --- 3. Добавляем суффиксы, чтобы избежать конфликтов
    df_edit = df_edit.add_suffix("_edit")
    df_edit = df_edit.rename(columns={"Subclass_edit": "Subclass"})

    # --- 4. JOIN
    df_joined = df_compare.merge(df_edit, on="Subclass", how="left")

    return df_joined
