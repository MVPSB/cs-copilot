"""落库前的轻量脱敏：手机号、身份证、邮箱、详细地址、长数字（订单号保留原样由调用方决定）。"""

from __future__ import annotations

import re

_PHONE = re.compile(r"(?<!\d)1[3-9]\d{9}(?!\d)")
_LANDLINE = re.compile(r"(?<!\d)0\d{2,3}-?\d{7,8}(?!\d)")
_ID_CARD = re.compile(r"(?<!\d)\d{17}[\dXx](?!\d)")
_EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
_LONG_DIGITS = re.compile(r"(?<!\d)\d{12,}(?!\d)")
_ADDRESS = re.compile(
    r"((?:[\u4e00-\u9fa5]{2,8}(?:省|自治区))?[\u4e00-\u9fa5]{2,8}市[\u4e00-\u9fa5]{2,8}(?:区|县))"
    r"(?:[\u4e00-\u9fa5A-Za-z0-9\-]{1,30}?(?:路|街|道|巷)|[\u4e00-\u9fa5A-Za-z0-9\-]{0,10})"
    r"(?:[\s]*[A-Za-z]?[\s]*\d*[\s]*(?:号楼|栋楼|号|栋|楼|室|层|座|单元)[\s]*){0,6}"
)


def mask_pii(text: str) -> str:
    """把可识别个人身份的信息打码，保留业务可读性。"""
    if not text:
        return text
    out = _EMAIL.sub("[邮箱]", text)
    out = _ID_CARD.sub("[身份证]", out)
    out = _LANDLINE.sub("[电话]", out)
    out = _PHONE.sub("[手机号]", out)
    out = _LONG_DIGITS.sub("[长数字]", out)
    out = _ADDRESS.sub(lambda m: f"{m.group(1)}[详细地址]", out)
    return out
