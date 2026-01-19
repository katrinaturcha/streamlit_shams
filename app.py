import streamlit as st
from pathlib import Path
import pandas as pd

from header_log import build_header_change_log_from_bytes
from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats
from DB import DB_COLUMNS
import io


# ================== STAGES ==================
STAGE_UPLOAD = "upload"
STAGE_SELECT_HEADERS = "select_headers"
STAGE_MAPPING = "mapping"
STAGE_COMPARE = "compare"
STAGE_DB_MAPPING = "db_mapping"
STAGE_DB_EXPORT = "db_export"
STAGE_SELECT_COMPARE_COLS = "select_compare_cols"



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

        "df_compare": None,
        "compare_stats": None,

        "db_column_mapping": None,

        "stage": STAGE_UPLOAD,
        "db_mapping_saved": False,
        "compare_cols_selected": None,

    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


init_state()


# ================== HELPERS ==================
def load_shams():
    if st.session_state.shams_bytes is None:
        with open(SHAMS_PATH, "rb") as f:
            st.session_state.shams_bytes = f.read()


# ================== UI ==================
st.title("Список активити провайдера")
st.markdown("---")


# ==================================================
# =============== STAGE 1 — UPLOAD =================
# ==================================================
if st.session_state.stage == STAGE_UPLOAD:

    st.subheader("Укажите новый источник")

    uploaded = st.file_uploader(
        "Загрузите файл shams2",
        type=["xlsx"]
    )

    if uploaded is not None:
        st.session_state.shams2_bytes = uploaded.read()

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Отменить"):
            st.session_state.shams2_bytes = None

    with col2:
        if st.button(
            "Применить",
            disabled=st.session_state.shams2_bytes is None
        ):
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

    left, right = st.columns(2)
    temp_selected = []

    for i, col in enumerate(headers):
        target = left if i % 2 == 0 else right
        with target:
            checked = st.checkbox(
                col,
                value=(col in prev_selected),
                key=f"chk_{col}"
            )
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
        if st.button(
            "Перейти к сопоставлению",
            disabled=len(temp_selected) == 0
        ):
            st.session_state.column_mapping = None
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.db_column_mapping = None
            st.session_state.db_mapping_saved = False
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
        current = {
            k: v for k, v in st.session_state.column_mapping.items()
            if k in headers_new_selected
        }
        for col in headers_new_selected:
            current.setdefault(col, None)
        st.session_state.column_mapping = current

    mapping = st.session_state.column_mapping

    st.markdown("---")

    for col_new in headers_new_selected:
        st.markdown(f"**{col_new} →**")

        options = ["<нет соответствия>"] + headers_old
        current_value = mapping.get(col_new)

        index = (
            headers_old.index(current_value) + 1
            if current_value in headers_old
            else 0
        )

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
        if st.button("Подтвердить сопоставление"):
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.db_column_mapping = None
            st.session_state.db_mapping_saved = False
            st.session_state.stage = STAGE_SELECT_COMPARE_COLS
            st.rerun()

# ==================================================
# ===== STAGE 3.5 — SELECT COLUMNS TO COMPARE ======
# ==================================================
if st.session_state.stage == STAGE_SELECT_COMPARE_COLS:

    st.subheader("Шаг 2.5 — какие столбцы сравнивать")
    st.caption("Сравнивается всегда: Description. Дополнительно выберите сопоставленные НЕчисловые столбцы.")

    # парсим, чтобы понять типы колонок (нужно для фильтра НЕчисловых)
    if st.session_state.get("df_full_old_cache") is None or st.session_state.get("df_full_new_cache") is None:
        df_full_old, *_ = parse_all_sheets_from_bytes(st.session_state.shams_bytes, sheets=None)
        df_full_new, *_ = parse_all_sheets_from_bytes(st.session_state.shams2_bytes, sheets=None)
        st.session_state.df_full_old_cache = df_full_old
        st.session_state.df_full_new_cache = df_full_new
    else:
        df_full_old = st.session_state.df_full_old_cache
        df_full_new = st.session_state.df_full_new_cache

    mapping = st.session_state.column_mapping or {}

    # кандидаты: только сопоставленные колонки
    mapped_new_cols = [new_col for new_col, old_col in mapping.items() if old_col]

    def _is_numeric_like(series: pd.Series) -> bool:
        s = series.dropna()
        if s.empty:
            return False
        # пробуем преобразовать к числу
        conv = pd.to_numeric(s.astype(str).str.replace(",", ".", regex=False), errors="coerce")
        ratio = conv.notna().mean()
        return ratio >= 0.9  # 90% значений похожи на числа

    # оставляем только НЕчисловые (по new-файлу; можно ужесточить, проверяя и old)
    non_numeric_candidates = []
    for new_col in mapped_new_cols:
        if new_col in df_full_new.columns:
            if not _is_numeric_like(df_full_new[new_col]):
                non_numeric_candidates.append(new_col)

    # UI чекбоксы
    prev = st.session_state.compare_cols_selected
    if prev is None:
        prev = list(non_numeric_candidates)

    left, right = st.columns(2)
    temp_selected = []

    for i, col in enumerate(non_numeric_candidates):
        target = left if i % 2 == 0 else right
        with target:
            checked = st.checkbox(col, value=(col in prev), key=f"cmp_{col}")
        if checked:
            temp_selected.append(col)

    st.session_state.compare_cols_selected = temp_selected

    st.markdown("---")
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_MAPPING
            st.rerun()

    with col2:
        if st.button("Перейти к сравнению"):
            # сбрасываем результат сравнения
            st.session_state.df_compare = None
            st.session_state.compare_stats = None
            st.session_state.db_column_mapping = None
            st.session_state.db_mapping_saved = False

            st.session_state.stage = STAGE_COMPARE
            st.rerun()

# ==================================================
# ============== STAGE 4 — COMPARE =================
# ==================================================
if st.session_state.stage == STAGE_COMPARE:

    st.subheader("Статистика сравнения")

    if st.session_state.df_compare is None:
        df_full_old, *_ = parse_all_sheets_from_bytes(
            st.session_state.shams_bytes, sheets=None
        )
        df_full_new, *_ = parse_all_sheets_from_bytes(
            st.session_state.shams2_bytes, sheets=None
        )

        # df_compare = compare_shams(
        #     df_full_old,
        #     df_full_new,
        #     st.session_state.column_mapping
        # )
        df_compare = compare_shams(
            df_full_old,
            df_full_new,
            st.session_state.column_mapping,
            compare_cols=st.session_state.compare_cols_selected or [],
        )

        st.session_state.df_compare = df_compare
        st.session_state.compare_stats = comparison_stats(df_compare)

    stats_df = st.session_state.compare_stats
    stats = dict(zip(stats_df["metric"], stats_df["value"]))

    st.markdown(f"""
    **Количество активити в старом файле:** {stats['Количество строк в старом файле']}  
    **Количество активити в новом файле:** {stats['Количество строк в новом файле']}  
    **Добавлено активити:** {stats['Добавлено']}  
    **Удалено активити:** {stats['Удалено']}  
    **Внесены изменения:** {stats['Изменено (по английским описаниям)']}  
    **Остались без изменений:** {stats['Не изменено']}  
    """)

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_MAPPING
            st.rerun()

    with col2:
        if st.button("Актуализировать в БД", type="primary"):
            st.session_state.stage = STAGE_DB_MAPPING
            st.rerun()



def _build_export_df(df_compare: pd.DataFrame, db_df: pd.DataFrame, db_map: dict) -> pd.DataFrame:
    """
    Экспорт:
    - Subclass_code, status
    - далее попарно: [source_col, mapped_db_col] (db_col берётся из db_df, НЕ копируется из source)
    - db-колонки, которые ни с чем не сопоставили — добавляем в конец
    """
    df_compare = df_compare.copy()
    db_df = db_df.copy()

    # гарантируем ключи
    if "Subclass_code" not in df_compare.columns:
        raise ValueError("В df_compare нет Subclass_code")
    if "Subclass_code" not in db_df.columns:
        raise ValueError("В db_df нет Subclass_code")

    # merge, чтобы значения БД подтянулись как есть
    merged = df_compare.merge(db_df, on="Subclass_code", how="left", suffixes=("", "_db"))

    front = [c for c in ["Subclass_code", "status"] if c in merged.columns]

    # колонки сравнения (то, что менеджер смотрит)
    compare_cols = [c for c in df_compare.columns if c not in ("Subclass_code", "status")]

    export_cols = list(front)

    mapped_db_cols_used = set()

    for src_col in compare_cols:
        export_cols.append(src_col)

        target_db = (db_map or {}).get(src_col)
        if target_db:
            # берём именно колонку из БД (уже в merged)
            if target_db in merged.columns:
                export_cols.append(target_db)
                mapped_db_cols_used.add(target_db)
            else:
                # если сопоставили с DB_COLUMNS, но в файле БД такой колонки нет
                # оставляем место, но не ломаем
                merged[target_db] = pd.NA
                export_cols.append(target_db)
                mapped_db_cols_used.add(target_db)

    # добавить несопоставленные db-колонки в конец (со своими значениями)
    db_extra = [c for c in db_df.columns if c not in ("Subclass_code",) and c not in mapped_db_cols_used]
    export_cols += db_extra

    # итог — без дублей, только существующие
    export_cols = [c for c in export_cols if c in merged.columns]

    return merged[export_cols]



# def _to_excel_bytes(df: pd.DataFrame, sheet_name: str = "export") -> bytes:
#     buf = io.BytesIO()
#     with pd.ExcelWriter(buf, engine="openpyxl") as writer:
#         df.to_excel(writer, index=False, sheet_name=sheet_name)
#     buf.seek(0)
#     return buf.getvalue()

def _to_excel_bytes(
    export_df: pd.DataFrame,
    df_sections: pd.DataFrame,
    df_divisions: pd.DataFrame,
    df_groups: pd.DataFrame,
    df_classes: pd.DataFrame,
    df_subclasses: pd.DataFrame,
) -> bytes:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="for_review")
        df_sections.to_excel(writer, index=False, sheet_name="sections")
        df_divisions.to_excel(writer, index=False, sheet_name="divisions")
        df_groups.to_excel(writer, index=False, sheet_name="groups")
        df_classes.to_excel(writer, index=False, sheet_name="classes")
        df_subclasses.to_excel(writer, index=False, sheet_name="subclasses")
    buf.seek(0)
    return buf.getvalue()

import re

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

    # 1) если уже есть Subclass_code — используем
    if "Subclass_code" in df_db.columns:
        df_db["Subclass_code"] = df_db["Subclass_code"].apply(_normalize_code)
        return df_db

    # 2) если есть колонка как в старом edit-файле
    if "Введите код бизнес-деятельности" in df_db.columns:
        df_db["Subclass_code"] = df_db["Введите код бизнес-деятельности"].apply(_normalize_code)
        return df_db

    # 3) если есть просто Subclass
    if "Subclass" in df_db.columns:
        df_db["Subclass_code"] = df_db["Subclass"].apply(_normalize_code)
        return df_db

    raise ValueError("В shams_edit1.xlsx не найден ключевой столбец (Subclass_code / Subclass / 'Введите код бизнес-деятельности').")



# ==================================================
# ============ STAGE 5 — DB MAPPING =================
# ==================================================
if st.session_state.stage == STAGE_DB_MAPPING:

    st.subheader("Сопоставление столбцов результата и Базы Данных")
    st.caption(
        "Если выбрать «<нет соответствия>», колонка всё равно пойдёт в итоговый файл "
        "и сохранит текущее имя."
    )

    df = st.session_state.df_compare
    if df is None or df.empty:
        st.error("Нет результата сравнения. Вернитесь на шаг сравнения.")
        st.stop()

    # --- страховка: если df_compare посчитан старой логикой (есть *_old/_new) ---
    legacy_cols = [c for c in df.columns if c.endswith("_old") or c.endswith("_new") or c == "diff_columns"]
    if legacy_cols:
        st.warning(
            "Похоже, результат сравнения был посчитан старой логикой (найдены *_old/_new или diff_columns). "
            "Пересчитываю сравнение заново..."
        )
        st.session_state.df_compare = None
        st.session_state.compare_stats = None
        st.session_state.stage = STAGE_COMPARE
        st.rerun()

    # --- формируем список колонок для сопоставления ---
    # По ТЗ: обязательно status + все колонки-логи + новые колонки без соответствия
    cols_to_map = []

    if "status" in df.columns:
        cols_to_map.append("status")

    # все кроме ключа и status
    other = [c for c in df.columns if c not in ("Subclass_code", "status")]

    # (опционально, но полезно) сортировка: сначала логи, потом обычные "новые без пары"
    log_cols = [c for c in other if c.endswith(". Лог изменений")]
    new_cols = [c for c in other if not c.endswith(". Лог изменений")]

    cols_to_map += log_cols + new_cols
    cols_to_map = list(dict.fromkeys(cols_to_map))  # убираем дубли, сохраняя порядок

    with st.expander("Список сопоставленных и новых столбцов", expanded=True):
        st.write(cols_to_map)

    # --- init/normalize mapping ---
    current_map = st.session_state.db_column_mapping or {}
    current_map = {k: v for k, v in current_map.items() if k in cols_to_map}
    for c in cols_to_map:
        current_map.setdefault(c, None)
    st.session_state.db_column_mapping = current_map
    mapping = st.session_state.db_column_mapping

    left, right = st.columns(2)

    for i, col in enumerate(cols_to_map):
        target = left if i % 2 == 0 else right
        with target:
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

    # 1) Загружаем таблицу "БД" (shams_edit1.xlsx)
    db_df = load_db_df()
    if db_df is None or db_df.empty:
        st.error("Файл БД пустой или не загрузился.")
        st.stop()

    # 2) Собираем экспортный df (рядом: столбец результата + столбец из БД)
    export_df = _build_export_df(df_compare, db_df, db_map)

    # 3) Берём уровни (sections/divisions/groups/classes/subclasses) из НОВОГО файла
    try:
        _, df_sections, df_divisions, df_groups, df_classes, df_subclasses = parse_all_sheets_from_bytes(
            st.session_state.shams2_bytes,
            sheets=None
        )
    except Exception as e:
        st.error(f"Не удалось распарсить уровни из shams2: {e}")
        st.stop()

    # 4) Экспорт в Excel (многолистный)
    xlsx_bytes = _to_excel_bytes(
        export_df=export_df,
        df_sections=df_sections,
        df_divisions=df_divisions,
        df_groups=df_groups,
        df_classes=df_classes,
        df_subclasses=df_subclasses,
    )

    st.download_button(
        label="Скачать в excel",
        data=xlsx_bytes,
        file_name="shams_compare_for_review.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад к сопоставлению с БД"):
            st.session_state.stage = STAGE_DB_MAPPING
            st.rerun()

    with col2:
        if st.button("Назад к сравнению"):
            st.session_state.stage = STAGE_COMPARE
            st.rerun()


# ==================================================
# ============ STAGE 6 — DB EXPORT ==================
# ==================================================
# if st.session_state.stage == STAGE_DB_EXPORT:
#
#     st.subheader("Экспорт в Excel")
#
#     if not st.session_state.get("db_mapping_saved"):
#         st.warning("Сначала нажмите «Сохранить сопоставление».")
#         st.stop()
#
#     df = st.session_state.df_compare
#     db_map = st.session_state.db_column_mapping or {}
#
#     db_df = load_db_df()
#
#     export_df = _build_export_df(df, db_df, db_map)
#     xlsx_bytes = _to_excel_bytes(export_df, sheet_name="for_review")
#
#     st.download_button(
#         label="Скачать в excel",
#         data=xlsx_bytes,
#         file_name="shams_compare_for_review.xlsx",
#         mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#     )
#
#     st.markdown("---")
#     if st.button("Назад к сопоставлению с БД"):
#         st.session_state.stage = STAGE_DB_MAPPING
#         st.rerun()