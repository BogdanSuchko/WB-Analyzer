import re
import json
import requests
from typing import List, Dict, Optional, Union, Any

class WbReview:
    def __init__(self, string: str):
        self.sku = self.get_sku(string=string)
        self.product_name = ""
        self.color = ""
        # Получаем root_id и заодно инициализируем product_name 
        self.root_id = self.get_product_info()
        
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }

    @staticmethod
    def get_sku(string: str) -> str:
        """Получение артикула"""
        if "wildberries" in string:
            pattern = r"\d{7,15}"
            sku = re.findall(pattern=pattern, string=string)
            if sku:
                return sku[0]
            else:
                raise Exception("Не удалось найти артикул")
        return string

    def get_product_name_from_page(self) -> Optional[str]:
        """Получает название товара непосредственно со страницы товара"""
        try:
            url = f"https://www.wildberries.ru/catalog/{self.sku}/detail.aspx"
            response = requests.get(url, headers=self.HEADERS)
            
            if response.status_code != 200:
                return None
            
            # Ищем название товара в HTML с помощью регулярного выражения
            title_pattern = r'<h1\s+class="product-page__title"[^>]*>(.*?)</h1>'
            title_match = re.search(title_pattern, response.text, re.DOTALL)
            
            if title_match:
                # Очищаем название от HTML-тегов и лишних пробелов
                title = re.sub(r'<[^>]+>', '', title_match.group(1))
                return title.strip()
            
            # Альтернативный поиск - для новой верстки
            title_pattern2 = r'<span\s+data-link="text{:selectedNomenclature.naming}"[^>]*>(.*?)</span>'
            title_match2 = re.search(title_pattern2, response.text, re.DOTALL)
            
            if title_match2:
                title = re.sub(r'<[^>]+>', '', title_match2.group(1))
                return title.strip()
            
            return None
        except Exception:
            return None

    def get_product_info(self) -> str:
        """
        Получение информации о товаре включая root_id, название, бренд и цвет
        Возвращает root_id товара
        """
        try:
            # Сначала пытаемся получить название со страницы
            page_title = self.get_product_name_from_page()
            if page_title:
                self.product_name = page_title
            
            # Пробуем получить данные через API для получения root_id
            response = requests.get(
                f'https://card.wb.ru/cards/v2/detail?appType=1&curr=byn&dest=-8144334&spp=30&nm={self.sku}',
                headers=self.HEADERS,
            )
            
            if response.status_code != 200:
                raise Exception("Не удалось получить данные товара через API")
            
            product_data = response.json()["data"]["products"][0]
            root_id = product_data["root"]
            
            # Если название не было получено со страницы, берем из API
            if not self.product_name:
                self.product_name = product_data.get("name", f"Товар {self.sku}")
                # Добавляем бренд к названию
                if "brand" in product_data and product_data["brand"]:
                    brand = product_data["brand"]
                    if brand not in self.product_name:
                        self.product_name = f"{brand} - {self.product_name}"
            
            # Получаем информацию о цвете/варианте товара если она есть
            if "colors" in product_data and len(product_data["colors"]) > 0:
                self.color = product_data["colors"][0]["name"]
            
            return root_id
        except Exception as e:
            print(f"Ошибка при получении root_id: {e}")
            
            # Если не удалось получить название и root_id, используем артикул
            if not self.product_name:
                self.product_name = f"Товар {self.sku}"
            
            return self.sku

    def get_review_data(self) -> Optional[Dict[str, Any]]:
        """Получение данных отзывов"""
        try:
            response = requests.get(f'https://feedbacks1.wb.ru/feedbacks/v1/{self.root_id}', headers=self.HEADERS)
            if response.status_code == 200:
                data = response.json()
                if data.get("feedbacks"):
                    return data
                raise Exception("Сервер 1 не подошел")
        except Exception:
            response = requests.get(f'https://feedbacks2.wb.ru/feedbacks/v1/{self.root_id}', headers=self.HEADERS)
            if response.status_code == 200:
                return response.json()
        return None

    def parse(self, only_this_variation=True, limit=100) -> List[str]:
        """
        Парсинг отзывов
        
        Args:
            only_this_variation: Если True, возвращает отзывы только для этого варианта товара,
                               Если False, возвращает все отзывы для всех вариантов товара
            limit: Максимальное количество отзывов для возврата
        """
        json_feedbacks = self.get_review_data()
        if not json_feedbacks:
            return []
        
        if only_this_variation:
            # Возвращаем отзывы только для конкретного варианта товара (по артикулу)
            feedbacks = [feedback.get("text") for feedback in json_feedbacks["feedbacks"]
                        if str(feedback.get("nmId")) == self.sku]
        else:
            # Возвращаем все отзывы для всех вариантов товара
            feedbacks = [feedback.get("text") for feedback in json_feedbacks["feedbacks"]]
        
        if len(feedbacks) > limit:
            feedbacks = feedbacks[:limit]
        
        return feedbacks