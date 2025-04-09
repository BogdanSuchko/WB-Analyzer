import os
import logging
from typing import List, Dict, Any
import re
import time
from dotenv import load_dotenv
from groq import Groq

# Загружаем переменные окружения из .env файла
load_dotenv()

# Настраиваем логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ReviewAnalyzer')

class ReviewAnalyzer:
    """
    Класс для анализа отзывов с Wildberries с использованием Groq API и модели Llama-4-Scout
    """
    
    @staticmethod
    def _truncate_reviews(reviews: List[str], max_length: int = 15000) -> List[str]:
        """
        Обрезает список отзывов, чтобы их общая длина не превышала max_length
        """
        if not reviews:
            return []
            
        total_length = 0
        truncated_reviews = []
        
        for review in reviews:
            # Добавляем отзыв, если общая длина не превышает максимальную
            if total_length + len(review) <= max_length:
                truncated_reviews.append(review)
                total_length += len(review)
            else:
                # Если отзыв слишком длинный, добавляем часть до достижения max_length
                available_length = max_length - total_length
                if available_length > 100:  # Если осталось достаточно места, добавляем часть отзыва
                    truncated_reviews.append(review[:available_length])
                break
                
        return truncated_reviews
    
    @staticmethod
    def _generate_ai_prompt(reviews: List[str], product_name: str) -> str:
        """
        Генерирует промпт для отправки в модель ИИ
        """
        reviews_text = "\n".join([f"Отзыв {i+1}: {review}" for i, review in enumerate(reviews)])
        
        prompt = f"""Проанализируй следующие отзывы о товаре "{product_name}".

ОТЗЫВЫ:
{reviews_text}

Твой ответ должен быть строго в следующем формате и не должен содержать эмодзи или другие символы:

Плюсы:
[перечисли основные положительные характеристики товара, основываясь на отзывах]

Минусы:
[перечисли основные отрицательные характеристики товара, основываясь на отзывах. Если минусов нет, напиши "Судя по отзывам, явных минусов не обнаружено"]

Рекомендации:
[напиши рекомендацию, стоит ли покупать этот товар, исходя из проанализированных отзывов. Добавь свое личное мнение и для каких категорий покупателей этот товар подойдет лучше всего]

Важные требования:
1. Не используй эмодзи
2. Используй только простой текст без форматирования
3. Строго придерживайся указанной структуры
4. Основывай свой анализ только на предоставленных отзывах
"""
        return prompt
    
    @staticmethod
    def _get_api_key() -> str:
        """Получает API ключ Groq из переменной окружения или файла"""
        # Ключ из .env файла уже должен быть загружен в переменные окружения через load_dotenv()
        api_key = os.environ.get("GROQ_API_KEY")
        
        # Если ключ не задан в переменных окружения, попробуем найти его в файлах
        if not api_key:
            key_file_paths = [
                os.path.expanduser("~/.groq/api_key"),
                "./.groq_api_key",
                "./groq_api_key.txt"
            ]
            
            for path in key_file_paths:
                if os.path.exists(path):
                    try:
                        with open(path, "r") as f:
                            api_key = f.read().strip()
                            break
                    except:
                        pass
        
        return api_key
    
    @staticmethod
    def _get_ai_response(prompt: str, max_attempts: int = 3) -> str:
        """
        Получает ответ от модели ИИ через Groq API с несколькими попытками в случае ошибки
        """
        api_key = ReviewAnalyzer._get_api_key()
        
        if not api_key:
            return """Ошибка анализа отзывов

Не найден API ключ Groq. Пожалуйста, установите переменную окружения GROQ_API_KEY
или создайте файл .env или .groq_api_key с ключом API.

Инструкции:
1. Получите API ключ на сайте https://console.groq.com
2. Сохраните ключ в переменной окружения GROQ_API_KEY
   или в файле .env в формате GROQ_API_KEY=ваш_ключ
   или в файле .groq_api_key в директории приложения"""
        
        # Устанавливаем API ключ напрямую в переменную окружения
        os.environ["GROQ_API_KEY"] = api_key
        
        model_name = "meta-llama/llama-4-scout-17b-16e-instruct"
        try:
            # Используем класс Groq
            client = Groq()
        except Exception as e:
            return f"Ошибка при инициализации клиента Groq: {str(e)}"
        
        for attempt in range(max_attempts):
            try:
                logger.info(f"Попытка {attempt+1} получить ответ от модели {model_name}")
                
                # Отправляем запрос к Groq API
                response = client.chat.completions.create(
                    model=model_name,
                    messages=[
                        {"role": "system", "content": "Ты - профессиональный аналитик отзывов о товарах. Твои ответы должны быть структурированными, информативными и строго придерживаться указанного формата без эмодзи."},
                        {"role": "user", "content": prompt}
                    ],
                    temperature=0.3,
                    max_tokens=1500,
                    top_p=0.8
                )
                
                if response and response.choices and len(response.choices) > 0:
                    logger.info("Успешно получен ответ от модели")
                    content = response.choices[0].message.content
                    # Удаляем эмодзи из ответа
                    clean_response = re.sub(r'[^\w\s\,\.\-\:\;\"\'\(\)\[\]\{\}\?\!]', '', content)
                    return clean_response
                
                logger.warning("Получен пустой ответ от модели, попробуем еще раз")
                time.sleep(2)  # Небольшая задержка перед следующей попыткой
                
            except Exception as e:
                logger.error(f"Ошибка при получении ответа от модели: {str(e)}")
                time.sleep(3)  # Увеличиваем задержку после ошибки
                
                # На последней попытке пробуем облегченную версию модели
                if attempt == max_attempts - 1:
                    logger.warning(f"Пробуем резервную модель llama-3-8b-8192 после {max_attempts} неудачных попыток")
                    try:
                        response = client.chat.completions.create(
                            model="llama-3-8b-8192",
                            messages=[
                                {"role": "system", "content": "Ты - профессиональный аналитик отзывов о товарах. Твои ответы должны быть структурированными, информативными и строго придерживаться указанного формата без эмодзи."},
                                {"role": "user", "content": prompt}
                            ],
                            temperature=0.3,
                            max_tokens=1500,
                            top_p=0.8
                        )
                        
                        if response and response.choices and len(response.choices) > 0:
                            logger.info("Успешно получен ответ от резервной модели")
                            content = response.choices[0].message.content
                            # Удаляем эмодзи из ответа
                            clean_response = re.sub(r'[^\w\s\,\.\-\:\;\"\'\(\)\[\]\{\}\?\!]', '', content)
                            return clean_response
                    except Exception as e:
                        logger.error(f"Ошибка при получении ответа от резервной модели: {str(e)}")
        
        # Если все попытки не удались, возвращаем сообщение об ошибке
        return """Ошибка анализа отзывов

К сожалению, не удалось получить анализ от ИИ-модели. 
Возможные причины:
- Проблемы с подключением к серверам Groq
- Ограничения по квоте API запросов
- Временные технические неполадки
- Неверный API ключ

Пожалуйста, проверьте корректность вашего API ключа и попробуйте еще раз позже."""
    
    @staticmethod
    def _format_analysis(raw_analysis: str) -> str:
        """
        Форматирует сырой ответ модели для лучшего отображения
        """
        # Проверяем, что ответ содержит нужные заголовки
        if "Плюсы:" not in raw_analysis:
            parts = raw_analysis.split("\n\n")
            formatted = "Плюсы:\n"
            if len(parts) > 0:
                formatted += parts[0] + "\n\n"
            formatted += "Минусы:\nИнформация о минусах не предоставлена\n\n"
            formatted += "Рекомендации:\n"
            if len(parts) > 1:
                formatted += parts[-1]
            return formatted
            
        return raw_analysis
    
    @classmethod
    def analyze_reviews(cls, reviews: List[str], product_name: str) -> str:
        """
        Анализирует отзывы с помощью модели Llama-4-Scout через Groq API
        
        Args:
            reviews: Список строк с отзывами
            product_name: Название товара
            
        Returns:
            Строка с отформатированным анализом отзывов
        """
        try:
            logger.info(f"Начинаем анализ {len(reviews)} отзывов для товара '{product_name}'")
            
            if not reviews:
                return f"""Анализ невозможен

Для товара "{product_name}" не найдено отзывов."""
            
            # Ограничиваем количество и объем отзывов (слишком много отзывов может превысить контекст модели)
            max_reviews = min(len(reviews), 100)  # Не более 100 отзывов
            truncated_reviews = cls._truncate_reviews(reviews[:max_reviews])
            
            # Если осталось слишком мало отзывов после обрезки
            if len(truncated_reviews) < 3 and len(reviews) >= 3:
                # Берем только первые 200 символов из каждого отзыва
                shortened_reviews = [review[:200] + ("..." if len(review) > 200 else "") for review in reviews[:30]]
                truncated_reviews = shortened_reviews
            
            # Генерируем промпт для ИИ
            prompt = cls._generate_ai_prompt(truncated_reviews, product_name)
            
            # Получаем ответ от ИИ
            raw_analysis = cls._get_ai_response(prompt)
            
            # Форматируем ответ
            formatted_analysis = cls._format_analysis(raw_analysis)
            
            # Не добавляем информацию о количестве проанализированных отзывов
            
            logger.info(f"Анализ для товара '{product_name}' успешно завершен")
            
            return formatted_analysis
            
        except Exception as e:
            logger.error(f"Ошибка при анализе отзывов: {str(e)}")
            import traceback
            error_details = traceback.format_exc()
            logger.error(f"Детали ошибки: {error_details}")
            
            return f"""Ошибка анализа отзывов

Во время анализа отзывов произошла ошибка: {str(e)}

Пожалуйста, попробуйте еще раз позже или проверьте наличие API ключа Groq.
""" 