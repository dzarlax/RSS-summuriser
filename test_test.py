import pytest
from unittest.mock import patch, MagicMock
from main import get_iam_api_token, count_tokens, process_entry, ...

def test_get_iam_api_token():
    # Имитируем успешный ответ от IAM
    with patch('requests.post') as mocked_post:
        mocked_response = MagicMock()
        mocked_response.json.return_value = {'iamToken': 'sample_token'}
        mocked_response.raise_for_status.return_value = None
        mocked_post.return_value = mocked_response

        result = get_iam_api_token('sa_id', 'key_id', 'https://iam_url', 'private_key')
        assert result == 'sample_token'

def test_count_tokens():
    # Имитируем успешный ответ от API токенизации
    with patch('requests.post') as mocked_post:
        mocked_response = MagicMock()
        mocked_response.json.return_value = {'tokens': [1, 2, 3]}
        mocked_post.return_value = mocked_response

        result = count_tokens('sample_text', 'api_key')
        assert result == 3

def test_process_entry():
    # Тест для проверки функции process_entry
    entry = MagicMock()
    entry.link = 'https://example.com'
    entry.published = 'Wed, 20 Oct 2023 12:00:00 +0000'
    entry.title = 'Sample title'
    entry.summary = 'Sample summary'
    
    with patch('trafilatura.fetch_url') as mocked_fetch, \
     patch('trafilatura.extract') as mocked_extract, \
     patch('main.summarize') as mocked_summarize:
        mocked_fetch.return_value = None
        mocked_extract.return_value = 'Extracted text'
        mocked_summarize.return_value = 'Summarized text'
        
        two_days_ago = datetime.strptime('Mon, 18 Oct 2023 12:00:00 +0000', '%a, %d %b %Y %H:%M:%S %z').replace(tzinfo=None)
    result = process_entry(entry, two_days_ago, 'api_key', [])
    
    assert result is not None
    assert result['description'] == 'Summarized text'
    assert result['title'] == 'Sample title'
