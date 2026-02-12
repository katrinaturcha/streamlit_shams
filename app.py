from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl.styles import PatternFill

from header_log import build_header_change_log_from_bytes
from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats
from DB import DB_COLUMNS

# ================== STAGES ==================
STAGE_UPLOAD = "upload"
STAGE_SELECT_HEADERS = "select_headers"
STAGE_MAPPING = "mapping"
STAGE_HIERARCHY = "hierarchy"          # <-- НОВОЕ
STAGE_COMPARE = "compare"
STAGE_DB_MAPPING = "db_mapping"
STAGE_DB_EXPORT = "db_export"

# ================== CONFIG ==================
st.set_page_config(layout="wide")

BASE_DIR = Path(__file__).resolve().parent
SHAMS_PATH = BASE_DIR / "shams.xlsx"
DB_PATH = BASE_DIR / "shams_edit1.xlsx"

if not DB_PATH.exists():
    st.error("Файл shams_edit1.xlsx (имитация БД) не найден")
    st.stop()

if not SHAMS_PATH.exists():
    st.error("Файл shams.xlsx не найден")
    st.stop()

# ================== SESSION STATE ==================
def init_state():
    defaults = {
        "shams_bytes": None,
        "shams2_bytes": None,

        "headers_old": None,
        "headers_new": None,
        "headers_new_selected": None,

        "column_mapping": None,                 # new_col -> old_col|None

        # НОВОЕ: настройки иерархии
        "provider_has_groups": False,
        "provider_has_classes": False,
        "hierarchy_column_roles": None,         # selected_new_col -> one of ["Activity Code","Class","Group","Общий столбец"]

        "df_compare": None,
        "compare_stats": None,

        # НОВОЕ: отдельные сравнения уровней
        "df_class_compare": None,
        "df_group_compare": None,

        "db_column_mapping": None,              # source_col -> db_col|None
        "db_cols_order": None,                  # порядок "источников" как в UI (для попарной выгрузки)

        "stage": STAGE_UPLOAD,
        "db_mapping_saved": False,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)

init_state()

# ================== HELPERS ==================
def load_shams():
    if st.session_state.shams_bytes is None:
        with open(SHAMS_PATH, "rb") as f:
            st.session_state.shams_bytes = f.read()

def _normalize_code(val):
    if pd.isna(val):
        return None
    s = re.sub(r"[^0-9]", "", str(val))
    if len(s) < 5:
        return None
    return f"{s[:4]}.{s[4:].ljust(2,'0')[:2]}"

def load_db_df() -> pd.DataFrame:
    """Читает shams_edit1.xlsx и гарантирует наличие Subclass_code."""
    df_db = pd.read_excel(DB_PATH)

    if "Subclass_code" in df_db.columns:
        df_db["Subclass_code"] = df_db["Subclass_code"].apply(_normalize_code)
        return df_db

    if "Введите код бизнес-деятельности" in df_db.columns:
        df_db["Subclass_code"] = df_db["Введите код бизнес-деятельности"].apply(_normalize_code)
        return df_db

    if "Subclass" in df_db.columns:
        df_db["Subclass_code"] = df_db["Subclass"].apply(_normalize_code)
        return df_db

    raise ValueError(
        "В shams_edit1.xlsx не найден ключевой столбец "
        "(Subclass_code / Subclass / 'Введите код бизнес-деятельности')"
    )

def _norm_col(x: str) -> str:
    if x is None:
        return ""
    s = str(x).replace("\u00A0", " ")
    s = " ".join(s.split())
    return s.strip().lower()

def write_excel_with_highlight(
    buf: io.BytesIO,
    export_df: pd.DataFrame,
    highlight_cols: list[str],
    df_sections: pd.DataFrame | None = None,
    df_divisions: pd.DataFrame | None = None,
    df_groups: pd.DataFrame | None = None,
    df_classes: pd.DataFrame | None = None,
    df_group_compare: pd.DataFrame | None = None,
    df_class_compare: pd.DataFrame | None = None,
):
    """
    Подсвечивает SHAMS-колонки (highlight_cols) на листе for_review,
    DB-колонки оставляет без заливки. Добавляет дополнительные листы.
    """
    fill = PatternFill(fill_type="solid", start_color="FFFFF2CC", end_color="FFFFF2CC")

    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="for_review")
        ws = writer.sheets["for_review"]

        col_to_idx = {_norm_col(name): i + 1 for i, name in enumerate(export_df.columns)}
        highlight_idxs = []
        for c in highlight_cols:
            idx = col_to_idx.get(_norm_col(c))
            if idx is not None:
                highlight_idxs.append(idx)

        max_row = ws.max_row
        for col_idx in highlight_idxs:
            for row_idx in range(1, max_row + 1):
                ws.cell(row=row_idx, column=col_idx).fill = fill

        # уровни (из shams2)
        if df_sections is not None:
            df_sections.to_excel(writer, index=False, sheet_name="sections")
        if df_divisions is not None:
            df_divisions.to_excel(writer, index=False, sheet_name="divisions")
        if df_groups is not None:
            df_groups.to_excel(writer, index=False, sheet_name="groups")
        if df_classes is not None:
            df_classes.to_excel(writer, index=False, sheet_name="classes")

        # отдельные сравнения (Group/Class)
        if df_group_compare is not None and not df_group_compare.empty:
            df_group_compare.to_excel(writer, index=False, sheet_name="group_compare")
        if df_class_compare is not None and not df_class_compare.empty:
            df_class_compare.to_excel(writer, index=False, sheet_name="class_compare")

def _build_export_df(
    df_compare: pd.DataFrame,
    db_df: pd.DataFrame,
    db_map: dict,
    cols_order: list[str],
) -> pd.DataFrame:
    """
    Делает попарную выгрузку как в UI:
    status, Subclass_code, (DB-пара для Subclass_code), далее (src_col, db_col) по порядку cols_order.
    """
    df_compare = df_compare.copy()
    db_df = db_df.copy()

    if "Subclass_code" not in df_compare.columns:
        raise ValueError("В df_compare нет Subclass_code")
    if "Subclass_code" not in db_df.columns:
        raise ValueError("В db_df нет Subclass_code")

    merged = df_compare.merge(db_df, on="Subclass_code", how="left", suffixes=("", "_db"))

    export_cols: list[str] = []
    used_db_cols: set[str] = set()

    def add(col: str):
        if col in merged.columns and col not in export_cols:
            export_cols.append(col)

    # 0) status
    add("status")

    # 1) Subclass_code
    add("Subclass_code")

    # 2) DB-пара для Subclass_code (если выбрана)
    target_db_code = (db_map or {}).get("Subclass_code")
    if target_db_code:
        add(target_db_code)
        used_db_cols.add(target_db_code)

    # 3) остальное — строго по UI, попарно
    for src_col in cols_order:
        if src_col in ("Subclass_code", "status"):
            continue

        add(src_col)

        target_db = (db_map or {}).get(src_col)
        if target_db:
            add(target_db)
            used_db_cols.add(target_db)

    # 4) несопоставленные DB-колонки (если нужны) — в конец
    for c in db_df.columns:
        if c == "Subclass_code":
            continue
        if c not in used_db_cols:
            add(c)

    return merged[export_cols]

# --------- сравнение уровней (Group/Class) ----------
def _to_scalar(x):
    if isinstance(x, pd.Series):
        non_null = x.dropna()
        return non_null.iloc[0] if len(non_null) else x.iloc[0]
    return x

def _clean_display_text(val) -> str:
    if pd.isna(val):
        return ""
    s = str(val).strip()
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
        return f"OLD: {old_s}".strip() if old_s else ""
    if status == "added":
        return f"NEW: {new_s}".strip() if new_s else ""
    return ""

def _pick_first_existing(df: pd.DataFrame, candidates: list[str]) -> str | None:
    cols_norm = {_norm_col(c): c for c in df.columns}
    for c in candidates:
        real = cols_norm.get(_norm_col(c))
        if real is not None:
            return real
    return None

def compare_level_descriptions(
    df_old_level: pd.DataFrame,
    df_new_level: pd.DataFrame,
    level_name: str,
    key_candidates: list[str],
    desc_candidates: list[str],
) -> pd.DataFrame:
    """
    Универсально сравнивает описания по коду уровня (Group/Class).
    Возвращает: <level_name>_code, status, Description (лог).
    """
    if df_old_level is None or df_new_level is None:
        return pd.DataFrame(columns=[f"{level_name}_code", "status", "Description"])

    df_old = df_old_level.copy()
    df_new = df_new_level.copy()

    key_old = _pick_first_existing(df_old, key_candidates)
    key_new = _pick_first_existing(df_new, key_candidates)
    desc_old = _pick_first_existing(df_old, desc_candidates)
    desc_new = _pick_first_existing(df_new, desc_candidates)

    if not key_old or not key_new:
        return pd.DataFrame(columns=[f"{level_name}_code", "status", "Description"])

    if not desc_old:
        desc_old = desc_old or desc_candidates[0]
        df_old[desc_old] = pd.NA
    if not desc_new:
        desc_new = desc_new or desc_candidates[0]
        df_new[desc_new] = pd.NA

    out_key = f"{level_name}_code"

    df_old[out_key] = df_old[key_old].astype(str).str.strip()
    df_new[out_key] = df_new[key_new].astype(str).str.strip()

    df_old = df_old[df_old[out_key].notna() & (df_old[out_key] != "")]
    df_new = df_new[df_new[out_key].notna() & (df_new[out_key] != "")]

    df_old = df_old[[out_key, desc_old]].rename(columns={desc_old: "desc_old"})
    df_new = df_new[[out_key, desc_new]].rename(columns={desc_new: "desc_new"})

    m = df_old.merge(df_new, on=out_key, how="outer", indicator=True)

    def _initial_status(row):
        if row["_merge"] == "left_only":
            return "deleted"
        if row["_merge"] == "right_only":
            return "added"
        return "potentially_changed"

    m["status"] = m.apply(_initial_status, axis=1)

    def _final_status(row):
        if row["status"] in ("added", "deleted"):
            return row["status"]
        old_v = str(_to_scalar(row.get("desc_old", "")) or "").strip()
        new_v = str(_to_scalar(row.get("desc_new", "")) or "").strip()
        return "changed" if old_v != new_v else "not changed"

    m["status"] = m.apply(_final_status, axis=1)
    m["Description"] = m.apply(lambda r: _fmt_log(r["status"], r.get("desc_old", ""), r.get("desc_new", "")), axis=1)

    return m[[out_key, "status", "Description"]]

# ================== UI ==================
st.title("Список активити провайдера")
st.markdown("---")

# ==================================================
# =============== STAGE 1 — UPLOAD =================
# ==================================================
if st.session_state.stage == STAGE_UPLOAD:
    st.subheader("Укажите новый источник")

    uploaded = st.file_uploader("Загрузите файл shams2", type=["xlsx"])
    if uploaded is not None:
        st.session_state.shams2_bytes = uploaded.read()

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Отменить"):
            st.session_state.shams2_bytes = None
    with col2:
        if st.button("Применить", disabled=st.session_state.shams2_bytes is None):
            load_shams()

            h_old, h_new, _ = build_header_change_log_from_bytes(
                st.session_state.shams_bytes,
                st.session_state.shams2_bytes,
                sheets=None,
            )
            st.session_state.headers_old = h_old
            st.session_state.headers_new = h_new
            st.session_state.headers_new_selected = list(h_new)

            st.session_state.stage = STAGE_SELECT_HEADERS
            st.rerun()

# ==================================================
# =========== STAGE 2 — SELECT HEADERS =============
# ==================================================
if st.session_state.stage == STAGE_SELECT_HEADERS:
    st.subheader("Шаг 1 — выбор столбцов нового файла (shams2)")
    st.caption("Отметьте столбцы, которые пойдут в сопоставление")

    headers = st.session_state.headers_new or []
    prev_selected = st.session_state.headers_new_selected or []
    temp_selected = []

    for col in headers:
        checked = st.checkbox(col, value=(col in prev_selected), key=f"chk_{col}")
        if checked:
            temp_selected.append(col)

    st.session_state.headers_new_selected = temp_selected

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_UPLOAD
            st.rerun()
    with col2:
        if st.button("Перейти к сопоставлению", disabled=len(temp_selected) == 0):
            st.session_state.column_mapping = None
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.db_column_mapping = None
            st.session_state.db_mapping_saved = False
            st.session_state.hierarchy_column_roles = None
            st.session_state.df_class_compare = None
            st.session_state.df_group_compare = None
            st.session_state.stage = STAGE_MAPPING
            st.rerun()

# ==================================================
# ============== STAGE 3 — MAPPING =================
# ==================================================
if st.session_state.stage == STAGE_MAPPING:
    st.subheader("Шаг 2 — ручное сопоставление столбцов")
    st.caption(
        "Для каждого выбранного столбца из НОВОГО файла выберите соответствующий столбец "
        "в СТАРОМ файле. Если соответствия нет — оставьте «<нет соответствия>»."
    )

    headers_old = st.session_state.headers_old or []
    headers_new_selected = st.session_state.headers_new_selected or []

    if st.session_state.column_mapping is None:
        st.session_state.column_mapping = {col: None for col in headers_new_selected}
    else:
        current = {k: v for k, v in st.session_state.column_mapping.items() if k in headers_new_selected}
        for col in headers_new_selected:
            current.setdefault(col, None)
        st.session_state.column_mapping = current

    mapping = st.session_state.column_mapping

    st.markdown("---")
    for col_new in headers_new_selected:
        st.markdown(f"**{col_new} →**")
        options = ["<нет соответствия>"] + headers_old
        current_value = mapping.get(col_new)
        index = (headers_old.index(current_value) + 1) if current_value in headers_old else 0
        selected = st.selectbox(
            f"Соответствие для {col_new}",
            options=options,
            index=index,
            key=f"map_{col_new}",
        )
        mapping[col_new] = None if selected == "<нет соответствия>" else selected

    st.session_state.column_mapping = mapping

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_SELECT_HEADERS
            st.rerun()
    with col2:
        if st.button("Далее: уровни иерархии"):
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.df_class_compare = None
            st.session_state.df_group_compare = None
            st.session_state.stage = STAGE_HIERARCHY
            st.rerun()

# ==================================================
# =========== STAGE 3.5 — HIERARCHY =================
# ==================================================
if st.session_state.stage == STAGE_HIERARCHY:
    st.subheader("Шаг 2.5 — уровни иерархии")
    st.caption(
        "Укажите, делит ли провайдер активити на группы/классы. "
        "Затем для каждого выбранного столбца shams2 выберите роль."
    )

    # чекбоксы (дословно)
    st.session_state.provider_has_groups = st.checkbox(
        "Провайдер разделяет активити на группы",
        value=bool(st.session_state.provider_has_groups),
    )
    st.session_state.provider_has_classes = st.checkbox(
        "Провайдер разделяет активити на классы",
        value=bool(st.session_state.provider_has_classes),
    )

    # варианты в выпадающем списке
    role_options = ["Общий столбец", "Activity Code"]
    if st.session_state.provider_has_classes:
        role_options.insert(2, "Class")
    if st.session_state.provider_has_groups:
        # если группы есть — автоматически подразумеваем и классы в списке (как ты просила)
        if "Class" not in role_options:
            role_options.insert(2, "Class")
        role_options.insert(3 if "Class" in role_options else 2, "Group")

    # init mapping roles
    selected_cols = st.session_state.headers_new_selected or []
    if st.session_state.hierarchy_column_roles is None:
        st.session_state.hierarchy_column_roles = {c: "Общий столбец" for c in selected_cols}
    else:
        cur = {k: v for k, v in st.session_state.hierarchy_column_roles.items() if k in selected_cols}
        for c in selected_cols:
            cur.setdefault(c, "Общий столбец")
        st.session_state.hierarchy_column_roles = cur

    roles_map = st.session_state.hierarchy_column_roles

    st.markdown("---")
    # один столбец
    for col in selected_cols:
        cur_val = roles_map.get(col, "Общий столбец")
        idx = role_options.index(cur_val) if cur_val in role_options else 0
        roles_map[col] = st.selectbox(
            label=col,
            options=role_options,
            index=idx,
            key=f"role_{col}",
        )

    st.session_state.hierarchy_column_roles = roles_map

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_MAPPING
            st.rerun()
    with col2:
        if st.button("Сохранить и перейти к статистике", type="primary"):
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.df_class_compare = None
            st.session_state.df_group_compare = None
            st.session_state.stage = STAGE_COMPARE
            st.rerun()

# ==================================================
# ============== STAGE 4 — COMPARE =================
# ==================================================
if st.session_state.stage == STAGE_COMPARE:
    st.subheader("Статистика сравнения")

    if st.session_state.df_compare is None:
        # парсим оба файла
        df_full_old, df_sections_old, df_divisions_old, df_groups_old, df_classes_old, df_subclasses_old = parse_all_sheets_from_bytes(
            st.session_state.shams_bytes, sheets=None
        )
        df_full_new, df_sections_new, df_divisions_new, df_groups_new, df_classes_new, df_subclasses_new = parse_all_sheets_from_bytes(
            st.session_state.shams2_bytes, sheets=None
        )

        # 1) Subclass (Activity Code): всегда сравниваем описания Subclass (как раньше)
        df_compare = compare_shams(
            df_full_old,
            df_full_new,
            st.session_state.column_mapping,
            compare_cols=[],  # только Description (Subclass)
        )
        st.session_state.df_compare = df_compare
        st.session_state.compare_stats = comparison_stats(df_compare)

        # 2) Class: отдельное сравнение, если включено
        if st.session_state.provider_has_classes:
            st.session_state.df_class_compare = compare_level_descriptions(
                df_old_level=df_classes_old,
                df_new_level=df_classes_new,
                level_name="Class",
                key_candidates=["Class_code", "Class", "Class Code", "code"],
                desc_candidates=["Class_en", "Description", "title_en", "name_en"],
            )
        else:
            st.session_state.df_class_compare = pd.DataFrame(columns=["Class_code", "status", "Description"])

        # 3) Group: отдельное сравнение, если включено
        if st.session_state.provider_has_groups:
            st.session_state.df_group_compare = compare_level_descriptions(
                df_old_level=df_groups_old,
                df_new_level=df_groups_new,
                level_name="Group",
                key_candidates=["Group_code", "Group", "Group Code", "code"],
                desc_candidates=["Group_en", "Description", "title_en", "name_en"],
            )
        else:
            st.session_state.df_group_compare = pd.DataFrame(columns=["Group_code", "status", "Description"])

    # --- вывод статистики Subclass ---
    stats_df = st.session_state.compare_stats
    stats = dict(zip(stats_df["metric"], stats_df["value"]))

    st.markdown(f"""
**Количество активити в старом файле:** {stats['Количество строк в старом файле']}  
**Количество активити в новом файле:** {stats['Количество строк в новом файле']}  
**Добавлено активити:** {stats['Добавлено']}  
**Удалено активити:** {stats['Удалено']}  
**Внесены изменения (Activity Code / Description):** {stats['Изменено (по выбранным столбцам)']}  
**Остались без изменений:** {stats['Не изменено']}  
""")

    # --- доп. статистика по Class/Group ---
    def _mini_stats(df_level: pd.DataFrame, label: str):
        if df_level is None or df_level.empty or "status" not in df_level.columns:
            return
        added = (df_level["status"] == "added").sum()
        deleted = (df_level["status"] == "deleted").sum()
        changed = (df_level["status"] == "changed").sum()
        not_changed = (df_level["status"] == "not changed").sum()
        total_old = df_level["status"].isin(["not changed", "changed", "deleted"]).sum()
        total_new = df_level["status"].isin(["not changed", "changed", "added"]).sum()

        st.markdown(f"""
**{label}:**  
• строк в старом: {total_old}  
• строк в новом: {total_new}  
• добавлено: {added}  
• удалено: {deleted}  
• изменено (Description): {changed}  
• без изменений: {not_changed}  
""")

    if st.session_state.provider_has_classes:
        _mini_stats(st.session_state.df_class_compare, "Class")
    if st.session_state.provider_has_groups:
        _mini_stats(st.session_state.df_group_compare, "Group")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_HIERARCHY
            st.rerun()
    with col2:
        if st.button("Выгрузить в excel для работы с обновлениями", type="primary"):
            st.session_state.stage = STAGE_DB_MAPPING
            st.rerun()

# ==================================================
# ============ STAGE 5 — DB MAPPING =================
# ==================================================
if st.session_state.stage == STAGE_DB_MAPPING:
    st.subheader("Сопоставление столбцов результата и Базы Данных")
    st.caption(
        "Сопоставьте только то, что хотите видеть рядом со значениями БД. "
        "status не сопоставляется (он всегда первым в выгрузке)."
    )

    df = st.session_state.df_compare
    if df is None or df.empty:
        st.error("Нет результата сравнения. Вернитесь на шаг сравнения.")
        st.stop()

    legacy_cols = [c for c in df.columns if c.endswith("_old") or c.endswith("_new") or c == "diff_columns"]
    if legacy_cols:
        st.warning("Результат сравнения выглядит как старый формат. Пересчитываю...")
        st.session_state.df_compare = None
        st.session_state.compare_stats = None
        st.session_state.stage = STAGE_COMPARE
        st.rerun()

    # порядок UI: Subclass_code первым (но status НЕ маппим)
    cols_to_map = []
    if "Subclass_code" in df.columns:
        cols_to_map.append("Subclass_code")

    other = [c for c in df.columns if c not in ("Subclass_code", "status", "Subclass")]

    # Description первым среди other
    if "Description" in other:
        other = ["Description"] + [c for c in other if c != "Description"]

    cols_to_map += other
    cols_to_map = list(dict.fromkeys(cols_to_map))

    st.session_state.db_cols_order = cols_to_map

    current_map = st.session_state.db_column_mapping or {}
    current_map = {k: v for k, v in current_map.items() if k in cols_to_map}
    for c in cols_to_map:
        current_map.setdefault(c, None)
    st.session_state.db_column_mapping = current_map
    mapping = st.session_state.db_column_mapping

    # UI: один столбец
    for col in cols_to_map:
        cur_val = mapping.get(col)
        selected = st.selectbox(
            label=col,
            options=["<нет соответствия>"] + DB_COLUMNS,
            index=(DB_COLUMNS.index(cur_val) + 1) if cur_val in DB_COLUMNS else 0,
            key=f"db_map_{col}",
        )
        mapping[col] = None if selected == "<нет соответствия>" else selected

    st.session_state.db_column_mapping = mapping

    st.markdown("---")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_COMPARE
            st.rerun()
    with col2:
        if st.button("Сохранить сопоставление", type="primary"):
            st.session_state.db_mapping_saved = True
            st.session_state.stage = STAGE_DB_EXPORT
            st.rerun()

# ==================================================
# ============ STAGE 6 — DB EXPORT ==================
# ==================================================
if st.session_state.stage == STAGE_DB_EXPORT:
    st.subheader("Экспорт в Excel")

    if not st.session_state.get("db_mapping_saved"):
        st.warning("Сначала нажмите «Сохранить сопоставление».")
        st.stop()

    df_compare = st.session_state.df_compare
    if df_compare is None or df_compare.empty:
        st.error("Нет данных для экспорта. Вернитесь на шаг сравнения.")
        st.stop()

    db_map = st.session_state.db_column_mapping or {}
    cols_order = st.session_state.get("db_cols_order") or []

    db_df = load_db_df()
    if db_df is None or db_df.empty:
        st.error("Файл БД пустой или не загрузился.")
        st.stop()

    export_df = _build_export_df(
        df_compare=df_compare,
        db_df=db_df,
        db_map=db_map,
        cols_order=cols_order,
    )

    # уровни из shams2 (для справочников)
    try:
        _, df_sections, df_divisions, df_groups, df_classes, _ = parse_all_sheets_from_bytes(
            st.session_state.shams2_bytes, sheets=None
        )
    except Exception as e:
        st.error(f"Не удалось распарсить уровни из shams2: {e}")
        st.stop()

    # подсветка: только SHAMS-колонки (status + Subclass_code + все src из cols_order)
    highlight_cols = ["status", "Subclass_code"] + [c for c in cols_order if c not in ("status", "Subclass_code")]

    buf = io.BytesIO()
    write_excel_with_highlight(
        buf=buf,
        export_df=export_df,
        highlight_cols=highlight_cols,
        df_sections=df_sections,
        df_divisions=df_divisions,
        df_groups=df_groups,
        df_classes=df_classes,
        df_group_compare=st.session_state.df_group_compare,
        df_class_compare=st.session_state.df_class_compare,
    )
    buf.seek(0)
    xlsx_bytes = buf.getvalue()

    st.download_button(
        label="Скачать в excel",
        data=xlsx_bytes,
        file_name="shams_compare_for_review.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("---")
    if st.button("Назад к сопоставлению с БД"):
        st.session_state.stage = STAGE_DB_MAPPING
        st.rerun()
