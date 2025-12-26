import streamlit as st
from pathlib import Path
import pandas as pd

from header_log import build_header_change_log_from_bytes
from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats
from DB import DB_COLUMNS

STAGE_UPLOAD = "upload"
STAGE_SELECT_HEADERS = "select_headers"
STAGE_MAPPING = "mapping"
STAGE_COMPARE = "compare"
STAGE_DB_MAPPING = "db_mapping"
STAGE_DB_EXPORT = "db_export"
STAGE_JOIN_EDIT = "join_edit"



# ================= CONFIG =================
st.set_page_config(layout="wide")

BASE_DIR = Path(__file__).resolve().parent
SHAMS_PATH = BASE_DIR / "shams.xlsx"

if not SHAMS_PATH.exists():
    st.error("Файл shams.xlsx не найден")
    st.stop()


# ================= SESSION STATE =================
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
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


init_state()


# ================= HELPERS =================
def load_shams():
    if st.session_state.shams_bytes is None:
        with open(SHAMS_PATH, "rb") as f:
            st.session_state.shams_bytes = f.read()


# ================= UI =================
st.title("Список активити провайдера")

st.markdown("---")

# ==================================================
# =============== STAGE 1 — UPLOAD =================
# ==================================================
if st.session_state.stage == "upload":

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
            # === запускаем header log ===
            load_shams()

            h_old, h_new, _ = build_header_change_log_from_bytes(
                st.session_state.shams_bytes,
                st.session_state.shams2_bytes,
                sheets=None
            )

            st.session_state.headers_old = h_old
            st.session_state.headers_new = h_new
            st.session_state.headers_new_selected = list(h_new)

            st.session_state.stage = "select_headers"
            st.rerun()


# ==================================================
# =========== STAGE 2 — SELECT HEADERS =============
# ==================================================
if st.session_state.stage == "select_headers":

    st.subheader("Шаг 1 — выбор столбцов нового файла (shams2)")
    st.caption("Отметьте столбцы, которые пойдут в сопоставление")

    headers = st.session_state.headers_new or []
    prev_selected = st.session_state.headers_new_selected or []

    left, right = st.columns(2)

    # собираем выбранные в новый список, НЕ меняя prev_selected в процессе рендера
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

    # фиксируем результат выбора один раз
    st.session_state.headers_new_selected = temp_selected

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад"):
            st.session_state.stage = "upload"
            st.rerun()

    with col2:
        if st.button(
            "Перейти к сопоставлению",
            disabled=len(temp_selected) == 0
        ):
            st.session_state.stage = STAGE_MAPPING
            st.rerun()


if st.session_state.stage == STAGE_MAPPING:

    # защита от отсутствия ключа
    if "column_mapping" not in st.session_state:
        st.session_state.column_mapping = None

    st.subheader("Шаг 2 — ручное сопоставление столбцов")
    st.caption(
        "Для каждого выбранного столбца из НОВОГО файла выберите соответствующий столбец "
        "в СТАРОМ файле. Если соответствия нет — оставьте «<нет соответствия>»."
    )

    headers_old = st.session_state.headers_old or []
    headers_new_selected = st.session_state.headers_new_selected or []

    # инициализация mapping
    if st.session_state.column_mapping is None:
        st.session_state.column_mapping = {col: None for col in headers_new_selected}
    else:
        current = dict(st.session_state.column_mapping)
        current = {k: v for k, v in current.items() if k in headers_new_selected}
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

        selected = st.selectbox( f"Соответствие для {col_new}", options=options, index=index, key=f"map_{col_new}")
        mapping[col_new] = None if selected == "<нет соответствия>" else selected

    st.session_state.column_mapping = mapping

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад"):
            st.session_state.stage = "select_headers"
            st.rerun()

    with col2:
        if st.button("Подтвердить сопоставление"):
            st.session_state.stage = "compare"
            st.rerun()

if st.session_state.stage == STAGE_COMPARE:

    st.subheader("Статистика сравнения")

    # парсим ТОЛЬКО если ещё не считали
    if st.session_state.df_compare is None:

        data_old = st.session_state.shams_bytes
        data_new = st.session_state.shams2_bytes

        df_full_old, *_ = parse_all_sheets_from_bytes(data_old, sheets=None)
        df_full_new, *_ = parse_all_sheets_from_bytes(data_new, sheets=None)

        df_compare = compare_shams(
            df_full_old,
            df_full_new,
            st.session_state.column_mapping
        )
        st.session_state.df_compare = df_compare
        st.session_state.compare_stats = comparison_stats(df_compare)

    stats_df = st.session_state.compare_stats
    stats = dict(zip(stats_df["metric"], stats_df["value"]))

    st.markdown(
        f"""
        **Количество активити в старом файле:** {stats['Количество строк в старом файле']}  
        **Количество активити в новом файле:** {stats['Количество строк в новом файле']}  
        **Добавлено активити:** {stats['Добавлено']}  
        **Удалено активити:** {stats['Удалено']}  
        **Внесены изменения:** {stats['Изменено (по английским описаниям)']}  
        **Остались без изменений:** {stats['Не изменено']}  
        """
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_MAPPING
            st.rerun()

    with col2:
        if st.button("Актуализировать в БД", type="primary"):
            st.session_state.stage = STAGE_DB_MAPPING
            st.rerun()


if st.session_state.stage == STAGE_DB_MAPPING:

    st.subheader("Сопоставление столбцов нового источника и Базы Данных")
    st.caption("Выберите, в какой столбец БД должен попасть каждый столбец результата")

    df = st.session_state.df_compare
    source_columns = list(df.columns)

    if st.session_state.db_column_mapping is None:
        st.session_state.db_column_mapping = {c: None for c in source_columns}

    mapping = st.session_state.db_column_mapping

    left, right = st.columns(2)

    for i, col in enumerate(source_columns):
        target = left if i % 2 == 0 else right
        with target:
            selected = st.selectbox(
                col,
                options=["<не использовать>"] + DB_COLUMNS,
                index=(
                    DB_COLUMNS.index(mapping[col]) + 1
                    if mapping[col] in DB_COLUMNS
                    else 0
                ),
                key=f"db_map_{col}"
            )
        mapping[col] = None if selected == "<не использовать>" else selected

    st.session_state.db_column_mapping = mapping

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_COMPARE
            st.rerun()

    with col2:
        if st.button("Добавить предыдущий обработанный файл (shams_edit.xlsx)"):
            st.session_state.stage = STAGE_JOIN_EDIT
            st.rerun()


if st.session_state.stage == STAGE_JOIN_EDIT:

    st.subheader("Присоединение предыдущего обработанного файла")

    uploaded = st.file_uploader(
        "Загрузите shams_edit.xlsx",
        type=["xlsx"]
    )

    if uploaded is None:
        st.stop()

    df_edit = pd.read_excel(uploaded)

    st.markdown("### Выберите столбцы для присоединения")

    edit_cols = list(df_edit.columns)
    selected_cols = []

    left, right = st.columns(2)

    for i, col in enumerate(edit_cols):
        target = left if i % 2 == 0 else right
        with target:
            if st.checkbox(col, key=f"edit_{col}"):
                selected_cols.append(col)

    st.markdown("---")

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Назад"):
            st.session_state.stage = STAGE_DB_MAPPING
            st.rerun()

    with col2:
        if st.button("Присоединить выбранные столбцы", disabled=len(selected_cols) == 0):

            from compare import join_with_edit

            st.session_state.df_compare = join_with_edit(
                st.session_state.df_compare,
                df_edit,
                selected_cols
            )

            st.session_state.stage = STAGE_DB_EXPORT
            st.rerun()
