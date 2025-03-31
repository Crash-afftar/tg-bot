import asyncio
import logging
import yaml
import re
import os
import time
import socket
import sys
import json
from telethon import TelegramClient
from telethon.errors import (
    ChannelPrivateError, 
    InviteHashExpiredError, 
    InviteHashInvalidError,
    FloodWaitError
)
from telethon.tl.types import PeerChannel
from filters import filter_message
from telethon.events import NewMessage

# Перевірка на одночасний запуск
def is_process_running():
    try:
        # Спроба створити сокет на локальному порту
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.bind(('localhost', 51423))  # Використовуємо унікальний порт
        sock.listen(1)
        return False  # Порт вільний, інший екземпляр не запущено
    except socket.error:
        return True  # Порт зайнятий, інший екземпляр запущено

# Створення класу фільтру для виключення Telethon логів
class TelethonFilter(logging.Filter):
    def filter(self, record):
        # Якщо лог починається з відомих Telethon повідомлень, фільтруємо його
        if any(record.getMessage().startswith(prefix) for prefix in 
              ["Handling", "Receiving", "Assigned", "Encrypting", "Encrypted", "Waiting", "Got difference"]):
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
    telethon_logger.setLevel(logging.WARNING)  # Ще менше логів від Telethon

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
        self.logger = logging.getLogger(__name__)
        self.config_last_modified = 0
        self.config_path = 'config.yaml'
        self.running = True
        self.connection_retries = 0
        self.max_connection_retries = 5
        self.message_handlers = []
        self.last_message_ids = {}  # Зберігає останні ID повідомлень для кожного каналу
        self.processed_messages = set()  # Множина IDs повідомлень, які вже були оброблені
    
    async def load_config(self):
        """Завантаження конфігурації з файлу."""
        try:
            with open(self.config_path, 'r', encoding='utf-8') as f:
                self.config = yaml.safe_load(f)
                self.config_last_modified = os.path.getmtime(self.config_path)
                logging.info("Конфігурацію оновлено успішно")
                return True
        except Exception as e:
            logging.error(f"Помилка читання конфігурації: {e}")
            return False
    
    async def check_config_updates(self):
        """Періодично перевіряє, чи оновився файл конфігурації, і перезавантажує його."""
        while self.running:
            try:
                # Перевіряємо, чи змінився файл конфігурації
                current_mtime = os.path.getmtime(self.config_path)
                if current_mtime > self.config_last_modified:
                    logging.info(f"Виявлено зміни у файлі конфігурації. Перезавантаження...")
                    
                    if await self.load_config():
                        logging.info("Конфігурацію успішно перезавантажено")
                    else:
                        logging.error("Не вдалося перезавантажити конфігурацію")
            except Exception as e:
                logging.error(f"Помилка при перевірці оновлень конфігурації: {e}", exc_info=True)
                # Продовжуємо спроби перевірки конфігурації
            
            # Перевіряємо кожні 30 секунд
            await asyncio.sleep(30)
    
    async def start_client(self):
        """Ініціалізує та запускає клієнт Telegram."""
        await self.load_config()
        
        if not self.config:
            logging.error("Немає конфігурації!")
            return
        
        # Використовуємо унікальне ім'я сесії, що включає hostname
        session_name = f"telegram_monitor_{socket.gethostname()}"
        logging.info(f"Використовуємо сесію: {session_name}")
        
        # Створюємо клієнт з оптимізованими налаштуваннями згідно документації Telegram API
        self.client = TelegramClient(
            session_name, 
            self.config['api_id'], 
            self.config['api_hash'],
            # Налаштування для оптимізованого отримання оновлень
            # catch_up=True - включає механізм різницевих оновлень
            # sequential_updates=False - дозволяє паралельну обробку оновлень
            catch_up=True,
            sequential_updates=False,
            request_retries=3,
            auto_reconnect=True,
            base_logger=logging.getLogger('telethon'),
            flood_sleep_threshold=60
        )
        
        try:
            # Підключаємося до Telegram
            await self.client.connect()
            
            # Авторизуємося, якщо потрібно
            if not await self.client.is_user_authorized():
                await self.client.start(phone=self.config['phone_number'])
                logging.info("Авторизацію завершено успішно")
            
            logging.info("Telegram клієнт підключено")
            
            # Оновлюємо обробники подій
            await self.update_handlers()
            
            # Запускаємо перевірку оновлень конфігурації
            asyncio.create_task(self.check_config_updates())
            
            # Запускаємо оптимізацію кешу діалогів для зменшення навантаження
            asyncio.create_task(self.optimize_dialogs_cache())
            
            # Запускаємо активне опитування каналів для швидшого отримання повідомлень
            asyncio.create_task(self.active_polling())
            
            logging.info("Telegram монітор запущено")
            
            try:
                # Очікуємо на завершення роботи клієнта
                await self.client.run_until_disconnected()
            except Exception as e:
                logging.error(f"Помилка в основному циклі: {e}", exc_info=True)
                # Спроба перезапуску клієнта в разі помилки
                logging.info("Спроба перезапуску через 10 секунд...")
                await asyncio.sleep(10)
                return await self.start_client()
        except Exception as e:
            logging.error(f"Помилка запуску клієнта: {e}", exc_info=True)
            # Спроба перезапуску у випадку помилки
            logging.info("Спроба перезапуску через 30 секунд...")
            await asyncio.sleep(30)
            return await self.start_client()
    
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
        # Важливо: chats=channel_ids вказує Telegram, які канали нас цікавлять
        @self.client.on(NewMessage(chats=channel_ids))
        async def handle_new_message(event):
            try:
                if not event.chat:
                    return
                
                # Перевіряємо, чи це повідомлення вже було оброблено
                msg_id = f"{event.chat.id}_{event.message.id}"
                if msg_id in self.processed_messages:
                    logging.debug(f"Повідомлення {msg_id} вже було оброблено раніше, пропускаємо")
                    return
                
                # Додаємо повідомлення до списку оброблених
                self.processed_messages.add(msg_id)
                
                # Обмежуємо розмір множини оброблених повідомлень (зберігаємо останні 1000)
                if len(self.processed_messages) > 1000:
                    # Видаляємо старі записи
                    excess = len(self.processed_messages) - 1000
                    self.processed_messages = set(list(self.processed_messages)[excess:])
                
                logging.info(f"Отримано повідомлення з каналу: {event.chat.title} (ID: {event.chat.id})")
                
                # Оновлюємо останній ID повідомлення для каналу
                self.last_message_ids[event.chat.id] = event.message.id
                
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
                            await self.client.forward_messages(PeerChannel(int(target_channel_id)), event.message)
                            logging.info(f"Переслано повідомлення з {event.chat.title} (ID: {event.chat.id}) до {target_channel_id}")
                        else:
                            logging.error("Не вказано ID цільового каналу в конфігурації")
                    
                    except Exception as e:
                        logging.error(f"Помилка пересилання: {e}")
                else:
                    logging.info(f"Повідомлення не відповідає фільтрам, пересилання скасовано")
            except Exception as e:
                logging.error(f"Помилка обробки повідомлення: {e}", exc_info=True)
                # Продовжуємо роботу бота, незважаючи на помилку в обробці одного повідомлення
        
        # Зберігаємо обробник у списку для можливості видалення в майбутньому
        self.message_handlers.append(handle_new_message)
    
    async def optimize_dialogs_cache(self):
        """Періодично оптимізує кеш діалогів для зменшення навантаження"""
        try:
            while True:
                try:
                    # Отримуємо список ID каналів для моніторингу
                    channel_ids = [int(channel_config['channel_id']) for channel_config in self.config.get('channels', [])]
                    
                    # Оптимізуємо кеш діалогів
                    from telethon.tl.functions.messages import GetDialogFiltersRequest
                    await self.client(GetDialogFiltersRequest())
                    
                    # Оновлюємо кеш тільки для потрібних каналів
                    for channel_id in channel_ids:
                        try:
                            # Отримуємо entity каналу і кешуємо його
                            entity = await self.client.get_entity(PeerChannel(channel_id))
                            logging.debug(f"Оновлено кеш для каналу: {entity.title} (ID: {channel_id})")
                        except Exception as e:
                            logging.debug(f"Помилка при оновленні кешу для каналу {channel_id}: {e}")
                    
                    # Викликаємо catch_up для отримання останніх оновлень
                    await self.client.catch_up()
                    logging.debug("Кеш діалогів оптимізовано")
                    
                except Exception as e:
                    logging.error(f"Помилка при оптимізації кешу діалогів: {e}", exc_info=True)
                
                # Оптимізуємо кеш кожні 5 хвилин
                await asyncio.sleep(300)
        except asyncio.CancelledError:
            logging.info("Завдання оптимізації кешу скасовано")
        except Exception as e:
            logging.error(f"Критична помилка в циклі оптимізації кешу: {e}", exc_info=True)

    async def active_polling(self):
        """Активне опитування каналів для швидшого отримання повідомлень"""
        try:
            # Інтервал опитування в секундах
            poll_interval = 30  # 30 секунд
            
            logging.info(f"Запуск активного опитування каналів (інтервал: {poll_interval} секунд)")
            
            while True:
                try:
                    # Отримуємо список ID каналів для моніторингу
                    channel_ids = [int(channel_config['channel_id']) for channel_config in self.config.get('channels', [])]
                    
                    if not channel_ids:
                        logging.warning("Не знайдено жодного каналу для опитування")
                        await asyncio.sleep(poll_interval)
                        continue
                    
                    for channel_id in channel_ids:
                        try:
                            # Отримуємо entity каналу 
                            entity = await self.client.get_entity(PeerChannel(channel_id))
                            
                            # Запитуємо останні 10 повідомлень
                            messages = await self.client.get_messages(entity, limit=10)
                            
                            if not messages:
                                continue
                            
                            # Перевіряємо наявність каналу в словнику останніх повідомлень
                            if channel_id not in self.last_message_ids:
                                # Перший запуск - запам'ятовуємо ID останнього повідомлення
                                self.last_message_ids[channel_id] = messages[0].id
                                logging.debug(f"Ініціалізовано ID останнього повідомлення для каналу {entity.title} (ID: {channel_id}): {self.last_message_ids[channel_id]}")
                                continue
                            
                            # Шукаємо нові повідомлення (з ID більшим ніж збережений)
                            last_id = self.last_message_ids[channel_id]
                            new_messages = [msg for msg in messages if msg.id > last_id]
                            
                            if not new_messages:
                                continue
                            
                            # Сортуємо повідомлення за ID (від старого до нового)
                            new_messages.sort(key=lambda msg: msg.id)
                            
                            logging.info(f"Знайдено {len(new_messages)} нових повідомлень у каналі {entity.title} (ID: {channel_id}) через активне опитування")
                            
                            # Обробляємо кожне нове повідомлення
                            for message in new_messages:
                                # Перевіряємо, чи це повідомлення вже було оброблено
                                msg_id = f"{channel_id}_{message.id}"
                                if msg_id in self.processed_messages:
                                    logging.debug(f"Повідомлення {msg_id} вже було оброблено раніше, пропускаємо")
                                    continue
                                
                                # Додаємо повідомлення до списку оброблених
                                self.processed_messages.add(msg_id)
                                
                                # Обмежуємо розмір множини оброблених повідомлень (зберігаємо останні 1000)
                                if len(self.processed_messages) > 1000:
                                    # Видаляємо старі записи
                                    excess = len(self.processed_messages) - 1000
                                    self.processed_messages = set(list(self.processed_messages)[excess:])
                                
                                # Оновлюємо ID останнього повідомлення
                                self.last_message_ids[channel_id] = message.id
                                
                                # Обробка повідомлення
                                message_text = message.text or ''
                                
                                # Знаходимо налаштування для цього каналу
                                current_channel_config = None
                                for channel_config in self.config.get('channels', []):
                                    if int(channel_config['channel_id']) == channel_id:
                                        current_channel_config = channel_config
                                        break
                                
                                if not current_channel_config:
                                    logging.warning(f"Не знайдено конфігурацію для каналу {entity.title} (ID: {channel_id})")
                                    continue
                                
                                # Перевірка фільтрів за ключовими словами
                                keywords = current_channel_config.get('keywords', [])
                                should_forward = not keywords or filter_message(message_text, keywords)
                                
                                if should_forward:
                                    try:
                                        # Отримання цільового каналу з загальної конфігурації
                                        target_channel_id = self.config.get('target_channel_id')
                                        
                                        if target_channel_id:
                                            # Використовуємо ID безпосередньо
                                            await self.client.forward_messages(PeerChannel(int(target_channel_id)), message)
                                            logging.info(f"[Активне опитування] Переслано повідомлення з {entity.title} (ID: {channel_id}) до {target_channel_id}")
                                        else:
                                            logging.error("Не вказано ID цільового каналу в конфігурації")
                                    except Exception as e:
                                        logging.error(f"Помилка пересилання: {e}")
                                else:
                                    logging.info(f"[Активне опитування] Повідомлення з {entity.title} (ID: {channel_id}) не відповідає фільтрам")
                            
                        except FloodWaitError as e:
                            logging.warning(f"Потрібно почекати {e.seconds} секунд перед наступним запитом")
                            await asyncio.sleep(e.seconds)
                        except Exception as e:
                            logging.error(f"Помилка при опитуванні каналу {channel_id}: {e}")
                    
                except Exception as e:
                    logging.error(f"Помилка в циклі активного опитування: {e}", exc_info=True)
                
                # Чекаємо перед наступним опитуванням
                await asyncio.sleep(poll_interval)
                
        except asyncio.CancelledError:
            logging.info("Завдання активного опитування скасовано")
        except Exception as e:
            logging.error(f"Критична помилка в циклі активного опитування: {e}", exc_info=True)
            # Перезапускаємо цикл опитування
            logging.info("Перезапуск циклу активного опитування через 10 секунд...")
            await asyncio.sleep(10)
            return await self.active_polling()

async def main():
    # Перевірка на одночасний запуск
    if is_process_running():
        logging.error("Інший екземпляр бота вже запущено. Завершення роботи.")
        print("ПОМИЛКА: Інший екземпляр бота вже запущено!")
        sys.exit(1)
        
    try:
        monitor = TelegramMonitor()
        await monitor.start_client()
    except KeyboardInterrupt:
        logging.info("Отримано сигнал завершення роботи")
    except Exception as e:
        logging.critical(f"Критична помилка програми: {e}", exc_info=True)
    finally:
        logging.info("Програму завершено")

if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("Програму завершено користувачем")
    except Exception as e:
        print(f"Критична помилка: {e}")
        logging.critical(f"Критична помилка при запуску програми: {e}", exc_info=True) 