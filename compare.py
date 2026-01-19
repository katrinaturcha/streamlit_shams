import re
import pandas as pd

from utils import normalize_text_for_compare, normalize_subclass_simple


def _to_scalar(x):
    """
    Гарантируем, что в сравнение/лог попадает скаляр.
    Иногда при дублях колонок pandas может вернуть Series.
    """
    if isinstance(x, pd.Series):
        # берём первое непустое, иначе первое
        non_null = x.dropna()
        return non_null.iloc[0] if len(non_null) else x.iloc[0]
    return x


def _fmt_log(status: str, old_val, new_val) -> str:
    old_val = _to_scalar(old_val)
    new_val = _to_scalar(new_val)

    # приводим к строкам (для лога)
    old_s = "" if pd.isna(old_val) else str(old_val).strip()
    new_s = "" if pd.isna(new_val) else str(new_val).strip()

    if status == "changed":
        return f"OLD: {old_s}\nNEW: {new_s}".strip()
    if status == "deleted":
        return f"OLD: {old_s}".strip() if old_s else ""
    if status == "added":
        return f"NEW: {new_s}".strip() if new_s else ""
    # not changed
    return ""


def compare_shams(
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    column_mapping: dict,
) -> pd.DataFrame:
    """
    Сравнение старого и нового SHAMS-файлов
    с учётом выбранных и сопоставленных столбцов.

    column_mapping:
        { new_col: old_col | None }

    Результат:
    - Subclass_code
    - status
    - Subclass_en. Лог изменений
    - для каждой сопоставленной колонки: "<new_col>. Лог изменений"
    - для новых колонок без соответствия: "<new_col>" (значение из new)
    """

    # ==================================================
    # 1. Подготовка ключа
    # ==================================================
    df_old = df_old.copy()
    df_new = df_new.copy()
    df_old.columns = [str(c).strip() for c in df_old.columns]
    df_new.columns = [str(c).strip() for c in df_new.columns]

    df_old["Subclass_code"] = df_old["Subclass"].apply(normalize_subclass_simple)
    df_new["Subclass_code"] = df_new["Subclass"].apply(normalize_subclass_simple)

    df_old = df_old[df_old["Subclass_code"].notna()]
    df_new = df_new[df_new["Subclass_code"].notna()]

    # ==================================================
    # 2. Разделяем выбранные колонки
    # ==================================================
    mapped_pairs = []    # (old_col, new_col)
    new_only_cols = []   # new_col без пары

    for new_col, old_col in (column_mapping or {}).items():
        if old_col:
            mapped_pairs.append((old_col, new_col))
        else:
            new_only_cols.append(new_col)

    # Subclass_en — всегда сравниваем
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
    # 5. Определяем changed / not changed (для совпавших ключей)
    # ==================================================
    diff_cols = []

    for _, row in df.iterrows():
        diffs = []

        if row["status"] == "potentially_changed":
            # сравнение Subclass_en
            old_val = normalize_text_for_compare(_to_scalar(row.get("Subclass_en_old", "")))
            new_val = normalize_text_for_compare(_to_scalar(row.get("Subclass_en_new", "")))
            if old_val != new_val:
                diffs.append(BASE_COMPARE_COL)

            # сравнение сопоставленных колонок
            for old_col, new_col in mapped_pairs:
                old_v = normalize_text_for_compare(_to_scalar(row.get(f"{old_col}_old", "")))
                new_v = normalize_text_for_compare(_to_scalar(row.get(f"{new_col}_new", "")))
                if old_v != new_v:
                    diffs.append(new_col)

        diff_cols.append(diffs)

    df["diff_columns"] = diff_cols

    def final_status(row):
        if row["status"] in ("added", "deleted"):
            return row["status"]
        if len(row["diff_columns"]) > 0:
            return "changed"
        return "not changed"

    df["status"] = df.apply(final_status, axis=1)

    # ==================================================
    # 6. Формируем "Логи изменений"
    # ==================================================
    # базовый лог Subclass_en
    log_col_base = f"{BASE_COMPARE_COL}. Лог изменений"
    df[log_col_base] = df.apply(
        lambda r: _fmt_log(
            r["status"],
            r.get("Subclass_en_old", ""),
            r.get("Subclass_en_new", ""),
        ),
        axis=1,
    )

    # логи для сопоставленных колонок
    log_cols = []
    for old_col, new_col in mapped_pairs:
        log_col = f"{new_col}. Лог изменений"
        log_cols.append(log_col)

        df[log_col] = df.apply(
            lambda r, oc=old_col, nc=new_col: _fmt_log(
                r["status"],
                r.get(f"{oc}_old", ""),
                r.get(f"{nc}_new", ""),
            ),
            axis=1,
        )

    # ==================================================
    # 7. Новые колонки без соответствия: оставляем как есть (из new)
    # ==================================================
    # new_only_out_cols = []
    # for new_col in new_only_cols:
    #     col_new_name = f"{new_col}_new"
    #     out_name = new_col  # сохраняем текущее имя
    #     if col_new_name in df.columns:
    #         df[out_name] = df[col_new_name]
    #         new_only_out_cols.append(out_name)
    # missing = []
    # for new_col in new_only_cols:
    #     if f"{new_col}_new" not in df.columns:
    #         missing.append((new_col, f"{new_col}_new"))
    # print("MISSING new_only:", missing[:20])
    # print("SAMPLE df cols:", list(df.columns)[:50])

    # ==================================================
    # 7. Новые колонки без соответствия: оставляем как есть (из new)
    #    НО ищем колонку устойчиво (strip, NBSP, переносы, двойные пробелы, регистр)
    # ==================================================
    def _norm_colname(x: str) -> str:
        if x is None:
            return ""
        s = str(x)
        s = s.replace("\u00A0", " ")          # NBSP -> обычный пробел
        s = s.replace("\n", " ").replace("\r", " ")
        s = " ".join(s.split())               # схлопнуть множественные пробелы
        return s.strip().lower()

    # индекс по df.columns: нормализованное имя -> реальное имя
    norm_to_real = {_norm_colname(c): c for c in df.columns}

    new_only_out_cols = []
    for new_col in new_only_cols:
        # хотим взять колонку из merged df с суффиксом _new
        wanted = f"{new_col}_new"

        real_col = None

        # 1) если вдруг совпало идеально
        if wanted in df.columns:
            real_col = wanted
        else:
            # 2) ищем по нормализованному имени
            real_col = norm_to_real.get(_norm_colname(wanted))

        if real_col:
            out_name = str(new_col).strip()   # сохраняем имя как в UI
            df[out_name] = df[real_col]
            new_only_out_cols.append(out_name)


    # ==================================================
    # 8. Финальный набор колонок
    # ==================================================
    front_cols = ["Subclass_code", "status"]
    final_cols = front_cols + [log_col_base] + log_cols + new_only_out_cols

    # на всякий случай — только существующие
    final_cols = [c for c in final_cols if c in df.columns]

    return df[final_cols]



def comparison_stats(df_compare: pd.DataFrame) -> pd.DataFrame:
    total_old = df_compare["status"].isin(["not changed", "changed", "deleted"]).sum()
    total_new = df_compare["status"].isin(["not changed", "changed", "added"]).sum()

    added = (df_compare["status"] == "added").sum()
    deleted = (df_compare["status"] == "deleted").sum()
    changed = (df_compare["status"] == "changed").sum()
    not_changed = (df_compare["status"] == "not changed").sum()

    return pd.DataFrame({
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


# import re
# import pandas as pd
#
# from utils import normalize_text_for_compare, normalize_subclass_simple
#
#
# def compare_shams(
#     df_old: pd.DataFrame,
#     df_new: pd.DataFrame,
#     column_mapping: dict,
# ) -> pd.DataFrame:
#     """
#     Сравнение старого и нового SHAMS-файлов
#     с учётом выбранных и сопоставленных столбцов.
#
#     column_mapping:
#         {
#             <new_col>: <old_col> | None
#         }
#
#     Логика:
#     - Subclass_en сравнивается ВСЕГДА
#     - если old_col != None → сравниваем old vs new
#     - если old_col == None → колонка считается новой
#       и просто добавляется как <col>_new
#     """
#
#     # ==================================================
#     # 1. Копии + нормализация ключа
#     # ==================================================
#     df_old = df_old.copy()
#     df_new = df_new.copy()
#
#     df_old["Subclass_code"] = df_old["Subclass"].apply(normalize_subclass_simple)
#     df_new["Subclass_code"] = df_new["Subclass"].apply(normalize_subclass_simple)
#
#     df_old = df_old[df_old["Subclass_code"].notna()]
#     df_new = df_new[df_new["Subclass_code"].notna()]
#
#     # ==================================================
#     # 2. Разделяем выбранные колонки
#     # ==================================================
#     mapped_pairs = []   # (old_col, new_col)
#     new_only_cols = [] # new_col без пары
#
#     for new_col, old_col in column_mapping.items():
#         if old_col:
#             mapped_pairs.append((old_col, new_col))
#         else:
#             new_only_cols.append(new_col)
#
#     BASE_COMPARE_COL = "Subclass_en"
#
#     # ==================================================
#     # 3. Суффиксы и merge
#     # ==================================================
#     df_old = df_old.add_suffix("_old")
#     df_new = df_new.add_suffix("_new")
#
#     df_old = df_old.rename(columns={"Subclass_code_old": "Subclass_code"})
#     df_new = df_new.rename(columns={"Subclass_code_new": "Subclass_code"})
#
#     df = pd.merge(
#         df_old,
#         df_new,
#         on="Subclass_code",
#         how="outer",
#         indicator=True,
#     )
#
#     # ==================================================
#     # 4. Первичный статус
#     # ==================================================
#     def initial_status(row):
#         if row["_merge"] == "left_only":
#             return "deleted"
#         if row["_merge"] == "right_only":
#             return "added"
#         return "potentially_changed"
#
#     df["status"] = df.apply(initial_status, axis=1)
#
#     # ==================================================
#     # 5. Поиск различий
#     # ==================================================
#     diff_columns = []
#
#     for _, row in df.iterrows():
#         diffs = []
#
#         if row["status"] == "potentially_changed":
#
#             # --- Subclass_en (всегда) ---
#             old_val = normalize_text_for_compare(row.get("Subclass_en_old", ""))
#             new_val = normalize_text_for_compare(row.get("Subclass_en_new", ""))
#
#             if old_val != new_val:
#                 diffs.append(BASE_COMPARE_COL)
#
#             # --- сопоставленные колонки ---
#             for old_col, new_col in mapped_pairs:
#                 old_v = normalize_text_for_compare(row.get(f"{old_col}_old", ""))
#                 new_v = normalize_text_for_compare(row.get(f"{new_col}_new", ""))
#
#                 if old_v != new_v:
#                     diffs.append(new_col)
#
#         diff_columns.append(diffs)
#
#     df["diff_columns"] = diff_columns
#
#     # ==================================================
#     # 6. Финальный статус
#     # ==================================================
#     def final_status(row):
#         if row["status"] in ("added", "deleted"):
#             return row["status"]
#         if len(row["diff_columns"]) > 0:
#             return "changed"
#         return "not changed"
#
#     df["status"] = df.apply(final_status, axis=1)
#
#     # ==================================================
#     # 7. Формирование итоговых колонок
#     # ==================================================
#     front_cols = [
#         "Subclass_code",
#         "status",
#         "diff_columns",
#     ]
#
#     base_cols = [
#         "Subclass_en_old",
#         "Subclass_en_new",
#     ]
#
#     dynamic_cols = []
#
#     # сопоставленные: old + new
#     for old_col, new_col in mapped_pairs:
#         dynamic_cols.append(f"{old_col}_old")
#         dynamic_cols.append(f"{new_col}_new")
#
#     # новые без пары: ТОЛЬКО new
#     for new_col in new_only_cols:
#         dynamic_cols.append(f"{new_col}_new")
#
#     final_cols = front_cols + base_cols + dynamic_cols
#     final_cols = [c for c in final_cols if c in df.columns]
#
#     return df[final_cols]
#
#
# # ==================================================
# # ================== STATS =========================
# # ==================================================
# def comparison_stats(df_compare: pd.DataFrame) -> pd.DataFrame:
#     total_old = df_compare["status"].isin(
#         ["not changed", "changed", "deleted"]
#     ).sum()
#     total_new = df_compare["status"].isin(
#         ["not changed", "changed", "added"]
#     ).sum()
#
#     added = (df_compare["status"] == "added").sum()
#     deleted = (df_compare["status"] == "deleted").sum()
#     changed = (df_compare["status"] == "changed").sum()
#     not_changed = (df_compare["status"] == "not changed").sum()
#
#     stats = pd.DataFrame(
#         {
#             "metric": [
#                 "Количество строк в старом файле",
#                 "Количество строк в новом файле",
#                 "Добавлено",
#                 "Удалено",
#                 "Изменено (по английским описаниям)",
#                 "Не изменено",
#             ],
#             "value": [
#                 total_old,
#                 total_new,
#                 added,
#                 deleted,
#                 changed,
#                 not_changed,
#             ],
#         }
#     )
#     return stats
#
#
# # ==================================================
# # ============== JOIN WITH EDIT ====================
# # ==================================================
# def join_with_edit(
#     df_compare: pd.DataFrame,
#     df_edit: pd.DataFrame,
# ) -> pd.DataFrame:
#     """
#     Присоединяет shams_edit.xlsx к df_compare
#     по нормализованному Subclass.
#
#     В df_edit ключевой столбец:
#     'Введите код бизнес-деятельности'
#     """
#
#     df_compare = df_compare.copy()
#     df_compare["Subclass"] = df_compare["Subclass"].astype(str)
#
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
#     df_edit["Subclass"] = df_edit["Введите код бизнес-деятельности"].apply(
#         normalize_subclass
#     )
#     df_edit["Subclass"] = df_edit["Subclass"].astype(str)
#
#     # суффиксы для избежания конфликтов
#     df_edit = df_edit.add_suffix("_edit")
#     df_edit = df_edit.rename(columns={"Subclass_edit": "Subclass"})
#
#     df_joined = df_compare.merge(df_edit, on="Subclass", how="left")
#
#     return df_joined
#
#

