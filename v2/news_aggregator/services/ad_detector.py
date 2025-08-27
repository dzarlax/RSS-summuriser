"""Advertising detection service with heuristics + optional AI refinement.

The detector produces a structured result that can be stored directly in the
Article fields: is_advertisement, ad_confidence, ad_type, ad_reasoning, ad_markers.
"""

from __future__ import annotations

import re
from typing import Dict, Any, List, Optional, Tuple


class AdDetector:
    """Detects advertising content using lightweight heuristics only.
    
    Note: AI detection is now handled by analyze_article_complete() in unified processing.
    This class provides heuristic-only detection as fallback.
    """

    def __init__(self, enable_ai: bool = False):
        # AI is disabled - unified analysis handles AI detection
        self.enable_ai = False
        
        # Strong advertisement markers (high confidence)
        self.strong_ad_markers: List[str] = [
            # Explicit advertisement words
            r"\bреклама\b", r"\bрекламн\w*\b", r"\bsponsored\b", r"\badvert\w*\b",
            r"\breklam[ai]\b", r"\bпартнерск\w*\s+материал\b",
            # Direct sales language
            r"\bкупи\w*\s+сейчас\b", r"\bbuy now\b", r"\bshop now\b", r"\bзаказать\s+сейчас\b",
            r"\bпромокод\b", r"\buse code\b", r"\bcoupon\b", r"\bскидка\s+\d+%\b",
        ]
        
        # Weak advertisement indicators (context dependent)
        self.weak_ad_markers: List[str] = [
            # Business/service offers
            r"\bоферт[ае]\b", r"\boffer\b", r"\bакци[яи]\b", r"\bpromotion\b",
            r"\bбесплатн\w*\b", r"\bfree\b", r"\bв\s+подарок\b",
            # Subscription/contact encouragement
            r"\bподписывайтесь\b", r"\bsubscribe\b", r"\bсвязаться\b", r"\bcontact us\b",
        ]

        # URL and param markers (strong indicators)
        self.url_markers: List[str] = [
            r"utm_(source|medium|campaign)", r"aff(id|iliate)?=", r"ref=", r"coupon=", r"promo=",
        ]

        # News source domains (lower ad probability)
        self.news_domains: List[str] = [
            "balkaninsight.com", "biznis.rs", "rts.rs", "b92.net", "politika.rs",
            "blic.rs", "novosti.rs", "tanjug.rs", "n1info.rs", "danas.rs"
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
        
        # Check if it's from a news source
        is_news_source = any(domain in url_str for domain in self.news_domains)
        
        # Strong advertisement markers (high weight)
        for pattern in self.strong_ad_markers:
            if re.search(pattern, text, flags=re.IGNORECASE):
                marker_hits.append(f"strong_ad:{pattern}")
                score += 0.4  # High weight for explicit ad markers

        # Weak advertisement markers (context dependent)
        for pattern in self.weak_ad_markers:
            if re.search(pattern, text, flags=re.IGNORECASE):
                marker_hits.append(f"weak_ad:{pattern}")
                # Lower weight for news sources
                weight = 0.1 if is_news_source else 0.2
                score += weight

        # URL markers (strong indicators)
        for pattern in self.url_markers:
            if pattern in url_str:
                marker_hits.append(f"url:{pattern}")
                score += 0.3

        # Personal service indicators (high ad probability)
        personal_patterns = [
            r"я\s+\w+,\s+\w+", r"i am \w+", r"моя\s+компания", r"мой\s+бизнес",
            r"наши\s+услуги", r"our services", r"обращайтесь", r"call me",
            r"предлагаю\s+услуги", r"опыт\s+\d+\s+лет", r"профессиональ\w+\s+услуги"
        ]
        for pattern in personal_patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                marker_hits.append(f"personal:{pattern}")
                score += 0.35

        # Event announcements (medium ad probability)
        event_patterns = [
            r"\d{1,2}\s+\w+\s+в\s+\d{1,2}:\d{2}", r"приходите", r"участвуйте",
            r"регистрация", r"билеты", r"tickets", r"register"
        ]
        for pattern in event_patterns:
            if re.search(pattern, text, flags=re.IGNORECASE):
                marker_hits.append(f"event:{pattern}")
                score += 0.15

        # Reduce score for news-like language
        news_indicators = [
            r"согласно\s+исследованию", r"по\s+данным", r"эксперты\s+считают",
            r"according to", r"experts say", r"research shows", r"правительство",
            r"министерство", r"парламент", r"government", r"ministry"
        ]
        for pattern in news_indicators:
            if re.search(pattern, text, flags=re.IGNORECASE):
                marker_hits.append(f"news_indicator:{pattern}")
                score -= 0.1  # Reduce ad probability

        # Apply news source penalty
        if is_news_source:
            marker_hits.append("source:news_domain")
            score *= 0.6  # Reduce score by 40% for news sources

        # Normalize score to [0, 1]
        score = max(0.0, min(1.0, score))

        # Adjust heuristic threshold based on source
        threshold = 0.25 if is_news_source else 0.35
        heuristic_is_ad = score >= threshold
        if heuristic_is_ad and (not self.enable_ai or score >= 0.6):
            return {
                'is_advertisement': True,
                'ad_confidence': round(score, 2),
                'ad_type': self._infer_type(text),
                'ad_reasoning': 'Heuristic markers exceeded threshold',
                'ad_markers': marker_hits,
            }

        # ============================================================================
        # REMOVED: AI refinement - Now handled by unified analysis
        # ============================================================================
        # AI detection is now handled by analyze_article_complete() in unified
        # processing. This AdDetector serves as heuristic-only fallback.

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

    # ============================================================================
    # REMOVED: AI prompt and parsing methods - Replaced by unified analysis
    # ============================================================================
    # _build_ai_prompt() and _parse_ai_result() were removed as AI detection
    # is now handled by analyze_article_complete() in unified processing.
    # This class now provides heuristic-only detection as fallback.


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


