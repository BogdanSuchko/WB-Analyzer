import re
import json
import asyncio
import aiohttp
from typing import List, Dict, Optional, Any

class WbReview:
    HEADERS = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36',
    }

    def __init__(self, string: str):
        self.sku: str = self.get_sku(string=string)
        self.product_name: str = ""
        self.color: str = ""
        self.root_id: Optional[str] = None
        self._session: Optional[aiohttp.ClientSession] = None
        
    async def _get_session(self) -> aiohttp.ClientSession:
        """Получает или создает сессию aiohttp."""
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=15)
            self._session = aiohttp.ClientSession(headers=self.HEADERS, timeout=timeout)
        return self._session

    async def close_session(self):
        """Закрывает сессию aiohttp, если она была создана."""
        if self._session and not self._session.closed:
            await self._session.close()
            self._session = None

    @staticmethod
    def get_sku(string: str) -> str:
        """Получение артикула. Может принимать URL или чистый артикул."""
        if not isinstance(string, str):
            raise TypeError(f"Входная строка должна быть str, получено: {type(string)}")
        
        string = string.strip()
        if not string:
            raise ValueError("Входная строка не может быть пустой")

        if "wildberries.ru/catalog/" in string:
            pattern = r"wildberries\.ru/catalog/(\d{7,15})"
            match = re.search(pattern, string)
            if match:
                return match.group(1)
            else:
                raise ValueError(f"Не удалось найти артикул в URL: {string}")
        elif string.isdigit() and 7 <= len(string) <= 15:
            return string
        else:
            raise ValueError(f"Некорректный формат для SKU: '{string}'. Ожидался URL Wildberries (например, 'https://www.wildberries.ru/catalog/1234567/detail.aspx') или числовой артикул (7-15 цифр).")

    async def _get_product_name_from_page(self) -> Optional[str]:
        """Асинхронно получает название товара непосредственно со страницы товара."""
        if not self.sku: return None
        try:
            session = await self._get_session()
            url = f"https://www.wildberries.ru/catalog/{self.sku}/detail.aspx"
            async with session.get(url, allow_redirects=True, timeout=aiohttp.ClientTimeout(total=20)) as response:
                if response.status != 200:
                    print(f"WB.PY: Запрос страницы товара {self.sku} вернул статус {response.status}. URL: {url}")
                    if response.history:
                        final_url = str(response.url)
                        if f"/catalog/{self.sku}/" not in final_url:
                            print(f"WB.PY: Обнаружен редирект на другой товар при запросе {url}, финальный URL: {final_url}. Имя текущего SKU ({self.sku}) получить не удастся.")
                    return None
                
                html_content = await response.text()
            
            title_pattern = r'<h1\s+class="product-page__title"[^>]*>(.*?)</h1>'
            title_match = re.search(title_pattern, html_content, re.DOTALL)
            
            if title_match:
                title = re.sub(r'<[^>]+>', '', title_match.group(1)).strip()
                title = re.sub(r'<!--.*?-->', '', title)
                return title if title else None
            
            title_pattern2 = r'<span\s+data-link="text{:selectedNomenclature.naming}"[^>]*>(.*?)</span>'
            title_match2 = re.search(title_pattern2, html_content, re.DOTALL)
            
            if title_match2:
                title = re.sub(r'<[^>]+>', '', title_match2.group(1)).strip()
                title = re.sub(r'<!--.*?-->', '', title)
                return title if title else None
            
            print(f"WB.PY: Не удалось найти имя товара на странице для SKU {self.sku}")
            return None
        except aiohttp.ClientError as e:
            print(f"WB.PY: Ошибка сети (aiohttp) при получении названия товара {self.sku}: {type(e).__name__} - {e}")
            return None
        except asyncio.TimeoutError:
            print(f"WB.PY: Таймаут при получении названия товара {self.sku} со страницы.")
            return None
        except Exception as e:
            print(f"WB.PY: Неожиданная ошибка при получении названия товара {self.sku} со страницы: {type(e).__name__} - {e}")
            return None

    async def _init_product_info(self):
        """
        Асинхронно инициализирует информацию о товаре: root_id, название, бренд и цвет.
        Вызывается перед операциями, требующими этих данных.
        """
        if self.root_id is not None and self.product_name:
            return

        page_title = await self._get_product_name_from_page()
        if page_title:
            self.product_name = page_title
        
        try:
            session = await self._get_session()
            api_url = f'https://card.wb.ru/cards/v2/detail?appType=1&curr=rub&dest=-1257786&spp=30&nm={self.sku}'
            async with session.get(api_url) as response:
                if response.status != 200:
                    print(f"WB.PY: Ошибка API {response.status} при получении данных для SKU {self.sku} с {api_url}")
                    if not self.product_name:
                        self.product_name = f"Товар {self.sku}"
                    self.root_id = self.sku
                    return

                product_data_json = await response.json()

            if not product_data_json.get("data") or not product_data_json["data"].get("products"):
                print(f"WB.PY: Структура ответа API (v2) изменилась или не содержит данных для SKU {self.sku}. URL: {api_url}")
                if not self.product_name: self.product_name = f"Товар {self.sku}"
                self.root_id = self.sku
                return

            product_info = product_data_json["data"]["products"][0]
            self.root_id = str(product_info.get("id", self.sku))

            api_name = product_info.get("name")
            if not self.product_name or self.product_name == self.sku:
                if api_name and api_name != self.sku :
                     self.product_name = api_name
                if not self.product_name or self.product_name == self.sku:
                    self.product_name = f"Товар {self.sku}"

            if "brand" in product_info and product_info["brand"]:
                brand = product_info["brand"]
                if brand.lower() not in self.product_name.lower():
                    self.product_name = f"{brand} / {self.product_name}"
            
            if "colors" in product_info and isinstance(product_info["colors"], list) and len(product_info["colors"]) > 0:
                current_color_name = ""
                for color_option in product_info["colors"]:
                    if isinstance(color_option, dict) and str(color_option.get("id")) == self.sku :
                        option_found = False
                        if "options" in color_option and isinstance(color_option["options"], list):
                            for opt in color_option["options"]:
                                if isinstance(opt, dict) and str(opt.get("id")) == self.sku:
                                    current_color_name = opt.get("name", "")
                                    option_found = True
                                    break
                        if option_found and current_color_name:
                            break
                        if not current_color_name and not option_found:
                             current_color_name = color_option.get("name","")

                self.color = current_color_name if current_color_name else product_info["colors"][0].get("name", "")

            elif "options" in product_info and isinstance(product_info["options"], list):
                 for option in product_info["options"]:
                     if isinstance(option, dict) and str(option.get("id")) == self.sku:
                         self.color = option.get("name", "")
                         break
            
            if self.root_id is None: self.root_id = self.sku

        except aiohttp.ClientError as e:
            print(f"WB.PY: Ошибка сети (aiohttp) при получении информации о товаре {self.sku} из API: {type(e).__name__} - {e}")
            if not self.product_name: self.product_name = f"Товар {self.sku}"
            if self.root_id is None: self.root_id = self.sku
        except asyncio.TimeoutError:
            print(f"WB.PY: Таймаут при получении информации о товаре {self.sku} из API.")
            if not self.product_name: self.product_name = f"Товар {self.sku}"
            if self.root_id is None: self.root_id = self.sku
        except json.JSONDecodeError as e:
            print(f"WB.PY: Ошибка декодирования JSON от API для товара {self.sku}: {e}")
            if not self.product_name: self.product_name = f"Товар {self.sku}"
            if self.root_id is None: self.root_id = self.sku
        except Exception as e:
            print(f"WB.PY: Неожиданная ошибка при инициализации информации о товаре {self.sku}: {type(e).__name__} - {e}")
            import traceback
            traceback.print_exc()
            if not self.product_name: self.product_name = f"Товар {self.sku}"
            if self.root_id is None: self.root_id = self.sku

    async def get_review_data(self) -> Optional[Dict[str, Any]]:
        """Асинхронно получает данные отзывов. Гарантирует, что root_id инициализирован."""
        if self.root_id is None:
            await self._init_product_info() 
            if self.root_id is None:
                print(f"WB.PY: Не удалось инициализировать root_id для SKU {self.sku}, отзывы не могут быть загружены.")
                return None
        
        session = await self._get_session()
        url_feedbacks = f"https://feedbacks.wildberries.ru/api/v1/feedbacks?imtId={self.root_id}&take=5000&skip=0"

        try:
            async with session.get(url_feedbacks) as response:
                if response.status == 200:
                    data = await response.json()
                    if isinstance(data, dict) and data.get("feedbacks") is not None:
                         return data
                    elif isinstance(data, list):
                         return {"feedbacks": data}
                    elif isinstance(data, dict) and not data.get("feedbacks") and not data:
                         print(f"WB.PY: Получен пустой объект {{}} в качестве ответа по отзывам для root_id {self.root_id}. Считаем, что отзывов нет.")
                         return {"feedbacks": []}
                    else:
                         print(f"WB.PY: Неожиданный формат данных отзывов для root_id {self.root_id}. Ответ: {str(data)[:200]}")
                         return {"feedbacks": []}

                else:
                    print(f"WB.PY: Сервер отзывов ({url_feedbacks}) не вернул успешный ответ ({response.status}) для root_id {self.root_id}. Ответ: {await response.text()[:200]}")
        except aiohttp.ClientError as e:
            print(f"WB.PY: Ошибка сети (aiohttp) при запросе отзывов с {url_feedbacks} для root_id {self.root_id}: {type(e).__name__} - {e}")
        except asyncio.TimeoutError:
            print(f"WB.PY: Таймаут при запросе отзывов с {url_feedbacks} для root_id {self.root_id}.")
        except json.JSONDecodeError as e:
            response_text_sample = ""
            if 'response' in locals() and hasattr(response, 'text'):
                try:
                    response_text_sample = (await response.text())[:200]
                except: pass
            print(f"WB.PY: Ошибка декодирования JSON с {url_feedbacks} для root_id {self.root_id}: {e}. Фрагмент ответа: '{response_text_sample}'")
        except Exception as e:
            print(f"WB.PY: Неожиданная ошибка при запросе отзывов с {url_feedbacks} для root_id {self.root_id}: {type(e).__name__} - {e}")
            import traceback
            traceback.print_exc()
        
        return None

    async def parse(self, only_this_variation: bool = True, limit: int = 300) -> List[Dict[str, str]]:
        """
        Асинхронный парсинг отзывов.
        Гарантирует, что информация о товаре (root_id, product_name) загружена перед парсингом.
        """
        if self.root_id is None or not self.product_name:
            await self._init_product_info()
            if self.root_id is None:
                 print(f"WB.PY: Критическая ошибка: не удалось получить root_id для SKU {self.sku}. Парсинг отзывов невозможен.")
                 return []

        json_feedbacks_data = await self.get_review_data()
        
        if not json_feedbacks_data or json_feedbacks_data.get("feedbacks") is None:
            print(f"WB.PY: Отзывы не найдены или не удалось загрузить для root_id: {self.root_id} (SKU: {self.sku})")
            return []

        actual_feedbacks_list = json_feedbacks_data.get("feedbacks", [])
        if not isinstance(actual_feedbacks_list, list) or not actual_feedbacks_list:
            if actual_feedbacks_list is not None:
                 print(f"WB.PY: Поле 'feedbacks' содержит неожиданный тип данных ({type(actual_feedbacks_list)}) или пусто для root_id: {self.root_id}. Ожидался список.")
            return []

        parsed_feedbacks: List[Dict[str, str]] = []
        for feedback_item in actual_feedbacks_list:
            if not isinstance(feedback_item, dict): continue

            text_content = feedback_item.get("text", "") or feedback_item.get("productValuation", "")
            
            can_add = False
            if only_this_variation:
                feedback_nm_id = feedback_item.get("nmId")
                if feedback_nm_id is not None:
                    if str(feedback_nm_id) == self.sku:
                        can_add = True
                else:
                    pass
            else:
                can_add = True

            if can_add:
                parsed_feedbacks.append({
                    "text": text_content,
                    "pros": feedback_item.get("pros", ""),
                    "cons": feedback_item.get("cons", "")
                })
        
        return parsed_feedbacks[:limit]