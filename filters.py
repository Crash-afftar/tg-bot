def check_keywords(message, keywords):
    """
    Перевіряє наявність ключових слів у повідомленні
    
    :param message: текст повідомлення
    :param keywords: список ключових слів
    :return: True, якщо знайдено хоча б одне ключове слово
    """
    message_lower = message.lower()
    return any(keyword.lower() in message_lower for keyword in keywords)

def filter_message(message, keywords):
    """
    Фільтрує повідомлення за ключовими словами
    
    :param message: повідомлення
    :param keywords: список ключових слів
    :return: True, якщо повідомлення проходить фільтр
    """
    if not keywords:  # Якщо список ключових слів пустий, пропускаємо всі повідомлення
        return True
    return check_keywords(message, keywords) 