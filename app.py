import streamlit as st
import pandas as pd
import io
from pathlib import Path

from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats


# ===================== CONFIG =====================
st.set_page_config(layout="wide")

BASE_DIR = Path(__file__).resolve().parent
BASE_FILE_PATH = BASE_DIR / "shams.xlsx"

if not BASE_FILE_PATH.exists():
    st.error(f"Файл shams.xlsx не найден: {BASE_FILE_PATH}")
    st.stop()


# ===================== SESSION STATE =====================
DEFAULT_STATE = {
    "activity_tab": "Общее",
    "step": None,
    "new_file": None,
    "selected_columns": None,
    "parsed_old": None,
    "parsed_new": None,
    "compare_result": None,
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

    col1, col2 = st.columns([1, 2])
    with col1:
        st.checkbox("Провайдер разрешает активити группы")
        st.checkbox("Провайдер разрешает активити классы")
        st.checkbox("Можно совмещать в пределах класса", value=True)
        st.checkbox("Можно совмещать классы (с одинаковым типом лицензии)")

    st.markdown("### Источник текущего списка видов деятельности")
    st.write("файл: xls, html, pdf")
    st.caption("актуализирован 09.12.2025")

    with open(BASE_FILE_PATH, "rb") as f:
        st.download_button(
            "Скачать",
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
        if st.button("Актуализировать", type="primary"):
            st.session_state.step = 1

    st.divider()
    st.info("Нет данных")


# ==================================================
# ===================== STEP 1 =====================
# ==================================================
@st.dialog("Укажите новый источник")
def dialog_upload_file():

    uploaded = st.file_uploader(
        "Перетащите сюда файл или загрузите",
        type=["xlsx"],
        key="upload_new_source"
    )

    # ✅ фиксируем файл в session_state
    if uploaded is not None:
        st.session_state.new_file = uploaded

    c1, c2 = st.columns(2)

    with c1:
        if st.button("Отменить"):
            st.session_state.step = None

    with c2:
        # ✅ кнопка активна, если файл реально есть
        if st.button(
            "Применить",
            disabled=st.session_state.new_file is None
        ):
            st.session_state.step = 2



if st.session_state.step == 1:
    dialog_upload_file()


# ==================================================
# ===================== STEP 2 =====================
# ==================================================
@st.dialog("Выберите какие данные из нового источника представляют для вас интерес")
def dialog_select_columns():
    df_preview = pd.read_excel(st.session_state.new_file)

    selected = st.multiselect(
        "Столбцы нового источника",
        df_preview.columns.tolist(),
        default=df_preview.columns.tolist()
    )

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Отменить"):
            st.session_state.step = None

    with c2:
        if st.button("Применить"):
            st.session_state.selected_columns = selected
            st.session_state.step = 3


if st.session_state.step == 2:
    dialog_select_columns()


# ==================================================
# ===================== STEP 3 =====================
# ==================================================
@st.dialog("Сравнение старого и нового источника")
def dialog_compare_sources():
    # --- старый файл ---
    with open(BASE_FILE_PATH, "rb") as f:
        old_bytes = f.read()

    old_xls = pd.ExcelFile(io.BytesIO(old_bytes))
    df_old_full, *_ = parse_all_sheets_from_bytes(old_bytes, sheets=old_xls.sheet_names)

    # --- новый файл ---
    new_bytes = st.session_state.new_file.read()
    new_xls = pd.ExcelFile(io.BytesIO(new_bytes))
    df_new_full, *_ = parse_all_sheets_from_bytes(new_bytes, sheets=new_xls.sheet_names)

    # --- фильтрация столбцов ---
    df_new_full = df_new_full[st.session_state.selected_columns]

    # --- сравнение ---
    df_compare = compare_shams(df_old_full, df_new_full)
    stats_df = comparison_stats(df_compare)

    st.session_state.parsed_old = df_old_full
    st.session_state.parsed_new = df_new_full
    st.session_state.compare_result = df_compare
    st.session_state.compare_stats = stats_df

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Отменить"):
            st.session_state.step = None
    with c2:
        if st.button("Продолжить"):
            st.session_state.step = 4


if st.session_state.step == 3:
    dialog_compare_sources()


# ==================================================
# ===================== STEP 4 =====================
# ==================================================
@st.dialog("Статистика сравнения")
def dialog_stats():
    stats_df = st.session_state.compare_stats
    stats = dict(zip(stats_df["metric"], stats_df["value"]))

    for k, v in stats.items():
        st.write(f"{k}: {v}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Отменить"):
            st.session_state.step = None
    with c2:
        if st.button("Актуализировать в БД"):
            st.session_state.step = 5


if st.session_state.step == 4:
    dialog_stats()


# ==================================================
# ===================== STEP 5 =====================
# ==================================================
@st.dialog("Сопоставление с Базой Данных")
def dialog_db_mapping():
    DB_MAPPING = {
        "Group": "Группа видов деятельности",
        "Class": "Класс видов деятельности",
        "Subclass": "Код бизнес-деятельности",
        "Description": "Официальное наименование",
        "External Party Approval": "Услуга органа",
        "Authority Name": "Орган",
    }

    for src, db in DB_MAPPING.items():
        st.write(f"{src} → {db}")

    c1, c2 = st.columns(2)
    with c1:
        if st.button("Отменить"):
            st.session_state.step = None
    with c2:
        if st.button("Подготовить таблицу"):
            st.success("Таблица подготовлена")
            st.session_state.step = None


if st.session_state.step == 5:
    dialog_db_mapping()
