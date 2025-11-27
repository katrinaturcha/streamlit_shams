import streamlit as st
import pandas as pd
import io

from header_log import build_header_change_log_from_bytes
from shams_parser import parse_all_sheets_from_bytes, make_processed_excel_bytes
from compare import compare_shams, comparison_stats, join_with_edit


SHEETS = ["2 исходный часть 1", "2 исходный часть 2", "2 исходный часть 3"]


st.set_page_config(page_title="Shams Activity Comparator", layout="wide")

st.title("Streamlit Shams — сравнение версий файла провайдера")


# =========================
# ШАГ 1. Загрузка файлов
# =========================

st.header("Шаг 1. Загрузите два файла провайдера")

col1, col2 = st.columns(2)
with col1:
    file_old = st.file_uploader("Старый файл (shams)", type=["xlsx"], key="file_old")
with col2:
    file_new = st.file_uploader("Новый файл (shams2)", type=["xlsx"], key="file_new")

if file_old and file_new:
    data_old = file_old.read()
    data_new = file_new.read()

    st.subheader("1.1. Сравнение структуры столбцов")

    headers_old, headers_new, df_log = build_header_change_log_from_bytes(data_old, data_new, SHEETS)

    c1, c2 = st.columns(2)
    with c1:
        st.markdown("**Заголовки старого файла (shams):**")
        st.write(headers_old)
    with c2:
        st.markdown("**Заголовки нового файла (shams2):**")
        st.write(headers_new)

    st.markdown("**Лог изменений столбцов:**")
    st.dataframe(df_log, use_container_width=True)

    st.info(
        "Кнопка ниже логически считает новый файл 'новым исходным файлом провайдера'.\n"
    )

    if st.button("Обновить изначальный файл провайдера (логически)"):
        st.session_state["baseline_set"] = True
        st.success("Новый файл отмечен как актуальный эталон в этой сессии.")

    st.markdown("---")

    # =========================
    # ШАГ 2. Обработка файлов
    # =========================

    st.header("Шаг 2. Обработка и сравнение содержимого")

    if st.button("Обработать файлы"):
        # парсим оба файла
        st.write("Обработка старого файла...")
        df_full_old, df_sec_old, df_div_old, df_grp_old, df_cls_old, df_sub_old = parse_all_sheets_from_bytes(
            data_old, SHEETS
        )
        st.write("Обработка нового файла...")
        df_full_new, df_sec_new, df_div_new, df_grp_new, df_cls_new, df_sub_new = parse_all_sheets_from_bytes(
            data_new, SHEETS
        )

        st.session_state["df_full_old"] = df_full_old
        st.session_state["df_full_new"] = df_full_new
        st.session_state["dfs_old"] = (df_sec_old, df_div_old, df_grp_old, df_cls_old, df_sub_old)
        st.session_state["dfs_new"] = (df_sec_new, df_div_new, df_grp_new, df_cls_new, df_sub_new)

        st.success("Файлы успешно обработаны. Ниже — сравнение.")

    # если уже обработано
    if "df_full_old" in st.session_state and "df_full_new" in st.session_state:
        df_full_old = st.session_state["df_full_old"]
        df_full_new = st.session_state["df_full_new"]

        # st.subheader("2.1. Сравнение df_full_old и df_full_new")

        # df_compare = compare_shams(df_full_old, df_full_new)
        # st.session_state["df_compare"] = df_compare
        #
        # st.dataframe(df_compare, use_container_width=True)
        df_compare = compare_shams(df_full_old, df_full_new)
        st.session_state["df_compare"] = df_compare

        # -----------------------------------------
        # 1) Показываем отдельные таблицы иерархии
        # -----------------------------------------

        st.subheader("2.1. Отдельные таблицы иерархии (объединённые старый + новый)")

        # достаём иерархию
        df_sec_old, df_div_old, df_grp_old, df_cls_old, df_sub_old = st.session_state["dfs_old"]
        df_sec_new, df_div_new, df_grp_new, df_cls_new, df_sub_new = st.session_state["dfs_new"]


        # =======================================
        # 1. Универсальная функция объединения
        # =======================================
        def merge_unique(df_old, df_new, key):
            """
            Объединяет старую и новую таблицу по ключу.
            Если код есть в обеих — берём новую запись.
            """
            df_old = df_old.copy()
            df_new = df_new.copy()

            df_old["source"] = "old"
            df_new["source"] = "new"

            # соединяем
            df = pd.concat([df_old, df_new], ignore_index=True)

            # сортируем так, чтобы новые были последними — overwrite
            df = df.sort_values(["source"], ascending=True)

            # убираем дубликаты по ключу, оставляя новую запись
            df_unique = df.drop_duplicates(subset=[key], keep="last")

            # удаляем служебный столбец
            df_unique = df_unique.drop(columns=["source"])

            # сортировка по ключу для красоты
            df_unique = df_unique.sort_values(key)

            return df_unique.reset_index(drop=True)


        # =======================================
        # 2. Объединяем все иерархии
        # =======================================
        df_sec_combined = merge_unique(df_sec_old, df_sec_new, "Section")
        df_div_combined = merge_unique(df_div_old, df_div_new, "Division")
        df_grp_combined = merge_unique(df_grp_old, df_grp_new, "Group")
        df_cls_combined = merge_unique(df_cls_old, df_cls_new, "Class")

        # =======================================
        # 3. Выводим в Streamlit
        # =======================================
        tab1, tab2, tab3, tab4 = st.tabs(["Sections", "Divisions", "Groups", "Classes"])

        with tab1:
            st.dataframe(df_sec_combined, use_container_width=True)

        with tab2:
            st.dataframe(df_div_combined, use_container_width=True)

        with tab3:
            st.dataframe(df_grp_combined, use_container_width=True)

        with tab4:
            st.dataframe(df_cls_combined, use_container_width=True)

        # Сохраняем в session_state для экспорта
        st.session_state["dfs_combined"] = (
            df_sec_combined,
            df_div_combined,
            df_grp_combined,
            df_cls_combined,
        )

        # -----------------------------------------
        # 2) Фильтрация сравнения
        # -----------------------------------------

        st.subheader("2.2. Сравнение df_full_old и df_full_new (укороченный вид)")

        df = df_compare.copy()

        # оставляем только нужные столбцы
        keep_cols = [
            "Subclass_norm",
            "status",
            "diff_columns",
            "Section_old", "Section_new",
            "Division_old", "Division_new",
            "Group_old", "Group_new",
            "Class_old", "Class_new",
            "Subclass_en_old", "Subclass_en_new",
            # динамические столбцы _new, если есть
        ]

        # добавить динамические колонки (_new)
        dynamic_new = [c for c in df.columns if c.endswith("_new") and any(
            key in c.lower()
            for key in ["authority", "approval", "date"]
        )]

        keep_cols.extend(dynamic_new)

        # фильтрация
        df_filtered = df[[c for c in keep_cols if c in df.columns]]
        df_filtered = df_filtered.rename(columns={"Subclass_norm": "Subclass"})
        st.dataframe(df_filtered, use_container_width=True)

        # сохраняем
        st.session_state["df_compare_filtered"] = df_filtered

        st.subheader("2.2. Статистика сравнения")
        stats = comparison_stats(df_compare)
        st.table(stats)

        st.subheader("2.3. Выгрузка обработанных файлов")

        # ==============================================
        # Достаём таблицы из session_state
        # ==============================================
        df_sec_old, df_div_old, df_grp_old, df_cls_old, df_sub_old = st.session_state["dfs_old"]
        df_sec_new, df_div_new, df_grp_new, df_cls_new, df_sub_new = st.session_state["dfs_new"]
        df_sec_combined, df_div_combined, df_grp_combined, df_cls_combined = st.session_state["dfs_combined"]


        # ------------------------------------------------------------
        # 1. Функция: делаем листы ТОЛЬКО старые
        # ------------------------------------------------------------
        def keep_old_columns(df, key):
            """
            Оставляет только старые столбцы:
            key | key_en_old | key_ar_old
            """
            cols = [key]
            if f"{key}_en_old" in df.columns:
                cols.append(f"{key}_en_old")
            if f"{key}_ar_old" in df.columns:
                cols.append(f"{key}_ar_old")
            return df[cols]


        # ------------------------------------------------------------
        # 2. Функция: делаем листы ТОЛЬКО новые
        # ------------------------------------------------------------
        def keep_new_columns(df, key):
            """
            Оставляет только новые столбцы:
            key | key_en_new | key_ar_new
            """
            cols = [key]
            if f"{key}_en_new" in df.columns:
                cols.append(f"{key}_en_new")
            if f"{key}_ar_new" in df.columns:
                cols.append(f"{key}_ar_new")
            return df[cols]


        # ------------------------------------------------------------
        # 3. Функция: делаем объединённые листы (для сравнения)
        # ------------------------------------------------------------
        def keep_combined_columns(df_combined, key):
            """
            Объединённое множество из старых+новых:
            key | key_en | key_ar
            """
            cols = [key, f"{key}_en", f"{key}_ar"]
            existing_cols = [c for c in cols if c in df_combined.columns]
            return df_combined[existing_cols]


        # ------------------------------------------------------------
        # 4. Генерация shams_edit1 (старый файл)
        # ------------------------------------------------------------
        def generate_shams_edit1(df_full, sec_old, div_old, grp_old, cls_old):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_full.to_excel(writer, sheet_name="Full", index=False)

                keep_old_columns(sec_old, "Section").to_excel(writer, sheet_name="Sections", index=False)
                keep_old_columns(div_old, "Division").to_excel(writer, sheet_name="Divisions", index=False)
                keep_old_columns(grp_old, "Group").to_excel(writer, sheet_name="Groups", index=False)
                keep_old_columns(cls_old, "Class").to_excel(writer, sheet_name="Classes", index=False)

            return output.getvalue()


        # ------------------------------------------------------------
        # 5. Генерация shams_edit2 (новый файл)
        # ------------------------------------------------------------
        def generate_shams_edit2(df_full, sec_new, div_new, grp_new, cls_new):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_full.to_excel(writer, sheet_name="Full", index=False)

                keep_new_columns(sec_new, "Section").to_excel(writer, sheet_name="Sections", index=False)
                keep_new_columns(div_new, "Division").to_excel(writer, sheet_name="Divisions", index=False)
                keep_new_columns(grp_new, "Group").to_excel(writer, sheet_name="Groups", index=False)
                keep_new_columns(cls_new, "Class").to_excel(writer, sheet_name="Classes", index=False)

            return output.getvalue()


        # ------------------------------------------------------------
        # 6. Генерация shams_compare (объединённая иерархия)
        # ------------------------------------------------------------
        def generate_shams_compare(df_filtered, sec_cmb, div_cmb, grp_cmb, cls_cmb):
            output = io.BytesIO()
            with pd.ExcelWriter(output, engine="xlsxwriter") as writer:
                df_filtered.to_excel(writer, sheet_name="Comparison", index=False)

                keep_combined_columns(sec_cmb, "Section").to_excel(writer, sheet_name="Sections", index=False)
                keep_combined_columns(div_cmb, "Division").to_excel(writer, sheet_name="Divisions", index=False)
                keep_combined_columns(grp_cmb, "Group").to_excel(writer, sheet_name="Groups", index=False)
                keep_combined_columns(cls_cmb, "Class").to_excel(writer, sheet_name="Classes", index=False)

            return output.getvalue()


        # ------------------------------------------------------------
        # Формируем файлы
        # ------------------------------------------------------------
        excel_old_bytes = generate_shams_edit1(df_full_old, df_sec_old, df_div_old, df_grp_old, df_cls_old)
        excel_new_bytes = generate_shams_edit2(df_full_new, df_sec_new, df_div_new, df_grp_new, df_cls_new)
        excel_compare_bytes = generate_shams_compare(
            df_filtered,
            df_sec_combined,
            df_div_combined,
            df_grp_combined,
            df_cls_combined,
        )

        # ------------------------------------------------------------
        # КНОПКИ СКАЧИВАНИЯ
        # ------------------------------------------------------------
        col_a, col_b, col_c = st.columns(3)

        with col_a:
            st.download_button(
                "Скачать обработанный старый файл (shams_edit1)",
                data=excel_old_bytes,
                file_name="shams_raw1_edit.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with col_b:
            st.download_button(
                "Скачать обработанный новый файл (shams_edit2)",
                data=excel_new_bytes,
                file_name="shams_raw2_edit.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        with col_c:
            st.download_button(
                "Скачать результат сравнения (shams_compare.xlsx)",
                data=excel_compare_bytes,
                file_name="shams_compare.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

        st.markdown("---")

        # =========================
        # ШАГ 3. Присоединение shams_edit1
        # =========================

        st.header("Шаг 3. Загрузите первый отредактированный файл и присоедините его")

        edit_file = st.file_uploader(
            "Загрузите первый отредактированный файл (shams_edit1.xlsx)",
            type=["xlsx"],
            key="edit_file",
        )

        if edit_file is not None:
            df_edit = pd.read_excel(edit_file)
            df_joined = join_with_edit(df_compare, df_edit)
            st.session_state["df_joined"] = df_joined

            st.subheader("3.1. Итоговая таблица с присоединённым shams_edit1")
            st.dataframe(df_joined, use_container_width=True)

            joined_bytes = io.BytesIO()
            df_joined.to_excel(joined_bytes, index=False)
            joined_bytes.seek(0)
            st.download_button(
                "Скачать итоговую таблицу (Excel)",
                data=joined_bytes,
                file_name="shams_joined.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
else:
    st.info("Загрузите оба файла (старый и новый), чтобы начать.")
