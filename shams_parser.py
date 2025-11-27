import pandas as pd
import re
import io
from typing import List, Tuple

from utils import (
    split_en_ar,
    extract_digits,
    is_text_cell,
    find_first_text_right,
    normalize_subclass_raw,
)

# Базовые колонки, которые не считаем "динамическими"
BASE_COLS = {"part", "section", "division", "group", "class", "subclass", "description", "الوصف"}


def detect_section(text_line):
    """
    Определяет Section строки формата:
    - Section G: Retail...
    - Section F Construction
    - Section K: Finance Section K: Finance (мусор → оставляем только первое)

    Возвращает: (Section_code, en_clean, ar_clean)
    """
    if not isinstance(text_line, str):
        return None, None, None

    s = text_line.strip()

    # 1. Находим начало секции
    m = re.match(r"^\s*section\s*([A-ZА-Я])\s*[:\-]?\s*(.*)$", s, re.I)
    if not m:
        return None, None, None

    letter = m.group(1).upper()
    rest = (m.group(2) or "").strip()

    # 2. Убираем арабский блок (оставляем только английский)
    rest_en, rest_ar = split_en_ar(rest)

    if not rest_en:
        rest_en = ""

    # 3. Удаляем паразитный текст после первого корректного описания
    #    удаляем всё после повторного "Section X"
    rest_en = re.split(r"\bSection\s+[A-Z]\b", rest_en, flags=re.I)[0].strip()

    # 4. Убираем предлоги, если строка начинается повторно с Section
    #    и повторные метки выборки
    rest_en = rest_en.replace("Division", "").replace("Group", "").replace("Class", "").replace("Description", "")
    rest_en = re.sub(r"\s{2,}", " ", rest_en).strip()

    # 5. Если после чистки строка пустая — лучше вернуть None
    if rest_en == "":
        rest_en = None

    return f"Section {letter}", rest_en, rest_ar


def detect_division(text_line: str):
    """Определяет Division формата 'Division 18 ...'."""
    if not isinstance(text_line, str):
        return None, None, None

    m = re.match(r"^\s*division\s+(\d{2})\s*(.*)$", text_line, re.I)
    if m:
        code = m.group(1)
        rest = (m.group(2) or "").strip()
        en, ar = split_en_ar(rest)
        return code, en, ar

    return None, None, None


def find_header_row(df: pd.DataFrame) -> int:
    header_keywords = {"division", "group", "class", "subclass", "description"}
    for i in range(len(df)):
        row = df.iloc[i].astype(str).str.lower().tolist()
        if any(k in row for k in header_keywords):
            return i
    raise ValueError("Не найден ряд с заголовками колонок")


def parse_sheet(df_raw: pd.DataFrame):
    sections = {}
    divisions = {}
    division_to_section = {}
    current_section = None

    # 1) Чтение SECTION / DIVISION текстом
    for _, row in df_raw.iterrows():
        text_line = " ".join(str(v) for v in row if pd.notna(v))

        sec_code, sec_en, sec_ar = detect_section(text_line)
        if sec_code:
            current_section = sec_code
            if sec_code not in sections:
                sections[sec_code] = {
                    "en": sec_en,
                    "ar": sec_ar,
                    "divisions": [],
                }
            continue

        div_code, div_en, div_ar = detect_division(text_line)
        if div_code:
            divisions.setdefault(div_code, {"en": div_en, "ar": div_ar})
            if current_section:
                sections[current_section]["divisions"].append(div_code)
                division_to_section[div_code] = current_section
            continue

    # 2) Поиск заголовков
    header_row = find_header_row(df_raw)
    header = df_raw.iloc[header_row].astype(str).str.strip()
    header_lower = header.str.lower()
    df = df_raw.iloc[header_row + 1:].reset_index(drop=True)

    col_group = header_lower[header_lower == "group"].index[0] if "group" in header_lower.values else None
    col_class = header_lower[header_lower == "class"].index[0] if "class" in header_lower.values else None
    col_subclass = header_lower[header_lower == "subclass"].index[0] if "subclass" in header_lower.values else None

    col_ar_descr = None
    for i, nm in enumerate(header_lower):
        if "الوصف" in nm:
            col_ar_descr = i
            break

    # динамические колонки
    dynamic_cols = []
    dynamic_col_indices = []
    for idx, nm in enumerate(header_lower):
        if nm not in BASE_COLS and nm not in {"", "unnamed: 0", "nan"}:
            dynamic_cols.append(header[idx])  # оригинальное имя
            dynamic_col_indices.append(idx)

    groups = {}
    classes = {}
    subclasses = {}

    # 3) Чтение Group / Class / Subclass
    for _, row in df.iterrows():
        arabic_descr = None
        if col_ar_descr is not None:
            v = row[col_ar_descr]
            if isinstance(v, str) and v.strip():
                arabic_descr = v.strip()

        row_dynamic_vals = {
            dynamic_cols[i]: row[dynamic_col_indices[i]]
            for i in range(len(dynamic_cols))
        }

        # GROUP
        if col_group is not None:
            raw = row[col_group]
            code = extract_digits(raw)
            if code and len(code) == 3:
                en = find_first_text_right(row, col_group)
                groups.setdefault(code, {"en": en, "ar": arabic_descr})

        # CLASS
        if col_class is not None:
            raw = row[col_class]
            code = extract_digits(raw)
            if code and len(code) == 4:
                en = find_first_text_right(row, col_class)
                classes.setdefault(code, {"en": en, "ar": arabic_descr})

        # SUBCLASS
        if col_subclass is not None:
            raw = row[col_subclass]
            if pd.notna(raw):
                code = normalize_subclass_raw(raw)
                if code:
                    en = find_first_text_right(row, col_subclass)
                    subclasses.setdefault(
                        code,
                        {
                            "en": en,
                            "ar": arabic_descr,
                            **row_dynamic_vals,
                        },
                    )

    return sections, divisions, division_to_section, groups, classes, subclasses, dynamic_cols


def parse_all_sheets_from_bytes(file_bytes: bytes, sheets: List[str]):
    """
    Принимает bytes Excel-файла, парсит все листы и
    возвращает df_full + отдельные уровни.
    """
    bio = io.BytesIO(file_bytes)
    xls = pd.ExcelFile(bio)

    S, D, MAP, G, C, SC = {}, {}, {}, {}, {}, {}
    dynamic_cols_all = set()

    for sheet in sheets:
        df_raw = pd.read_excel(xls, sheet_name=sheet, header=None)
        s, d, m, g, c, sc, dyn = parse_sheet(df_raw)

        for sec, data in s.items():
            if sec not in S:
                S[sec] = {"en": data["en"], "ar": data["ar"], "divisions": []}
            for dv in data["divisions"]:
                if dv not in S[sec]["divisions"]:
                    S[sec]["divisions"].append(dv)

        D.update(d)
        MAP.update(m)
        G.update(g)
        C.update(c)
        SC.update(sc)

        for col in dyn:
            dynamic_cols_all.add(col)

    dynamic_cols = list(dynamic_cols_all)

    # ====== Датафреймы уровней ======
    df_sections = pd.DataFrame([
        {"Section": sec, "Section_en": v["en"], "Section_ar": v["ar"], "Divisions": v["divisions"]}
        for sec, v in S.items()
    ])

    df_divisions = pd.DataFrame([
        {"Division": div, "Division_en": v["en"], "Division_ar": v["ar"], "Section": MAP.get(div)}
        for div, v in D.items()
    ])

    df_groups = pd.DataFrame([
        {"Group": grp, "Group_en": v["en"], "Group_ar": v["ar"], "Division": grp[:2]}
        for grp, v in G.items()
    ])

    df_classes = pd.DataFrame([
        {"Class": cls, "Class_en": v["en"], "Class_ar": v["ar"], "Group": cls[:3]}
        for cls, v in C.items()
    ])

    records = []
    for sc, v in SC.items():
        rec = {
            "Subclass": sc,
            "Subclass_en": v["en"],
            "Subclass_ar": v["ar"],
            "Class": sc.replace(".", "")[:4],
        }
        for col in dynamic_cols:
            rec[col] = v.get(col)
        records.append(rec)

    df_subclasses = pd.DataFrame(records)

    # ====== Полная иерархия ======
    df_full = (
        df_subclasses
        .merge(df_classes, on="Class", how="left")
        .merge(df_groups, on="Group", how="left")
        .merge(df_divisions, on="Division", how="left")
        .merge(df_sections, on="Section", how="left")
    )

    static_cols = [
        "Section", "Section_en", "Section_ar",
        "Division", "Division_en", "Division_ar",
        "Group", "Group_en", "Group_ar",
        "Class", "Class_en", "Class_ar",
        "Subclass", "Subclass_en", "Subclass_ar",
    ]

    df_full = df_full[static_cols + dynamic_cols]

    return df_full, df_sections, df_divisions, df_groups, df_classes, df_subclasses


def make_processed_excel_bytes(df_full, df_sections, df_divisions, df_groups, df_classes, df_subclasses) -> bytes:
    """
    Создаёт многолистный Excel в памяти:
    - full
    - sections
    - divisions
    - groups
    - classes
    - subclasses
    """
    import io
    from openpyxl import Workbook  # только чтобы engine openpyxl точно подтянулся
    buffer = io.BytesIO()

    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df_full.to_excel(writer, index=False, sheet_name="full")
        df_sections[["Section", "Section_en", "Section_ar"]].to_excel(writer, index=False, sheet_name="sections")
        df_divisions[["Division", "Division_en", "Division_ar"]].to_excel(writer, index=False, sheet_name="divisions")
        df_groups[["Group", "Group_en", "Group_ar"]].to_excel(writer, index=False, sheet_name="groups")
        df_classes[["Class", "Class_en", "Class_ar"]].to_excel(writer, index=False, sheet_name="classes")
        df_subclasses[["Subclass", "Subclass_en", "Subclass_ar"]].to_excel(writer, index=False, sheet_name="subclasses")

    buffer.seek(0)
    return buffer.getvalue()
