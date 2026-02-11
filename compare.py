from __future__ import annotations

import pandas as pd

from utils import normalize_text_for_compare, normalize_subclass_simple

def compare_level_descriptions(df_old: pd.DataFrame, df_new: pd.DataFrame, key_col: str, desc_col: str) -> pd.DataFrame:
    """
    Универсальное сравнение справочника уровней (groups/classes/subclasses):
    возвращает: key_col, status, Description (лог OLD/NEW)
    """
    df_old = df_old.copy()
    df_new = df_new.copy()

    df_old.columns = [str(c).strip() for c in df_old.columns]
    df_new.columns = [str(c).strip() for c in df_new.columns]

    if key_col not in df_old.columns or key_col not in df_new.columns:
        raise ValueError(f"Нет ключа {key_col} в одном из датафреймов")
    if desc_col not in df_old.columns or desc_col not in df_new.columns:
        raise ValueError(f"Нет описания {desc_col} в одном из датафреймов")

    o = df_old[[key_col, desc_col]].rename(columns={desc_col: "desc_old"})
    n = df_new[[key_col, desc_col]].rename(columns={desc_col: "desc_new"})

    m = o.merge(n, on=key_col, how="outer", indicator=True)

    def _status(r):
        if r["_merge"] == "left_only":
            return "deleted"
        if r["_merge"] == "right_only":
            return "added"
        old_v = normalize_text_for_compare(r.get("desc_old", ""))
        new_v = normalize_text_for_compare(r.get("desc_new", ""))
        return "changed" if old_v != new_v else "not changed"

    m["status"] = m.apply(_status, axis=1)
    m["Description"] = m.apply(lambda r: _fmt_log(r["status"], r.get("desc_old",""), r.get("desc_new","")), axis=1)

    return m[[key_col, "status", "Description"]]


def _to_scalar(x):
    if isinstance(x, pd.Series):
        non_null = x.dropna()
        return non_null.iloc[0] if len(non_null) else x.iloc[0]
    return x


def _clean_display_text(val) -> str:
    """
    Чистим ТОЛЬКО отображение в логе, чтобы не было:
    OLD: - Real estate consultancy
    """
    if pd.isna(val):
        return ""
    s = str(val).strip()

    # убираем лидирующие маркеры/буллеты/тире
    while True:
        s2 = s.lstrip()
        for prefix in ("- ", "– ", "— ", "• ", "· ", "* ", "•\t", "·\t", "-\t", "–\t", "—\t"):
            if s2.startswith(prefix):
                s2 = s2[len(prefix):].lstrip()
                break
        else:
            s2 = s2.lstrip("-–—•·* \t")
        if s2 == s:
            break
        s = s2

    return s.strip()


def _fmt_log(status: str, old_val, new_val) -> str:
    old_val = _to_scalar(old_val)
    new_val = _to_scalar(new_val)

    old_s = _clean_display_text(old_val)
    new_s = _clean_display_text(new_val)

    if status == "changed":
        return f"OLD: {old_s}\nNEW: {new_s}".strip()
    if status == "deleted":
        return old_s.strip() if old_s else ""
    if status == "added":
        return new_s.strip() if new_s else ""
    return ""


def compare_shams(
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    column_mapping: dict,
    compare_cols: list | None = None,  # <-- НОВОЕ: какие new_col сравнивать (кроме Description)
) -> pd.DataFrame:
    """
    Результат:
    - Subclass_code
    - status
    - Description. Лог изменений (это Subclass_en old/new)
    - для каждой выбранной сопоставленной колонки: "<new_col>. Лог изменений"
    - для новых колонок без соответствия: "<new_col>" (значение из new)
    """

    df_old = df_old.copy()
    df_new = df_new.copy()

    # чистим имена колонок
    df_old.columns = [str(c).strip() for c in df_old.columns]
    df_new.columns = [str(c).strip() for c in df_new.columns]

    # ключ
    df_old["Subclass_code"] = df_old["Subclass"].apply(normalize_subclass_simple)
    df_new["Subclass_code"] = df_new["Subclass"].apply(normalize_subclass_simple)

    df_old = df_old[df_old["Subclass_code"].notna()]
    df_new = df_new[df_new["Subclass_code"].notna()]

    # mapping: new_col -> old_col|None
    mapped_pairs_all = []
    new_only_cols = []

    for new_col, old_col in (column_mapping or {}).items():
        if old_col:
            mapped_pairs_all.append((old_col, new_col))
        else:
            new_only_cols.append(new_col)

    # какие сопоставленные колонки реально сравниваем (кроме Description)
    compare_set = set(compare_cols or [])
    mapped_pairs_to_compare = [(o, n) for (o, n) in mapped_pairs_all if n in compare_set]

    # Description = Subclass_en
    BASE_OLD = "Subclass_en_old"
    BASE_NEW = "Subclass_en_new"
    LOG_DESC = "Description"

    # суффиксы
    df_old = df_old.add_suffix("_old").rename(columns={"Subclass_code_old": "Subclass_code"})
    df_new = df_new.add_suffix("_new").rename(columns={"Subclass_code_new": "Subclass_code"})

    df = pd.merge(df_old, df_new, on="Subclass_code", how="outer", indicator=True)
    # после merge добавляем Subclass (для сопоставления с БД)
    # берём из нового файла, если есть; иначе из старого
    if "Subclass_new" in df.columns:
        df["Subclass"] = df["Subclass_new"]
    elif "Subclass_old" in df.columns:
        df["Subclass"] = df["Subclass_old"]
    # первичный статус
    def _initial_status(row):
        if row["_merge"] == "left_only":
            return "deleted"
        if row["_merge"] == "right_only":
            return "added"
        return "potentially_changed"

    df["status"] = df.apply(_initial_status, axis=1)

    # diff только по: Description + выбранные текстовые сопоставленные
    diff_cols = []
    for _, row in df.iterrows():
        diffs = []
        if row["status"] == "potentially_changed":
            old_val = normalize_text_for_compare(_to_scalar(row.get(BASE_OLD, "")))
            new_val = normalize_text_for_compare(_to_scalar(row.get(BASE_NEW, "")))
            if old_val != new_val:
                diffs.append("Description")

            for old_col, new_col in mapped_pairs_to_compare:
                old_v = normalize_text_for_compare(_to_scalar(row.get(f"{old_col}_old", "")))
                new_v = normalize_text_for_compare(_to_scalar(row.get(f"{new_col}_new", "")))
                if old_v != new_v:
                    diffs.append(new_col)

        diff_cols.append(diffs)

    df["diff_columns"] = diff_cols

    def _final_status(row):
        if row["status"] in ("added", "deleted"):
            return row["status"]
        if len(row["diff_columns"]) > 0:
            return "changed"
        return "not changed"

    df["status"] = df.apply(_final_status, axis=1)

    # === логи ===
    df[LOG_DESC] = df.apply(
        lambda r: _fmt_log(r["status"], r.get(BASE_OLD, ""), r.get(BASE_NEW, "")),
        axis=1,
    )

    log_cols = []
    for old_col, new_col in mapped_pairs_to_compare:
        log_name = new_col
        log_cols.append(log_name)
        df[log_name] = df.apply(
            lambda r, oc=old_col, nc=new_col: _fmt_log(
                r["status"],
                r.get(f"{oc}_old", ""),
                r.get(f"{nc}_new", ""),
            ),
            axis=1,
        )

    # новые колонки без соответствия: вытаскиваем из *_new устойчиво
    def _norm_colname(x: str) -> str:
        if x is None:
            return ""
        s = str(x).replace("\u00A0", " ")
        s = s.replace("\n", " ").replace("\r", " ")
        s = " ".join(s.split())
        return s.strip().lower()

    norm_to_real = {_norm_colname(c): c for c in df.columns}

    new_only_out_cols = []
    for new_col in new_only_cols:
        wanted = f"{new_col}_new"
        real_col = wanted if wanted in df.columns else norm_to_real.get(_norm_colname(wanted))
        if real_col:
            out_name = str(new_col).strip()
            df[out_name] = df[real_col]
            new_only_out_cols.append(out_name)

    # итог
    # удалить блок after merge про Subclass
    final_cols = ["Subclass_code", "status", LOG_DESC] + log_cols + new_only_out_cols
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
            "Изменено (по выбранным столбцам)",
            "Не изменено",
        ],
        "value": [total_old, total_new, added, deleted, changed, not_changed],
    })


