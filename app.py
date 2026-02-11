# app.py
from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any

import pandas as pd
import streamlit as st
from openpyxl.styles import PatternFill

from DB import DB_COLUMNS
from compare import compare_shams, comparison_stats, compare_level_descriptions  # compare_level_descriptions будет в compare.py
from header_log import build_header_change_log_from_bytes
from shams_parser import parse_all_sheets_from_bytes


# ================== STAGES ==================
STAGE_UPLOAD = "upload"
STAGE_SELECT_HEADERS = "select_headers"
STAGE_MAPPING = "mapping"
STAGE_HIERARCHY = "hierarchy"          # NEW
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

        "df_compare": None,
        "compare_stats": None,

        # NEW: hierarchy step
        "hier_levels_count": 1,          # 1|2|3
        "hier_cols_role": {},            # {col_name: role}
        # role in {"level1","level2","level3","skip","common"}
        # common = общий столбец (не относится к уровням)

        # DB mapping/export
        "db_column_mapping": None,       # {src_col: db_col|None}
        "db_mapping_saved": False,
        "db_cols_order": None,           # порядок src_cols из UI DB mapping

        "stage": STAGE_UPLOAD,
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


def unpack_shams_parse(res: Any):
    """
    parse_all_sheets_from_bytes может возвращать разное число датафреймов.
    Приводим к единому виду:
      full, sections, divisions, groups, classes, subclasses
    """
    empty = pd.DataFrame()

    if res is None:
        return empty, empty, empty, empty, empty, empty

    if not isinstance(res, (tuple, list)):
        return res, empty, empty, empty, empty, empty

    full = res[0] if len(res) > 0 else empty
    sections = res[1] if len(res) > 1 else empty
    divisions = res[2] if len(res) > 2 else empty
    groups = res[3] if len(res) > 3 else empty
    classes = res[4] if len(res) > 4 else empty
    subclasses = res[5] if len(res) > 5 else empty
    return full, sections, divisions, groups, classes, subclasses


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
    df_subclasses: pd.DataFrame | None = None,
):
    """
    Подсвечивает колонки из highlight_cols (SHAMS), оставляя DB-колонки без заливки.
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

        max_row = ws.max_row  # включая заголовок
        for col_idx in highlight_idxs:
            for row_idx in range(1, max_row + 1):
                ws.cell(row=row_idx, column=col_idx).fill = fill

        # дополнительные листы
        if df_sections is not None and not df_sections.empty:
            df_sections.to_excel(writer, index=False, sheet_name="sections")
        if df_divisions is not None and not df_divisions.empty:
            df_divisions.to_excel(writer, index=False, sheet_name="divisions")
        if df_groups is not None and not df_groups.empty:
            df_groups.to_excel(writer, index=False, sheet_name="groups")
        if df_classes is not None and not df_classes.empty:
            df_classes.to_excel(writer, index=False, sheet_name="classes")
        if df_subclasses is not None and not df_subclasses.empty:
            df_subclasses.to_excel(writer, index=False, sheet_name="subclasses")


def _build_export_df(
    df_compare: pd.DataFrame,
    db_df: pd.DataFrame,
    db_map: dict,
    cols_order: list[str],
) -> pd.DataFrame:
    """
    Экспорт попарно как на шаге сопоставления с БД:
    status (1), Subclass_code (2), db_pair_for_Subclass_code (3)
    затем: src_col, db_col (если выбрана), строго по cols_order.
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

    # 2) db_pair для Subclass_code (если выбрана)
    db_code = (db_map or {}).get("Subclass_code")
    if db_code:
        if db_code not in merged.columns:
            merged[db_code] = pd.NA
        add(db_code)
        used_db_cols.add(db_code)

    # 3) дальше строго по порядку UI (попарно)
    for src_col in cols_order:
        if src_col in ("status", "Subclass_code"):
            continue

        add(src_col)

        target_db = (db_map or {}).get(src_col)
        if target_db:
            if target_db not in merged.columns:
                merged[target_db] = pd.NA
            add(target_db)
            used_db_cols.add(target_db)

    # 4) несопоставленные колонки БД в конец (если нужны)
    for c in db_df.columns:
        if c == "Subclass_code":
            continue
        if c not in used_db_cols:
            add(c)

    return merged[export_cols]


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
                sheets=None
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
            st.session_state.db_cols_order = None

            st.session_state.hier_cols_role = {}
            st.session_state.hier_levels_count = 1

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
            key=f"map_{col_new}"
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
        if st.button("Дальше: уровни иерархии"):
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.db_column_mapping = None
            st.session_state.db_mapping_saved = False
            st.session_state.db_cols_order = None

            st.session_state.stage = STAGE_HIERARCHY
            st.rerun()


# ==================================================
# ============ STAGE 3.5 — HIERARCHY ===============
# ==================================================
if st.session_state.stage == STAGE_HIERARCHY:
    st.subheader("Шаг 3 — уровни иерархии")
    st.caption("Выберите количество уровней и укажите, к какому уровню относится каждый столбец shams2.")

    # 1) Сколько уровней
    st.session_state.hier_levels_count = st.radio(
        "Сколько уровней иерархии сравнивать?",
        options=[1, 2, 3],
        horizontal=True,
        index=[1, 2, 3].index(st.session_state.get("hier_levels_count", 1)),
        key="hier_levels_count_radio",
    )

    st.markdown("---")
    st.caption(
        "Для каждого столбца выберите:\n"
        "- Уровень 1/2/3 (описания будут сравниваться на этом уровне)\n"
        "- Это общий столбец (не относится к уровням)\n"
        "- Не включать в сопоставление"
    )

    # columns to classify: выбранные пользователем колонки из shams2
    cols = st.session_state.headers_new_selected or []
    role_map = st.session_state.get("hier_cols_role") or {}

    # роль по умолчанию: Description => common, остальное => skip (чтобы пользователь осознанно назначал)
    def default_role(c: str) -> str:
        if str(c).strip().lower() in ("description", "описание"):
            return "common"
        return "skip"

    options = [
        ("level1", "1 уровень"),
        ("level2", "2 уровень"),
        ("level3", "3 уровень"),
        ("common", "это общий столбец"),
        ("skip", "не включать в сопоставление"),
    ]

    # отображаем в один столбец
    for c in cols:
        key = f"hier_role_{c}"
        cur = role_map.get(c, default_role(c))
        label_map = {k: v for k, v in options}

        selected_label = st.selectbox(
            label=c,
            options=[v for _, v in options],
            index=[v for _, v in options].index(label_map[cur]),
            key=key,
        )

        inv = {v: k for k, v in options}
        role_map[c] = inv[selected_label]

    # если уровней меньше, чем указано в назначениях — всё равно оставляем, но сравнение выполнится только по lvl
    st.session_state.hier_cols_role = role_map

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_MAPPING
            st.rerun()

    with col2:
        if st.button("Сохранить и перейти к статистике", type="primary"):
            st.session_state.stage = STAGE_COMPARE
            st.rerun()


# ==================================================
# ============== STAGE 4 — COMPARE =================
# ==================================================
if st.session_state.stage == STAGE_COMPARE:
    st.subheader("Статистика сравнения")

    try:
        if st.session_state.df_compare is None:
            res_old = parse_all_sheets_from_bytes(st.session_state.shams_bytes, sheets=None)
            res_new = parse_all_sheets_from_bytes(st.session_state.shams2_bytes, sheets=None)

            df_full_old, df_sections_old, df_divisions_old, df_groups_old, df_classes_old, df_subclasses_old = unpack_shams_parse(res_old)
            df_full_new, df_sections_new, df_divisions_new, df_groups_new, df_classes_new, df_subclasses_new = unpack_shams_parse(res_new)

            # Subclass compare (основной compare.py)
            df_compare = compare_shams(df_full_old, df_full_new, st.session_state.column_mapping)
            st.session_state.df_compare = df_compare
            st.session_state.compare_stats = comparison_stats(df_compare)

            # дополнительные сравнения уровней (будут выгружены отдельными листами на экспорте)
            st.session_state.level_compare_class = None
            st.session_state.level_compare_group = None

            lvl = int(st.session_state.get("hier_levels_count") or 1)

            # сравнение описаний классов и групп — теперь всегда делаем,
            # если выбран lvl >= 2/3 и листы не пустые.
            if lvl >= 2 and isinstance(df_classes_old, pd.DataFrame) and isinstance(df_classes_new, pd.DataFrame) and (not df_classes_old.empty) and (not df_classes_new.empty):
                st.session_state.level_compare_class = compare_level_descriptions(df_classes_old, df_classes_new)

            if lvl >= 3 and isinstance(df_groups_old, pd.DataFrame) and isinstance(df_groups_new, pd.DataFrame) and (not df_groups_old.empty) and (not df_groups_new.empty):
                st.session_state.level_compare_group = compare_level_descriptions(df_groups_old, df_groups_new)

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
            if st.button("Выгрузить в эксель для работы с обновлениями", type="primary"):
                st.session_state.stage = STAGE_DB_MAPPING
                st.rerun()

    except Exception as e:
        st.error("Ошибка на шаге сравнения. Ниже — причина:")
        st.exception(e)
        st.stop()


# ==================================================
# ============ STAGE 5 — DB MAPPING =================
# ==================================================
if st.session_state.stage == STAGE_DB_MAPPING:
    st.subheader("Сопоставление столбцов результата и Базы Данных")
    st.caption("Status не сопоставляем. Subclass не сопоставляем. Subclass_code сопоставляем.")

    df = st.session_state.df_compare
    if df is None or df.empty:
        st.error("Нет результата сравнения. Вернитесь на шаг сравнения.")
        st.stop()

    # страховка: старая логика
    legacy_cols = [c for c in df.columns if c.endswith("_old") or c.endswith("_new") or c == "diff_columns"]
    if legacy_cols:
        st.warning("Результат сравнения посчитан старой логикой. Пересчитаю...")
        st.session_state.df_compare = None
        st.session_state.compare_stats = None
        st.session_state.stage = STAGE_COMPARE
        st.rerun()

    cols_to_map: list[str] = []

    # Subclass_code обязателен
    if "Subclass_code" in df.columns:
        cols_to_map.append("Subclass_code")

    # остальное, кроме служебных
    other = [c for c in df.columns if c not in ("Subclass_code", "status", "Subclass")]

    # Description первым
    if "Description" in other:
        other = ["Description"] + [c for c in other if c != "Description"]

    cols_to_map += other
    cols_to_map = list(dict.fromkeys(cols_to_map))  # no dups

    st.session_state.db_cols_order = cols_to_map

    current_map = st.session_state.db_column_mapping or {}
    current_map = {k: v for k, v in current_map.items() if k in cols_to_map}
    for c in cols_to_map:
        current_map.setdefault(c, None)
    st.session_state.db_column_mapping = current_map
    mapping = st.session_state.db_column_mapping

    # один столбец UI
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

    try:
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

        # уровни из shams2
        res_new = parse_all_sheets_from_bytes(st.session_state.shams2_bytes, sheets=None)
        df_full_new, df_sections, df_divisions, df_groups, df_classes, df_subclasses = unpack_shams_parse(res_new)

        # дополнительные листы сравнения уровней
        df_cmp_class = st.session_state.get("level_compare_class")
        df_cmp_group = st.session_state.get("level_compare_group")

        # какие колонки подсвечиваем (только SHAMS)
        highlight_cols = ["status", "Subclass_code"] + [c for c in cols_order if c != "Subclass_code"]

        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as writer:
            # for_review с подсветкой
            export_df.to_excel(writer, index=False, sheet_name="for_review")
            ws = writer.sheets["for_review"]

            fill = PatternFill(fill_type="solid", start_color="FFFFF2CC", end_color="FFFFF2CC")
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

            # уровни
            if df_sections is not None and not df_sections.empty:
                df_sections.to_excel(writer, index=False, sheet_name="sections")
            if df_divisions is not None and not df_divisions.empty:
                df_divisions.to_excel(writer, index=False, sheet_name="divisions")
            if df_groups is not None and not df_groups.empty:
                df_groups.to_excel(writer, index=False, sheet_name="groups")
            if df_classes is not None and not df_classes.empty:
                df_classes.to_excel(writer, index=False, sheet_name="classes")
            if df_subclasses is not None and not df_subclasses.empty:
                df_subclasses.to_excel(writer, index=False, sheet_name="subclasses")

            # сравнения описаний уровней (если есть)
            if isinstance(df_cmp_class, pd.DataFrame) and not df_cmp_class.empty:
                df_cmp_class.to_excel(writer, index=False, sheet_name="compare_classes")

            if isinstance(df_cmp_group, pd.DataFrame) and not df_cmp_group.empty:
                df_cmp_group.to_excel(writer, index=False, sheet_name="compare_groups")

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

    except Exception as e:
        st.error("Ошибка на шаге экспорта. Ниже — причина:")
        st.exception(e)
        st.stop()
