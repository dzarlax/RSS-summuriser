# 📰 News Aggregator - Public API Documentation

## 🌐 Basic Information

**Base URL**: `https://news.dzarlax.dev`  
**API Version**: v1  
**Response Format**: JSON  
**Authentication**: Not required (public endpoints)

## 📋 Public Endpoints

### 1. 📰 Get News Feed

```http
GET /api/public/feed
```

Main endpoint for retrieving the news feed with filtering and pagination.

#### Query Parameters

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `limit` | integer | No | 20 | Number of articles (1-1000) |
| `offset` | integer | No | 0 | Offset for pagination (≥0) |
| `since_hours` | integer | No | - | Articles from the last N hours (1-168) |
| `category` | string | No | - | Filter by category |
| `hide_ads` | boolean | No | true | Hide advertisement materials |

#### Available Categories
- `serbia` - Serbia
- `tech` - Technology
- `business` - Business
- `science` - Science
- `politics` - Politics
- `international` - International
- `other` - Other
- `advertisements` - Advertisement materials

#### Request Example
```bash
curl "https://news.dzarlax.dev/api/public/feed?limit=5&category=tech&since_hours=24"
```

#### Response
```json
{
  "articles": [
    {
      "id": 845,
      "title": "New AI Technology",
      "summary": "Article summary...",
      "url": "https://example.com/article",
      "image_url": "https://example.com/image.jpg",
      "source_id": 1,
      "source_name": "Tech News",
      "category": "Tech",
      "categories": [
        {
          "name": "Tech",
          "display_name": "Technology",
          "confidence": 0.95,
          "color": "#2196F3"
        }
      ],
      "published_at": "2025-08-27T09:00:00Z",
      "fetched_at": "2025-08-27T09:05:00Z",
      "is_advertisement": false,
      "ad_confidence": 0.0,
      "ad_type": null,
      "ad_reasoning": null,
      "ad_markers": [],
      "media_files": [
        {
          "url": "https://example.com/image.jpg",
          "type": "image",
          "thumbnail": "https://example.com/thumb.jpg"
        }
      ],
      "images": [
        {
          "url": "https://example.com/image.jpg",
          "type": "image",
          "thumbnail": "https://example.com/thumb.jpg"
        }
      ],
      "videos": [],
      "documents": [],
      "primary_image": "https://example.com/image.jpg"
    }
  ],
  "total": 1,
  "limit": 5,
  "offset": 0
}
```

### 2. 🏷️ Get Category Statistics

```http
GET /api/public/categories
```

Returns the count of articles per category.

#### Request Example
```bash
curl "https://news.dzarlax.dev/api/public/categories"
```

#### Response
```json
{
  "categories": {
    "all": 909,
    "serbia": 328,
    "tech": 256,
    "other": 215,
    "business": 89,
    "science": 27,
    "politics": 7,
    "international": 0
  }
}
```

## 📄 Data Structure

### Article Object

| Field | Type | Description |
|-------|------|-------------|
| `id` | integer | Unique article ID |
| `title` | string | Article title |
| `summary` | string | AI-generated summary |
| `url` | string | Link to the original article |
| `image_url` | string | Main image (legacy field) |
| `source_id` | integer | Source ID |
| `source_name` | string | Source name |
| `category` | string | Primary category |
| `categories` | array | Array of categories with confidence levels |
| `published_at` | string | Publication date (ISO 8601, always present) |
| `fetched_at` | string | Fetch date (ISO 8601) |
| `is_advertisement` | boolean | Whether it's an advertisement |
| `ad_confidence` | float | AI confidence in ad classification (0-1) |
| `ad_type` | string | Type of advertisement |
| `ad_reasoning` | string | Reason for ad classification |
| `ad_markers` | array | Advertisement markers found |
| `media_files` | array | All media files |
| `images` | array | Images only |
| `videos` | array | Videos only |
| `documents` | array | Documents only |
| `primary_image` | string | Primary image URL |

### Category Object

| Field | Type | Description |
|-------|------|-------------|
| `name` | string | System name of the category |
| `display_name` | string | Display name |
| `confidence` | float | AI categorization confidence (0-1) |
| `color` | string | UI color (hex) |

### Media File Object

| Field | Type | Description |
|-------|------|-------------|
| `url` | string | Media file URL |
| `type` | string | Type: "image", "video", "document" |
| `thumbnail` | string | Thumbnail URL (optional) |

## 🔍 Usage Examples

### Get Latest News
```bash
curl "https://news.dzarlax.dev/api/public/feed?limit=10"
```

### Get News for Serbia from last 12 hours
```bash
curl "https://news.dzarlax.dev/api/public/feed?category=serbia&since_hours=12&limit=20"
```

### Get Tech News including Ads
```bash
curl "https://news.dzarlax.dev/api/public/feed?category=tech&hide_ads=false&limit=15"
```

### Get Advertisements Only
```bash
curl "https://news.dzarlax.dev/api/public/feed?category=advertisements&limit=10"
```

### Pagination (Page 3, 20 items per page)
```bash
curl "https://news.dzarlax.dev/api/public/feed?limit=20&offset=40"
```

## ⚠️ Limitations and Recommendations

- **Rate Limiting**: No strict limits for public endpoints currently
- **Maximum Limit**: 1000 articles per request
- **Caching**: API results may be cached
- **Fallback**: Returns a test article if the database is unavailable

## 🌐 Web Interface

### Public Pages
- `/` - Main news feed page
- `/feed` - Alternative news feed
- `/cards` - Card view of news
- `/list` - List view of news

## 🔧 Technical Information

- **Backend**: FastAPI + SQLAlchemy
- **Database**: PostgreSQL  
- **AI**: Google Gemini API for summarization and categorization
- **Docker**: Full containerization
- **Health Check**: `GET /health`
