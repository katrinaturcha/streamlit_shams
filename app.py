import streamlit as st
import pandas as pd
from pathlib import Path

from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats
from header_log import build_header_change_log_from_bytes


# ===================== CONFIG =====================
st.set_page_config(layout="wide")

BASE_DIR = Path(__file__).resolve().parent
SHAMS_PATH = BASE_DIR / "shams.xlsx"

if not SHAMS_PATH.exists():
    st.error("Файл shams.xlsx не найден")
    st.stop()


# ===================== SESSION STATE =====================
def init_state():
    defaults = {
        "activity_tab": "Список",

        "shams_bytes": None,
        "shams2_bytes": None,

        "headers_old": None,
        "headers_new": None,
        "headers_new_selected": None,

        "column_mapping": None,

        "compare_df": None,
        "compare_stats": None,

        "open_upload_dialog": False,
        "open_header_select_dialog": False,
        "open_mapping_dialog": False,
        "open_stats_dialog": False,
    }
    for k, v in defaults.items():
        st.session_state.setdefault(k, v)


init_state()


# ===================== HELPERS =====================
def load_base_shams():
    if st.session_state.shams_bytes is None:
        with open(SHAMS_PATH, "rb") as f:
            st.session_state.shams_bytes = f.read()


# ===================== SIDEBAR =====================
with st.sidebar:
    st.markdown("### Виды деятельности")
    st.session_state.activity_tab = st.selectbox(
        "",
        ["Общее", "Список"],
        index=0 if st.session_state.activity_tab == "Общее" else 1
    )


# ===================== ОБЩЕЕ =====================
if st.session_state.activity_tab == "Общее":
    st.markdown("## Общее про активити провайдера")

    with open(SHAMS_PATH, "rb") as f:
        st.download_button(
            "Скачать shams.xlsx",
            data=f,
            file_name="shams.xlsx"
        )


# ===================== СПИСОК =====================
if st.session_state.activity_tab == "Список":
    st.markdown("## Список активити провайдера")

    _, _, _, c4 = st.columns([1, 1, 4, 1])
    with c4:
        if st.button("Актуализировать", type="primary"):
            st.session_state.open_upload_dialog = True
            st.rerun()

    st.info("Нет данных")


# ===================== DIALOG 1 — UPLOAD =====================
if st.session_state.open_upload_dialog:

    @st.dialog("Укажите новый источник")
    def upload_dialog():
        uploaded = st.file_uploader(
            "Загрузите файл shams2",
            type=["xlsx"]
        )

        if uploaded is not None:
            st.session_state.shams2_bytes = uploaded.read()

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Отменить"):
                st.session_state.open_upload_dialog = False
                st.rerun()

        with c2:
            if st.button(
                "Применить",
                disabled=st.session_state.shams2_bytes is None
            ):
                st.session_state.open_upload_dialog = False
                st.session_state.open_header_select_dialog = True
                st.rerun()

    upload_dialog()


# ===================== DIALOG 2 — HEADER SELECT =====================
if st.session_state.open_header_select_dialog:

    @st.dialog("Шаг 1 — выбор столбцов нового файла (shams2)")
    def select_headers_dialog():
        load_base_shams()

        h_old, h_new, _ = build_header_change_log_from_bytes(
            st.session_state.shams_bytes,
            st.session_state.shams2_bytes,
            sheets=None
        )

        st.session_state.headers_old = h_old
        st.session_state.headers_new = h_new

        if st.session_state.headers_new_selected is None:
            st.session_state.headers_new_selected = list(h_new)

        st.markdown("### Заголовки нового файла")
        left, right = st.columns(2)

        for i, col in enumerate(h_new):
            target = left if i % 2 == 0 else right
            with target:
                checked = st.checkbox(
                    col,
                    value=col in st.session_state.headers_new_selected,
                    key=f"chk_{col}"
                )

            if checked and col not in st.session_state.headers_new_selected:
                st.session_state.headers_new_selected.append(col)
            if not checked and col in st.session_state.headers_new_selected:
                st.session_state.headers_new_selected.remove(col)

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Отменить"):
                st.session_state.open_header_select_dialog = False
                st.rerun()

        with c2:
            if st.button(
                "Перейти к сопоставлению",
                disabled=len(st.session_state.headers_new_selected) == 0
            ):
                st.session_state.open_header_select_dialog = False
                st.session_state.open_mapping_dialog = True
                st.rerun()

    select_headers_dialog()


# ===================== DIALOG 3 — MAPPING =====================
if st.session_state.open_mapping_dialog:

    @st.dialog("Шаг 2 — ручное сопоставление столбцов")
    def mapping_dialog():
        h_old = st.session_state.headers_old
        h_new = st.session_state.headers_new_selected

        if st.session_state.column_mapping is None:
            st.session_state.column_mapping = {c: None for c in h_new}

        for col_new in h_new:
            opts = ["<нет соответствия>"] + h_old
            current = st.session_state.column_mapping.get(col_new)
            idx = opts.index(current) if current in opts else 0

            mapped = st.selectbox(
                f"{col_new} →",
                opts,
                index=idx,
                key=f"map_{col_new}"
            )

            st.session_state.column_mapping[col_new] = (
                None if mapped == "<нет соответствия>" else mapped
            )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Отменить"):
                st.session_state.open_mapping_dialog = False
                st.rerun()

        with c2:
            if st.button("Запустить сравнение"):
                st.session_state.open_mapping_dialog = False
                st.session_state.open_stats_dialog = True
                st.rerun()

    mapping_dialog()


# ===================== DIALOG 4 — STATS =====================
if st.session_state.open_stats_dialog:

    @st.dialog("Сравнение и статистика")
    def stats_dialog():
        load_base_shams()

        df_old, *_ = parse_all_sheets_from_bytes(st.session_state.shams_bytes, sheets=None)
        df_new, *_ = parse_all_sheets_from_bytes(st.session_state.shams2_bytes, sheets=None)

        df_compare = compare_shams(df_old, df_new)
        stats = comparison_stats(df_compare)

        st.dataframe(stats, use_container_width=True)

        if st.button("Готово"):
            st.session_state.open_stats_dialog = False
            st.rerun()

    stats_dialog()
