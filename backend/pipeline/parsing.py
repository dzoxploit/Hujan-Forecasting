"""Parsing angka dan koordinat fleksibel (sel 3 notebook)."""

import re

import numpy as np
import pandas as pd


def fix_digit_typos(text):
    return (
        text
        .replace("O", "0")
        .replace("o", "0")
        .replace("I", "1")
        .replace("i", "1")
    )


def parse_flexible_decimal(value):

    if pd.isna(value):
        return np.nan

    text = fix_digit_typos(str(value).strip())
    if text == "":
        return np.nan

    has_comma = "," in text
    has_period = "." in text

    if has_comma and has_period:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif has_comma:
        parts = text.split(",")
        if len(parts) > 2:
            if all(len(p) == 3 for p in parts[1:]):
                text = "".join(parts)
            else:
                text = "".join(parts[:-1]) + "." + parts[-1]
        else:
            text = text.replace(",", ".")
    elif has_period:
        parts = text.split(".")
        if len(parts) > 2:
            if all(len(p) == 3 for p in parts[1:]):
                text = "".join(parts)
            else:
                text = "".join(parts[:-1]) + "." + parts[-1]

    try:
        return float(text)
    except Exception:
        return np.nan


def parse_coordinate_value(value):

    if pd.isna(value):
        return np.nan

    text = fix_digit_typos(str(value).strip())
    if text == "":
        return np.nan

    simple_value = parse_flexible_decimal(text)
    if not pd.isna(simple_value):
        return simple_value

    text_upper = text.upper()
    direction = None
    if "S" in text_upper or "W" in text_upper:
        direction = -1
    elif "N" in text_upper or "E" in text_upper:
        direction = 1

    numbers = re.findall(r"[-+]?\d+(?:[.,]\d+)?", text)

    if len(numbers) >= 3:
        try:
            degree = parse_flexible_decimal(numbers[0])
            minute = parse_flexible_decimal(numbers[1])
            second = parse_flexible_decimal(numbers[2])

            result = abs(degree) + minute / 60.0 + second / 3600.0

            if direction == -1:
                result = -abs(result)
            elif degree < 0:
                result = -abs(result)

            return result
        except Exception:
            pass

    return np.nan
