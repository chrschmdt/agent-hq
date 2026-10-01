from __future__ import annotations

import re

from ahq.guardrails.replies import EMAIL, USER

FIELDS = re.compile(r'("(?:first_name|last_name|address1|address2|zip|email|phone)"\s*:\s*)"[^"]*"')
STREET = re.compile(
    r"\b\d{1,5}\s+(?:[A-Z][a-z]+\s+){1,3}"
    r"(?:Street|St|Avenue|Ave|Road|Rd|Lane|Ln|Drive|Dr|Boulevard|Blvd|Way|Court|Ct|Place|Pl)\b\.?"
)
REDACTED = "[redacted]"


def redact(text: str) -> str:
    text = FIELDS.sub(rf'\1"{REDACTED}"', text)
    text = EMAIL.sub("[email]", text)
    text = USER.sub("[customer]", text)
    return STREET.sub("[address]", text)
