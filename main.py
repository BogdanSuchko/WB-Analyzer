# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import os
import re
import multiprocessing
from dotenv import load_dotenv
import traceback # Для подробного отчета об ошибках

# --- Проверка зависимостей ---
try:
    from wb import WbReview
    from ai import ReviewAnalyzer
except ImportError as e:
    root = tk.Tk()
    root.withdraw()
    messagebox.showerror("Ошибка импорта", f"Не удалось импортировать модули: {e}\n\nУбедитесь, что 'wb.py' и 'ai.py' существуют и содержат классы WbReview и ReviewAnalyzer.")
    root.destroy()
    exit()

# --- Настройка ---
load_dotenv()
ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# --- Константы ---
APP_NAME = "WB Analyzer"
ACCENT_COLOR = "#0a84ff"
CARD_COLOR = "#2c2c2e"
INPUT_BG = "#39393d"
TEXT_COLOR = "#ffffff"
SECONDARY_TEXT = "#86868b"

# --- Пользовательские виджеты ---
class CustomEntry(ctk.CTkEntry):
    """Кастомный CTkEntry без лишней логики."""
    pass # Дополнительная логика пока не требуется

# --- Основной класс приложения ---
class ReviewAnalyzerApp(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.title(APP_NAME)
        self.geometry("900x400")
        self.minsize(700, 400)

        # --- Переменные состояния ---
        self.loading_frame = None
        self.loading_label = None
        self.result_queue = None
        self.mode_var = ctk.StringVar(value="single")

        # --- Шрифты ---
        # Централизованное определение шрифтов - хорошая практика
        self.fonts = {
            "title": ctk.CTkFont(size=26, weight="bold"),
            "subtitle": ctk.CTkFont(size=14),
            "header": ctk.CTkFont(size=13, weight="bold"),
            "text": ctk.CTkFont(size=13),
            "button": ctk.CTkFont(size=15, weight="bold"),
            "result_title": ctk.CTkFont(size=18, weight="bold"),
            "result_text": ctk.CTkFont(size=14),
            "footer": ctk.CTkFont(size=11),
            "back_button": ctk.CTkFont(size=13),
        }

        # --- Инициализация ---
        self._check_groq_api_key()
        self._setup_frames()
        self._setup_main_widgets()
        self._setup_result_widgets()

        self.bind("<Button-1>", self._defocus)
        self.mode_var.trace_add("write", self._update_url_placeholder)

        # Показать основной фрейм при запуске
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)

    # --- Основные методы настройки ---

    def _setup_frames(self):
        """Создает основной фрейм и фрейм результатов."""
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.result_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.result_frame.bind("<Configure>", self._update_title_wraplength)

    def _setup_main_widgets(self):
        """Создает все виджеты для главного экрана."""
        # Заголовок
        ctk.CTkLabel(self.main_frame, text=APP_NAME, font=self.fonts["title"], text_color=ACCENT_COLOR).pack(pady=(5, 2))
        ctk.CTkLabel(self.main_frame, text="Интеллектуальный анализ отзывов с Wildberries", font=self.fonts["subtitle"], text_color=SECONDARY_TEXT).pack(pady=(0, 15))

        # Карточка контента
        content_frame = ctk.CTkFrame(self.main_frame, fg_color=CARD_COLOR, corner_radius=15)
        content_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=5)
        content_frame.bind("<Button-1>", self._defocus) # Разрешить снятие фокуса по клику на фон карточки

        # Секция ввода (Режим + URL)
        input_section_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        input_section_frame.pack(fill=tk.X, padx=20, pady=(20, 15))
        input_section_frame.bind("<Button-1>", self._defocus)

        self._create_mode_switcher(input_section_frame)
        self._create_url_input(input_section_frame)

        # Кнопка "Анализировать"
        button_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        button_frame.pack(pady=(10, 20), fill=tk.X)
        button_frame.bind("<Button-1>", self._defocus)
        ctk.CTkButton(
            button_frame, text="Анализировать отзывы", font=self.fonts["button"], width=250, height=45,
            command=self.start_analysis, corner_radius=10, fg_color=ACCENT_COLOR,
            hover_color="#0069d9", border_width=1, border_color="#1a94ff"
        ).pack(anchor=tk.CENTER)

        # Нижний колонтитул (подвал)
        ctk.CTkLabel(self.main_frame, text="Анализ обычно занимает от 3 до 10 секунд (больше, если в режиме сравнения товаров)", font=self.fonts["footer"], text_color=SECONDARY_TEXT).pack(pady=(0, 5))

    def _create_mode_switcher(self, parent):
        """Создает радиокнопки выбора режима."""
        mode_frame = ctk.CTkFrame(parent, fg_color="transparent")
        mode_frame.pack(fill=tk.X, pady=(0, 10))
        ctk.CTkLabel(mode_frame, text="Режим анализа:", font=self.fonts["header"], anchor="w", text_color=TEXT_COLOR).pack(side=tk.LEFT, padx=(0, 10))
        modes = [("Один товар", "single"), ("Сравнение товаров", "multi")]
        for i, (text, value) in enumerate(modes):
            ctk.CTkRadioButton(
                mode_frame, text=text, variable=self.mode_var, value=value,
                font=self.fonts["text"], text_color=TEXT_COLOR, fg_color=ACCENT_COLOR,
                command=self._update_url_placeholder # Обновлять и при клике
            ).pack(side=tk.LEFT, padx=(0, 15 if i == 0 else 0))

    def _create_url_input(self, parent):
        """Создает поле ввода URL/ID."""
        ctk.CTkLabel(parent, text="Ссылка на товар или артикул", font=self.fonts["header"], anchor="w", text_color=TEXT_COLOR).pack(fill=tk.X, pady=(0, 8))
        url_input_frame = ctk.CTkFrame(parent, fg_color=INPUT_BG, corner_radius=10)
        url_input_frame.pack(fill=tk.X)
        self.url_input = CustomEntry(
            url_input_frame, height=40, border_width=0, fg_color="transparent",
            text_color=TEXT_COLOR, font=self.fonts["text"]
        )
        self.url_input.pack(fill=tk.X, padx=10, pady=8)
        self._update_url_placeholder() # Установить начальный плейсхолдер

    def _setup_result_widgets(self):
        """Создает все виджеты для экрана результатов."""
        # Заголовок (Кнопка "Назад")
        header_frame = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        header_frame.pack(fill=tk.X, pady=(10, 5), padx=20)
        ctk.CTkButton(
            header_frame, text="← Назад", font=self.fonts["back_button"], command=self.go_back,
            width=100, height=32, corner_radius=16, fg_color="#3a3a3c",
            text_color=TEXT_COLOR, hover_color="#4a4a4c"
        ).pack(side=tk.LEFT)

        # Название товара (Создано, но упаковывается динамически)
        self.product_title_label = ctk.CTkLabel(
            self.result_frame, text="", font=self.fonts["result_title"],
            text_color=TEXT_COLOR, anchor='w', justify="left"
        )

        # Карточка результата и текстовое поле (Созданы, но упаковываются динамически)
        self.result_card = ctk.CTkFrame(self.result_frame, corner_radius=15, fg_color=CARD_COLOR)
        self.result_text = ctk.CTkTextbox(
            self.result_card, font=self.fonts["result_text"], wrap="word", fg_color="transparent",
            text_color=TEXT_COLOR, corner_radius=0, border_width=0, border_spacing=10,
            state=tk.DISABLED
        )
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=5, pady=5) # Текстовое поле упаковано внутри карточки

    # --- Взаимодействие с UI и вспомогательные функции ---

    def _defocus(self, event=None):
        """Убирает фокус с виджетов ввода при клике в другом месте."""
        widget = event.widget
        # Упрощенная проверка: если виджет в фокусе - не виджет события,
        # и виджет события - не Entry или Textbox (или их внутренние части), убрать фокус.
        # Это может быть немного менее точно, но охватывает большинство случаев.
        focused = self.focus_get()
        if focused and widget != focused and not isinstance(widget, (ctk.CTkEntry, ctk.CTkTextbox, tk.Text)):
             # Проверить родительские виджеты на всякий случай
             try:
                 if not isinstance(widget.master, (ctk.CTkEntry, ctk.CTkTextbox)):
                      if not isinstance(widget.master.master, (ctk.CTkEntry, ctk.CTkTextbox)):
                           self.focus_set()
             except (AttributeError, tk.TclError): # Обработать случаи, когда родительский виджет не существует или виджет уничтожен
                 self.focus_set()

    def _update_url_placeholder(self, *args):
        """Обновляет текст-плейсхолдер в поле ввода URL в зависимости от выбранного режима."""
        if hasattr(self, 'url_input') and self.url_input.winfo_exists():
            is_multi = self.mode_var.get() == "multi"
            placeholder = "Вставьте ссылки или артикулы через запятую" if is_multi else "Вставьте ссылку или артикул товара Wildberries"
            self.url_input.configure(placeholder_text=placeholder)

    def _update_title_wraplength(self, event=None):
        """Корректирует длину переноса строки метки заголовка результата в зависимости от ширины фрейма."""
        try:
            # Отступы padx по 25 с каждой стороны для метки заголовка
            new_width = self.result_frame.winfo_width() - 50
            if new_width < 100: new_width = 100 # Минимальная ширина переноса
            if hasattr(self, 'product_title_label') and self.product_title_label.winfo_exists():
                self.product_title_label.configure(wraplength=new_width)
        except (tk.TclError, AttributeError):
             pass # Игнорировать ошибки, если виджеты не существуют во время изменения размера

    def _set_result_text(self, text):
        """Безопасно обновляет текстовое поле результата."""
        if hasattr(self, 'result_text') and self.result_text.winfo_exists():
            self.result_text.configure(state=tk.NORMAL)
            self.result_text.delete("1.0", tk.END)
            self.result_text.insert(tk.END, text)
            self.result_text.configure(state=tk.DISABLED)

    def go_back(self):
        """Переключает с экрана результатов обратно на главный экран."""
        self.result_frame.pack_forget()
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)
        if hasattr(self, 'url_input'): self.url_input.delete(0, tk.END)
        self.title(APP_NAME)

    def show_loading_screen(self, message="Анализируем отзывы...\nПожалуйста, подождите"):
        """Отображает оверлей загрузки."""
        self.main_frame.pack_forget()
        if self.loading_frame and self.loading_frame.winfo_exists():
            self.loading_frame.destroy() # Очистить предыдущий, если есть

        self.loading_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.loading_frame.pack(fill=tk.BOTH, expand=True, padx=40, pady=40)

        loading_card = ctk.CTkFrame(self.loading_frame, corner_radius=20, fg_color=CARD_COLOR)
        loading_card.pack(fill=tk.BOTH, expand=True)

        self.loading_label = ctk.CTkLabel(loading_card, text=message, font=self.fonts["result_title"], text_color=TEXT_COLOR)
        self.loading_label.pack(expand=True, pady=20)

        # Использование place для центрирования контейнера прогресс-бара может быть проще
        progress_container = ctk.CTkFrame(loading_card, fg_color="transparent")
        progress_container.pack(pady=(0, 30)) # Упаковать под меткой
        # progress_container.place(relx=0.5, rely=0.8, anchor=tk.CENTER) # Альтернативное центрирование

        progress = ctk.CTkProgressBar(progress_container, width=250, mode="indeterminate", height=8, corner_radius=4, fg_color="#3a3a3c", progress_color=ACCENT_COLOR)
        progress.pack()
        progress.start()

        self.update_idletasks() # Гарантировать обновление UI
        return self.loading_frame

    def _destroy_loading_screen(self, loading_screen):
        """Безопасно уничтожает экран загрузки."""
        if loading_screen and loading_screen.winfo_exists():
            loading_screen.destroy()
        self.loading_frame = None
        self.loading_label = None

    def _check_groq_api_key(self):
        """Проверяет наличие GROQ_API_KEY в .env."""
        # Упрощенная проверка - просто посмотреть, загружен ли он
        api_key = os.getenv("GROQ_API_KEY")
        if not api_key:
             # Использовать self.after, чтобы убедиться, что главное окно готово перед показом предупреждения
             self.after(100, lambda: messagebox.showwarning(
                 "API ключ Groq",
                 "API ключ Groq (GROQ_API_KEY) не найден в файле .env.\n"
                 "Он необходим для работы ИИ-анализа.\n\n"
                 "1. Получите ключ на console.groq.com\n"
                 "2. Сохраните его в файле .env (GROQ_API_KEY=ваш_ключ)\n\n"
                 "Без ключа анализ отзывов не будет работать."
             ))

    # --- Извлечение ID товара ---

    @staticmethod
    def extract_product_id(url_or_id):
        """Извлекает ID товара WB из строки (URL или прямой ID)."""
        clean_input = url_or_id.strip()
        # Приоритет числовым строкам (вероятно, прямой артикул)
        if clean_input.isdigit() and len(clean_input) >= 5:
            return clean_input

        # Регулярные выражения для разных форматов URL
        patterns = [
            r"/catalog/(\d{5,})",    # https://www.wildberries.ru/catalog/12345678/detail.aspx
            r"/product/(\d{5,})",    # https://www.wildberries.ru/product/12345678/detail.aspx (менее распространен?)
            r"(?:nm|card)=(\d{5,})" # https://...detail.aspx?targetUrl=BP&size=...&card=12345678 или &nm=...
        ]
        for pattern in patterns:
            match = re.search(pattern, clean_input, re.IGNORECASE) # Добавлено игнорирование регистра
            if match:
                return match.group(1)
        return None

    # --- Организация анализа ---

    def start_analysis(self):
        """Инициирует анализ на основе ввода и режима."""
        url_or_id_input = self.url_input.get().strip()
        if not url_or_id_input:
            messagebox.showerror("Ошибка", "Введите ссылку на товар или его артикул.")
            return

        mode = self.mode_var.get()
        ids_to_analyze = []

        if mode == "single":
            product_id = self.extract_product_id(url_or_id_input)
            if not product_id:
                messagebox.showerror("Ошибка ID", f"Не удалось извлечь артикул из:\n'{url_or_id_input}'")
                return
            ids_to_analyze.append(product_id)
        else: # режим сравнения
            items = [item.strip() for item in url_or_id_input.split(',')]
            for item in items:
                if not item: continue
                product_id = self.extract_product_id(item)
                if not product_id:
                    messagebox.showerror("Ошибка ID", f"Не удалось извлечь артикул из:\n'{item}'\n\nПроверьте все введенные ссылки/артикулы.")
                    return # Остановиться, если какой-либо ID недействителен в режиме сравнения
                ids_to_analyze.append(product_id)

            if not ids_to_analyze:
                messagebox.showerror("Ошибка", "Не введено ни одного корректного артикула/ссылки для сравнения.")
                return
            # Избегать дубликатов
            ids_to_analyze = sorted(list(set(ids_to_analyze)))


        if not ids_to_analyze: # Не должно произойти, исходя из проверок выше, но безопасность прежде всего
             messagebox.showerror("Ошибка", "Не удалось определить товары для анализа.")
             return

        # --- Запуск процесса ---
        self.result_queue = multiprocessing.Queue()
        target_process = self.perform_analysis_process # По умолчанию - одиночный
        process_args = (ids_to_analyze[0], self.result_queue) # Аргументы для одиночного
        loading_message = f"Получаем информацию о товаре {ids_to_analyze[0]}..."

        if len(ids_to_analyze) > 1:
             target_process = self.perform_multiple_analysis_process
             process_args = (ids_to_analyze, self.result_queue)
             loading_message = f"Получаем информацию о товарах ({len(ids_to_analyze)})..."

        loading_screen = self.show_loading_screen(loading_message)

        analysis_process = multiprocessing.Process(
            target=target_process,
            args=process_args,
            daemon=True
        )
        analysis_process.start()
        self.after(100, self.check_analysis_results, loading_screen)

    # --- Целевые функции мультипроцессинга (статические методы) ---

    @staticmethod
    def _fetch_product_data(product_id, result_queue):
        """Получает название и отзывы для одного товара. Выполняется в рабочем процессе."""
        try:
            wb_review = WbReview(product_id)
            product_name = wb_review.product_name or f"Товар {product_id}"
            # Отправить обновление *перед* потенциально долгим парсингом
            result_queue.put({"type": "update_loading_fetch", "product_name": product_name})
            reviews = wb_review.parse(only_this_variation=True) # Предполагая, что это желаемое поведение
            return {
                "product_id": product_id,
                "product_name": product_name,
                "reviews": reviews or [], # Убедиться, что это список
                "review_count": len(reviews) if reviews else 0
            }
        except Exception as e:
            error_msg = f"Ошибка при получении данных для товара {product_id}: {e}"
            result_queue.put({"type": "error", "message": error_msg})
            return None # Указать на неудачу для этого товара

    @staticmethod
    def _generate_comparison_prompt(individual_analyses):
        """Генерирует промпт для ИИ для сравнения нескольких товаров."""
        num_products = len(individual_analyses)
        if num_products < 2: return "" # Нельзя сравнить менее 2

        prompt = f"Сравни следующие {num_products} товар{'а' if 2 <= num_products <= 4 else 'ов'} ({' и '.join(p['product_name'] for p in individual_analyses.values())}) на основе краткого анализа отзывов по каждому:\n\n"

        for i, (product_id, data) in enumerate(individual_analyses.items(), 1):
            prompt += f"Товар {i}: {data['product_name']} (Артикул: {product_id})\n"
            prompt += f"Анализ отзывов:\n{data['analysis']}\n\n"

        # Общие инструкции по структуре
        prompt += """
Твоя задача - провести объективное и структурированное сравнение.

Структурируй свой ответ строго по следующему шаблону:
"""
        # Добавить конкретные примеры в зависимости от количества товаров
        if num_products == 2:
             prompt += """
Товар 1 (Артикул: [номер]): [Краткое описание первого товара]
Товар 2 (Артикул: [номер]): [Краткое описание второго товара]

Основные плюсы и минусы:
- Товар 1:
  Плюсы: [список]
  Минусы: [список]
- Товар 2:
  Плюсы: [список]
  Минусы: [список]

Сравнение по ключевым параметрам:
[Сравни по 3-5 важным параметрам, релевантным для этих товаров]

Рекомендации:
[Для кого или для каких целей лучше подходит каждый товар. Избегай однозначного "лучше", если это не очевидно.]
"""
        else: # 3+ товара
            prompt += """
Товар 1 (Артикул: [номер]): [краткое описание]
Товар 2 (Артикул: [номер]): [краткое описание]
... (для всех товаров) ...

Основные плюсы и минусы (для каждого товара):
- Товар 1:
  Плюсы: [список]
  Минусы: [список]
- Товар 2:
  Плюсы: [список]
  Минусы: [список]
... (для всех товаров) ...

Сравнительный анализ по параметрам:
[Сравни все товары по 3-5 важным параметрам]

Общие рекомендации:
[Выдели сильные стороны каждого и для каких ситуаций/покупателей они могут подойти.]
"""
        prompt += "\nСтрого придерживайся этой структуры. Не используй вводных фраз вроде 'Вот сравнение...' или заключений вроде 'Надеюсь, это поможет'. Без эмодзи."
        return prompt

    @staticmethod
    def _get_single_analysis(product_data, result_queue):
        """Выполняет ИИ-анализ отзывов одного товара."""
        product_id = product_data["product_id"]
        product_name = product_data["product_name"]
        reviews = product_data["reviews"]

        if not reviews:
            return f"Для товара '{product_name}' ({product_id}) не найдено отзывов для анализа."

        try:
            if not hasattr(ReviewAnalyzer, 'analyze_reviews'):
                 raise AttributeError("Метод 'analyze_reviews' не найден в ReviewAnalyzer.")
            # Сообщить UI, что начинается анализ для этого товара
            result_queue.put({"type": "update_loading_analyze", "product_name": product_name})
            analysis = ReviewAnalyzer.analyze_reviews(reviews, product_name)
            return analysis
        except Exception as e:
            error_msg = f"Ошибка ИИ-анализа для {product_name} ({product_id}): {e}"
            result_queue.put({"type": "error_partial", "message": error_msg}) # Не фатальная ошибка
            return f"Не удалось выполнить анализ для товара '{product_name}': Ошибка ({type(e).__name__})."

    @staticmethod
    def perform_analysis_process(product_id, result_queue):
        """Функция рабочего процесса для анализа ОДНОГО товара."""
        try:
            # 1. Получение данных
            product_data = ReviewAnalyzerApp._fetch_product_data(product_id, result_queue)
            if not product_data: return # Ошибка уже отправлена получателем данных

            # 2. Выполнение анализа
            analysis_result = ReviewAnalyzerApp._get_single_analysis(product_data, result_queue)

            # 3. Отправка финального результата
            result_type = "result" if product_data["reviews"] else "no_reviews"
            result_queue.put({
                "type": result_type,
                "product_name": product_data["product_name"],
                "analysis": analysis_result if result_type == "result" else f"У товара '{product_data['product_name']}' ({product_id}) нет отзывов."
            })

        except Exception as e:
            # Перехват всех неожиданных ошибок в одиночном процессе
            error_details = traceback.format_exc()
            result_queue.put({"type": "error", "message": f"Критическая ошибка при анализе товара {product_id}:\n{e}\n\nTraceback:\n{error_details}"})

    @staticmethod
    def perform_multiple_analysis_process(product_ids, result_queue):
        """Функция рабочего процесса для анализа и СРАВНЕНИЯ нескольких товаров."""
        try:
            # 1. Получение данных для всех товаров
            products_data = []
            for pid in product_ids:
                 data = ReviewAnalyzerApp._fetch_product_data(pid, result_queue)
                 if data: # Добавлять, только если получение данных прошло успешно
                     products_data.append(data)
                 # Если получение данных не удалось, ошибка уже отправлена через очередь

            if not products_data:
                 result_queue.put({"type": "error", "message": "Не удалось получить данные ни для одного из указанных товаров."})
                 return
            if len(products_data) < 2 and len(product_ids) >= 2:
                # Проверить, собирались ли мы сравнивать, но не удалось получить достаточно данных о товарах
                 result_queue.put({"type": "error", "message": f"Удалось получить данные только для {len(products_data)} из {len(product_ids)} товаров. Сравнение невозможно."})
                 # Опционально: продолжить анализ одного полученного товара? Нет, просто выдать ошибку для сравнения.
                 return

            # 2. Выполнение индивидуальных анализов
            individual_analyses = {}
            for p_data in products_data:
                analysis = ReviewAnalyzerApp._get_single_analysis(p_data, result_queue)
                individual_analyses[p_data["product_id"]] = {
                    "product_name": p_data["product_name"],
                    "analysis": analysis # Содержит сообщение об ошибке, если анализ не удался
                }

            # 3. Генерация промпта для сравнения и получение ответа ИИ
            result_queue.put({"type": "update_loading_compare", "count": len(individual_analyses)})
            comparison_prompt = ReviewAnalyzerApp._generate_comparison_prompt(individual_analyses)

            if not comparison_prompt: # Должно произойти, только если < 2 анализов завершились успешно
                 result_queue.put({"type": "error", "message": "Недостаточно данных для создания сравнения."})
                 return

            try:
                 if not hasattr(ReviewAnalyzer, '_get_ai_response'):
                      raise AttributeError("Метод '_get_ai_response' не найден в ReviewAnalyzer.")
                 comparison_analysis = ReviewAnalyzer._get_ai_response(comparison_prompt)
                 product_names = [d["product_name"] for d in individual_analyses.values()]
                 comparison_title = f"Сравнение: {', '.join(product_names)}"

                 result_queue.put({
                     "type": "result",
                     "product_name": comparison_title, # Заголовок для экрана результатов
                     "analysis": comparison_analysis
                 })
            except Exception as ai_error:
                 error_details = traceback.format_exc()
                 result_queue.put({"type": "error", "message": f"Ошибка при генерации сравнения ИИ:\n{ai_error}\n\nTraceback:\n{error_details}"})

        except Exception as e:
            # Перехват всех неожиданных ошибок в многопроцессном режиме
            error_details = traceback.format_exc()
            result_queue.put({"type": "error", "message": f"Критическая ошибка при сравнении товаров:\n{e}\n\nTraceback:\n{error_details}"})


    # --- Обработка результатов (Проверка очереди из основного потока) ---

    def check_analysis_results(self, loading_screen):
        """Периодически проверяет очередь результатов из процесса анализа."""
        if not loading_screen or not loading_screen.winfo_exists():
            return # Прекратить проверку, если экран загрузки исчез

        try:
            result = self.result_queue.get_nowait()

            # Обработать различные типы сообщений из очереди
            if result["type"] == "update_loading_fetch":
                self._update_loading_text(f"Получаем данные: \"{result.get('product_name', '?')}\"...")
                self.after(100, self.check_analysis_results, loading_screen) # Продолжить проверку
            elif result["type"] == "update_loading_analyze":
                 self._update_loading_text(f"Анализ ИИ: \"{result.get('product_name', '?')}\"...")
                 self.after(100, self.check_analysis_results, loading_screen) # Продолжить проверку
            elif result["type"] == "update_loading_compare":
                 self._update_loading_text(f"Создаем сравнение для {result.get('count', '?')} товаров...")
                 self.after(100, self.check_analysis_results, loading_screen) # Продолжить проверку
            elif result["type"] == "result":
                 self._destroy_loading_screen(loading_screen)
                 self.show_results(result["product_name"], result["analysis"])
            elif result["type"] == "no_reviews":
                 self._destroy_loading_screen(loading_screen)
                 self.show_no_reviews(result["product_name"])
            elif result["type"] == "error": # Фатальная ошибка
                 self._destroy_loading_screen(loading_screen)
                 self.show_error_on_main_screen(result["message"])
            elif result["type"] == "error_partial": # Не фатальная, возможно, записать в лог?
                 print(f"ПРЕДУПРЕЖДЕНИЕ (не фатально): {result['message']}") # Записать в консоль
                 # Продолжить проверку для получения финального результата
                 self.after(100, self.check_analysis_results, loading_screen)

        except multiprocessing.queues.Empty:
            # Очередь пуста, проверить позже
            self.after(100, self.check_analysis_results, loading_screen)
        except tk.TclError:
             # Экран загрузки мог быть неожиданно уничтожен
             print("Предупреждение: Окно загрузки исчезло во время проверки.")
             if not self.result_frame.winfo_ismapped(): self.go_back() # Попытаться восстановить состояние
        except Exception as e:
            # Перехватить неожиданные ошибки во время обработки результатов
            self._destroy_loading_screen(loading_screen)
            error_details = traceback.format_exc()
            self.show_error_on_main_screen(f"Критическая ошибка обработки результатов:\n{e}\n\nTraceback:\n{error_details}")

    def _update_loading_text(self, text):
         """Безопасно обновляет текст метки загрузки."""
         if self.loading_label and self.loading_label.winfo_exists():
             self.loading_label.configure(text=text)
             self.update_idletasks()


    # --- Отображение финальных результатов/ошибок ---

    def show_results(self, product_name, analysis):
        """Отображает экран с результатами анализа."""
        if self.main_frame.winfo_ismapped(): self.main_frame.pack_forget()
        self.result_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self.title(f"Анализ: {product_name[:50]}{'...' if len(product_name)>50 else ''}") # Укоротить заголовок, если он слишком длинный

        # Упаковать заголовок и карточку (только если еще не упакованы - может случиться при восстановлении после ошибки)
        if not self.product_title_label.winfo_ismapped():
             self.product_title_label.pack(pady=(15, 10), padx=25, fill=tk.X, anchor='n')
        if not self.result_card.winfo_ismapped():
             self.result_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 15))

        self.product_title_label.configure(text=product_name) # Обновить текст
        self._set_result_text(analysis)
        self.update_idletasks()
        self._update_title_wraplength() # Скорректировать перенос строк после упаковки/обновления
        self.after(150, self._resize_window_based_on_content) # Изменить размер после небольшой задержки

    def show_no_reviews(self, product_name):
        """Отображает сообщение о том, что отзывы не найдены."""
        if self.main_frame.winfo_ismapped(): self.main_frame.pack_forget()
        self.result_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)

        self.title(f"Нет отзывов: {product_name[:50]}{'...' if len(product_name)>50 else ''}")

        # Упаковать заголовок и карточку
        if not self.product_title_label.winfo_ismapped():
             self.product_title_label.pack(pady=(15, 10), padx=25, fill=tk.X, anchor='n')
        if not self.result_card.winfo_ismapped():
            self.result_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 15))

        self.product_title_label.configure(text=product_name)
        no_reviews_message = f"У товара '{product_name}' пока нет отзывов.\n\nАнализ невозможен."
        self._set_result_text(no_reviews_message)
        self.update_idletasks()
        self._update_title_wraplength()
        # Обычно нет необходимости автоматически изменять размер для этого короткого сообщения

    def show_error_on_main_screen(self, message):
        """Отображает окно с сообщением об ошибке, убедившись, что главный экран виден."""
        if not self.main_frame.winfo_ismapped():
            self.go_back() # Сначала переключиться обратно на главный экран
        # Использовать self.after, чтобы убедиться, что go_back() завершил рендеринг перед показом всплывающего окна
        self.after(50, lambda: messagebox.showerror("Ошибка анализа", message, parent=self)) # Установить родительский элемент

    def _resize_window_based_on_content(self):
        """Пытается изменить размер окна на основе высоты текста результата."""
        # Это эвристика и может быть не идеальной
        try:
            if not self.result_text.winfo_exists() or not self.result_frame.winfo_ismapped():
                 return

            self.result_text.update_idletasks()
            # Оценить требуемую высоту: строки * высота_строки + отступы
            # CTkTextbox не имеет прямого подсчета строк, использовать index('end-1c')
            num_lines = int(self.result_text.index('end-1c').split('.')[0])
            # Оценить высоту строки на основе шрифта - это приблизительно!
            line_height_estimate = self.fonts["result_text"].cget("size") + 6 # Добавить немного отступа
            text_height = num_lines * line_height_estimate

            # Добавить высоту для заголовка, кнопки, отступов и т.д.
            other_elements_height = 150
            total_content_height = text_height + other_elements_height

            # Ограничить высоту между minsize и 85% высоты экрана
            screen_height = self.winfo_screenheight()
            max_height = int(screen_height * 0.85)
            min_height = self.winfo_reqheight() # Использовать запрошенный минимум или текущую геометрию
            min_h = max(min_height, 400) # Гарантировать минимум 400px

            new_height = max(min_h, min(total_content_height, max_height))

            # Сохранить ширину, настроить высоту
            current_width = self.winfo_width()
            # Гарантировать минимальную ширину для лучшего макета, особенно при сравнении
            min_w = 900 if "Сравнение" in self.product_title_label.cget("text") else 700
            new_width = max(current_width, min_w)

            self.geometry(f"{new_width}x{int(new_height)}") # Использовать int для геометрии

        except (tk.TclError, AttributeError, ValueError) as e:
            print(f"Предупреждение: Не удалось автоматически изменить размер окна: {e}")


# --- Точка входа в приложение ---
if __name__ == "__main__":
    # Требуется для упаковки с multiprocessing (например, PyInstaller)
    multiprocessing.freeze_support()

    app = None # Инициализировать app значением None
    try:
        # Проверка зависимостей теперь происходит при импорте
        app = ReviewAnalyzerApp()
        app.mainloop()

    except tk.TclError as e:
        # Обработать случаи, когда сам Tkinter не может инициализироваться
        print(f"КРИТИЧЕСКАЯ ОШИБКА Tcl/Tk: {e}")
        messagebox.showerror("Ошибка Tcl/Tk", f"Не удалось инициализировать графическую подсистему:\n{e}\n\nВозможно, отсутствует необходимая библиотека или дисплей.")
    except Exception as e:
        # Перехватить любые другие неожиданные ошибки запуска
        print(f"КРИТИЧЕСКАЯ ОШИБКА ЗАПУСКА: {e}")
        error_details = traceback.format_exc()
        print(error_details)
        try:
             # Попытаться показать сообщение об ошибке, если возможно
             root = tk.Tk()
             root.withdraw()
             messagebox.showerror("Критическая ошибка", f"Произошла непредвиденная ошибка при запуске приложения:\n{e}")
             root.destroy()
        except Exception: # Если даже показ ошибки не удался
             pass # Просто вывести в консоль (уже сделано)
