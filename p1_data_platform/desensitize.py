"""P1 脱敏：对 PII 字段做掩码，落库即脱敏、原始 PII 不落业务表。

规则类型登记在 desensitization_rule 表，这里实现四类：mask / phone / email / idcard。
"""
from __future__ import annotations

import re


def mask_name(name: str) -> str:
    """姓名脱敏：保留首字，其余用 * 替换。张伟 → 张*"""
    if not name:
        return ""
    return name[0] + "*" * (len(name) - 1)


def mask_phone(phone: str) -> str:
    """手机脱敏：前 3 后 4 保留，中间 4 位 *。13812340001 → 138****0001"""
    if not phone or len(phone) < 7:
        return phone or ""
    return f"{phone[:3]}****{phone[-4:]}"


def mask_email(email: str) -> str:
    """邮箱脱敏：@ 前保留首字符，其余 *。zhangwei@example.com → z******@example.com"""
    if not email or "@" not in email:
        return email or ""
    local, domain = email.split("@", 1)
    return f"{local[0]}{'*' * (len(local) - 1)}@{domain}"


def mask_idcard(idcard: str) -> str:
    """身份证脱敏：前 6 后 4 保留。110101199001011234 → 110101********1234"""
    if not idcard or len(idcard) < 10:
        return idcard or ""
    return f"{idcard[:6]}{'*' * (len(idcard) - 10)}{idcard[-4:]}"


def desensitize_customer(row: dict) -> dict:
    """把原始客户行转成脱敏后可落库的行，并生成稳定客户编号。"""
    cid = row["cid"]
    return {
        "customer_no": f"CUST{cid:04d}",
        "name_masked": mask_name(row.get("name", "")),
        "phone_masked": mask_phone(row.get("phone", "")),
        "email_masked": mask_email(row.get("email", "")),
        "city": row.get("city", ""),
        "level": row.get("level", "normal"),
        "cid": cid,  # 保留原始 cid 仅用于本次发布阶段做关联，不落 customer 表
    }


# 便于验证输出
def _demo() -> None:
    sample = {"name": "张伟", "phone": "13812340001", "email": "zhangwei@example.com", "idcard": "110101199001011234"}
    print("name  ->", mask_name(sample["name"]))
    print("phone ->", mask_phone(sample["phone"]))
    print("email ->", mask_email(sample["email"]))
    print("idcard->", mask_idcard(sample["idcard"]))


if __name__ == "__main__":
    _demo()
