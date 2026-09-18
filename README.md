# Seal Life Bot 🦭

Telegram-бот про тюленей с боёвкой, крафтом, подземельями, кланами и многим другим.

## Деплой на Render

1. Загрузите репозиторий на GitHub
2. На [dashboard.render.com](https://dashboard.render.com) создайте новый Blueprint, указав этот репозиторий
3. Установите переменную окружения `TELEGRAM_BOT_TOKEN` — токен вашего бота от @BotFather
4. Render автоматически соберёт и запустит бота

## Локальный запуск

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN=ваш_токен
python main.py
```
