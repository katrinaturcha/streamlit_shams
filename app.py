from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Optional

import pandas as pd
import streamlit as st
from openpyxl.styles import PatternFill

from header_log import build_header_change_log_from_bytes
from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats
from utils import normalize_text_for_compare
from DB import DB_COLUMNS

# ================== STAGES ==================
STAGE_UPLOAD = "upload"
STAGE_SELECT_HEADERS = "select_headers"
STAGE_MAPPING = "mapping"
STAGE_HIERARCHY = "hierarchy"  # <-- НОВОЕ
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

        "column_mapping": None,  # new_col -> old_col|None

        # НОВОЕ: чекбоксы и роли колонок
        "provider_has_groups": False,
        "provider_has_classes": False,
        "hierarchy_roles": None,  # {new_col: "Activity Code"|"Class"|"Group"|"Общий столбец"}

        "df_compare": None,
        "compare_stats": None,

        # сравнение уровней
        "df_groups_cmp": None,
        "df_classes_cmp": None,
        "df_subclasses_cmp": None,

        "db_column_mapping": None,  # source_col -> db_col|None
        "db_cols_order": None,      # порядок src-колонок как в UI (для попарной выгрузки)

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

def compare_level_like_subclass(
    df_old: pd.DataFrame,
    df_new: pd.DataFrame,
    key_col: str,
    desc_col: str,
    out_key_name: Optional[str] = None,
    out_desc_name: str = "Description",
) -> pd.DataFrame:
    """
    Сравнение уровня (Group/Class/Subclass) по ключу и описанию:
    выход: status, <key>, Description (в виде OLD/NEW как в Subclass)
    """
    out_key_name = out_key_name or key_col

    if df_old is None or df_old.empty:
        df_old = pd.DataFrame(columns=[key_col, desc_col])
    if df_new is None or df_new.empty:
        df_new = pd.DataFrame(columns=[key_col, desc_col])

    df_old = df_old.copy()
    df_new = df_new.copy()

    df_old.columns = [str(c).strip() for c in df_old.columns]
    df_new.columns = [str(c).strip() for c in df_new.columns]

    if key_col not in df_old.columns and key_col not in df_new.columns:
        return pd.DataFrame(columns=["status", out_key_name, out_desc_name])

    need_old = [c for c in [key_col, desc_col] if c in df_old.columns]
    need_new = [c for c in [key_col, desc_col] if c in df_new.columns]
    df_old = df_old[need_old].copy()
    df_new = df_new[need_new].copy()

    df_old = df_old.add_suffix("_old").rename(columns={f"{key_col}_old": key_col})
    df_new = df_new.add_suffix("_new").rename(columns={f"{key_col}_new": key_col})

    merged = pd.merge(df_old, df_new, on=key_col, how="outer", indicator=True)

    def _initial_status(m):
        if m == "left_only":
            return "deleted"
        if m == "right_only":
            return "added"
        return "potentially_changed"

    merged["status"] = merged["_merge"].apply(_initial_status)

    old_desc = f"{desc_col}_old"
    new_desc = f"{desc_col}_new"

    def _final_status(row):
        stt = row["status"]
        if stt in ("added", "deleted"):
            return stt
        old_v = normalize_text_for_compare(row.get(old_desc, ""))
        new_v = normalize_text_for_compare(row.get(new_desc, ""))
        return "changed" if old_v != new_v else "not changed"

    merged["status"] = merged.apply(_final_status, axis=1)

    def _fmt(row):
        stt = row["status"]
        o = "" if pd.isna(row.get(old_desc)) else str(row.get(old_desc)).strip()
        n = "" if pd.isna(row.get(new_desc)) else str(row.get(new_desc)).strip()
        if stt == "changed":
            return f"OLD: {o}\nNEW: {n}".strip()
        if stt == "deleted":
            return o.strip() if o else ""
        if stt == "added":
            return n.strip() if n else ""
        return ""

    merged[out_desc_name] = merged.apply(_fmt, axis=1)

    out = merged[[key_col, "status", out_desc_name]].rename(columns={key_col: out_key_name})
    out = out[["status", out_key_name, out_desc_name]]
    return out

def _build_export_df(
    df_compare: pd.DataFrame,
    db_df: pd.DataFrame,
    db_map: dict,
    cols_order: list[str],
) -> pd.DataFrame:
    """
    Делает for_review попарно:
    status, Subclass_code, <db for Subclass_code>, Description, <db for Description>, ...
    затем несопоставленные db-колонки в конец.
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

    # 2) пара для Subclass_code (если выбрана)
    target_db_code = (db_map or {}).get("Subclass_code")
    if target_db_code:
        add(target_db_code)
        used_db_cols.add(target_db_code)

    # 3) остальное по порядку UI (попарно)
    for src_col in cols_order:
        if src_col in ("Subclass_code", "status"):
            continue

        add(src_col)

        target_db = (db_map or {}).get(src_col)
        if target_db:
            add(target_db)
            used_db_cols.add(target_db)

    # 4) оставшиеся DB-колонки в конец (если нужны)
    for c in db_df.columns:
        if c == "Subclass_code":
            continue
        if c not in used_db_cols:
            add(c)

    return merged[export_cols]

def write_excel_with_highlight(
    buf: io.BytesIO,
    export_df: pd.DataFrame,
    highlight_cols: list[str],
    df_sections: pd.DataFrame | None = None,
    df_divisions: pd.DataFrame | None = None,
    df_groups_cmp: pd.DataFrame | None = None,
    df_classes_cmp: pd.DataFrame | None = None,
    df_subclasses_cmp: pd.DataFrame | None = None,
    debug: bool = False,
):
    """Подсвечивает только SHAMS-колонки (highlight_cols) на листе for_review."""
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

        if debug:
            print("EXPORT COLS:", list(export_df.columns))
            print("HIGHLIGHT COLS:", highlight_cols)
            print("HIGHLIGHT IDXS:", highlight_idxs)

        max_row = ws.max_row
        for col_idx in highlight_idxs:
            for row_idx in range(1, max_row + 1):
                ws.cell(row=row_idx, column=col_idx).fill = fill

        # Дополнительные листы
        if df_sections is not None:
            df_sections.to_excel(writer, index=False, sheet_name="sections")
        if df_divisions is not None:
            df_divisions.to_excel(writer, index=False, sheet_name="divisions")

        # ВАЖНО: эти листы — именно сравнение
        if df_groups_cmp is not None:
            df_groups_cmp.to_excel(writer, index=False, sheet_name="groups")
        if df_classes_cmp is not None:
            df_classes_cmp.to_excel(writer, index=False, sheet_name="classes")
        if df_subclasses_cmp is not None:
            df_subclasses_cmp.to_excel(writer, index=False, sheet_name="subclasses")

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
            st.session_state.hierarchy_roles = None
            st.session_state.df_groups_cmp = None
            st.session_state.df_classes_cmp = None
            st.session_state.df_subclasses_cmp = None
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
        if st.button("Далее: Уровни иерархии"):
            st.session_state.stage = STAGE_HIERARCHY
            st.rerun()

# ==================================================
# ============ STAGE 3.5 — HIERARCHY ================
# ==================================================
if st.session_state.stage == STAGE_HIERARCHY:
    st.subheader("Уровни иерархии")
    st.caption(
        "Поставьте галочки и укажите роль каждого выбранного столбца shams2. "
        "Опции «не включать…» нет: либо общий столбец, либо один из уровней."
    )

    st.session_state.provider_has_groups = st.checkbox(
        "Провайдер разделяет активити на группы",
        value=bool(st.session_state.provider_has_groups),
    )
    st.session_state.provider_has_classes = st.checkbox(
        "Провайдер разделяет активити на классы",
        value=bool(st.session_state.provider_has_classes),
    )

    # варианты выбора роли
    role_options = ["Общий столбец", "Activity Code"]
    if st.session_state.provider_has_classes or st.session_state.provider_has_groups:
        if "Class" not in role_options:
            role_options.insert(2, "Class")
    if st.session_state.provider_has_groups:
        if "Group" not in role_options:
            role_options.insert(3 if "Class" in role_options else 2, "Group")

    selected_cols = st.session_state.headers_new_selected or []

    if st.session_state.hierarchy_roles is None:
        st.session_state.hierarchy_roles = {c: "Общий столбец" for c in selected_cols}
    else:
        cur = {k: v for k, v in st.session_state.hierarchy_roles.items() if k in selected_cols}
        for c in selected_cols:
            cur.setdefault(c, "Общий столбец")
        st.session_state.hierarchy_roles = cur

    roles_map = st.session_state.hierarchy_roles

    st.markdown("---")
    for col in selected_cols:
        cur_val = roles_map.get(col, "Общий столбец")
        idx = role_options.index(cur_val) if cur_val in role_options else 0
        roles_map[col] = st.selectbox(
            label=col,
            options=role_options,
            index=idx,
            key=f"role_{col}",
        )

    st.session_state.hierarchy_roles = roles_map

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
            st.session_state.df_groups_cmp = None
            st.session_state.df_classes_cmp = None
            st.session_state.df_subclasses_cmp = None
            st.session_state.stage = STAGE_COMPARE
            st.rerun()

# ==================================================
# ============== STAGE 4 — COMPARE =================
# ==================================================
if st.session_state.stage == STAGE_COMPARE:
    st.subheader("Статистика сравнения")

    if st.session_state.df_compare is None:
        df_main_old, df_sections_old, df_divisions_old, df_groups_old, df_classes_old, df_subclasses_old = parse_all_sheets_from_bytes(
            st.session_state.shams_bytes, sheets=None
        )
        df_main_new, df_sections_new, df_divisions_new, df_groups_new, df_classes_new, df_subclasses_new = parse_all_sheets_from_bytes(
            st.session_state.shams2_bytes, sheets=None
        )

        # 1) сравнение активити (Subclass) как раньше
        df_compare = compare_shams(
            df_main_old,
            df_main_new,
            st.session_state.column_mapping,
        )
        st.session_state.df_compare = df_compare
        st.session_state.compare_stats = comparison_stats(df_compare)

        # 2) сравнения уровней (как ты дала функцию)
        #    важно: имена колонок key/desc должны соответствовать parse_all_sheets_from_bytes
        #    здесь оставляю "как было": Group_code/Group_en, Class_code/Class_en, Subclass_code/Subclass_en
        st.session_state.df_groups_cmp = (
            compare_level_like_subclass(df_groups_old, df_groups_new, key_col="Group_code", desc_col="Group_en", out_key_name="Group_code")
            if st.session_state.provider_has_groups else pd.DataFrame(columns=["status", "Group_code", "Description"])
        )
        st.session_state.df_classes_cmp = (
            compare_level_like_subclass(df_classes_old, df_classes_new, key_col="Class_code", desc_col="Class_en", out_key_name="Class_code")
            if (st.session_state.provider_has_classes or st.session_state.provider_has_groups) else pd.DataFrame(columns=["status", "Class_code", "Description"])
        )
        st.session_state.df_subclasses_cmp = (
            compare_level_like_subclass(df_subclasses_old, df_subclasses_new, key_col="Subclass_code", desc_col="Subclass_en", out_key_name="Subclass_code")
        )

    stats_df = st.session_state.compare_stats
    stats = dict(zip(stats_df["metric"], stats_df["value"]))

    st.markdown(f"""
**Количество активити в старом файле:** {stats['Количество строк в старом файле']}  
**Количество активити в новом файле:** {stats['Количество строк в новом файле']}  
**Добавлено активити:** {stats['Добавлено']}  
**Удалено активити:** {stats['Удалено']}  
**Внесены изменения:** {stats['Изменено (по выбранным столбцам)']}  
**Остались без изменений:** {stats['Не изменено']}  
""")

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
    st.caption("status не сопоставляется. Subclass_code сопоставляется и идёт первой парой после status.")

    df = st.session_state.df_compare
    if df is None or df.empty:
        st.error("Нет результата сравнения. Вернитесь на шаг сравнения.")
        st.stop()

    # колонки для сопоставления с БД: Subclass_code + остальное (Description первым)
    cols_to_map: list[str] = []
    if "Subclass_code" in df.columns:
        cols_to_map.append("Subclass_code")

    other = [c for c in df.columns if c not in ("Subclass_code", "status", "Subclass")]
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

    # уровни из нового файла (sections/divisions) + сравнения (groups/classes/subclasses)
    try:
        _, df_sections, df_divisions, _, _, _ = parse_all_sheets_from_bytes(
            st.session_state.shams2_bytes, sheets=None
        )
    except Exception as e:
        st.error(f"Не удалось распарсить уровни из shams2: {e}")
        st.stop()

    highlight_cols = ["status", "Subclass_code"] + [c for c in cols_order if c not in ("status", "Subclass_code")]

    buf = io.BytesIO()
    write_excel_with_highlight(
        buf=buf,
        export_df=export_df,
        highlight_cols=highlight_cols,
        df_sections=df_sections,
        df_divisions=df_divisions,
        df_groups_cmp=st.session_state.df_groups_cmp,
        df_classes_cmp=st.session_state.df_classes_cmp,
        df_subclasses_cmp=st.session_state.df_subclasses_cmp,
        debug=False,
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
