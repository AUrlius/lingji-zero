"""对抗性提示词清洗器

检测并清洗：
- Unicode 零宽字符 (U+200B-U+200F, U+FEFF)
- ASCII 控制字符 (U+0000-U+001F 除 \\t \\n \\r)
- Base64 编码高熵片段
- 分隔符注入 (---SYSTEM---, ====END==== 等)
"""

import base64
import math
import re
from collections import Counter
from dataclasses import dataclass, field


@dataclass
class SanitizeResult:
    cleaned: str
    threats_detected: int = 0
    threats: list[str] = field(default_factory=list)


class AdversarialTextSanitizer:
    """对抗性提示词清洗器

    检测并清洗：
    - Unicode 零宽字符 (U+200B-U+200F, U+FEFF)
    - ASCII 控制字符 (U+0000-U+001F 除 \\t \\n \\r)
    - Base64 编码高熵片段
    - 分隔符注入 (---SYSTEM---, ====END==== 等)
    """

    ZERO_WIDTH = re.compile("[\u200b-\u200f\ufeff]")
    CONTROL_CHARS = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f]")
    BASE64_CANDIDATE = re.compile(r"[A-Za-z0-9+/]{12,}={0,2}")
    SEPARATOR_INJECTION = re.compile(
        r"---+[A-Z]+---+|={3,}[A-Z]+={3,}", re.IGNORECASE
    )

    def sanitize(self, text: str) -> SanitizeResult:
        if not text or not text.strip():
            return SanitizeResult(cleaned=text or "")

        cleaned = text
        threats: list[str] = []

        # 1. 零宽字符
        zw_matches = self.ZERO_WIDTH.findall(cleaned)
        if zw_matches:
            cleaned = self.ZERO_WIDTH.sub("", cleaned)
            threats.append(f"stripped {len(zw_matches)} zero-width characters")

        # 2. ASCII 控制字符
        ctrl_matches = self.CONTROL_CHARS.findall(cleaned)
        if ctrl_matches:
            cleaned = self.CONTROL_CHARS.sub("", cleaned)
            threats.append(f"stripped {len(ctrl_matches)} control characters")

        # 3. 分隔符注入
        sep_matches = self.SEPARATOR_INJECTION.findall(cleaned)
        if sep_matches:
            for m in sep_matches:
                cleaned = cleaned.replace(m, "[REDACTED]")
            threats.append(f"blocked {len(sep_matches)} separator injection(s)")

        # 4. Base64 高熵检测
        b64_matches = self.BASE64_CANDIDATE.findall(cleaned)
        for m in b64_matches:
            if self._is_likely_base64(m):
                cleaned = cleaned.replace(m, "[B64]")
                threats.append(f"blocked base64 payload ({len(m)} chars)")

        return SanitizeResult(
            cleaned=cleaned,
            threats_detected=len(threats),
            threats=threats,
        )

    @staticmethod
    def _is_likely_base64(s: str) -> bool:
        if len(s) < 12:
            return False
        # Real base64 almost always mixes upper and lowercase;
        # plain English words matching the regex won't.
        has_upper = any(c.isupper() for c in s)
        has_lower = any(c.islower() for c in s)
        if not (has_upper and has_lower):
            return False
        try:
            decoded = base64.b64decode(s, validate=True)
            if len(decoded) < 4:
                return False
        except Exception:
            return False
        counts = Counter(s.rstrip("="))
        total = sum(counts.values())
        entropy = -sum((c / total) * math.log2(c / total) for c in counts.values())
        return entropy > 2.0
