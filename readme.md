# Проект новостной рассылки

## Описание проекта
Проект "Новостная рассылка" разработан для автоматизации процессов сбора, обработки и распространения новостей с использованием технологий RSS-лент и мессенджера Telegram. Этот проект помогает упростить доступ к актуальным новостям, позволяя пользователям быстро получать обновления по интересующим их темам без необходимости вручную искать информацию на различных новостных порталах. Проект состоит из двух основных компонентов: скрипта для парсинга и краткого изложения новостей (`summarization.py`) и скрипта для отправки этих изложений пользователям через Telegram (`evening_news2.py`).

### Основные задачи проекта
1. **Автоматизация сбора новостей**: `summarization.py` парсит RSS-ленты и извлекает статьи.
2. **Генерация кратких изложений**: Создание сокращенных версий статей с помощью алгоритмов обработки текста.
3. **Хранение данных**: Изложения сохраняются в облачном хранилище для дальнейшей обработки.
4. **Форматирование и отправка новостей**: `evening_news2.py` отправляет изложения пользователям через Telegram, используя при этом технологии нейронных сетей для оптимизации текста.

### Использование нейронных сетей
В `evening_news2.py` применяются нейронные сети для дальнейшей обработки и оптимизации текстов новостей перед их отправкой. Это позволяет улучшить читаемость и информативность текстов, делая их более привлекательными для конечного пользователя.

### Использование Telegraph
Для сообщений, превышающих максимально допустимую длину в Telegram, используется платформа Telegraph. Скрипт автоматически создает страницу на Telegraph и отправляет пользователю ссылку на нее, что позволяет обойти ограничения по длине сообщений и предоставить пользователю полный текст статьи.


## Требования
Для работы проекта необходимы Python 3.6+ и библиотеки из файла `requirements.txt`. Вот основные из них:
- pandas
- requests
- feedparser
- pytz
- BeautifulSoup
- boto3
- telegraph
- scikit-learn
- llama-cpp-python

