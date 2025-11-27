import re
import pandas as pd
import math
import unicodedata


def split_en_ar(text):
    """Разделяет английский и арабский текст в одной ячейке."""
    if not text:
        return None, None
    s = str(text).strip()
    m = re.search(r"[\u0600-\u06FF].*", s)
    if m:
        ar = m.group().strip()
        en = s[:m.start()].strip()
        return en or None, ar or None
    return s or None, None


def extract_digits(val):
    """Извлекает только цифры."""
    if pd.isna(val):
        return None
    s = re.sub(r"[^\d]", "", str(val))
    return s if s else None


def is_text_cell(x):
    """Проверяет, является ли ячейка текстовой (не чистое число)."""
    if pd.isna(x):
        return False
    s = str(x).strip()
    if not s:
        return False
    if s.replace(".", "").isdigit():
        return False
    return True


def find_first_text_right(row, start_col):
    """Ищет первое текстовое значение справа от start_col."""
    for col in range(start_col + 1, len(row)):
        v = row.iloc[col]
        if is_text_cell(v):
            return str(v).strip()
    return None


def normalize_subclass_raw(val):
    """
    Приводит сырое значение Subclass к формату NNNN.NN
    с учётом возможных дробей и хвостов.

    Примеры:
      4321.02         -> 4321.02
      9000,149999999  -> 9000.15
      1572.1          -> 1572.10
    """
    if val is None or pd.isna(val):
        return None

    s = str(val).strip().replace(",", ".")
    digits = re.sub(r"[^\d]", "", s)
    if len(digits) < 5:
        return None  # слишком коротко, это не Subclass

    main = digits[:4]
    frac_raw = digits[4:]

    if len(frac_raw) <= 2:
        frac = frac_raw.ljust(2, "0")
    else:
        scale = 10 ** (len(frac_raw) - 2)
        frac_int = math.ceil(int(frac_raw) / scale)
        if frac_int == 100:
            main_int = int(main) + 1
            main = f"{main_int:04d}"
            frac_int = 0
        frac = f"{frac_int:02d}"

    return f"{main}.{frac}"


def normalize_text_for_compare(s: str) -> str:
    """Нормализация текста для сравнения (tolower + только буквы/цифры)."""
    if pd.isna(s):
        return ""

        # 1) приводим к строке
    s = str(s)

    # 2) нормализуем unicode (очищаем разные виды пробелов/точек)
    s = unicodedata.normalize("NFKD", s)

    # 3) убираем все символы кроме A-Z a-z 0-9
    s = re.sub(r"[^A-Za-z0-9]+", "", s)

    # 4) нижний регистр
    return s.lower()


def normalize_subclass_simple(code):
    """
    Нормализатор для сравнения (если Subclass уже в виде NNNN.NN или просто цифры).
    """
    if pd.isna(code):
        return None
    s = re.sub(r"[^0-9]", "", str(code))
    if len(s) < 5:
        return None
    return f"{s[:4]}.{s[4:].ljust(2, '0')[:2]}"
