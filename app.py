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
    st.error("Файл shams.xlsx не найден в проекте")
    st.stop()


# ===================== SESSION STATE =====================
DEFAULT_STATE = {
    "activity_tab": "Список",
    "step": None,

    "shams_bytes": None,

    "headers_old": None,
    "headers_new": None,
    "header_log": None,

    "headers_new_selected": None,     # <--- ВАЖНО: выбор чекбоксов
    "column_mapping": None,

    "compare_df": None,
    "compare_stats": None,
}

for k, v in DEFAULT_STATE.items():
    if k not in st.session_state:
        st.session_state[k] = v


# ===================== HELPERS =====================
def set_step(n):
    st.session_state.step = n


def cancel_steps():
    st.session_state.step = None


def load_base_shams_bytes():
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


# ==================================================
# ===================== ОБЩЕЕ ======================
# ==================================================
if st.session_state.activity_tab == "Общее":
    st.markdown("## Общее про активити провайдера")

    st.markdown("### Источник текущего списка видов деятельности")
    st.write("файл: xls, html, pdf")
    st.caption("актуализирован 09.12.2025")

    with open(SHAMS_PATH, "rb") as f:
        st.download_button(
            "Скачать shams.xlsx",
            data=f,
            file_name="shams.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        )


# ==================================================
# ===================== СПИСОК =====================
# ==================================================
if st.session_state.activity_tab == "Список":
    st.markdown("## Список активити провайдера")

    c1, c2, c3, c4 = st.columns([1, 1, 4, 1])
    with c1:
        st.button("Импорт", disabled=True)
    with c2:
        st.button("Экспорт", disabled=True)
    with c4:
        st.button("Актуализировать", type="primary", on_click=lambda: set_step(1))

    st.divider()
    st.info("Нет данных")


# ==================================================
# ===================== STEP 1 =====================
# ==================================================
@st.dialog("Укажите новый источник")
def step_1_upload():

    uploaded = st.file_uploader(
        "Загрузите новый файл (shams2)",
        type=["xlsx"],
        key="upload_shams2"
    )

    # ✅ читаем файл ТОЛЬКО ОДИН РАЗ
    if uploaded is not None and st.session_state.get("shams2_bytes") is None:
        st.session_state.shams2_bytes = uploaded.read()

    col1, col2 = st.columns(2)

    with col1:
        st.button("Отменить", on_click=cancel_steps)

    with col2:
        st.button(
            "Применить",
            disabled=st.session_state.get("shams2_bytes") is None,
            on_click=lambda: set_step(2)
        )


if st.session_state.step == 1:
    step_1_upload()


# ==================================================
# ===================== STEP 2 =====================
# ==================================================
@st.dialog("Шаг 1 — выбор столбцов нового файла (shams2)")
def step_2_select_new_headers():
    load_base_shams_bytes()

    headers_old, headers_new, log_df = build_header_change_log_from_bytes(
        st.session_state.shams_bytes,
        st.session_state.shams2_bytes,
        sheets=None
    )

    st.session_state.headers_old = headers_old
    st.session_state.headers_new = headers_new
    st.session_state.header_log = log_df

    # -----------------------------
    # ВЫВОД старого файла и лога — УБРАН (по твоей просьбе)
    # -----------------------------
    # st.markdown("### Заголовки старого файла (shams):")
    # st.write(headers_old)
    #
    # st.markdown("### Лог изменений столбцов:")
    # st.dataframe(log_df, use_container_width=True)

    st.markdown("### Заголовки нового файла (shams2)")
    st.caption("Отметьте галочками столбцы, которые пойдут в сопоставление.")

    # Инициализация выбранных (по умолчанию: все)
    if st.session_state.headers_new_selected is None:
        st.session_state.headers_new_selected = list(headers_new)

    if st.session_state.headers_new_selected is None:
        st.session_state.headers_new_selected = list(headers_new)

    left, right = st.columns(2)

    for i, col in enumerate(headers_new):
        target_col = left if i % 2 == 0 else right

        with target_col:
            checked = st.checkbox(
                col,
                value=col in st.session_state.headers_new_selected,
                key=f"chk_new_{col}"
            )

        # 🔑 обновляем session_state сразу
        if checked and col not in st.session_state.headers_new_selected:
            st.session_state.headers_new_selected.append(col)

        if not checked and col in st.session_state.headers_new_selected:
            st.session_state.headers_new_selected.remove(col)


    c1, c2 = st.columns(2)
    with c1:
        st.button("Отменить", on_click=cancel_steps)

    with c2:
        st.button(
            "Перейти к сопоставлению",
            disabled=len(st.session_state.headers_new_selected) == 0,
            on_click=lambda: set_step(3)
        )


if st.session_state.step == 2:
    step_2_select_new_headers()


# ==================================================
# ===================== STEP 3 =====================
# ==================================================
@st.dialog("Шаг 2 — ручное сопоставление столбцов")
def step_3_manual_mapping():
    headers_old = st.session_state.headers_old or []
    headers_new_selected = st.session_state.headers_new_selected or []

    # ВАЖНО: маппинг создаём/храним ТОЛЬКО для выбранных столбцов нового файла
    if st.session_state.column_mapping is None:
        st.session_state.column_mapping = {col: None for col in headers_new_selected}
    else:
        # если пользователь поменял галочки на шаге 2 — синхронизируем mapping
        mapping = dict(st.session_state.column_mapping)
        mapping = {k: v for k, v in mapping.items() if k in headers_new_selected}
        for k in headers_new_selected:
            mapping.setdefault(k, None)
        st.session_state.column_mapping = mapping

    mapping = st.session_state.column_mapping

    st.info(
        "Для каждого выбранного столбца из НОВОГО файла выберите соответствующий столбец в СТАРОМ файле.\n"
        "Если пары нет — оставьте <нет соответствия>."
    )

    for col_new in headers_new_selected:
        st.write(f"**{col_new} →**")

        opts = ["<нет соответствия>"] + headers_old
        current = mapping.get(col_new)

        if current in headers_old:
            idx = headers_old.index(current) + 1
        else:
            idx = 0

        mapped_col = st.selectbox(
            f"Выберите соответствующий столбец для `{col_new}`",
            options=opts,
            index=idx,
            key=f"map_{col_new}"
        )

        mapping[col_new] = None if mapped_col == "<нет соответствия>" else mapped_col

    st.session_state.column_mapping = mapping

    c1, c2 = st.columns(2)
    with c1:
        st.button("Отменить", on_click=cancel_steps)

    with c2:
        st.button("Запустить сравнение данных", on_click=lambda: set_step(4))


if st.session_state.step == 3:
    step_3_manual_mapping()


# ==================================================
# ===================== STEP 4 =====================
# ==================================================
@st.dialog("Сравнение данных и статистика")
def step_4_parse_and_compare():
    load_base_shams_bytes()

    # Парсим оба сырых файла
    df_old_full, *_ = parse_all_sheets_from_bytes(st.session_state.shams_bytes, sheets=None)
    df_new_full, *_ = parse_all_sheets_from_bytes(st.session_state.shams2_bytes, sheets=None)

    # Сравнение (как в compare.py)
    df_compare = compare_shams(df_old_full, df_new_full)
    stats_df = comparison_stats(df_compare)

    st.session_state.compare_df = df_compare
    st.session_state.compare_stats = stats_df

    st.markdown("### Статистика")
    st.dataframe(stats_df, use_container_width=True)

    c1, c2 = st.columns(2)
    with c1:
        st.button("Отменить", on_click=cancel_steps)
    with c2:
        st.button("Готово", on_click=cancel_steps)


if st.session_state.step == 4:
    step_4_parse_and_compare()
