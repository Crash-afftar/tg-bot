import asyncio
import logging
import yaml
import re
import os
import time
from telethon import TelegramClient, events
from telethon.errors import (
    ChannelPrivateError, 
    InviteHashExpiredError, 
    InviteHashInvalidError
)
from telethon.tl.functions.channels import JoinChannelRequest
from telethon.tl.functions.messages import ImportChatInviteRequest
from telethon.tl.types import InputPeerChannel, Channel, PeerChannel
from filters import filter_message

# Створення класу фільтру для виключення Telethon логів
class TelethonFilter(logging.Filter):
    def filter(self, record):
        # Якщо лог починається з відомих Telethon повідомлень, фільтруємо його
        if any(record.getMessage().startswith(prefix) for prefix in 
              ["Handling", "Receiving", "Assigned", "Encrypting", "Encrypted", "Waiting"]):
            return False
        return True

# Налаштування розширеного логування
def setup_logging():
    # Основний логер
    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG)
    
    # Форматер для логів
    formatter = logging.Formatter('%(asctime)s - %(levelname)s: %(message)s')
    
    # Обробник для файлу (зберігає всі деталі)
    file_handler = logging.FileHandler('telegram_monitor.log', encoding='utf-8')
    file_handler.setLevel(logging.DEBUG)
    file_handler.setFormatter(formatter)
    
    # Обробник для консолі (тільки важливі повідомлення)
    console_handler = logging.StreamHandler()
    console_handler.setLevel(logging.INFO)  # Тільки INFO і вище
    console_handler.setFormatter(formatter)
    console_handler.addFilter(TelethonFilter())  # Додаємо фільтр для Telethon
    
    # Додаємо обробники до логера
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)
    
    # Налаштовуємо логер Telethon на нижчий рівень
    telethon_logger = logging.getLogger('telethon')
    telethon_logger.setLevel(logging.INFO)  # Менше Telethon повідомлень у файлі

# Ініціалізуємо логування
setup_logging()

def extract_channel_identifier(link):
    """
    Витягує username та/або invite hash з посилання на канал
    
    :param link: посилання на канал
    :return: (username, invite_hash)
    """
    if not link:
        return None, None
    
    # Спроба знайти запрошувальне посилання (t.me/+HASH або t.me/joinchat/HASH)
    invite_match = re.search(r't\.me/(?:joinchat/|\+)([a-zA-Z0-9_-]+)', link)
    invite_hash = invite_match.group(1) if invite_match else None
    
    # Спроба знайти звичайне посилання (t.me/USERNAME)
    username_match = re.search(r't\.me/(?!joinchat)(?!\+)([a-zA-Z0-9_]+)', link)
    username = username_match.group(1) if username_match else None
    
    # Перевірка на випадок, якщо передано просто username без посилання
    username_only_match = re.match(r'^([a-zA-Z0-9_]+)$', link)
    if not username and not invite_hash and username_only_match:
        username = username_only_match.group(1)
    
    return username, invite_hash

class TelegramMonitor:
    def __init__(self):
        self.config = None
        self.client = None
        self.logger = logging.getLogger(__name__)  # Використовуємо loggers для кращої організації
        self.config_last_modified = 0
        self.message_handlers = []
        self.config_path = 'config.yaml'
    
    async def load_config(self):
        """Завантаження конфігурації з файлу."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
                self.config_last_modified = os.path.getmtime(self.config_path)
                logging.info("Конфігурація оновлена успішно")
                return True
        except Exception as e:
            logging.error(f"Помилка читання конфігурації: {e}")
            return False
    
    async def update_handlers(self):
        """Оновлює обробники подій відповідно до поточної конфігурації."""
        # Видаляємо старі обробники
        for handler in self.message_handlers:
            self.client.remove_event_handler(handler)
        
        self.message_handlers = []
        
        # Отримуємо список ID каналів для моніторингу
        channel_ids = [int(channel_config['channel_id']) for channel_config in self.config.get('channels', [])]
        logging.info(f"Оновлено моніторинг каналів: {channel_ids}")
        
        # Виводимо більше інформації про канали
        for channel_config in self.config.get('channels', []):
            channel_id = int(channel_config['channel_id'])
            try:
                entity = await self.client.get_entity(PeerChannel(channel_id))
                logging.info(f"Знайдено канал: {entity.title} (ID: {channel_id})")
            except Exception as e:
                logging.warning(f"Не вдалося отримати інформацію про канал {channel_id}: {e}")
        
        # Виводимо інформацію про цільовий канал
        target_channel_id = self.config.get('target_channel_id')
        try:
            target_entity = await self.client.get_entity(PeerChannel(int(target_channel_id)))
            logging.info(f"Цільовий канал: {target_entity.title} (ID: {target_channel_id})")
        except Exception as e:
            logging.error(f"Не вдалося отримати інформацію про цільовий канал {target_channel_id}: {e}")
        
        # Реєструємо новий обробник для визначених каналів
        @self.client.on(events.NewMessage(chats=channel_ids))
        async def handle_new_message(event):
            if not event.chat:
                return
            
            logging.info(f"Отримано повідомлення з каналу: {event.chat.title} (ID: {event.chat.id})")
            
            # Обробка повідомлення
            message_text = event.message.text or ''
            logging.info(f"Текст повідомлення: {message_text}")
            
            # Знаходимо налаштування для цього каналу
            current_channel_config = None
            for channel_config in self.config.get('channels', []):
                if int(channel_config['channel_id']) == event.chat.id:
                    current_channel_config = channel_config
                    keywords = current_channel_config.get('keywords', [])
                    logging.info(f"Знайдено конфігурацію для каналу {event.chat.id}. Ключові слова: {keywords}")
                    break
            
            if not current_channel_config:
                logging.warning(f"Не знайдено конфігурацію для каналу {event.chat.id}")
                return
            
            # Перевірка фільтрів за ключовими словами
            keywords = current_channel_config.get('keywords', [])
            should_forward = not keywords or filter_message(message_text, keywords)
            logging.info(f"Перевірка фільтрації: should_forward={should_forward}, keywords={keywords}")
            
            if should_forward:
                try:
                    # Отримання цільового каналу з загальної конфігурації
                    target_channel_id = self.config.get('target_channel_id')
                    
                    if target_channel_id:
                        # Використовуємо ID безпосередньо
                        await self.client.send_message(PeerChannel(int(target_channel_id)), message_text)
                        logging.info(f"Переслано повідомлення з {event.chat.id} ({event.chat.title}) до {target_channel_id}")
                    else:
                        logging.error("Не вказано ID цільового каналу в конфігурації")
                
                except Exception as e:
                    logging.error(f"Помилка пересилання: {e}")
            else:
                logging.info(f"Повідомлення не відповідає фільтрам, пересилання скасовано")
        
        # Зберігаємо обробник у списку для можливості видалення в майбутньому
        self.message_handlers.append(handle_new_message)
    
    async def check_config_updates(self):
        """Періодично перевіряє, чи оновився файл конфігурації, і перезавантажує його."""
        while True:
            try:
                # Перевіряємо, чи змінився файл конфігурації
                current_mtime = os.path.getmtime(self.config_path)
                if current_mtime > self.config_last_modified:
                    logging.info(f"Виявлено зміни у файлі конфігурації. Перезавантаження...")
                    
                    if await self.load_config():
                        await self.update_handlers()
                        logging.info("Конфігурацію успішно перезавантажено")
                    else:
                        logging.error("Не вдалося перезавантажити конфігурацію")
            except Exception as e:
                logging.error(f"Помилка при перевірці оновлень конфігурації: {e}")
            
            # Перевіряємо кожні 30 секунд
            await asyncio.sleep(30)
    
    async def start_client(self):
        await self.load_config()
        
        if not self.config:
            logging.error("Немає конфігурації!")
            return
        
        self.client = TelegramClient('session', 
                                     self.config['api_id'], 
                                     self.config['api_hash'])
        
        await self.client.start(phone=self.config['phone_number'])
        logging.info("Telegram клієнт авторизований")
        
        # Оновлюємо обробники подій
        await self.update_handlers()
        
        # Запускаємо перевірку оновлень конфігурації
        asyncio.create_task(self.check_config_updates())
        
        logging.info("Telegram монітор запущено")
        await self.client.run_until_disconnected()

async def main():
    monitor = TelegramMonitor()
    await monitor.start_client()

if __name__ == '__main__':
    asyncio.run(main()) 