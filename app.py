import streamlit as st
import pandas as pd
import io
from pathlib import Path

from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats
from header_log import build_header_change_log_from_bytes


# ===================== CONFIG =====================
st.set_page_config(layout="wide")

BASE_DIR = Path(__file__).resolve().parent
SHAMS_PATH = BASE_DIR / "shams.xlsx"

if not SHAMS_PATH.exists():
    st.error("Файл shams.xlsx не найден в проекте")
    st.stop()


# ===================== SESSION STATE =====================
DEFAULT_STATE = {
    "activity_tab": "Список",
    "step": None,

    "shams_bytes": None,
    "shams2_bytes": None,

    "headers_old": None,
    "headers_new": None,
    "header_log": None,

    "column_mapping": None,

    "df_old_parsed": None,
    "df_new_parsed": None,

    "compare_df": None,
    "compare_stats": None,
}

for k, v in DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ===================== SIDEBAR =====================
with st.sidebar:
    st.markdown("### Виды деятельности")
    st.session_state.activity_tab = st.selectbox(
        "",
        ["Общее", "Список"],
        index=0 if st.session_state.activity_tab == "Общее" else 1
    )


# ==================================================
# ===================== ОБЩЕЕ ======================
# ==================================================
if st.session_state.activity_tab == "Общее":
    st.markdown("## Общее про активити провайдера")

    st.markdown("### Источник текущего списка видов деятельности")

    with open(SHAMS_PATH, "rb") as f:
        st.download_button(
            "Скачать shams.xlsx",
            data=f,
            file_name="shams.xlsx"
        )


# ==================================================
# ===================== СПИСОК =====================
# ==================================================
if st.session_state.activity_tab == "Список":
    st.markdown("## Список активити провайдера")

    if st.button("Актуализировать", type="primary"):
        st.session_state.step = 1


# ==================================================
# ===================== STEP 1 =====================
# ==================================================
def apply_new_source():
    st.session_state.step = 2


@st.dialog("Укажите новый источник")
def step_1_upload():

    uploaded = st.file_uploader(
        "Загрузите новый файл (shams2)",
        type=["xlsx"],
        key="upload_shams2"
    )

    if uploaded is not None:
        st.session_state.shams2_bytes = uploaded.read()

    col1, col2 = st.columns(2)

    with col1:
        st.button("Отменить", on_click=lambda: st.session_state.update(step=None))

    with col2:
        st.button(
            "Применить",
            disabled="shams2_bytes" not in st.session_state,
            on_click=apply_new_source
        )



if st.session_state.step == 1:
    step_1_upload()


# ==================================================
# ===================== STEP 2 =====================
# ==================================================
@st.dialog("Шаг 1 — автоматическое сравнение столбцов")
def step_2_auto_header_compare():

    headers_old, headers_new, log_df = build_header_change_log_from_bytes(
        st.session_state.shams_bytes,
        st.session_state.shams2_bytes,
        sheets=None
    )

    st.session_state.headers_old = headers_old
    st.session_state.headers_new = headers_new
    st.session_state.header_log = log_df

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("**Заголовки старого файла (shams):**")
        st.write(headers_old)
    with col2:
        st.markdown("**Заголовки нового файла (shams2):**")
        st.write(headers_new)

    st.markdown("**Лог изменений столбцов:**")
    st.dataframe(log_df, use_container_width=True)

    if st.button("Перейти к сопоставлению"):
        st.session_state.step = 3


if st.session_state.step == 2:
    step_2_auto_header_compare()


# ==================================================
# ===================== STEP 3 =====================
# ==================================================
@st.dialog("Шаг 2 — ручное сопоставление столбцов")
def step_3_manual_mapping():

    if st.session_state.column_mapping is None:
        st.session_state.column_mapping = {
            col: None for col in st.session_state.headers_new
        }

    mapping = st.session_state.column_mapping

    st.info(
        "Для каждого столбца из НОВОГО файла выберите соответствие в СТАРОМ файле "
        "или оставьте пустым."
    )

    for col_new in st.session_state.headers_new:
        selected = st.selectbox(
            f"{col_new} →",
            ["<нет соответствия>"] + st.session_state.headers_old,
            index=(
                st.session_state.headers_old.index(mapping[col_new]) + 1
                if mapping[col_new] in st.session_state.headers_old
                else 0
            ),
            key=f"map_{col_new}"
        )
        mapping[col_new] = None if selected == "<нет соответствия>" else selected

    st.session_state.column_mapping = mapping

    if st.button("Запустить сравнение данных"):
        st.session_state.step = 4


if st.session_state.step == 3:
    step_3_manual_mapping()


# ==================================================
# ===================== STEP 4 =====================
# ==================================================
@st.dialog("Сравнение данных и статистика")
def step_4_parse_and_compare():

    # парсинг
    df_old, *_ = parse_all_sheets_from_bytes(st.session_state.shams_bytes, sheets=None)
    df_new, *_ = parse_all_sheets_from_bytes(st.session_state.shams2_bytes, sheets=None)

    # сравнение
    compare_df = compare_shams(df_old, df_new)
    stats_df = comparison_stats(compare_df)

    st.session_state.compare_df = compare_df
    st.session_state.compare_stats = stats_df

    st.markdown("### Статистика")
    st.dataframe(stats_df, use_container_width=True)

    if st.button("Готово"):
        st.session_state.step = None


if st.session_state.step == 4:
    step_4_parse_and_compare()
