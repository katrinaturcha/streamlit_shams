
import streamlit as st
import pandas as pd
from pathlib import Path

from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats



# ===================== CONFIG =====================
st.set_page_config(layout="wide")

BASE_FILE_PATH = Path("shams.xlsx")

# ===================== SESSION STATE =====================
DEFAULT_STATE = {
    "activity_tab": "Общее",
    "step": None,
    "new_file": None,
    "parsed_old": None,
    "parsed_new": None,
    "selected_columns": None,
    "column_mapping_old_new": None,
    "compare_result": None,
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
if st.session_state.step == 1:
    with st.modal("Укажите новый источник"):
        uploaded = st.file_uploader(
            "Перетащите сюда файл или загрузите",
            type=["xlsx"]
        )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Отменить"):
                st.session_state.step = None

        with c2:
            if uploaded and st.button("Применить"):
                st.session_state.new_file = uploaded
                st.session_state.step = 2


# ==================================================
# ===================== STEP 2 =====================
# ==================================================
if st.session_state.step == 2:
    with st.modal("Выберите какие данные из нового источника представляют для вас интерес"):
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


# ==================================================
# ===================== STEP 3 =====================
# ==================================================
if st.session_state.step == 3:
    with st.modal("Установи соответствие данных нового источника со старым источником"):
        old_cols = [
            "Division",
            "Group",
            "Class",
            "Subclass",
            "Description",
            "External Party Approval",
            "Authority Name",
        ]

        new_cols = st.session_state.selected_columns

        mapping = {}
        for col in old_cols:
            mapping[col] = st.selectbox(
                f"{col} ←",
                [""] + new_cols
            )

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Отменить"):
                st.session_state.step = None

        with c2:
            if st.button("Сравнить"):
                # === 1. Читаем старый файл (shams.xlsx) ===
                with open(BASE_FILE_PATH, "rb") as f:
                    old_bytes = f.read()

                df_old_full, *_ = parse_all_sheets_from_bytes(
                    old_bytes,
                    sheets=["Sheet1"]  # при необходимости заменить на реальные листы
                )

                # === 2. Читаем новый файл (shams2.xlsx) ===
                new_bytes = st.session_state.new_file.read()

                df_new_full, *_ = parse_all_sheets_from_bytes(
                    new_bytes,
                    sheets=["Sheet1"]
                )

                # === 3. Оставляем только выбранные пользователем столбцы ===
                selected_cols = st.session_state.selected_columns
                df_new_full = df_new_full[selected_cols]

                # === 4. Сравниваем старый и новый источники ===
                df_compare = compare_shams(
                    df_old=df_old_full,
                    df_new=df_new_full,
                )

                # === 5. Считаем статистику ===
                stats_df = comparison_stats(df_compare)

                # === 6. Сохраняем в session_state ===
                st.session_state.parsed_old = df_old_full
                st.session_state.parsed_new = df_new_full
                st.session_state.compare_result = df_compare
                st.session_state.compare_stats = stats_df

                st.session_state.step = 4

# ==================================================
# ===================== STEP 4 =====================
# ==================================================
if st.session_state.step == 4:
    with st.modal("Статистика сравнения"):
        stats = st.session_state.compare_result["stats"]

        st.write(f"Количество активити в старом файле: {stats['old']}")
        st.write(f"Количество активити в новом файле: {stats['new']}")
        st.write(f"Добавлено активити: {stats['added']}")
        st.write(f"Удалено активити: {stats['deleted']}")
        st.write(f"Внесены изменения: {stats['changed']}")
        st.write(f"Остались без изменений: {stats['unchanged']}")

        c1, c2 = st.columns(2)
        with c1:
            if st.button("Отменить"):
                st.session_state.step = None

        with c2:
            if st.button("Актуализировать в БД"):
                st.session_state.step = 5


# ==================================================
# ===================== STEP 5 =====================
# ==================================================
if st.session_state.step == 5:
    with st.modal("Установи соответствие данных нового источника с данными в Базе Данных"):
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
            if st.button("Подготовить таблицу для работы"):
                st.success("Таблица подготовлена")
                st.session_state.step = None
