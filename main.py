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
    """CTkEntry с поддержкой Ctrl+V/A (рус/англ), Ctrl+BackSpace с авто-повтором и Delete."""
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Ctrl+V и Ctrl+A (ловим keysym для рус/англ)
        self.bind('<Control-KeyPress>', self._on_ctrl_key)
        # Ctrl+BackSpace: ручной автоповтор удаления слова
        self.bind('<KeyPress-BackSpace>', self._on_backspace_press)
        self.bind('<KeyRelease-BackSpace>', self._on_backspace_release)
        # Delete очищает весь текст (ловим KeyPress, чтобы проверить state)
        self.bind('<KeyPress-Delete>', self._on_delete_press)

    def _on_ctrl_key(self, event):
        ks = event.keysym.lower()
        kc = event.keycode
        # Ctrl+V (физическая V=86 или русская М)
        if kc == 86 or ks == 'м':
            try:
                self.insert(self.index(tk.INSERT), self.clipboard_get())
            except tk.TclError:
                pass
            return 'break'
        # Ctrl+A (физическая A=65 или русская Ф)
        if kc == 65 or ks == 'ф':
            self.select_range(0, tk.END)
            self.icursor(tk.END)
            return 'break'
        # Остальные Ctrl-сочетания пропускаем (Ctrl+C и т.д.)
        return None

    def _on_backspace_press(self, event):
        # При Ctrl+BackSpace запускаем удаление слова с повтором
        if event.state & 0x4:
            # Убедимся, что не запущен уже другой автоповтор
            if not getattr(self, '_bs_active', False):
                self._bs_active = True
                self._delete_prev_word()
            return 'break' # Предотвратить стандартное удаление символа
        # Если не Ctrl, пусть работает стандартный Backspace
        return None

    def _delete_prev_word(self):
        # Проверяем флаг активности перед выполнением
        if not getattr(self, '_bs_active', False):
            return
        pos = self.index(tk.INSERT)
        text = self.get()
        if pos > 0:
            # пропускаем пробелы слева
            i = pos
            while i > 0 and text[i-1].isspace(): i -= 1
            # пропускаем символы слова
            j = i
            while j > 0 and not text[j-1].isspace(): j -= 1
            # удаляем
            if j != pos:
                self.delete(j, pos)
                self.icursor(j)
            # планируем следующий вызов, если флаг всё ещё активен
            if getattr(self, '_bs_active', False):
                self._bs_after_id = self.after(100, self._delete_prev_word)
        else:
             # Если курсор в начале, прекращаем автоповтор
             self._bs_active = False

    def _on_backspace_release(self, event):
        # Останавливаем автоповтор Ctrl+BackSpace при отпускании клавиши
        if getattr(self, '_bs_active', False):
            self._bs_active = False
            if hasattr(self, '_bs_after_id'):
                self.after_cancel(self._bs_after_id)
                # Безопасное удаление атрибута
                try: del self._bs_after_id
                except AttributeError: pass
        return None

    def _on_delete_press(self, event):
        # Delete (без Ctrl) очищает весь текст
        if not (event.state & 0x4): # Убедимся, что Ctrl не нажат
            self.delete(0, tk.END)
            return 'break'
        return None

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
        
        # Переменные для отдельных полей ввода товаров при сравнении
        self.product_entries = []
        self.product_frames = []

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
        self.mode_var.trace_add("write", self._update_input_mode)

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
        
        # Контейнер для полей ввода
        self.input_container = ctk.CTkFrame(content_frame, fg_color="transparent")
        self.input_container.pack(fill=tk.X, padx=20, pady=(0, 15))
        
        # Создаем поле для одного товара (по умолчанию)
        self._create_single_product_input(self.input_container)
        
        # Создаем контейнер для нескольких товаров (скрыт изначально)
        self.multi_products_container = ctk.CTkFrame(self.input_container, fg_color="transparent")
        
        # Создаем форму для сравнения товаров (до 4 полей)
        self._create_multi_products_input(self.multi_products_container)

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
        ctk.CTkLabel(self.main_frame, text="Анализ обычно занимает от 3 до 10 секунд", font=self.fonts["footer"], text_color=SECONDARY_TEXT).pack(pady=(0, 5))

    def _create_mode_switcher(self, parent):
        """Создает радиокнопки выбора режима."""
        mode_frame = ctk.CTkFrame(parent, fg_color="transparent")
        mode_frame.pack(fill=tk.X, pady=(0, 10))
        ctk.CTkLabel(mode_frame, text="Режим анализа:", font=self.fonts["header"], anchor="w", text_color=TEXT_COLOR).pack(side=tk.LEFT, padx=(0, 10))
        modes = [("Один товар", "single"), ("Сравнение товаров", "multi")]
        for i, (text, value) in enumerate(modes):
            ctk.CTkRadioButton(
                mode_frame, text=text, variable=self.mode_var, value=value,
                font=self.fonts["text"], text_color=TEXT_COLOR, fg_color=ACCENT_COLOR
            ).pack(side=tk.LEFT, padx=(0, 15 if i == 0 else 0))

    def _create_single_product_input(self, parent):
        """Создает поле ввода URL/ID для одного товара."""
        self.single_product_frame = ctk.CTkFrame(parent, fg_color="transparent")
        self.single_product_frame.pack(fill=tk.X)
        
        ctk.CTkLabel(
            self.single_product_frame, 
            text="Ссылка на товар или артикул", 
            font=self.fonts["header"], 
            anchor="w", 
            text_color=TEXT_COLOR
        ).pack(fill=tk.X, pady=(0, 8))
        
        url_input_frame = ctk.CTkFrame(self.single_product_frame, fg_color=INPUT_BG, corner_radius=10)
        url_input_frame.pack(fill=tk.X)
        
        self.url_input = CustomEntry(
            url_input_frame, height=40, border_width=0, fg_color="transparent",
            text_color=TEXT_COLOR, font=self.fonts["text"], 
            placeholder_text="Вставьте ссылку или артикул товара Wildberries"
        )
        self.url_input.pack(fill=tk.X, padx=10, pady=8)

    def _create_multi_products_input(self, parent):
        """Создает поля ввода для сравнения до 4 товаров."""
        instruction_label = ctk.CTkLabel(
            parent, 
            text="Введите до 4 товаров для сравнения:", 
            font=self.fonts["header"], 
            anchor="w", 
            text_color=TEXT_COLOR
        )
        instruction_label.pack(fill=tk.X, pady=(0, 10))
        
        # Создаем 4 поля для товаров
        for i in range(4):
            product_frame = ctk.CTkFrame(parent, fg_color="transparent")
            product_frame.pack(fill=tk.X, pady=(0, 10))
            
            label_text = f"Товар {i+1}:"
            ctk.CTkLabel(
                product_frame, 
                text=label_text, 
                font=self.fonts["text"], 
                width=70,
                anchor="w", 
                text_color=TEXT_COLOR
            ).pack(side=tk.LEFT, padx=(0, 10))
            
            input_frame = ctk.CTkFrame(product_frame, fg_color=INPUT_BG, corner_radius=10)
            input_frame.pack(side=tk.LEFT, fill=tk.X, expand=True)
            
            entry = CustomEntry(
                input_frame, 
                height=35, 
                border_width=0, 
                fg_color="transparent",
                text_color=TEXT_COLOR, 
                font=self.fonts["text"], 
                placeholder_text=f"Ссылка или артикул товара {i+1}"
            )
            entry.pack(fill=tk.X, padx=10, pady=5)
            
            self.product_entries.append(entry)
            self.product_frames.append(product_frame)

    def _update_input_mode(self, *args):
        """Обновляет режим ввода в зависимости от выбранного режима."""
        is_multi = self.mode_var.get() == "multi"
        
        # Скрываем/показываем соответствующие поля ввода
        if is_multi:
            self.single_product_frame.pack_forget()
            self.multi_products_container.pack(fill=tk.X)
        else:
            self.multi_products_container.pack_forget()
            self.single_product_frame.pack(fill=tk.X)
            
        # Изменяем размер окна при переключении режимов
        if is_multi:
            current_width = self.winfo_width()
            self.geometry(f"{current_width}x650")  # Увеличиваем высоту для режима сравнения
        else:
            current_width = self.winfo_width()
            self.geometry(f"{current_width}x400")

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

    def _update_title_wraplength(self, event=None):
        """Корректирует длину переноса строки метки заголовка результата в зависимости от ширины фрейма."""
        try:
            # Отступы padx по 25 с каждой стороны для метки заголовка
            wraplength = self.result_frame.winfo_width() - 50
            if wraplength > 0 and hasattr(self, 'product_title_label'):
                self.product_title_label.configure(wraplength=wraplength)
        except tk.TclError:
            # Обработать случай, когда виджет уничтожен
            pass

    def _set_result_text(self, text):
        """Задает текст в результирующем текстовом поле."""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.configure(state=tk.DISABLED)

    def go_back(self):
        """Возвращается на основной экран."""
        self.result_frame.pack_forget()
        self.main_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=15)
        self.geometry("900x650" if self.mode_var.get() == "multi" else "900x400")
        
    def show_loading_screen(self, message="Анализируем отзывы...\nПожалуйста, подождите"):
        """Показывает экран загрузки."""
        # Создаем полупрозрачный оверлей поверх всего окна
        loading_screen = tk.Toplevel(self)
        loading_screen.title("")
        loading_screen.geometry(f"{self.winfo_width()}x{self.winfo_height()}+{self.winfo_rootx()}+{self.winfo_rooty()}")
        loading_screen.configure(bg="#1E1E1E")
        loading_screen.attributes("-alpha", 0.95)  # Полупрозрачность
        loading_screen.transient(self)  # Привязываем к родительскому окну
        loading_screen.overrideredirect(True)  # Убираем рамку окна
        loading_screen.resizable(False, False)
        loading_screen.attributes("-topmost", True)
        loading_screen.lift()
        
        # Добавляем все на экран загрузки
        frame = tk.Frame(loading_screen, bg="#1E1E1E")
        frame.place(relx=0.5, rely=0.5, anchor=tk.CENTER)
        
        # Используем стандартный виджет Label с animated gif, т.к. ctk не поддерживает анимированные изображения
        spinner_label = tk.Label(frame, bg="#1E1E1E", fg="#FFFFFF", font=('Arial', 20))
        spinner_label.config(text="⚙️")
        spinner_label.pack(pady=(0, 10))
        
        message_label = tk.Label(frame, text=message, fg="#FFFFFF", bg="#1E1E1E", font=('Arial', 12))
        message_label.pack(pady=(0, 10))
        
        # Сохраняем для возможности обновления
        self.loading_frame = frame
        self.loading_label = message_label
        
        # Обновляем GUI и убеждаемся, что окно видимо перед вызовом grab_set
        loading_screen.update()
        
        # Обернем вызов grab_set в try-except для безопасности
        try:
            # Даем немного времени на отрисовку окна
            self.after(100, lambda: self._safely_grab_focus(loading_screen))
        except Exception as e:
            print(f"Предупреждение: Не удалось захватить фокус: {e}")
        
        return loading_screen
        
    def _safely_grab_focus(self, window):
        """Безопасно захватывает фокус для окна, если оно видимо."""
        try:
            if window.winfo_exists() and window.winfo_viewable():
                window.grab_set()
        except tk.TclError as e:
            print(f"Предупреждение: Не удалось захватить фокус: {e}")

    def _destroy_loading_screen(self, loading_screen):
        """Уничтожает экран загрузки."""
        try:
            loading_screen.destroy()
            self.loading_frame = None
            self.loading_label = None
        except (tk.TclError, AttributeError):
            # Обработать случай, когда окно уже уничтожено
            pass

    def _check_groq_api_key(self):
        """Проверяет наличие API ключа Groq."""
        api_key = os.environ.get("GROQ_API_KEY")
        if not api_key:
            key_paths = [os.path.expanduser("~/.groq/api_key"), "./.groq_api_key", "./groq_api_key.txt"]
            for path in key_paths:
                if os.path.exists(path):
                    try:
                        with open(path, "r") as f:
                            api_key = f.read().strip()
                            if api_key:
                                break
                    except:
                        pass

        if not api_key:
            warning = (
                "API ключ Groq не найден. Функции анализа будут недоступны.\n\n"
                "Для использования необходимо:\n"
                "1. Получить API ключ на сайте https://console.groq.com\n"
                "2. Сохранить его в файле .env в формате GROQ_API_KEY=ваш_ключ"
            )
            messagebox.showwarning("Отсутствует API ключ", warning)

    @staticmethod
    def extract_product_id(url_or_id):
        """
        Извлекает идентификатор товара из URL или возвращает сам ID, если передана строка с цифрами.
        
        Args:
            url_or_id: URL товара или его артикул
            
        Returns:
            str: Идентификатор товара
        """
        # Если передан артикул (строка цифр), возвращаем его
        if re.match(r'^\d+$', url_or_id.strip()):
            return url_or_id.strip()
        
        # Если передан URL, извлекаем артикул
        try:
            # Для wildberries.ru/catalog/ID/detail.aspx
            # Или для wildberries.ru/catalog/ID/
            if "wildberries.ru/catalog/" in url_or_id:
                pattern = r"wildberries\.ru/catalog/(\d+)"
                match = re.search(pattern, url_or_id)
                if match:
                    return match.group(1)
                
            # Паттерн для прямых числовых идентификаторов из URL
            pattern = r"\d{7,15}"  # Ищем 7+ цифр подряд
            match = re.search(pattern, url_or_id)
            if match:
                return match.group(0)
        except:
            pass
            
        # Если не удалось извлечь, возвращаем исходную строку
        return url_or_id.strip()

    def start_analysis(self):
        """Запускает процесс анализа отзывов."""
        loading_screen = self.show_loading_screen()
        
        try:
            self.result_queue = multiprocessing.Queue()
            
            # Определяем режим анализа
            mode = self.mode_var.get()
            
            if mode == "single":
                # Анализ одного товара
                product_id = self.url_input.get().strip()
                if not product_id:
                    self._destroy_loading_screen(loading_screen)
                    messagebox.showerror("Ошибка", "Введите ссылку на товар или его артикул.")
                    return
                
                # Извлекаем ID товара
                product_id = self.extract_product_id(product_id)
                
                # Запускаем процесс анализа
                process = multiprocessing.Process(
                    target=self.perform_analysis_process,
                    args=(product_id, self.result_queue)
                )
                process.daemon = True
                process.start()
                
            else:
                # Анализ нескольких товаров
                product_ids = []
                
                # Собираем непустые товары из полей ввода
                for entry in self.product_entries:
                    product_id = entry.get().strip()
                    if product_id:
                        product_ids.append(self.extract_product_id(product_id))
                
                if len(product_ids) < 2:
                    self._destroy_loading_screen(loading_screen)
                    messagebox.showerror("Ошибка", "Введите минимум два товара для сравнения.")
                    return
                
                # Запускаем процесс анализа нескольких товаров
                process = multiprocessing.Process(
                    target=self.perform_multiple_analysis_process,
                    args=(product_ids, self.result_queue)
                )
                process.daemon = True
                process.start()
            
            # После запуска процесса планируем проверку очереди результатов
            self.after(100, lambda: self.check_analysis_results(loading_screen))
            
        except Exception as e:
            self._destroy_loading_screen(loading_screen)
            messagebox.showerror("Ошибка", f"Неизвестная ошибка: {str(e)}")
            
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

        # Извлекаем названия товаров (brand_name или product_name)
        product_names = []
        for data in individual_analyses.values():
            full_name = data['product_name']
            # Пытаемся извлечь brand_name из product_name (предполагая формат "Brand - Name")
            parts = full_name.split(' - ')
            brand_name = parts[0] if len(parts) > 1 else full_name
            product_names.append(brand_name)

        prompt = f"Сравни следующие {num_products} товар{'а' if 2 <= num_products <= 4 else 'ов'} ({', '.join(product_names)}) на основе краткого анализа отзывов по каждому:\n\n"

        for product_id, data in individual_analyses.items():
            full_name = data['product_name']
            parts = full_name.split(' - ')
            brand_name = parts[0] if len(parts) > 1 else full_name
            prompt += f"{brand_name} (Артикул: {product_id})\n"
            prompt += f"Анализ отзывов:\n{data['analysis']}\n\n"

        # Общие инструкции по структуре
        prompt += """
Твоя задача - провести объективное и структурированное сравнение.

Структурируй свой ответ строго по следующему шаблону:
"""
        if num_products == 2:
            prompt += f"""
{product_names[0]} (Артикул: [номер]): [Краткое описание первого товара]
{product_names[1]} (Артикул: [номер]): [Краткое описание второго товара]

Основные плюсы и минусы:
- {product_names[0]}:
  Плюсы: [список]
  Минусы: [список]
- {product_names[1]}:
  Плюсы: [список]
  Минусы: [список]

Сравнение по ключевым параметрам:
[Сравни по 3-5 важным параметрам, релевантным для этих товаров]

Рекомендации:
[Напиши развернутую рекомендацию, какой товар лучше выбрать и почему. Объясни, для каких целей и категорий покупателей каждый из товаров подходит больше. Укажи преимущества одного товара над другим. Дай четкий совет, какой товар является лучшим выбором по соотношению цена/качество или для конкретных потребностей. Твоя рекомендация должна быть подробной и включать минимум 5-7 предложений.]
"""
        else: 
            prompt += f"""
{product_names[0]} (Артикул: [номер]): [краткое описание]
{product_names[1]} (Артикул: [номер]): [краткое описание]
... (для всех товаров) ...

Основные плюсы и минусы (для каждого товара):
"""
            for name in product_names:
                prompt += f"- {name}:\n  Плюсы: [список]\n  Минусы: [список]\n"
            prompt += """
Сравнительный анализ по параметрам:
[Сравни все товары по 3-5 важным параметрам]

Рекомендации:
[Напиши развернутую рекомендацию, какой товар лучше выбрать из всех представленных и почему. Дай конкретные советы о том, какой товар подходит для разных категорий покупателей и сценариев использования. Выдели явного лидера по соотношению цена/качество. Если есть товары, которые не рекомендуется покупать, явно укажи это с объяснением причин. Рекомендация должна быть подробной и включать минимум 5-7 предложений.]
"""
        prompt += "\nСтрого придерживайся этой структуры. Без эмодзи."
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
            
            # Проверка на наличие ошибки в тексте анализа
            if analysis.startswith("Ошибка GitHub Models API:") or "tokens_limit_reached" in analysis:
                error_msg = f"Ошибка при анализе товара '{product_name}': {analysis}"
                result_queue.put({"type": "error_partial", "message": error_msg})
                return f"""Не удалось выполнить анализ из-за ограничений API.

Анализ товара '{product_name}' не выполнен из-за ограничения размера запроса.
Ошибка: {analysis}

Попробуйте снова позже или используйте другой API."""
                
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
