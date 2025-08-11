"""Advertising detection service with heuristics + optional AI refinement.

The detector produces a structured result that can be stored directly in the
Article fields: is_advertisement, ad_confidence, ad_type, ad_reasoning, ad_markers.
"""

from __future__ import annotations

import re
from typing import Dict, Any, List, Optional, Tuple


class AdDetector:
    """Detects advertising content using lightweight heuristics and optional AI."""

    def __init__(self, enable_ai: bool = True):
        self.enable_ai = enable_ai
        # Keyword markers in multiple languages (Russian/English/Serbian/Generic)
        self.keyword_markers: List[str] = [
            # Russian
            r"\bреклама\b", r"\bпартнер(?:ск|скaя|ская)?\b", r"\bакци\w*\b", r"\bскидк\w*\b",
            r"\bпромокод\b", r"\bоферт[ае]\b", r"\bзаказ\w*\b", r"\bкуп\w*\b",
            r"\bполуч\w*\b", r"\bв\s+подарок\b", r"\bбесплатн\w*\b",
            r"\bподписывайтесь\b", r"\bподписка\b", r"\bмагазин\b", r"\bбренд\b",
            # English
            r"\bsponsored\b", r"\bpromotion\b", r"\bpromo\b", r"\badvert\w*\b", r"\baffiliate\b",
            r"\boffer\b", r"\bdiscount\b", r"\bsale\b", r"\bbuy now\b", r"\buse code\b",
            r"\blimited time\b", r"\bsubscribe\b", r"\bsign up\b", r"\bshop now\b",
            # Serbian (Latin/Cyrillic common terms)
            r"\breklam[ai]\b", r"\bpopust\b", r"\bpromocij\w*\b", r"\bakcij\w*\b",
        ]

        # URL and param markers
        self.url_markers: List[str] = [
            r"utm_(source|medium|campaign)", r"aff(id|iliate)?=", r"ref=", r"coupon=", r"promo=",
        ]

        # Strong CTA phrases
        self.cta_markers: List[str] = [
            r"\bзаказ\w*\b", r"\bзакажи\w*\b", r"\bоформи\w*\s+заказ\b", r"\bполуч\w*\b",
            r"\blearn more\b", r"\bget your\b", r"\bjoin now\b", r"\bapply now\b", r"\bbook now\b",
            r"\bскачай\b", r"\bshop now\b", r"\bbuy now\b",
        ]

    async def detect(self, *, title: Optional[str], content: Optional[str], url: Optional[str]) -> Dict[str, Any]:
        """Run detection and return structured result.

        Returns:
            {
              'is_advertisement': bool,
              'ad_confidence': float (0..1),
              'ad_type': Optional[str],
              'ad_reasoning': Optional[str],
              'ad_markers': List[str]
            }
        """
        text = " ".join([t for t in [title or "", content or ""] if t]).lower()
        url_str = (url or "").lower()

        marker_hits: List[str] = []
        score = 0.0

        # Keyword markers
        for pattern in self.keyword_markers:
            if re.search(pattern, text, flags=re.IGNORECASE):
                marker_hits.append(f"kw:{pattern}")
                score += 0.12

        # CTA markers
        for pattern in self.cta_markers:
            if re.search(pattern, text, flags=re.IGNORECASE):
                marker_hits.append(f"cta:{pattern}")
                score += 0.15

        # URL markers
        for pattern in self.url_markers:
            if pattern in url_str:
                marker_hits.append(f"url:{pattern}")
                score += 0.1

        # Heavy punctuation / emojis (often in promos)
        exclamations = text.count("!")
        if exclamations >= 3:
            marker_hits.append("punct:exclamations>=3")
            score += 0.08

        # Percent signs (discounts)
        perc = text.count("%")
        if perc >= 1:
            marker_hits.append("symbol:%")
            score += 0.06

        # Capitalized SALE words (in Latin alph.)
        if re.search(r"\b(SALE|DEAL|OFFER)\b", text):
            marker_hits.append("kw:SALE")
            score += 0.1

        # Normalize score to [0, 1]
        score = min(1.0, score)

        # Heuristic decision first
        heuristic_is_ad = score >= 0.3 or ("kw:реклама" in marker_hits)
        if heuristic_is_ad and (not self.enable_ai or score >= 0.6):
            return {
                'is_advertisement': True,
                'ad_confidence': round(score, 2),
                'ad_type': self._infer_type(text),
                'ad_reasoning': 'Heuristic markers exceeded threshold',
                'ad_markers': marker_hits,
            }

        # Optional AI refinement when heuristics are inconclusive
        if self.enable_ai:
            try:
                from .ai_client import get_ai_client
                ai_client = get_ai_client()
                prompt = self._build_ai_prompt(title=title, content=content, url=url)
                # Reuse summarization model for classification
                response = await ai_client._make_raw_ai_request(prompt, model=ai_client.summarization_model)  # type: ignore
                parsed = self._parse_ai_result(response)
                if parsed:
                    # Merge markers and map AI confidence to ad-likelihood
                    markers = sorted(list(set(marker_hits + parsed.get('markers', []))))
                    ai_is_ad = bool(parsed.get('is_ad', False))
                    ai_conf = float(parsed.get('confidence', 0.0))  # model's own confidence
                    if ai_is_ad:
                        conf = max(score, ai_conf)
                    else:
                        # If AI says not-ad with confidence X, convert to ad-likelihood ~ (1 - X)
                        conf = max(score, max(0.0, 1.0 - ai_conf))
                    return {
                        'is_advertisement': ai_is_ad,
                        'ad_confidence': round(min(1.0, conf), 2),
                        'ad_type': parsed.get('ad_type'),
                        'ad_reasoning': parsed.get('reason'),
                        'ad_markers': markers,
                    }
            except Exception:
                # Fallback to heuristics result on AI failure
                pass

        # Default heuristic output
        return {
            'is_advertisement': heuristic_is_ad,
            'ad_confidence': round(score, 2),
            'ad_type': self._infer_type(text) if heuristic_is_ad else None,
            'ad_reasoning': 'Heuristic below threshold' if not heuristic_is_ad else 'Heuristic markers',
            'ad_markers': marker_hits,
        }

    def _infer_type(self, text: str) -> Optional[str]:
        """Guess advertising type from text."""
        if re.search(r"\baffiliate|ref=|affid\b", text):
            return 'affiliate_marketing'
        if re.search(r"\b(sale|discount|скидк|акци)\b", text, re.IGNORECASE):
            return 'promotion'
        if re.search(r"\bsubscribe|подписк\b", text, re.IGNORECASE):
            return 'subscription_promo'
        return 'product_promotion'

    def _build_ai_prompt(self, *, title: Optional[str], content: Optional[str], url: Optional[str]) -> str:
        """Build a compact classification prompt for AI."""
        t = (title or '').strip()
        c = (content or '').strip()[:1200]
        u = (url or '').strip()
        return (
            "Classify if the following article is an advertisement. Respond JSON with keys: "
            "is_ad (true/false), confidence (0..1), ad_type, reason, markers (array).\n"
            f"Title: {t}\nURL: {u}\nText: {c}"
        )

    def _parse_ai_result(self, response: Any) -> Optional[Dict[str, Any]]:
        """Parse AI JSON-style answer from completion API."""
        try:
            if not response or 'choices' not in response:
                return None
            text = response['choices'][0]['message']['content']
            import json, re as _re
            m = _re.search(r"\{[\s\S]*\}", text)
            if not m:
                return None
            data = json.loads(m.group())
            return {
                'is_ad': bool(data.get('is_ad', False)),
                'confidence': float(data.get('confidence', 0.0)),
                'ad_type': data.get('ad_type'),
                'reason': data.get('reason'),
                'markers': data.get('markers', []) if isinstance(data.get('markers', []), list) else [],
            }
        except Exception:
            return None


def awaitable(func):
    """Deprecated: kept for backward compatibility in case of external imports."""
    import asyncio
    def wrapper(*args, **kwargs):
        try:
            loop = asyncio.get_running_loop()
            return loop.create_task(func(*args, **kwargs))
        except RuntimeError:
            return asyncio.run(func(*args, **kwargs))
    return wrapper


