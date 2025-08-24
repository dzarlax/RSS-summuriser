"""
Category parsing utilities for handling AI responses.
"""

def parse_category(category_raw, valid_categories=None, title=None, content=None, return_multiple=False):
    """
    Parse and clean category from AI response, handling composite categories.
    Uses smart selection based on context when multiple categories are present.
    
    Args:
        category_raw: Raw category string from AI
        valid_categories: List of valid categories (default: standard categories)
        title: Article title for context-based selection (optional)
        content: Article content for context-based selection (optional)
        return_multiple: If True, return all relevant categories with confidence scores
    
    Returns:
        str or List[dict]: Single category name or list of categories with confidence scores
    """
    if not category_raw:
        return 'Other'
    
    # Default valid categories
    if valid_categories is None:
        valid_categories = ['Business', 'Tech', 'Science', 'Serbia', 'Other']
    
    # Clean the category string
    category_str = str(category_raw).strip()
    
    # Remove common AI response artifacts
    category_str = category_str.replace('(choose ONE category only)', '')
    category_str = category_str.replace('OR', '|')
    category_str = category_str.strip()
    
    # If it contains separators (|, /, ,, etc.), use smart selection
    for separator in ['|', '/', ',', ' and ', ' & ']:
        if separator in category_str:
            parts = [part.strip() for part in category_str.split(separator)]
            valid_parts = []
            
            # Collect all valid categories
            for part in parts:
                clean_part = ''.join(c for c in part if c.isalpha())
                if clean_part in valid_categories:
                    valid_parts.append(clean_part)
            
            if valid_parts:
                if return_multiple:
                    # Return all relevant categories with confidence scores
                    categories_with_scores = _get_categories_with_confidence(valid_parts, title, content)
                    print(f"    🏷️ Parsed composite category '{category_raw}' -> {len(categories_with_scores)} categories: {[c['name'] for c in categories_with_scores]}")
                    return categories_with_scores
                else:
                    # Smart selection based on context (backward compatibility)
                    selected = _select_best_category(valid_parts, title, content)
                    print(f"    🏷️ Parsed composite category '{category_raw}' -> '{selected}' (smart choice from: {valid_parts})")
                    return selected
            break
    
    # Single category - clean and validate
    clean_category = ''.join(c for c in category_str if c.isalpha())
    if clean_category in valid_categories:
        if return_multiple:
            # Return single category with confidence 1.0
            return [{'name': clean_category, 'confidence': 1.0}]
        else:
            return clean_category
    
    # Fallback to Other
    print(f"    ⚠️ Unknown category '{category_raw}' -> 'Other'")
    if return_multiple:
        return [{'name': 'Other', 'confidence': 0.5}]
    else:
        return 'Other'


def _select_best_category(categories, title=None, content=None):
    """
    Select the best category from multiple options based on context.
    
    Args:
        categories: List of valid category names
        title: Article title for context analysis
        content: Article content for context analysis
    
    Returns:
        str: Best matching category
    """
    if len(categories) == 1:
        return categories[0]
    
    # Combine title and content for analysis
    text = ""
    if title:
        text += title.lower() + " "
    if content:
        text += content[:500].lower()  # First 500 chars for performance
    
    # Category-specific keywords for smart matching
    category_keywords = {
        'Serbia': [
            'serbia', 'serbian', 'belgrade', 'beograd', 'srbija', 'srbije', 'srbiju',
            'vučić', 'vucic', 'president', 'government', 'parliament', 'ministry',
            'novi sad', 'niš', 'kragujevac', 'subotica', 'zemun', 'vojvodina',
            'kosovo', 'metohija', 'republika srpska', 'bosnia'
        ],
        'Tech': [
            'technology', 'tech', 'software', 'hardware', 'computer', 'digital',
            'internet', 'web', 'app', 'application', 'programming', 'code',
            'artificial intelligence', 'ai', 'machine learning', 'blockchain',
            'cryptocurrency', 'bitcoin', 'startup', 'innovation', 'gadget',
            'smartphone', 'tablet', 'laptop', 'cloud', 'data', 'algorithm'
        ],
        'Business': [
            'business', 'company', 'corporation', 'enterprise', 'market', 'economy',
            'financial', 'finance', 'investment', 'profit', 'revenue', 'sales',
            'trade', 'commerce', 'industry', 'manufacturing', 'retail',
            'banking', 'stock', 'shares', 'merger', 'acquisition', 'ceo',
            'management', 'strategy', 'growth', 'expansion'
        ],
        'Science': [
            'science', 'research', 'study', 'experiment', 'discovery', 'scientist',
            'university', 'academic', 'journal', 'publication', 'theory',
            'medicine', 'medical', 'health', 'biology', 'chemistry', 'physics',
            'mathematics', 'engineering', 'laboratory', 'clinical', 'trial'
        ]
    }
    
    # Score each category based on keyword matches
    scores = {}
    for category in categories:
        if category in category_keywords:
            score = 0
            for keyword in category_keywords[category]:
                if keyword in text:
                    # Weight longer keywords more heavily
                    score += len(keyword.split())
            scores[category] = score
        else:
            scores[category] = 0
    
    # Return category with highest score, or first one if tie
    if any(score > 0 for score in scores.values()):
        best_category = max(scores.keys(), key=lambda k: scores[k])
        return best_category
    
    # If no keywords match, use logical priority:
    # Serbia (most specific) > Science/Tech/Business (domain-specific) > Other (fallback)
    priority_order = ['Serbia', 'Science', 'Tech', 'Business', 'Other']
    for priority_cat in priority_order:
        if priority_cat in categories:
            return priority_cat
    
    # Fallback to first category
    return categories[0]


def _get_categories_with_confidence(categories, title=None, content=None):
    """
    Get all relevant categories with confidence scores based on context.
    
    Args:
        categories: List of valid category names
        title: Article title for context analysis
        content: Article content for context analysis
    
    Returns:
        List[dict]: Categories with confidence scores, sorted by relevance
    """
    if len(categories) == 1:
        return [{'name': categories[0], 'confidence': 1.0}]
    
    # Combine title and content for analysis
    text = ""
    if title:
        text += title.lower() + " "
    if content:
        text += content[:500].lower()  # First 500 chars for performance
    
    # Category-specific keywords for smart matching
    category_keywords = {
        'Serbia': [
            'serbia', 'serbian', 'belgrade', 'beograd', 'srbija', 'srbije', 'srbiju',
            'vučić', 'vucic', 'president', 'government', 'parliament', 'ministry',
            'novi sad', 'niš', 'kragujevac', 'subotica', 'zemun', 'vojvodina',
            'kosovo', 'metohija', 'republika srpska', 'bosnia'
        ],
        'Tech': [
            'technology', 'tech', 'software', 'hardware', 'computer', 'digital',
            'internet', 'web', 'app', 'application', 'programming', 'code',
            'artificial intelligence', 'ai', 'machine learning', 'blockchain',
            'cryptocurrency', 'bitcoin', 'startup', 'innovation', 'gadget',
            'smartphone', 'tablet', 'laptop', 'cloud', 'data', 'algorithm'
        ],
        'Business': [
            'business', 'company', 'corporation', 'enterprise', 'market', 'economy',
            'financial', 'finance', 'investment', 'profit', 'revenue', 'sales',
            'trade', 'commerce', 'industry', 'manufacturing', 'retail',
            'banking', 'stock', 'shares', 'merger', 'acquisition', 'ceo',
            'management', 'strategy', 'growth', 'expansion'
        ],
        'Science': [
            'science', 'research', 'study', 'experiment', 'discovery', 'scientist',
            'university', 'academic', 'journal', 'publication', 'theory',
            'medicine', 'medical', 'health', 'biology', 'chemistry', 'physics',
            'mathematics', 'engineering', 'laboratory', 'clinical', 'trial'
        ]
    }
    
    # Calculate confidence scores for each category
    results = []
    total_score = 0
    
    for category in categories:
        if category in category_keywords:
            score = 0
            for keyword in category_keywords[category]:
                if keyword in text:
                    # Weight longer keywords more heavily
                    score += len(keyword.split())
            total_score += score
            results.append({'name': category, 'raw_score': score})
        else:
            results.append({'name': category, 'raw_score': 0})
    
    # Convert raw scores to confidence values (0.3 to 1.0 range)
    if total_score > 0:
        for result in results:
            if result['raw_score'] > 0:
                # Categories with matches get confidence 0.6-1.0 based on score
                confidence = 0.6 + (result['raw_score'] / total_score) * 0.4
            else:
                # Categories without matches get lower confidence 0.3-0.5
                confidence = 0.3
            result['confidence'] = round(confidence, 2)
    else:
        # No keyword matches - assign equal moderate confidence
        base_confidence = 0.7
        for i, result in enumerate(results):
            # Slight preference for first categories (AI's original order)
            result['confidence'] = round(base_confidence - (i * 0.1), 2)
    
    # Filter out very low confidence categories and sort by confidence
    # Keep at least one category, but filter out confidence < 0.3
    filtered_results = [r for r in results if r['confidence'] >= 0.3]
    if not filtered_results:  # Fallback if all filtered out
        filtered_results = results
    filtered_results.sort(key=lambda x: x['confidence'], reverse=True)
    
    # Return only name and confidence
    return [{'name': r['name'], 'confidence': r['confidence']} for r in filtered_results]
