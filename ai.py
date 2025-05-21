import os
import logging
from typing import List, Dict, Any
import re
import time
from dotenv import load_dotenv

# Импорт для GitHub Models API через Azure AI Inference
try:
    from azure.ai.inference import ChatCompletionsClient
    from azure.ai.inference.models import SystemMessage, UserMessage
    from azure.core.credentials import AzureKeyCredential
    GITHUB_MODELS_AVAILABLE = True
except ImportError:
    GITHUB_MODELS_AVAILABLE = False

try:
    from groq import Groq
    import httpx
    GROQ_AVAILABLE = True
except ImportError as e:
    GROQ_AVAILABLE = False
    
# Загружаем переменные окружения из .env файла
load_dotenv()

# Настраиваем логирование
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')
logger = logging.getLogger('ReviewAnalyzer')

class ReviewAnalyzer:
    """
    Класс для анализа отзывов с Wildberries с использованием Groq API и модели Llama-4-Scout
    """
    
    # Добавляем константы для GitHub Models API
    GITHUB_MODELS_ENDPOINT = "https://models.inference.ai.azure.com"
    GITHUB_MODEL_NAME = "DeepSeek-V3-0324"
    
    # Флаг, указывающий, что Groq API временно недоступен (ошибка 429)
    _groq_api_rate_limited = False
    
    # Время последней ошибки 429 от Groq API
    _groq_api_rate_limited_time = 0
    
    # Интервал для повторной проверки доступности Groq API (в секундах)
    _groq_api_retry_interval = 60
    
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
    def _should_try_groq_api() -> bool:
        """
        Проверяет, следует ли пытаться использовать Groq API
        или сразу переключиться на GitHub Models API
        """
        # Если Groq API не ограничен по скорости, используем его
        if not ReviewAnalyzer._groq_api_rate_limited:
            return True
            
        # Проверяем, прошло ли достаточно времени с момента последней ошибки 429
        current_time = time.time()
        time_since_rate_limit = current_time - ReviewAnalyzer._groq_api_rate_limited_time
        
        # Если прошло достаточно времени, сбрасываем флаг и пробуем Groq API снова
        if time_since_rate_limit >= ReviewAnalyzer._groq_api_retry_interval:
            logger.info(f"Прошло {time_since_rate_limit:.1f} секунд с момента ограничения Groq API. Пробуем снова.")
            ReviewAnalyzer._groq_api_rate_limited = False
            return True
            
        logger.info(f"Groq API все еще ограничен. Используем GitHub Models API. Повторная проверка через {ReviewAnalyzer._groq_api_retry_interval - time_since_rate_limit:.1f} секунд.")
        return False
    
    @staticmethod
    def _mark_groq_api_rate_limited():
        """Отмечает Groq API как временно недоступный из-за ограничения скорости"""
        ReviewAnalyzer._groq_api_rate_limited = True
        ReviewAnalyzer._groq_api_rate_limited_time = time.time()
        logger.warning(f"Groq API помечен как ограниченный на {ReviewAnalyzer._groq_api_retry_interval} секунд")
    
    @staticmethod
    def _generate_ai_prompt(reviews: List[str], product_name: str) -> str:
        """
        Генерирует промпт для отправки в модель ИИ
        """
        # Если используется GitHub Models API, сильно сокращаем промпт для соблюдения лимитов DeepSeek
        if ReviewAnalyzer._groq_api_rate_limited:
            # Более агрессивное сокращение для DeepSeek модели (ограничение 8000 токенов)
            # Берем только 20 отзывов максимум и ограничиваем их длину до 100 символов
            shortened_reviews = reviews[:20]
            reviews_text = "\n".join([f"Отзыв {i+1}: {review[:100]}..." if len(review) > 100 else f"Отзыв {i+1}: {review}" 
                                     for i, review in enumerate(shortened_reviews)])
        else:
            # Для Groq используем стандартный формат
            reviews_text = "\n".join([f"Отзыв {i+1}: {review}" for i, review in enumerate(reviews)])
        
        prompt = f"""Проанализируй следующие отзывы о товаре "{product_name}".

ОТЗЫВЫ:
{reviews_text}

Твой ответ должен быть строго в следующем формате и не должен содержать эмодзи или другие символы:

Плюсы:
- [первый плюс]
- [второй плюс]
- [и т.д. - перечисли основные положительные характеристики товара в виде маркированного списка]

Минусы:
- [первый минус]
- [второй минус]
- [и т.д. - перечисли основные отрицательные характеристики товара в виде маркированного списка. Если минусов нет, напиши "Судя по отзывам, явных минусов не обнаружено"]

Рекомендации:
[Напиши развернутую рекомендацию, стоит ли покупать этот товар, исходя из проанализированных отзывов. Добавь информацию о том, для каких категорий покупателей этот товар подойдет лучше всего. Рекомендация должна быть подробной, минимум 3-5 предложений.]

Важные требования:
1. Не используй эмодзи
2. Используй только простой текст без форматирования
3. Строго придерживайся указанной структуры
4. Основывай свой анализ только на предоставленных отзывах
5. Плюсы и минусы оформляй в виде маркированного списка с дефисами
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
    def _get_github_token() -> str:
        """Получает GitHub API токен из переменной окружения"""
        return os.environ.get("GITHUB_TOKEN", "")
    
    @staticmethod
    def _get_ai_response_github(prompt: str) -> str:
        """
        Получает ответ от модели ИИ через GitHub Models API
        Используется как запасной вариант при ошибке 429 от Groq
        """
        if not GITHUB_MODELS_AVAILABLE:
            return "Ошибка: Модуль azure-ai-inference не установлен. Выполните 'pip install azure-ai-inference'."
        
        token = ReviewAnalyzer._get_github_token()
        if not token:
            return "Ошибка: Не найден токен GitHub. Укажите GITHUB_TOKEN в файле .env"
        
        try:
            logger.info(f"Используем GitHub Models API с моделью {ReviewAnalyzer.GITHUB_MODEL_NAME}")
            
            client = ChatCompletionsClient(
                endpoint=ReviewAnalyzer.GITHUB_MODELS_ENDPOINT,
                credential=AzureKeyCredential(token),
            )
            
            response = client.complete(
                messages=[
                    SystemMessage("Ты - профессиональный аналитик отзывов о товарах. Твои ответы должны быть структурированными, информативными и строго придерживаться указанного формата без эмодзи."),
                    UserMessage(prompt),
                ],
                temperature=0.3,
                top_p=0.8,
                max_tokens=1500,
                model=ReviewAnalyzer.GITHUB_MODEL_NAME
            )
            
            if response and response.choices and len(response.choices) > 0:
                logger.info("Успешно получен ответ от GitHub Models API")
                content = response.choices[0].message.content
                # Удаляем эмодзи из ответа
                clean_response = re.sub(r'[^\w\s\,\.\-\:\;\"\'\(\)\[\]\{\}\?\!]', '', content)
                return clean_response
            else:
                return "Ошибка: Не удалось получить ответ от GitHub Models API"
                
        except Exception as e:
            logger.error(f"Ошибка при использовании GitHub Models API: {str(e)}")
            return f"Ошибка GitHub Models API: {str(e)}"
    
    @staticmethod
    def _get_ai_response(prompt: str, max_attempts: int = 3) -> str:
        """
        Получает ответ от модели ИИ через Groq API с несколькими попытками в случае ошибки
        """
        # Проверяем, следует ли использовать Groq API или сразу GitHub Models API
        if not ReviewAnalyzer._should_try_groq_api():
            return ReviewAnalyzer._get_ai_response_github(prompt)
            
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
        
        if not GROQ_AVAILABLE:
            logger.warning("Библиотека Groq недоступна, используем GitHub Models API")
            return ReviewAnalyzer._get_ai_response_github(prompt)
            
        # Устанавливаем API ключ напрямую в переменную окружения
        os.environ["GROQ_API_KEY"] = api_key
        
        model_name = "meta-llama/llama-4-scout-17b-16e-instruct"
        try:
            # Создаем кастомный HTTP клиент без автоматических retry
            transport = httpx.HTTPTransport(retries=0)
            http_client = httpx.Client(transport=transport)
            
            # Используем класс Groq с кастомным клиентом
            client = Groq(api_key=api_key, http_client=http_client)
        except Exception as e:
            logger.error(f"Ошибка при инициализации клиента Groq: {str(e)}")
            # Пробуем резервный API
            return ReviewAnalyzer._get_ai_response_github(prompt)
        
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
                
            except httpx.HTTPStatusError as e:
                status_code = e.response.status_code
                error_str = str(e)
                logger.error(f"HTTP ошибка при получении ответа от модели: {error_str}")
                
                # Проверяем, является ли ошибка 429 (Too Many Requests)
                if status_code == 429:
                    logger.warning("Обнаружено ограничение запросов (429). Переключаемся на GitHub Models API")
                    # Помечаем Groq API как временно недоступный
                    ReviewAnalyzer._mark_groq_api_rate_limited()
                    # Используем GitHub Models API как резервный вариант
                    return ReviewAnalyzer._get_ai_response_github(prompt)
                
                time.sleep(3)  # Увеличиваем задержку после ошибки
            
            except Exception as e:
                error_str = str(e)
                logger.error(f"Ошибка при получении ответа от модели: {error_str}")
                
                # Проверяем, является ли ошибка связана с ограничением запросов
                if "429" in error_str or "too many requests" in error_str.lower():
                    logger.warning("Обнаружено ограничение запросов. Переключаемся на GitHub Models API")
                    # Помечаем Groq API как временно недоступный
                    ReviewAnalyzer._mark_groq_api_rate_limited()
                    # Используем GitHub Models API как резервный вариант
                    return ReviewAnalyzer._get_ai_response_github(prompt)
                
                time.sleep(3)  # Увеличиваем задержку после ошибки
                
        # Последняя попытка - попробуем GitHub Models API
        logger.warning("Все попытки с Groq исчерпаны, пробуем GitHub Models API")
        return ReviewAnalyzer._get_ai_response_github(prompt)
    
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