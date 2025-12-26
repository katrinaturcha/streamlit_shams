import streamlit as st
import pandas as pd
from pathlib import Path

from header_log import build_header_change_log_from_bytes
from shams_parser import parse_all_sheets_from_bytes
from compare import compare_shams, comparison_stats

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

        "stage": "upload",  # upload | select_headers
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
            st.session_state.stage = "mapping"  # следующий этап (сопоставление)
            st.rerun()


if st.session_state.stage == "mapping":

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

        selected = st.selectbox(
            f"Соответствие для `{col_new}`",
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
            st.session_state.stage = "select_headers"
            st.rerun()

    with col2:
        if st.button("Подтвердить сопоставление"):
            st.session_state.stage = "compare"
            st.rerun()

if st.session_state.stage == "compare":

    st.subheader("Статистика сравнения")

    # === 1. Парсинг обоих файлов (ЛОГИКА СОХРАНЕНА) ===
    data_old = st.session_state.shams_bytes
    data_new = st.session_state.shams2_bytes

    (
        df_full_old,
        df_sec_old,
        df_div_old,
        df_grp_old,
        df_cls_old,
        df_sub_old,
    ) = parse_all_sheets_from_bytes(data_old, sheets=None)

    (
        df_full_new,
        df_sec_new,
        df_div_new,
        df_grp_new,
        df_cls_new,
        df_sub_new,
    ) = parse_all_sheets_from_bytes(data_new, sheets=None)

    # сохраняем — пригодится для БД и экспорта
    st.session_state["df_full_old"] = df_full_old
    st.session_state["df_full_new"] = df_full_new
    st.session_state["dfs_old"] = (df_sec_old, df_div_old, df_grp_old, df_cls_old, df_sub_old)
    st.session_state["dfs_new"] = (df_sec_new, df_div_new, df_grp_new, df_cls_new, df_sub_new)

    # === 2. Сравнение ===
    df_compare = compare_shams(df_full_old, df_full_new)
    st.session_state["df_compare"] = df_compare

    # === 3. Статистика (КЛЮЧЕВОЙ UI) ===
    stats_df = comparison_stats(df_compare)
    st.session_state["compare_stats"] = stats_df

    # преобразуем в словарь для красивого вывода
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

    st.markdown("---")

    # === 4. Кнопки управления ===
    col1, col2 = st.columns(2)

    with col1:
        if st.button("Отменить"):
            st.session_state.stage = "mapping"
            st.rerun()

    with col2:
        if st.button("Актуализировать в БД", type="primary"):
            st.session_state.stage = "db_update"
            st.rerun()
