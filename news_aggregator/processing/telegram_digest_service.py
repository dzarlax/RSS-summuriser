import logging
"""Telegram Digest Service for news aggregation."""

import math
from datetime import datetime, date
from typing import Dict, Any, List, Optional

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, text

from ..models import Article, DailySummary
from ..services.telegram_service import get_telegram_service

logger = logging.getLogger(__name__)


class TelegramDigestService:
    """Service for generating and sending Telegram digests."""
    
    def __init__(self):
        """Initialize Telegram digest service."""
        self.telegram_service = get_telegram_service()
    
    async def generate_telegram_digest(self, db: AsyncSession, stats: Dict[str, Any]):
        """Generate and send Telegram digest of today's articles."""
        logger.info("📲 Generating Telegram digest...")
        try:
            today = datetime.utcnow().date()
            
            # Get articles from today, grouped by category
            query = text("""
                SELECT 
                    c.display_name as category_name,
                    c.color as category_color,
                    COUNT(DISTINCT a.id) as article_count,
                    STRING_AGG(DISTINCT a.title, ' | ') as titles,
                    STRING_AGG(DISTINCT a.summary, ' | ') as summaries
                FROM articles a
                INNER JOIN article_categories ac ON a.id = ac.article_id
                INNER JOIN categories c ON ac.category_id = c.id
                WHERE DATE(a.published_at) = :today
                    AND a.summary IS NOT NULL
                    AND a.summary != ''
                    AND LENGTH(a.summary) > 50
                GROUP BY c.id, c.display_name, c.color
                ORDER BY article_count DESC
                LIMIT 10
            """)
            
            result = await db.execute(query, {'today': today})
            categories = result.fetchall()
            
            if not categories:
                logger.info("  📭 No articles found for today's digest")
                return
            
            # Generate combined digest
            digest_text = await self._create_combined_digest(db, today)
            
            if not digest_text or len(digest_text.strip()) < 100:
                logger.info("  📭 Generated digest is too short, skipping")
                return
            
            # Send digest to Telegram
            if self.telegram_service:
                # Split digest into multiple messages if needed (Telegram has 4096 character limit)
                header = f"📊 **Дайджест новостей за {today.strftime('%d.%m.%Y')}**\n\n"
                footer = f"\n\n🤖 *Сгенерировано автоматически*"
                
                digest_parts = self._split_digest_into_parts(header, categories, footer)
                
                for i, part in enumerate(digest_parts, 1):
                    try:
                        await self.telegram_service.send_message(part)
                        logger.info(f"  ✅ Sent digest part {i}/{len(digest_parts)}")
                        # Small delay between messages
                        if i < len(digest_parts):
                            import asyncio
                            await asyncio.sleep(1)
                            
                    except Exception as e:
                        logger.error(f"  ❌ Failed to send digest part {i}: {e}")
                        stats['errors'].append(f"Telegram digest part {i} failed: {e}")
                
                logger.info(f"  📤 Telegram digest sent successfully ({len(digest_parts)} parts)")
                stats.setdefault('telegram_digest_sent', 0)
                stats['telegram_digest_sent'] += 1
            else:
                logger.warning("  ⚠️ Telegram service not available")
        except Exception as e:
            error_msg = f"Telegram digest generation failed: {e}"
            logger.error(f"  ❌ {error_msg}")
            stats['errors'].append(error_msg)

    async def generate_and_save_daily_summaries(self, db: AsyncSession, date, categories: Dict[str, List]):
        """Generate and save daily summaries for each category."""
        logger.info(f"📝 Generating daily summaries for {date}...")
        try:
            from ..services.ai_client import get_ai_client
            ai_client = get_ai_client()
            
            saved_summaries = 0
            
            for category_name, articles in categories.items():
                if not articles or len(articles) < 2:  # Skip categories with less than 2 articles
                    continue
                
                try:
                    logger.info(f"  🏷️ Processing category: {category_name} ({len(articles)} articles)")
                    # Prepare articles text for AI
                    articles_text = []
                    for article in articles[:10]:  # Limit to 10 articles per category
                        title = article.get('title', '').strip()
                        summary = article.get('summary', '').strip()
                        if title and summary:
                            articles_text.append(f"• {title}\n  {summary}")
                    
                    if not articles_text:
                        continue
                    
                    combined_text = '\n\n'.join(articles_text)
                    
                    # Generate summary using AI
                    category_summary = await ai_client.summarize_articles_for_category(
                        category_name=category_name,
                        articles_text=combined_text
                    )
                    
                    if category_summary and len(category_summary.strip()) > 50:
                        # Save to database
                        daily_summary = DailySummary(
                            date=date,
                            category=category_name,
                            summary=category_summary,
                            article_count=len(articles)
                        )
                        db.add(daily_summary)
                        saved_summaries += 1
                        
                        logger.info(f"    ✅ Generated summary for {category_name}")
                    else:
                        logger.warning(f"    ⚠️ AI generated empty summary for {category_name}")
                except Exception as e:
                    logger.error(f"    ❌ Failed to generate summary for {category_name}: {e}")
                    continue
            
            if saved_summaries > 0:
                await db.commit()
                logger.info(f"  💾 Saved {saved_summaries} daily summaries")
            else:
                logger.info(f"  📭 No summaries generated")
        except Exception as e:
            await db.rollback()
            logger.error(f"  ❌ Daily summaries generation failed: {e}")
            raise

    async def _create_combined_digest(self, db: AsyncSession, date: datetime.date) -> str:
        """Create a combined digest from daily summaries."""
        try:
            # Get daily summaries for the date
            query = select(DailySummary).where(DailySummary.date == date).order_by(DailySummary.article_count.desc())
            result = await db.execute(query)
            summaries = result.scalars().all()
            
            if not summaries:
                return ""
            
            # Build digest text
            digest_parts = []
            total_articles = sum(s.article_count for s in summaries)
            
            digest_parts.append(f"📰 **Главные новости за {date.strftime('%d.%m.%Y')}**")
            digest_parts.append(f"Всего статей: {total_articles}")
            digest_parts.append("")
            
            for summary in summaries:
                category_icon = self._get_category_icon(summary.category)
                digest_parts.append(f"{category_icon} **{summary.category}** ({summary.article_count} статей)")
                digest_parts.append(summary.summary)
                digest_parts.append("")
            
            return '\n'.join(digest_parts)
            
        except Exception as e:
            logger.error(f"  ❌ Failed to create combined digest: {e}")
            return ""

    def _split_digest_into_parts(self, header: str, summaries, footer: str, 
                                max_length: int = 4000) -> List[str]:
        """Split digest into parts that fit Telegram message limits."""
        parts = []
        current_part = header
        
        for summary in summaries:
            category_text = f"📂 **{summary.category}** ({summary.article_count} статей)\n"
            category_text += f"{summary.summary}\n\n"
            
            # Check if adding this category would exceed the limit
            if len(current_part + category_text + footer) > max_length:
                # Finish current part and start new one
                if len(current_part.strip()) > len(header.strip()):
                    parts.append(current_part.rstrip() + footer)
                    current_part = header
                
            current_part += category_text
        
        # Add the final part
        if len(current_part.strip()) > len(header.strip()):
            parts.append(current_part.rstrip() + footer)
        
        return parts if parts else [header + footer]

    def _build_digest_part(self, header: str, categories, total_articles: int, 
                          part_num: int = 1, total_parts: int = 1) -> str:
        """Build a single digest part."""
        part_header = header
        if total_parts > 1:
            part_header += f" (часть {part_num}/{total_parts})"
        
        digest_lines = [part_header, ""]
        
        if part_num == 1:
            digest_lines.append(f"📊 Всего статей: {total_articles}")
            digest_lines.append("")
        
        for category in categories:
            category_icon = self._get_category_icon(category.category_name)
            digest_lines.append(f"{category_icon} **{category.category_name}** ({category.article_count} статей)")
            
            # Add brief category summary if available
            if hasattr(category, 'summaries') and category.summaries:
                summaries_text = category.summaries[:200] + "..." if len(category.summaries) > 200 else category.summaries
                digest_lines.append(summaries_text)
            
            digest_lines.append("")
        
        return '\n'.join(digest_lines)

    def _get_category_icon(self, category_name: str) -> str:
        """Get emoji icon for category."""
        category_icons = {
            'Политика': '🏛️',
            'Экономика': '💼',
            'Технологии': '💻',
            'Спорт': '⚽',
            'Культура': '🎭',
            'Наука': '🔬',
            'Прочее': '📰'
        }
        return category_icons.get(category_name, '📰')

