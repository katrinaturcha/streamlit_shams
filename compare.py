import pandas as pd
import re

from utils import normalize_text_for_compare, normalize_subclass_simple


def compare_shams(df_old, df_new):

    df_old = df_old.copy()
    df_new = df_new.copy()

    # нормализуем ключ
    df_old["Subclass_norm"] = df_old["Subclass"].apply(normalize_subclass)
    df_new["Subclass_norm"] = df_new["Subclass"].apply(normalize_subclass)

    df_old = df_old[df_old["Subclass_norm"].notna()]
    df_new = df_new[df_new["Subclass_norm"].notna()]

    # добавляем суффиксы
    df_old = df_old.add_suffix("_old")
    df_new = df_new.add_suffix("_new")

    # вернуть имя ключа
    df_old = df_old.rename(columns={"Subclass_norm_old": "Subclass_norm"})
    df_new = df_new.rename(columns={"Subclass_norm_new": "Subclass_norm"})

    # FULL JOIN
    df = pd.merge(df_old, df_new, on="Subclass_norm", how="outer", indicator=True)

    # -------------------------------
    # Первичное определение статуса
    # -------------------------------
    def classify(row):
        if row["_merge"] == "left_only":
            return "deleted"
        if row["_merge"] == "right_only":
            return "added"
        return "potentially_changed"

    df["status"] = df.apply(classify, axis=1)

    # -------------------------------
    # Сравнение ТОЛЬКО Subclass_en
    # -------------------------------
    diff_list = []

    for _, row in df.iterrows():
        diffs = []

        if row["status"] == "potentially_changed":
            old_val = normalize_text(row.get("Subclass_en_old", ""))
            new_val = normalize_text(row.get("Subclass_en_new", ""))

            if old_val != new_val:
                diffs.append("Subclass_en")

        diff_list.append(diffs)

    df["diff_columns"] = diff_list

    # -------------------------------
    # Финальный статус
    # -------------------------------
    def final_status(row):
        if row["status"] in ("added", "deleted"):
            return row["status"]
        if len(row["diff_columns"]) > 0:
            return "changed"
        return "not changed"

    df["status"] = df.apply(final_status, axis=1)

    # -------------------------------
    # Итоговый порядок
    # -------------------------------
    front_cols = ["Subclass_norm", "status", "diff_columns"]
    other = [c for c in df.columns if c not in front_cols and c != "_merge"]

    return df[front_cols + other]


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
    df_edit = df_edit.copy()
    df_edit["Subclass_norm"] = df_edit["Введите код бизнес-деятельности"].apply(normalize_subclass_simple)

    df_edit_renamed = df_edit.add_suffix("_edit")
    df_edit_renamed = df_edit_renamed.rename(columns={"Subclass_norm_edit": "Subclass_norm"})

    df_compare = df_compare.copy()
    df_compare["Subclass_norm"] = df_compare["Subclass_norm"].astype(str)

    df_joined = df_compare.merge(df_edit_renamed, on="Subclass_norm", how="left")
    return df_joined
