# watermarkbot

MAX-бот: водяной знак на фото/видео в личке и каналах. Продуктовое ТЗ — [`TZ.md`](TZ.md).

## Локально

Контейнеры — **OrbStack** (контекст `orbstack`), не Docker Desktop. CLI тот же: `docker` / `docker compose`.

1. Python 3.12, ffmpeg, OrbStack запущен (`docker context show` → `orbstack`).
2. Скопировать `.env.example` → `.env`, вписать `MAX_TOKEN`.
3. Поднять Postgres на хост-порт **5433**: `docker compose up -d postgres`.
4. Запуск бота (long-poll): `./run.sh`.

`DATABASE_URL` по умолчанию: `postgresql://watermark:watermark@127.0.0.1:5433/watermarkbot`.

Порт API `8010` (`WEBHOOK_PATH=/max-webhook`). Без токена или без `user_id` из `GET /me` процесс не стартует.

Полный compose (bot + postgres) через OrbStack: `docker compose up --build` после заполненного `.env`.

## Тесты

```
python3 -m venv .venv
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest -q
```

ffmpeg нужен для `tests/test_video.py`.
