# Telegram Монітор Каналів

## Опис

Інструмент для моніторингу обраних Telegram каналів з можливістю фільтрації повідомлень за ключовими словами та пересилання їх у цільовий канал.

## Особливості

- ✅ Моніторинг тільки вказаних у конфігурації каналів (без зайвого навантаження)
- ✅ Фільтрація повідомлень за ключовими словами
- ✅ Автоматичне пересилання повідомлень у цільовий канал
- ✅ Гаряче оновлення конфігурації без перезапуску бота
- ✅ Обробка помилок та автоматичне відновлення після збоїв
- ✅ Детальне логування для відстеження роботи

## Технічні вимоги

- Python 3.8+
- Доступ до Telegram API (api_id та api_hash)
- Телефонний номер для авторизації в Telegram

## Встановлення

1. Клонуйте репозиторій:

```bash
git clone https://github.com/username/tg-bot.git
cd tg-bot
```

2. Встановіть залежності:

```bash
pip install -r requirements.txt
```

## Налаштування

### 1. Отримання Telegram API доступу

1. Відвідайте https://my.telegram.org/auth
2. Увійдіть в систему
3. Перейдіть до "API development tools"
4. Створіть новий додаток (заповніть будь-якими даними)
5. Запишіть `api_id` та `api_hash`

### 2. Налаштування конфігурації

Створіть або відредагуйте файл `config.yaml`:

```yaml
api_id: "12345678" # Ваш Telegram API ID
api_hash: "abcdef0123456789abcdef0123456789" # Ваш Telegram API Hash
phone_number: "+380123456789" # Ваш номер телефону для авторизації
target_channel_id: "1234567890" # ID цільового каналу для пересилання

# Канали для моніторингу
channels:
  - channel_id: "1111111111" # ID каналу для моніторингу
    keywords: ["ключове слово 1", "ключове слово 2"] # Список ключових слів (якщо порожній - пересилаються всі повідомлення)

  - channel_id: "2222222222" # ID іншого каналу
    keywords: [] # Порожній список - пересилаються всі повідомлення з цього каналу
```

### 3. Отримання ID каналів

Для отримання ID каналу:

1. Перешліть повідомлення з потрібного каналу в @userinfobot
2. Бот покаже ID каналу в форматі "forwarded from: НАЗВА_КАНАЛУ (id: XXXXXXXXXX)"
3. Використовуйте цей ID в конфігурації

## Запуск

### Використання bat-файлу (Windows)

Просто двічі клацніть `run_monitor.bat` або запустіть його з командного рядка:

```bash
run_monitor.bat
```

### Запуск скрипту напряму

```bash
python monitor.py
```

## Перша авторизація

При першому запуску вам буде запропоновано:

1. Ввести код підтвердження, надісланий у Telegram
2. (Можливо) ввести пароль від двофакторної автентифікації

Після успішної авторизації сесія буде збережена, і повторна авторизація не знадобиться.

## Як це працює

1. Бот автентифікується в Telegram
2. Встановлює моніторинг тільки для вказаних у конфігурації каналів
3. Періодично (кожні 10 секунд) перевіряє наявність нових повідомлень
4. Фільтрує повідомлення за ключовими словами
5. Пересилає відповідні повідомлення в цільовий канал
6. Кожні 30 секунд перевіряє зміни у конфігурації

## Додаткова інформація

- Для перегляду логів відкрийте файл `telegram_monitor.log`
- При зміні `config.yaml` бот автоматично застосує нові налаштування без перезапуску
- Для коректної роботи необхідно мати доступ до всіх вказаних каналів

## Вирішення проблем

- **Помилка авторизації**: Видаліть файли `.session` та `.session-journal` і запустіть скрипт заново
- **Канал не моніториться**: Переконайтеся, що вказано правильний ID і ви є учасником каналу
- **Повідомлення не пересилаються**: Перевірте, чи маєте ви право писати в цільовий канал
