# RSS Summarizer

An application for collecting, summarizing, and distributing RSS feeds using AI summarization API.

## Features

- Collection and merging of RSS feeds from various sources
- AI-powered article summarization using API
- Caching of results to optimize API usage
- Storage in S3-compatible storage
- Error notifications via Telegram
- Daily news digest generation and distribution
- Category classification of articles
- Adaptive rate limiting for API calls
- Comprehensive logging and monitoring

## Requirements

- Python 3.8+
- Access to AI summarization API
- S3-compatible storage (e.g., AWS S3, Yandex Object Storage)
- Telegram bot (optional, for notifications)
- Telegraph API access (for news digest)

## Installation

1. Clone the repository:
```bash
git clone https://github.com/yourusername/rss-summarizer.git
cd rss-summarizer
```

2. Create and activate a virtual environment:
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

3. Install dependencies:
```bash
pip install -r src/requirements.txt
```

4. Set up environment variables:
```bash
cp src/.env.example src/.env
```

5. Edit the `.env` file with your values for all variables.

## Configuration

Edit the `.env` file and specify the following parameters:

### API Settings
- `endpoint_300`: Summarization API endpoint URL
- `token_300`: API authorization token
- `RPS`: Maximum requests per second to the API
- `CONSTRUCTOR_KM_API`: News digest API endpoint
- `CONSTRUCTOR_KM_API_KEY`: News digest API key
- `MODEL`: AI model name for classification

### S3 Settings
- `BUCKET_NAME`: S3 bucket name
- `ENDPOINT_URL`: S3-compatible storage URL
- `ACCESS_KEY`: Access key
- `SECRET_KEY`: Secret key
- `rss_300_file_name`: RSS feed file name for storage

### RSS Settings
- `logo_url`: Default logo URL
- `RSS_LINKS`: URL of the file containing RSS feed list
- `feed_url`: URL for the main RSS feed

### Telegram Settings
- `TELEGRAM_BOT_TOKEN`: Telegram bot token
- `TELEGRAM_CHAT_ID`: Chat ID for notifications
- `TELEGRAM_CHAT_ID_NEWS`: Chat ID for news digest
- `TELEGRAPH_ACCESS_TOKEN`: Telegraph API access token

## Usage

### RSS Feed Processing
Run the summarization script:
```bash
cd src
python summarization.py
```

### Daily News Digest
Run the news digest script:
```bash
cd src
python evening_news_Constructor_KM.py [prod|test]
```

## Project Structure

- `src/summarization.py`: Main RSS feed processing script
- `src/evening_news_Constructor_KM.py`: Daily news digest generation script
- `src/shared.py`: Common functions and utilities
- `src/requirements.txt`: Project dependencies
- `src/.env`: Environment variables file (not included in repository)
- `src/.env.example`: Example environment variables file

## Features in Detail

### RSS Feed Processing
- Merges multiple RSS feeds into a single feed
- Summarizes articles using AI
- Caches results to minimize API usage
- Stores results in S3-compatible storage
- Implements adaptive rate limiting
- Provides comprehensive logging and monitoring

### Daily News Digest
- Generates daily news summaries
- Classifies articles into categories
- Creates formatted news digests
- Distributes digests via Telegram
- Publishes detailed versions on Telegraph
- Supports both production and test environments

## Logging

Logs are saved to `output.log` in the project root directory. Logging level can be configured in the `setup_logging()` function in both scripts.

## Error Handling

- Comprehensive error handling and logging
- Automatic retries for API calls
- Telegram notifications for critical errors
- Rate limiting and backoff strategies
- Cache management for API results

## Monitoring

The application includes:
- API usage monitoring
- Response time tracking
- Error rate monitoring
- Daily quota tracking
- Performance statistics logging
