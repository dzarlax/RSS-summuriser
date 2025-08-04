# Docker Deployment Guide

## Автоматическая сборка и публикация

### GitHub Action

Настроен автоматический workflow для сборки и публикации Docker образов:

**Triggers:**
- Push в main branch (при изменении в папке v2/)
- Pull Request
- Release публикация
- Manual dispatch

**Возможности:**
- ✅ Multi-platform build (AMD64, ARM64)
- ✅ Автоматические теги на основе git refs
- ✅ GitHub Actions cache для ускорения сборки
- ✅ Security scanning с Trivy
- ✅ Автообновление описания на DockerHub
- ✅ Тестирование образа перед публикацией

### Теги образов

- `latest` - Последняя стабильная версия (main branch)
- `main` - Последний билд из main branch
- `v2.x.x` - Specific version releases
- `pr-XXX` - Pull request previews

## Настройка DockerHub

### Необходимые секреты в GitHub

```bash
# GitHub Repository Settings -> Secrets and variables -> Actions
DOCKERHUB_USERNAME=your_dockerhub_username
DOCKERHUB_TOKEN=your_dockerhub_access_token
```

### Создание Access Token

1. Войти в [DockerHub](https://hub.docker.com)
2. Account Settings -> Security -> Access Tokens
3. New Access Token -> Read, Write, Delete
4. Сохранить токен в GitHub Secrets

## Локальная сборка

### Простая сборка
```bash
cd v2
docker build -f docker/Dockerfile -t rss-summarizer .
```

### Сборка с метаданными
```bash
docker build -f docker/Dockerfile \
  --build-arg BUILDTIME="$(date -u +'%Y-%m-%dT%H:%M:%SZ')" \
  --build-arg VERSION="2.0.0" \
  --build-arg REVISION="$(git rev-parse HEAD)" \
  -t rss-summarizer:local .
```

### Multi-platform сборка
```bash
# Настройка buildx
docker buildx create --name multiplatform --use
docker buildx inspect --bootstrap

# Сборка для нескольких платформ
docker buildx build \
  --platform linux/amd64,linux/arm64 \
  -f docker/Dockerfile \
  -t rss-summarizer:multiplatform \
  --push .
```

## Production Deployment

### Минимальный production setup

```yaml
version: '3.8'
services:
  web:
    image: dzarlax/rss-summarizer:latest
    ports:
      - "8000:8000"
    environment:
      - DATABASE_URL=postgresql://user:pass@postgres:5432/newsdb
      - CONSTRUCTOR_KM_API=your_api_endpoint
      - CONSTRUCTOR_KM_API_KEY=Bearer your_api_key
      - TELEGRAM_TOKEN=your_bot_token
      - TELEGRAM_CHAT_ID=your_chat_id
    depends_on:
      - postgres
    restart: unless-stopped
    
  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: newsdb
      POSTGRES_USER: newsuser
      POSTGRES_PASSWORD: newspass123
    volumes:
      - postgres_data:/var/lib/postgresql/data
    restart: unless-stopped

volumes:
  postgres_data:
```

### Production с nginx и SSL

```yaml
version: '3.8'
services:
  nginx:
    image: nginx:alpine
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf:ro
      - ./ssl:/etc/ssl:ro
    depends_on:
      - web
    restart: unless-stopped

  web:
    image: dzarlax/rss-summarizer:latest
    expose:
      - "8000"
    environment:
      - DATABASE_URL=postgresql://newsuser:${DB_PASSWORD}@postgres:5432/newsdb
      - CONSTRUCTOR_KM_API=${CONSTRUCTOR_KM_API}
      - CONSTRUCTOR_KM_API_KEY=${CONSTRUCTOR_KM_API_KEY}
      - TELEGRAM_TOKEN=${TELEGRAM_TOKEN}
      - TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
      - LOG_LEVEL=INFO
      - MAX_WORKERS=5
    depends_on:
      postgres:
        condition: service_healthy
    restart: unless-stopped
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8000/health"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  postgres:
    image: postgres:15-alpine
    environment:
      POSTGRES_DB: newsdb
      POSTGRES_USER: newsuser
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - postgres_data:/var/lib/postgresql/data
      - ./backups:/backup
    restart: unless-stopped
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -U newsuser -d newsdb"]
      interval: 10s
      timeout: 5s
      retries: 5

volumes:
  postgres_data:
```

## Kubernetes Deployment

### Namespace
```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: rss-aggregator
```

### ConfigMap
```yaml
apiVersion: v1
kind: ConfigMap
metadata:
  name: rss-config
  namespace: rss-aggregator
data:
  LOG_LEVEL: "INFO"
  MAX_WORKERS: "5"
  SUMMARIZATION_MODEL: "gpt-4o-mini"
  CATEGORIZATION_MODEL: "gpt-4o-mini"
  DIGEST_MODEL: "gpt-4.1"
```

### Secret
```yaml
apiVersion: v1
kind: Secret
metadata:
  name: rss-secrets
  namespace: rss-aggregator
type: Opaque
stringData:
  DATABASE_URL: "postgresql://newsuser:password@postgres-service:5432/newsdb"
  CONSTRUCTOR_KM_API: "your_api_endpoint"
  CONSTRUCTOR_KM_API_KEY: "Bearer your_api_key"
  TELEGRAM_TOKEN: "your_bot_token"
  TELEGRAM_CHAT_ID: "your_chat_id"
```

### Deployment
```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rss-aggregator
  namespace: rss-aggregator
spec:
  replicas: 2
  selector:
    matchLabels:
      app: rss-aggregator
  template:
    metadata:
      labels:
        app: rss-aggregator
    spec:
      containers:
      - name: rss-aggregator
        image: dzarlax/rss-summarizer:latest
        ports:
        - containerPort: 8000
        envFrom:
        - configMapRef:
            name: rss-config
        - secretRef:
            name: rss-secrets
        livenessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 60
          periodSeconds: 30
        readinessProbe:
          httpGet:
            path: /health
            port: 8000
          initialDelaySeconds: 30
          periodSeconds: 10
        resources:
          requests:
            memory: "512Mi"
            cpu: "250m"
          limits:
            memory: "1Gi"
            cpu: "500m"
```

### Service
```yaml
apiVersion: v1
kind: Service
metadata:
  name: rss-service
  namespace: rss-aggregator
spec:
  selector:
    app: rss-aggregator
  ports:
  - port: 80
    targetPort: 8000
  type: ClusterIP
```

## Мониторинг и логирование

### Prometheus metrics
```yaml
# Добавить в deployment
- name: metrics
  containerPort: 8000
  
# ServiceMonitor для Prometheus Operator
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: rss-aggregator
spec:
  selector:
    matchLabels:
      app: rss-aggregator
  endpoints:
  - port: metrics
    path: /metrics
```

### Grafana Dashboard
```json
{
  "dashboard": {
    "title": "RSS Aggregator",
    "panels": [
      {
        "title": "HTTP Requests",
        "type": "graph",
        "targets": [
          {
            "expr": "rate(http_requests_total[5m])"
          }
        ]
      }
    ]
  }
}
```

## Безопасность

### Security best practices

1. **Non-root user**: Образ запускается под пользователем `appuser` (uid: 1000)
2. **No secrets in layers**: Все секреты передаются через environment variables
3. **Regular scanning**: Автоматическое сканирование уязвимостей с Trivy
4. **Minimal base image**: Использование python:3.12-slim
5. **Health checks**: Встроенные health checks для контейнера

### Network security
```yaml
# Network policies для Kubernetes
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: rss-network-policy
spec:
  podSelector:
    matchLabels:
      app: rss-aggregator
  policyTypes:
  - Ingress
  - Egress
  ingress:
  - from:
    - podSelector:
        matchLabels:
          app: nginx
    ports:
    - protocol: TCP
      port: 8000
  egress:
  - to:
    - podSelector:
        matchLabels:
          app: postgres
    ports:
    - protocol: TCP
      port: 5432
  - to: []  # Allow external API calls
    ports:
    - protocol: TCP
      port: 443
```

## Troubleshooting

### Частые проблемы

**1. Контейнер не стартует**
```bash
# Проверить логи
docker logs rss-aggregator

# Проверить health check
docker inspect rss-aggregator | grep Health -A 10
```

**2. Ошибки подключения к БД**
```bash
# Проверить сетевое соединение
docker exec rss-aggregator ping postgres

# Проверить переменные окружения
docker exec rss-aggregator env | grep DATABASE
```

**3. Playwright не работает**
```bash
# Проверить установку браузеров
docker exec rss-aggregator playwright install-deps
docker exec rss-aggregator playwright install chromium
```

### Debug режим
```yaml
# Добавить в docker-compose.yml
environment:
  - LOG_LEVEL=DEBUG
  - DEVELOPMENT=true
```

### Профилирование
```bash
# Подключиться к контейнеру
docker exec -it rss-aggregator bash

# Запустить профилировщик
python -m cProfile -o profile.stats -m news_aggregator.cli process
```

## Мигарция

### Обновление образа
```bash
# Pull новый образ
docker pull dzarlax/rss-summarizer:latest

# Обновить compose
docker-compose pull
docker-compose up -d
```

### Rollback
```bash
# Откатиться к предыдущей версии
docker-compose down
docker pull dzarlax/rss-summarizer:v2.0.0
# Обновить docker-compose.yml с нужным тегом
docker-compose up -d
```