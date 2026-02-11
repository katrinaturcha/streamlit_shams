from __future__ import annotations

import io
import re
from pathlib import Path

import pandas as pd
import streamlit as st
from openpyxl.styles import PatternFill

from header_log import build_header_change_log_from_bytes
from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats, compare_level_descriptions
from DB import DB_COLUMNS


# ================== STAGES ==================
STAGE_UPLOAD = "upload"
STAGE_SELECT_HEADERS = "select_headers"
STAGE_MAPPING = "mapping"
STAGE_HIERARCHY = "hierarchy"
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
        "column_mapping": None,
        "df_compare": None,          # subclasses compare (main)
        "compare_stats": None,
        "df_compare_class": None,    # classes compare
        "df_compare_group": None,    # groups compare
        "db_column_mapping": None,
        "stage": STAGE_UPLOAD,
        "db_mapping_saved": False,
        "db_cols_order": None,

        # hierarchy step
        "hier_levels_count": None,   # 1/2/3
        "hier_col_roles": None,      # {selected_col: "level1"/"level2"/"level3"/"exclude"/"common"}
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


def _guess_key_and_desc_cols(df: pd.DataFrame, level_name: str) -> tuple[str, str]:
    """
    Эвристика, чтобы не хардкодить имена колонок уровней.
    level_name: "group" / "class" / "subclass"
    """
    cols = [str(c).strip() for c in df.columns]

    # key: предпочитаем что-то с "code"
    key_candidates = [c for c in cols if "code" in c.lower()]
    key_col = key_candidates[0] if key_candidates else cols[0]

    # desc: предпочитаем *_en, затем "description", затем любой текстовый
    desc_candidates = [c for c in cols if c.lower().endswith("_en") or " english" in c.lower() or "description" in c.lower()]
    if not desc_candidates:
        # часто бывает что описание = Name/Title
        desc_candidates = [c for c in cols if any(x in c.lower() for x in ["name", "title", "desc", "опис", "наимен"])]
    desc_col = desc_candidates[0] if desc_candidates else (cols[1] if len(cols) > 1 else cols[0])

    return key_col, desc_col


def write_excel_with_highlight(
    buf: io.BytesIO,
    export_df: pd.DataFrame,
    highlight_cols: list[str],
    df_sections: pd.DataFrame | None = None,
    df_divisions: pd.DataFrame | None = None,
    df_groups: pd.DataFrame | None = None,
    df_classes: pd.DataFrame | None = None,
    df_subclasses: pd.DataFrame | None = None,
    df_classes_compare: pd.DataFrame | None = None,
    df_groups_compare: pd.DataFrame | None = None,
    debug: bool = False,
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

        if debug:
            print("EXPORT COLS:", list(export_df.columns))
            print("HIGHLIGHT COLS:", highlight_cols)
            print("HIGHLIGHT IDXS:", highlight_idxs)

        max_row = ws.max_row
        for col_idx in highlight_idxs:
            for row_idx in range(1, max_row + 1):
                ws.cell(row=row_idx, column=col_idx).fill = fill

        # уровни отдельными листами
        if df_sections is not None:
            df_sections.to_excel(writer, index=False, sheet_name="sections")
        if df_divisions is not None:
            df_divisions.to_excel(writer, index=False, sheet_name="divisions")
        if df_groups is not None:
            df_groups.to_excel(writer, index=False, sheet_name="groups")
        if df_classes is not None:
            df_classes.to_excel(writer, index=False, sheet_name="classes")
        if df_subclasses is not None:
            df_subclasses.to_excel(writer, index=False, sheet_name="subclasses")

        # сравнение уровней
        if df_classes_compare is not None:
            df_classes_compare.to_excel(writer, index=False, sheet_name="classes_compare")
        if df_groups_compare is not None:
            df_groups_compare.to_excel(writer, index=False, sheet_name="groups_compare")


def _build_export_df(
    df_compare: pd.DataFrame,
    db_df: pd.DataFrame,
    db_map: dict,
    cols_order: list[str],
) -> pd.DataFrame:
    """
    Экспорт делаем строго "попарно" как в UI:
    - status
    - Subclass_code + (DB-пара если выбрана)
    - далее по cols_order: src + db (если выбрана)
    - в конце несопоставленные колонки из БД (опционально)
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

    def add_db_pair(src_col: str, target_db: str | None):
        """
        Если target_db совпадает с src_col, берём db-версию (suffix _db),
        а чтобы не было двух одинаковых заголовков — переименовываем в "... (DB)".
        """
        if not target_db:
            return

        target_db = str(target_db).strip()
        if not target_db:
            return

        # обычный случай: db колонка не совпадает по имени со src_col
        if target_db != src_col:
            if target_db in merged.columns:
                add(target_db)
                used_db_cols.add(target_db)
            else:
                merged[target_db] = pd.NA
                add(target_db)
                used_db_cols.add(target_db)
            return

        # случай: target_db == src_col (иначе будет дубль заголовка)
        db_version = f"{target_db}_db"
        if db_version in merged.columns:
            new_name = f"{target_db} (DB)"
            # создаём отдельную колонку с безопасным именем
            if new_name not in merged.columns:
                merged[new_name] = merged[db_version]
            add(new_name)
            used_db_cols.add(target_db)
        else:
            # если по какой-то причине suffix нет
            new_name = f"{target_db} (DB)"
            merged[new_name] = pd.NA
            add(new_name)
            used_db_cols.add(target_db)

    # 0) status первым
    add("status")

    # 1) Subclass_code вторым
    add("Subclass_code")

    # 2) DB-пара для Subclass_code (если выбрана)
    add_db_pair("Subclass_code", (db_map or {}).get("Subclass_code"))

    # 3) дальше строго по UI-порядку
    for src_col in cols_order or []:
        if src_col in ("status", "Subclass_code", "Subclass"):
            continue
        if src_col not in merged.columns:
            continue

        add(src_col)
        add_db_pair(src_col, (db_map or {}).get(src_col))

    # 4) несопоставленные колонки БД в конец
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
            st.session_state.df_compare_class = None
            st.session_state.df_compare_group = None
            st.session_state.db_column_mapping = None
            st.session_state.db_mapping_saved = False
            st.session_state.db_cols_order = None
            st.session_state.hier_levels_count = None
            st.session_state.hier_col_roles = None
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
        index = headers_old.index(current_value) + 1 if current_value in headers_old else 0

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
        if st.button("Подтвердить сопоставление"):
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.df_compare_class = None
            st.session_state.df_compare_group = None
            st.session_state.db_column_mapping = None
            st.session_state.db_mapping_saved = False
            st.session_state.db_cols_order = None

            # новый шаг
            st.session_state.hier_levels_count = None
            st.session_state.hier_col_roles = None
            st.session_state.stage = STAGE_HIERARCHY
            st.rerun()


# ==================================================
# ========= STAGE 3.5 — HIERARCHY LEVELS ===========
# ==================================================
if st.session_state.stage == STAGE_HIERARCHY:
    st.subheader("Шаг 3 — Уровни иерархии")
    st.caption(
        "1) Выберите, сколько уровней используем.\n"
        "2) Для каждого выбранного столбца shams2 укажите роль: уровень / не включать / общий."
    )

    selected_cols = st.session_state.headers_new_selected or []

    # 1) сколько уровней
    lvl_options = [1, 2, 3]
    lvl_default_idx = 0 if st.session_state.hier_levels_count is None else lvl_options.index(st.session_state.hier_levels_count)
    lvl = st.radio(
        "Сколько уровней иерархии?",
        options=lvl_options,
        index=lvl_default_idx,
        horizontal=True,
    )
    st.session_state.hier_levels_count = lvl

    # 2) роли
    if st.session_state.hier_col_roles is None:
        st.session_state.hier_col_roles = {c: "common" for c in selected_cols}
    else:
        cur = {k: v for k, v in st.session_state.hier_col_roles.items() if k in selected_cols}
        for c in selected_cols:
            cur.setdefault(c, "common")
        st.session_state.hier_col_roles = cur

    role_labels = {
        "level1": "1 уровень",
        "level2": "2 уровень",
        "level3": "3 уровень",
        "exclude": "не включать в сопоставление",
        "common": "это общий столбец",
    }

    allowed_roles = (
        ["level1", "exclude", "common"] if lvl == 1 else
        ["level1", "level2", "exclude", "common"] if lvl == 2 else
        ["level1", "level2", "level3", "exclude", "common"]
    )

    for col in selected_cols:
        cur_role = st.session_state.hier_col_roles.get(col, "common")
        if cur_role not in allowed_roles:
            cur_role = "common"

        selected = st.selectbox(
            label=col,
            options=allowed_roles,
            index=allowed_roles.index(cur_role),
            format_func=lambda x: role_labels.get(x, x),
            key=f"hier_role_{col}",
        )
        st.session_state.hier_col_roles[col] = selected

    st.markdown("---")
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_MAPPING
            st.rerun()
    with c2:
        if st.button("Сохранить и перейти к статистике", type="primary"):
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.df_compare_class = None
            st.session_state.df_compare_group = None
            st.session_state.stage = STAGE_COMPARE
            st.rerun()


# ==================================================
# ============== STAGE 4 — COMPARE =================
# ==================================================
if st.session_state.stage == STAGE_COMPARE:
    st.subheader("Статистика сравнения")

    if st.session_state.df_compare is None:
        # main + levels
        df_full_old, df_sections_old, df_divisions_old, df_groups_old, df_classes_old, df_subclasses_old = parse_all_sheets_from_bytes(
            st.session_state.shams_bytes, sheets=None
        )
        df_full_new, df_sections_new, df_divisions_new, df_groups_new, df_classes_new, df_subclasses_new = parse_all_sheets_from_bytes(
            st.session_state.shams2_bytes, sheets=None
        )

        # 1) subclasses compare (главная таблица) — как раньше
        df_compare_sub = compare_shams(df_full_old, df_full_new, st.session_state.column_mapping)
        st.session_state.df_compare = df_compare_sub
        st.session_state.compare_stats = comparison_stats(df_compare_sub)

        # 2) classes/groups compare — в зависимости от выбранного количества уровней
        lvl = st.session_state.get("hier_levels_count") or 1

        if lvl >= 2 and df_classes_old is not None and df_classes_new is not None and not df_classes_old.empty and not df_classes_new.empty:
            class_key, class_desc = _guess_key_and_desc_cols(df_classes_old, "class")
            st.session_state.df_compare_class = compare_level_descriptions(
                df_old=df_classes_old,
                df_new=df_classes_new,
                key_col=class_key,
                desc_col=class_desc,
            )

        if lvl >= 3 and df_groups_old is not None and df_groups_new is not None and not df_groups_old.empty and not df_groups_new.empty:
            group_key, group_desc = _guess_key_and_desc_cols(df_groups_old, "group")
            st.session_state.df_compare_group = compare_level_descriptions(
                df_old=df_groups_old,
                df_new=df_groups_new,
                key_col=group_key,
                desc_col=group_desc,
            )

    stats_df = st.session_state.compare_stats
    stats = dict(zip(stats_df["metric"], stats_df["value"]))

    st.markdown(
        f"""
**Количество активити в старом файле:** {stats['Количество строк в старом файле']}  
**Количество активити в новом файле:** {stats['Количество строк в новом файле']}  
**Добавлено активити:** {stats['Добавлено']}  
**Удалено активити:** {stats['Удалено']}  
**Внесены изменения:** {stats['Изменено (по выбранным столбцам)']}  
**Остались без изменений:** {stats['Не изменено']}  
"""
    )

    # доп. статистика по уровням
    if st.session_state.df_compare_class is not None:
        dfc = st.session_state.df_compare_class
        st.markdown(f"**Классы — изменено:** {(dfc['status'] == 'changed').sum()} | добавлено: {(dfc['status'] == 'added').sum()} | удалено: {(dfc['status'] == 'deleted').sum()}")

    if st.session_state.df_compare_group is not None:
        dfg = st.session_state.df_compare_group
        st.markdown(f"**Группы — изменено:** {(dfg['status'] == 'changed').sum()} | добавлено: {(dfg['status'] == 'added').sum()} | удалено: {(dfg['status'] == 'deleted').sum()}")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_HIERARCHY
            st.rerun()
    with col2:
        if st.button("Выгрузить в эксель для работы с обновлениями", type="primary"):
            st.session_state.stage = STAGE_DB_MAPPING
            st.rerun()


# ==================================================
# ============ STAGE 5 — DB MAPPING =================
# ==================================================
if st.session_state.stage == STAGE_DB_MAPPING:
    st.subheader("Сопоставление столбцов результата и Базы Данных")
    st.caption("Выберите, в какой столбец БД должен попасть каждый столбец результата. Status не сопоставляется.")

    df = st.session_state.df_compare
    if df is None or df.empty:
        st.error("Нет результата сравнения. Вернитесь на шаг сравнения.")
        st.stop()

    # страховка для старой логики compare
    legacy_cols = [c for c in df.columns if c.endswith("_old") or c.endswith("_new") or c == "diff_columns"]
    if legacy_cols:
        st.warning("Похоже, сравнение было посчитано старой логикой. Пересчитываю...")
        st.session_state.df_compare = None
        st.session_state.compare_stats = None
        st.session_state.df_compare_class = None
        st.session_state.df_compare_group = None
        st.session_state.stage = STAGE_COMPARE
        st.rerun()

    # колонки для сопоставления с БД:
    # - обязательно Subclass_code
    # - остальные (кроме служебных status/Subclass)
    cols_to_map: list[str] = []
    if "Subclass_code" in df.columns:
        cols_to_map.append("Subclass_code")

    other = [c for c in df.columns if c not in ("Subclass_code", "status", "Subclass")]
    if "Description" in other:
        other = ["Description"] + [c for c in other if c != "Description"]

    cols_to_map += other
    cols_to_map = list(dict.fromkeys(cols_to_map))

    st.session_state.db_cols_order = cols_to_map

    # init mapping
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
    c1, c2 = st.columns(2)
    with c1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_COMPARE
            st.rerun()
    with c2:
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

    db_df = load_db_df()
    if db_df is None or db_df.empty:
        st.error("Файл БД пустой или не загрузился.")
        st.stop()

    cols_order = st.session_state.get("db_cols_order") or []

    export_df = _build_export_df(
        df_compare=df_compare,
        db_df=db_df,
        db_map=db_map,
        cols_order=cols_order,
    )

    # если Subclass внезапно присутствует — не выводим (как договорились)
    export_df = export_df.drop(columns=["Subclass"], errors="ignore")

    # уровни из shams2
    try:
        _, df_sections, df_divisions, df_groups, df_classes, df_subclasses = parse_all_sheets_from_bytes(
            st.session_state.shams2_bytes, sheets=None
        )
    except Exception as e:
        st.error(f"Не удалось распарсить уровни из shams2: {e}")
        st.stop()

    # колонки, которые подсвечиваем (ТОЛЬКО SHAMS):
    # status + Subclass_code + остальные src колонки из UI-списка
    highlight_cols = ["status", "Subclass_code"] + [c for c in cols_order if c != "Subclass_code"]

    buf = io.BytesIO()
    write_excel_with_highlight(
        buf=buf,
        export_df=export_df,
        highlight_cols=highlight_cols,
        df_sections=df_sections,
        df_divisions=df_divisions,
        df_groups=df_groups,
        df_classes=df_classes,
        df_subclasses=df_subclasses,
        df_classes_compare=st.session_state.get("df_compare_class"),
        df_groups_compare=st.session_state.get("df_compare_group"),
        debug=False,  # поставь True на один запуск, если снова не окрасит
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
