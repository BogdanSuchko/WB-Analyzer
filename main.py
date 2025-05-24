# -*- coding: utf-8 -*-
import tkinter as tk
from tkinter import messagebox
import customtkinter as ctk
import os
import re
import multiprocessing
from dotenv import load_dotenv
import traceback # Для подробного отчета об ошибках
import datetime # <-- ДОБАВЛЕНО ДЛЯ ИСТОРИИ
import json # <-- ДОБАВЛЕНО ДЛЯ СОХРАНЕНИЯ/ЗАГРУЗКИ ИСТОРИИ

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
        self.geometry("900x450") # <-- ИЗМЕНЕНО
        self.minsize(700, 400)

        # --- Переменные состояния ---
        self.loading_overlay_frame = None # Фрейм для индикатора загрузки
        self.loading_overlay_label = None # Метка внутри фрейма загрузки
        self.result_queue = None
        self.mode_var = ctk.StringVar(value="single")
        
        # Переменные для отдельных полей ввода товаров при сравнении
        self.product_entries = []
        self.product_frames = []

        self.analysis_history = [] # <-- ДОБАВЛЕНО ДЛЯ ИСТОРИИ
        self.history_file_path = self._get_history_file_path() # <-- ДОБАВЛЕНО
        self._ensure_history_dir_exists() # <-- ДОБАВЛЕНО
        self._load_history_from_file() # <-- ДОБАВЛЕНО
        self.viewing_from_history = False # <-- ФЛАГ ДЛЯ НАВИГАЦИИ ИЗ ИСТОРИИ
        self.is_fullscreen = False # <-- ФЛАГ ДЛЯ ПОЛНОЭКРАННОГО РЕЖИМА

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
            "loading_icon": ctk.CTkFont(size=30),
            "loading_text": ctk.CTkFont(size=16),
        }

        # --- Инициализация ---
        self._check_groq_api_key()
        self._setup_frames()
        self._setup_main_widgets()
        self._setup_result_widgets()
        self._setup_history_widgets() # <-- ДОБАВЛЕНО ДЛЯ ИСТОРИИ
        self._setup_loading_overlay() # Создаем фрейм загрузки

        self.bind("<Button-1>", self._defocus)
        self.mode_var.trace_add("write", self._update_input_mode)
        self.bind("<F11>", self._toggle_fullscreen) # <-- ДОБАВЛЕНО ДЛЯ F11

        # Показать основной фрейм при запуске
        self.main_frame.pack(expand=True, fill="both") # Показываем главный экран сначала

    # --- Основные методы настройки ---

    def _setup_frames(self):
        """Создает основной фрейм и фрейм результатов."""
        self.main_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.result_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.history_frame = ctk.CTkFrame(self, fg_color="transparent") # <-- ДОБАВЛЕНО ДЛЯ ИСТОРИИ
        # Фрейм загрузки создается в _setup_loading_overlay

    def _setup_loading_overlay(self):
        """Создает виджеты для оверлея загрузки (скрыт по умолчанию)."""
        self.loading_overlay_frame = ctk.CTkFrame(self, fg_color=CARD_COLOR, corner_radius=10)
        # Не пакуем его сразу, он будет показан при необходимости

        # Центральный фрейм внутри оверлея для вертикального центрирования
        center_frame = ctk.CTkFrame(self.loading_overlay_frame, fg_color="transparent")
        center_frame.place(relx=0.5, rely=0.5, anchor="center")

        loading_icon_label = ctk.CTkLabel(center_frame, text="", font=self.fonts["loading_icon"], text_color=ACCENT_COLOR)
        loading_icon_label.pack(pady=(0, 10))

        self.loading_overlay_label = ctk.CTkLabel(center_frame, text="Анализ...", font=self.fonts["loading_text"], wraplength=300)
        self.loading_overlay_label.pack()


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

        # Кнопка "История анализов"
        history_button_frame = ctk.CTkFrame(content_frame, fg_color="transparent")
        history_button_frame.pack(pady=(0, 10), fill=tk.X) # Немного меньше отступ сверху
        history_button_frame.bind("<Button-1>", self._defocus)
        ctk.CTkButton(
            history_button_frame, text="История анализов", font=self.fonts["text"], # Шрифт поменьше
            width=200, height=35, command=self.show_history_screen, corner_radius=8,
            fg_color="#4a4a4c", hover_color="#5a5a5c", text_color=TEXT_COLOR
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
            self.geometry(f"{current_width}x450") # <-- ИЗМЕНЕНО

    def _setup_result_widgets(self):
        """Создает все виджеты для экрана результатов (для одиночного и сравнения)."""
        # --- Общие элементы для обоих режимов --- 
        header_frame = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        header_frame.pack(fill=tk.X, pady=(10, 5), padx=20)
        ctk.CTkButton(
            header_frame, text="← Назад", font=self.fonts["back_button"], command=self.go_back,
            width=100, height=32, corner_radius=16, fg_color="#3a3a3c",
            text_color=TEXT_COLOR, hover_color="#4a4a4c"
        ).pack(side=tk.LEFT)

        # --- Контейнер для ОДИНОЧНОГО АНАЛИЗА --- 
        self.single_result_container = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        # Этот контейнер будет упаковываться/распаковываться в show_results

        self.product_title_label = ctk.CTkLabel(
            self.single_result_container, text="", font=self.fonts["result_title"],
            text_color=TEXT_COLOR, anchor='w', justify="left"
        )
        # Упаковывается при отображении одиночного результата

        self.result_card = ctk.CTkFrame(self.single_result_container, corner_radius=15, fg_color=CARD_COLOR, border_width=2, border_color=ACCENT_COLOR)
        # Упаковывается при отображении одиночного результата

        self.result_text = ctk.CTkTextbox(
            self.result_card,
            font=self.fonts["result_text"],
            wrap="word",
            fg_color="transparent",
            text_color=TEXT_COLOR,
            # corner_radius=0, # Let it use default
            border_width=0,
            border_spacing=8, # Matched comparison style
            state=tk.DISABLED
        )
        self.result_text.pack(fill=tk.BOTH, expand=True, padx=10, pady=10) # Increased padding

        # --- Контейнер для СРАВНИТЕЛЬНОГО АНАЛИЗА (КОЛОНКИ) --- 
        self.comparison_result_container = ctk.CTkFrame(self.result_frame, fg_color="transparent")
        # Этот контейнер будет упаковываться/распаковываться в show_comparison_results

        self.comparison_overall_title_label = ctk.CTkLabel(
            self.comparison_result_container, text="", font=self.fonts["result_title"],
            text_color=TEXT_COLOR, anchor='w', justify="left", wraplength=700 # Начальная длина переноса
        )
        # Упаковывается в show_comparison_results

        self.columns_container_frame = ctk.CTkFrame(self.comparison_result_container, fg_color="transparent")
        # Упаковывается в show_comparison_results, колонки добавляются динамически
        
        # Контейнер для рекомендаций (с карточным фоном)
        self.recommendation_outer_container = ctk.CTkFrame(self.comparison_result_container, fg_color="transparent")
        # Упаковывается в show_comparison_results

        self.recommendation_card = ctk.CTkFrame(self.recommendation_outer_container, corner_radius=15, fg_color=CARD_COLOR, border_width=2, border_color=ACCENT_COLOR)
        # Упаковывается внутри self.recommendation_outer_container
        
        self.recommendation_title_label = ctk.CTkLabel(
            self.recommendation_card, text="🏆 Общие рекомендации и выводы:",
            font=self.fonts["header"], text_color=ACCENT_COLOR, anchor='w', justify="left"
        )
        # Упаковывается внутри self.recommendation_card

        self.recommendation_textbox = ctk.CTkTextbox(
            self.recommendation_card, font=self.fonts["result_text"], wrap="word",
            fg_color="transparent", text_color=TEXT_COLOR, corner_radius=0,
            border_width=0, border_spacing=10, state=tk.DISABLED # Убираем height=200
        )
        # Упаковывается внутри self.recommendation_card
        
        # Список для хранения ссылок на виджеты колонок, чтобы их можно было очищать
        self._dynamic_column_widgets = []

    def _setup_history_widgets(self):
        """Создает виджеты для экрана истории."""
        # --- Общие элементы для экрана истории ---
        history_header_frame = ctk.CTkFrame(self.history_frame, fg_color="transparent")
        history_header_frame.pack(fill=tk.X, pady=(10, 5), padx=20)
        
        ctk.CTkButton(
            history_header_frame, text="← Назад", font=self.fonts["back_button"], 
            command=self.go_back_to_main_from_history, # Новая команда
            width=100, height=32, corner_radius=16, fg_color="#3a3a3c",
            text_color=TEXT_COLOR, hover_color="#4a4a4c"
        ).pack(side=tk.LEFT)

        # Добавляем кнопку очистки истории
        self.clear_history_button = ctk.CTkButton(
            history_header_frame, text="Очистить всю историю", font=self.fonts["back_button"],
            command=self._clear_history, width=150, height=32, corner_radius=16,
            fg_color="#e74c3c", hover_color="#c0392b", text_color=TEXT_COLOR,
            text_color_disabled="#D3D3D3"  # Светло-серый для неактивного состояния
        )
        self.clear_history_button.pack(side=tk.RIGHT)

        history_title_label = ctk.CTkLabel(
            self.history_frame, text="История анализов", font=self.fonts["result_title"],
            text_color=TEXT_COLOR, anchor='center'
        )
        history_title_label.pack(pady=(5, 15), padx=20, fill=tk.X)

        # Scrollable frame для элементов истории
        self.history_scroll_frame = ctk.CTkScrollableFrame(self.history_frame, fg_color=CARD_COLOR, corner_radius=10)
        self.history_scroll_frame.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 15))
        
        # Начальное сообщение, если история пуста
        self.no_history_label = ctk.CTkLabel(self.history_scroll_frame, 
                                             text="История анализов пока пуста.",
                                             font=self.fonts["text"], 
                                             text_color=SECONDARY_TEXT)
        # self.no_history_label.pack(pady=20) # Будет упаковано в _populate_history_list

    def _clear_history(self):
        """Очищает историю анализов после подтверждения."""
        confirm = messagebox.askyesno(
            title="Подтверждение очистки истории",
            message="Вы действительно хотите удалить всю историю анализов?\nЭто действие нельзя будет отменить.",
            icon=messagebox.WARNING,
            parent=self
        )
        
        if confirm:
            self.analysis_history = []  # Очищаем список истории
            self._save_history_to_file()  # Сохраняем пустой список в файл
            self._populate_history_list()  # Обновляем отображение списка истории

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

    def _toggle_fullscreen(self, event=None):
        """Переключает полноэкранный режим окна."""
        self.is_fullscreen = not self.is_fullscreen
        self.attributes("-fullscreen", self.is_fullscreen)
        # Если выходим из полноэкранного режима, и окно было 'zoomed', восстанавливаем 'normal'
        # Это помогает избежать странного поведения с размерами после выхода из F11, если окно было максимизировано.
        if not self.is_fullscreen and self.state() == 'zoomed':
            self.state('normal')
            # Можно добавить небольшую задержку и восстановить исходные размеры, если нужно,
            # но пока оставим так для простоты.
            # self.geometry("900x650" if self.mode_var.get() == "multi" else "900x450")


    def _update_title_wraplength(self, event=None):
        """Корректирует длину переноса строки метки заголовка результата в зависимости от ширины фрейма."""
        try:
            # Для одиночного результата
            if hasattr(self, 'product_title_label') and self.product_title_label.winfo_ismapped():
                wraplength_single = self.single_result_container.winfo_width() - 50 # Используем ширину single_result_container
                if wraplength_single > 0:
                    self.product_title_label.configure(wraplength=wraplength_single)
            
            # Для сравнительного результата
            if hasattr(self, 'comparison_overall_title_label') and self.comparison_overall_title_label.winfo_ismapped():
                wraplength_compare = self.comparison_result_container.winfo_width() - 50 # Используем ширину comparison_result_container
                if wraplength_compare > 0:
                    self.comparison_overall_title_label.configure(wraplength=wraplength_compare)

        except tk.TclError:
            pass # Виджет может быть уничтожен

    def _set_result_text(self, text):
        """Задает текст в результирующем текстовом поле."""
        self.result_text.configure(state=tk.NORMAL)
        self.result_text.delete("1.0", tk.END)
        self.result_text.insert("1.0", text)
        self.result_text.configure(state=tk.DISABLED)

    def go_back(self):
        """Возвращается на основной экран или на экран истории."""
        if self.state() == 'zoomed': 
            self.state('normal')
        
        self.result_frame.pack_forget()
        self.single_result_container.pack_forget() 
        self.comparison_result_container.pack_forget() 

        if self.viewing_from_history:
            self.viewing_from_history = False # Сбрасываем флаг
            self.show_history_screen() # Возвращаемся на экран истории
        else:
            self.history_frame.pack_forget() # Скрываем историю, если вдруг была активна (маловероятно тут)
            self.main_frame.pack(expand=True, fill="both")
            self.geometry("900x650" if self.mode_var.get() == "multi" else "900x450") 
            self.title(APP_NAME) 
        
    def _show_loading_overlay(self, message):
        """Показывает оверлей загрузки с указанным сообщением."""
        self.main_frame.pack_forget()
        self.result_frame.pack_forget()
        self.loading_overlay_label.configure(text=message)
        self.loading_overlay_frame.pack(expand=True, fill="both", padx=20, pady=20)
        self.update_idletasks() # Обновить GUI немедленно


    def _hide_loading_overlay(self):
        """Скрывает оверлей загрузки."""
        self.loading_overlay_frame.pack_forget()


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
        # Сбрасываем флаг просмотра из истории, так как это новый анализ
        self.viewing_from_history = False
        
        # Показать экран загрузки ПЕРЕД запуском процесса
        loading_message = "Анализируем отзывы...\nПожалуйста, подождите"
        self._show_loading_overlay(loading_message)

        try:
            self.result_queue = multiprocessing.Queue()
            
            # Определяем режим анализа
            mode = self.mode_var.get()
            
            if mode == "single":
                # Анализ одного товара
                product_id_input = self.url_input.get().strip()
                if not product_id_input:
                    self._hide_loading_overlay() # Скрыть загрузку при ошибке запуска процесса
                    messagebox.showerror("Ошибка", "Введите ссылку на товар или его артикул.", parent=self)
                    return
                
                # Извлекаем ID товара
                product_id = self.extract_product_id(product_id_input)
                
                # Запускаем процесс анализа
                self._show_loading_overlay(f"Анализируем: {product_id_input[:30]}...") # Обновляем сообщение при старте
                process = multiprocessing.Process(
                    target=self.perform_analysis_process,
                    args=(product_id, self.result_queue)
                )
                process.daemon = True
                process.start()
                
            else: # Режим "multi" (сравнение)
                product_ids_inputs = [] # Для хранения сырых введенных строк
                product_ids_processed = [] # Для хранения обработанных (извлеченных) ID

                for entry in self.product_entries:
                    product_input_raw = entry.get().strip()
                    if product_input_raw:
                        product_ids_inputs.append(product_input_raw)
                        product_ids_processed.append(self.extract_product_id(product_input_raw))
                
                if len(product_ids_processed) < 2:
                    self._hide_loading_overlay() # Сначала скрываем оверлей
                    # Теперь восстанавливаем главный экран, чтобы он был фоном для диалога
                    self.main_frame.pack(expand=True, fill="both") 

                    if len(product_ids_processed) == 1:
                        actual_input_for_dialog = product_ids_inputs[0]
                        id_to_analyze_single = product_ids_processed[0]

                        user_choice = messagebox.askyesno(
                            title="Сравнение товаров",
                            message=f"Вы указали только один товар: \"{actual_input_for_dialog[:40]}{'...' if len(actual_input_for_dialog)>40 else ''}\" для сравнения.\n\nХотите проанализировать его в режиме 'Один товар'?",
                            icon=messagebox.QUESTION,
                            parent=self
                        )
                        if user_choice: # Пользователь выбрал "Да"
                            self.mode_var.set("single")
                            self.url_input.delete(0, tk.END)
                            self.url_input.insert(0, id_to_analyze_single)
                            # Снова показываем оверлей, так как сейчас начнется анализ
                            self._show_loading_overlay(f"Анализируем: {actual_input_for_dialog[:30]}...")
                            process = multiprocessing.Process(
                                target=self.perform_analysis_process,
                                args=(id_to_analyze_single, self.result_queue)
                            )
                            process.daemon = True
                            process.start()
                            self.after(100, lambda: self.check_analysis_results())
                            return 
                        else: # Пользователь выбрал "Нет"
                            # main_frame уже восстановлен, просто выходим
                            return
                    else: # Меньше одного товара (0 валидных вводов)
                        messagebox.showerror("Ошибка", "Введите минимум два товара для сравнения.", parent=self)
                        # main_frame уже восстановлен, просто выходим
                        return
                
                # Если товаров 2 или больше, продолжаем как обычно для сравнения
                # В этом случае _show_loading_overlay был вызван в самом начале start_analysis
                # и не скрывался, так что все корректно.
                # Однако, для ясности и если бы мы меняли начальный вызов, можно было бы добавить его здесь:
                # self._show_loading_overlay(f"Анализируем {len(product_ids_processed)} товаров для сравнения...")
                # Но так как он УЖЕ показан в начале start_analysis и не был скрыт для этого пути, 
                # можно просто обновить его текст, если нужно, или оставить как есть.
                # Обновим текст для ясности, что именно происходит
                self.loading_overlay_label.configure(text=f"Анализируем {len(product_ids_processed)} товаров для сравнения...")

                process = multiprocessing.Process(
                    target=self.perform_multiple_analysis_process,
                    args=(product_ids_processed, self.result_queue) # Передаем обработанные ID
                )
                process.daemon = True
                process.start()
            
            # После запуска процесса планируем проверку очереди результатов
            self.after(100, lambda: self.check_analysis_results())
            
        except Exception as e:
            self._hide_loading_overlay() # Скрыть загрузку при ошибке запуска процесса
            detailed_error = traceback.format_exc()
            print(f"Ошибка запуска процесса анализа: {e}\n{detailed_error}")
            messagebox.showerror("Ошибка", f"Не удалось запустить процесс анализа:\n{e}")

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
    def _get_single_analysis(product_data, result_queue):
        """Выполняет ИИ-анализ отзывов одного товара."""
        product_id = product_data["product_id"]
        product_name = product_data["product_name"]
        reviews = product_data["reviews"]

        if not reviews:
            return f"На текущий момент для товара «{product_name}» (арт. {product_id}) не найдено отзывов. К сожалению, без них анализ провести невозможно. Попробуйте проверить позже, возможно, они появятся!"

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
    def _generate_comparison_prompt(individual_analyses_data):
        """Генерирует промпт для ИИ для получения ОБЩИХ РЕКОМЕНДАЦИЙ по выбору между несколькими товарами,
        предполагая, что их индивидуальные анализы уже известны и будут отображены отдельно."""
        num_products = len(individual_analyses_data)
        if num_products < 2: return ""

        product_info_for_prompt = []
        for data in individual_analyses_data.values(): # individual_analyses_data это individual_analyses_map
            product_info_for_prompt.append(
                f"{data['product_name']} (количество реальных отзывов для анализа: {data.get('review_count', 'неизвестно')})"
            )
        
        product_names_str = ", ".join(product_info_for_prompt)

        prompt = f"Тебе предоставлены индивидуальные анализы для {num_products} товар{'а' if 2 <= num_products <= 4 else 'ов'}: {product_names_str}. Эти анализы будут показаны пользователю отдельно.\n\n"
        prompt += "Твоя задача — на основе этих (невидимых тебе сейчас, но предполагаемых развернутых) индивидуальных анализов, а также УЧИТЫВАЯ КОЛИЧЕСТВО ОТЗЫВОВ для каждого товара, предоставить ТОЛЬКО ИТОГОВЫЕ ОБЩИЕ РЕКОМЕНДАЦИИ И ВЫВОДЫ для пользователя, который пытается выбрать между этими товарами.\n\n"
        prompt += "ВАЖНЫЕ УКАЗАНИЯ:\n"
        prompt += "- Если у товара очень мало отзывов (например, меньше 5) или в его индивидуальном анализе указано, что сделать выводы невозможно (например, из-за отсутствия или недостаточности данных), ЭТОТ ТОВАР НЕ МОЖЕТ БЫТЬ НАЗВАН 'ВЫБОРОМ РЕДАКЦИИ' И НЕ МОЖЕТ БЫТЬ РЕКОМЕНДОВАН КАК ЛУЧШИЙ. В таких случаях честно укажи на нехватку данных для уверенных выводов по этому товару.\n"
        prompt += "- Твои рекомендации должны основываться на ДОСТОВЕРНОМ анализе. Не делай предположений или необоснованных выводов при недостатке данных.\n"
        prompt += "- Если по всем товарам мало данных, так и укажи, что сделать однозначный выбор сложно.\n\n"
        prompt += "Структурируй свой ответ СТРОГО по следующему шаблону:\n\n"

        prompt += "## 🏆 Итоговые рекомендации и вывод:\n\n"
        prompt += "### 🔥 Выбор редакции (если есть явный лидер на основе ДОСТАТОЧНОГО количества отзывов и УВЕРЕННОГО анализа):\n"
        prompt += "[Назови товар, который считаешь лучшим выбором. Обязательно УЧИТЫВАЙ КОЛИЧЕСТВО ОТЗЫВОВ и результаты индивидуального анализа. Если у товара мало отзывов или анализ был неубедительным, он НЕ МОЖЕТ быть выбором редакции. Если явного лидера нет или по всем товарам недостаточно данных, честно укажи это. Объясни свой выбор (3-4 предложения).]\n\n"

        prompt += "### ⚠️ Возможные компромиссы и предостережения:\n"
        prompt += "[Укажи, на какие компромиссы придется пойти при выборе каждого из товаров, или какие у них есть недостатки, важные для определенных групп пользователей. Если для какого-то товара было мало отзывов, отметь это как риск или причину для осторожности.]\n\n"

        prompt += "### 🤔 Для кого какой товар (с учетом количества отзывов):\n"
        prompt += f"[Кратко, для каждого из {num_products} товаров ({', '.join([d['product_name'] for d in individual_analyses_data.values()])}), укажи, для какой основной цели или типа покупателя он лучше всего подходит. ЕСЛИ ДЛЯ ТОВАРА МАЛО ОТЗЫВОВ, ОБЯЗАТЕЛЬНО УПОМЯНИ ЭТОТ ФАКТ, например: '{individual_analyses_data[list(individual_analyses_data.keys())[0]]['product_name']} - может подойти для X, но отзывов пока мало для уверенности'. Дай оценку для всех товаров.]\n\n"
        
        prompt += "Пожалуйста, будь объективен. Без эмодзи. Не повторяй индивидуальные плюсы и минусы товаров, так как они будут показаны отдельно."
        return prompt

    @staticmethod
    def _get_ai_response(prompt):
        """Выполняет запрос ИИ для сравнения."""
        try:
            if not hasattr(ReviewAnalyzer, '_get_ai_response'):
                 raise AttributeError("Метод '_get_ai_response' не найден в ReviewAnalyzer.")
            return ReviewAnalyzer._get_ai_response(prompt)
        except Exception as e:
            error_msg = f"Ошибка при получении ответа ИИ: {e}"
            return f"Ошибка при получении ответа ИИ: {error_msg}"

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
            products_data = {}
            for pid in product_ids:
                 data = ReviewAnalyzerApp._fetch_product_data(pid, result_queue)
                 if data: # Добавлять, только если получение данных прошло успешно
                     products_data[pid] = data
                 # Если получение данных не удалось, ошибка уже отправлена через очередь

            if not products_data:
                 result_queue.put({"type": "error", "message": "Не удалось получить данные ни для одного из указанных товаров."})
                 return
            if len(products_data) < 2 and len(product_ids) >= 2:
                 result_queue.put({"type": "error", "message": f"Удалось получить данные только для {len(products_data)} из {len(product_ids)} товаров. Сравнение невозможно."})
                 return

            # 2. Выполнение индивидуальных анализов
            individual_analyses_map = {} # Используем map для сохранения порядка и доступа по ID, если нужно
            for pid, p_data in products_data.items():
                # Не отправляем update_loading_analyze из _get_single_analysis в UI,
                # так как это будет выглядеть как много быстрых обновлений.
                # Вместо этого, перед циклом можно отправить одно "Анализируем товары..."
                # или после каждого анализа обновлять "Проанализировано X из Y..."
                result_queue.put({"type": "update_loading_analyze_multi", "current": len(individual_analyses_map) + 1, "total": len(products_data), "product_name": p_data["product_name"]})
                analysis_text = ReviewAnalyzerApp._get_single_analysis(p_data, result_queue) # result_queue передается для error_partial
                individual_analyses_map[pid] = {
                    "product_id": pid, # Добавим ID для возможного использования
                    "product_name": p_data["product_name"],
                    "analysis": analysis_text, # Содержит сообщение об ошибке, если анализ не удался
                    "review_count": p_data["review_count"]
                }
            
            # Проверим, сколько анализов реально удалось получить (не содержат явных ошибок)
            successful_analyses_list = [
                data for data in individual_analyses_map.values()
                if "Не удалось выполнить анализ" not in data["analysis"] and "не найдено отзывов" not in data["analysis"]
            ]

            if len(successful_analyses_list) < 2:
                # Если после индивидуальных анализов осталось меньше двух успешных, сравнение не имеет смысла.
                # Отправим результаты индивидуальных анализов (даже если они с ошибками)
                # и сообщение, что сравнение невозможно.
                # Это более сложный сценарий для UI, пока просто выдадим ошибку сравнения.
                # TODO: Позже можно улучшить UI для показа частичных результатов.
                result_queue.put({"type": "error", "message": f"Не удалось получить достаточно успешных индивидуальных анализов для {len(product_ids)} товаров. Сравнение невозможно."})
                # Возможно, стоит передать individual_analyses_map, чтобы показать, что есть
                # result_queue.put({
                # "type": "multi_result_partial_failure",
                # "comparison_title": f"Анализ товаров (сравнение не удалось)",
                # "individual_product_analyses": list(individual_analyses_map.values()),
                # "overall_recommendation": "Сравнение не удалось из-за ошибок при анализе отдельных товаров."
                # })
                return

            # 3. Генерация промпта для ОБЩИХ РЕКОМЕНДАЦИЙ и получение ответа ИИ
            result_queue.put({"type": "update_loading_compare", "count": len(successful_analyses_list)})
            # Передаем individual_analyses_map (или successful_analyses_list) в _generate_comparison_prompt
            # чтобы он мог использовать имена товаров в промпте.
            comparison_prompt = ReviewAnalyzerApp._generate_comparison_prompt(individual_analyses_map)


            if not comparison_prompt:
                 result_queue.put({"type": "error", "message": "Недостаточно данных для создания общих рекомендаций."})
                 return

            overall_recommendation_analysis = ReviewAnalyzerApp._get_ai_response(comparison_prompt)
            
            product_names_for_title = [d["product_name"] for d in individual_analyses_map.values()] # Используем все, даже если анализ неудачный для заголовка
            comparison_title = f"Сравнение: {', '.join(product_names_for_title)}"

            result_queue.put({
                "type": "multi_result", # Новый тип результата
                "comparison_title": comparison_title,
                "individual_product_analyses": list(individual_analyses_map.values()), # Список словарей с индивидуальными анализами
                "overall_recommendation": overall_recommendation_analysis
            })

        except Exception as e:
            error_details = traceback.format_exc()
            result_queue.put({"type": "error", "message": f"Критическая ошибка при сравнении товаров:\\n{e}\\n\\nTraceback:\\n{error_details}"})


    # --- Обработка результатов (Проверка очереди из основного потока) ---

    def check_analysis_results(self):
        """Периодически проверяет очередь результатов из процесса анализа."""
        try:
            result = self.result_queue.get_nowait()

            if result["type"] == "update_loading_fetch":
                self.loading_overlay_label.configure(text=f"Получаем данные: \"{result.get('product_name', '?')}\"...")
                self.after(100, self.check_analysis_results)
            elif result["type"] == "update_loading_analyze":
                 self.loading_overlay_label.configure(text=f"Анализ ИИ: \"{result.get('product_name', '?')}\"...")
                 self.after(100, self.check_analysis_results)
            elif result["type"] == "update_loading_analyze_multi":
                 self.loading_overlay_label.configure(text=f"Анализируем товар {result.get('current','?')} из {result.get('total','?')}: \"{result.get('product_name', '?')}\"...")
                 self.after(100, self.check_analysis_results)
            elif result["type"] == "update_loading_compare":
                 self.loading_overlay_label.configure(text=f"Подготовка общих рекомендаций для {result.get('count', '?')} товаров...")
                 self.after(100, self.check_analysis_results)
            elif result["type"] == "result": # Одиночный анализ
                 self._hide_loading_overlay()
                 self.show_results(result["product_name"], result["analysis"])
            elif result["type"] == "multi_result": # Новый тип для сравнения
                 self._hide_loading_overlay()
                 self.show_comparison_results(result["comparison_title"], result["individual_product_analyses"], result["overall_recommendation"])
            elif result["type"] == "no_reviews":
                 self._hide_loading_overlay()
                 self.show_no_reviews(result["product_name"])
            elif result["type"] == "error":
                 self._hide_loading_overlay()
                 self.show_error_on_main_screen(result["message"])
            elif result["type"] == "error_partial":
                 print(f"ПРЕДУПРЕЖДЕНИЕ (не фатально): {result['message']}")
                 self.after(100, self.check_analysis_results)

        except multiprocessing.queues.Empty:
            self.after(100, self.check_analysis_results)
        except tk.TclError:
             # Экран загрузки мог быть неожиданно уничтожен
             print("Предупреждение: Окно загрузки исчезло во время проверки.")
             if not self.result_frame.winfo_ismapped(): self.go_back() # Попытаться восстановить состояние
        except Exception as e:
            # Перехватить неожиданные ошибки во время обработки результатов
            self._hide_loading_overlay() # Скрыть оверлей
            error_details = traceback.format_exc()
            self.show_error_on_main_screen(f"Критическая ошибка обработки результатов:\n{e}\n\nTraceback:\n{error_details}")

    # --- Отображение финальных результатов/ошибок ---

    def show_results(self, product_name, analysis, from_history=False): # <-- ДОБАВЛЕН from_history
        """Отображает экран с результатами анализа для ОДНОГО товара."""
        if not from_history:
            # Сохраняем в историю только если это новый анализ
            self.analysis_history.append({
                'type': 'single',
                'timestamp': datetime.datetime.now(),
                'product_name': product_name,
                'analysis': analysis
            })
            # Ограничение на размер истории (например, последние 20 записей)
            if len(self.analysis_history) > 20:
                self.analysis_history.pop(0) # Удаляем самый старый элемент
            self._save_history_to_file() # <-- СОХРАНЯЕМ ИСТОРИЮ

        if self.state() == 'zoomed': # Если было максимизировано
            self.state('normal')
        # self.attributes('-fullscreen', False) # Больше не используем
        if self.main_frame.winfo_ismapped(): self.main_frame.pack_forget()
        if self.comparison_result_container.winfo_ismapped(): self.comparison_result_container.pack_forget()
        
        self.result_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self.single_result_container.pack(fill=tk.BOTH, expand=True) # Показываем контейнер для одиночного

        self.title(f"Анализ: {product_name[:50]}{'...' if len(product_name)>50 else ''}")

        if not self.product_title_label.winfo_ismapped():
             self.product_title_label.pack(pady=(15, 10), padx=25, fill=tk.X, anchor='n')
        if not self.result_card.winfo_ismapped():
             self.result_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 15))

        self.product_title_label.configure(text=product_name)
        self._set_result_text(analysis)
        self.update_idletasks()
        self._update_title_wraplength() 
        self.after(150, self._resize_window_based_on_content) 

    def show_no_reviews(self, product_name):
        """Отображает сообщение о том, что отзывы не найдены (для одиночного товара)."""
        # Анализы без отзывов не сохраняем в историю
        if self.state() == 'zoomed': # Если было максимизировано
            self.state('normal')
        # self.attributes('-fullscreen', False) # Больше не используем
        if self.main_frame.winfo_ismapped(): self.main_frame.pack_forget()
        if self.comparison_result_container.winfo_ismapped(): self.comparison_result_container.pack_forget()

        self.result_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self.single_result_container.pack(fill=tk.BOTH, expand=True) # Показываем контейнер для одиночного

        self.title(f"Нет отзывов: {product_name[:50]}{'...' if len(product_name)>50 else ''}")

        if not self.product_title_label.winfo_ismapped():
             self.product_title_label.pack(pady=(15, 10), padx=25, fill=tk.X, anchor='n')
        if not self.result_card.winfo_ismapped():
            self.result_card.pack(fill=tk.BOTH, expand=True, padx=20, pady=(0, 15))

        self.product_title_label.configure(text=product_name)
        no_reviews_message = f"У товара '{product_name}' пока нет отзывов.\n\nАнализ невозможен."
        self._set_result_text(no_reviews_message)
        self.update_idletasks()
        self._update_title_wraplength()

    def show_comparison_results(self, overall_title, individual_analyses, overall_recommendation, from_history=False): # <-- ДОБАВЛЕН from_history
        """Отображает экран с результатами сравнения в КОЛОНКАХ."""
        if not from_history:
            # Сохраняем в историю только если это новый анализ
            self.analysis_history.append({
                'type': 'multi',
                'timestamp': datetime.datetime.now(),
                'comparison_title': overall_title,
                'individual_product_analyses': individual_analyses, # Сохраняем полный набор данных
                'overall_recommendation': overall_recommendation
            })
            # Ограничение на размер истории
            if len(self.analysis_history) > 20:
                self.analysis_history.pop(0)
            self._save_history_to_file() # <-- СОХРАНЯЕМ ИСТОРИЮ

        if self.main_frame.winfo_ismapped(): self.main_frame.pack_forget()
        if self.single_result_container.winfo_ismapped(): self.single_result_container.pack_forget()

        self.result_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self.comparison_result_container.pack(fill=tk.BOTH, expand=True, padx=10, pady=10)
        
        # self.attributes('-fullscreen', True) # Заменяем на максимизацию
        if self.state() != 'zoomed': # Максимизировать, если еще не максимизировано
            self.state('zoomed') 

        self.title(f"{overall_title[:60]}{'...' if len(overall_title)>60 else ''}")
        
        # Общий заголовок сравнения
        self.comparison_overall_title_label.pack(pady=(0, 10), padx=15, fill=tk.X, anchor='n')
        self.comparison_overall_title_label.configure(text=overall_title)

        # Очистка предыдущих колонок, если они были
        for widget in self._dynamic_column_widgets:
            widget.destroy()
        self._dynamic_column_widgets = []

        self.columns_container_frame.pack(fill=tk.BOTH, expand=True, pady=(0,10))

        num_columns = len(individual_analyses)
        if num_columns == 0: return # Не должно случиться, если логика в perform_multiple_analysis_process верна

        for i, product_data in enumerate(individual_analyses):
            column_frame = ctk.CTkFrame(self.columns_container_frame, border_width=2, border_color=ACCENT_COLOR, corner_radius=10, fg_color=CARD_COLOR)
            column_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=5, pady=5)
            self._dynamic_column_widgets.append(column_frame) # Для последующей очистки

            # Название товара в колонке
            product_name_label = ctk.CTkLabel(column_frame, text=product_data["product_name"], font=self.fonts["header"], text_color=ACCENT_COLOR, wraplength=column_frame.winfo_width()-20)
            product_name_label.pack(pady=(10, 5), padx=10, fill=tk.X)
            # Динамическое обновление wraplength для заголовка колонки
            def update_label_wraplength(event, label=product_name_label, frame=column_frame):
                new_width = frame.winfo_width() - 20
                if new_width > 0 : label.configure(wraplength=new_width)
            column_frame.bind("<Configure>", lambda e, lbl=product_name_label, frm=column_frame: update_label_wraplength(e, lbl, frm), add="+")
            
            # Отзывов найдено (если есть)
            review_count_val = product_data.get('review_count', 'N/A')
            review_count_text = f"(Отзывов взято для анализа: {review_count_val})" if review_count_val != 'N/A' else ""
            review_count_label = ctk.CTkLabel(column_frame, text=review_count_text, font=self.fonts["footer"], text_color=SECONDARY_TEXT)
            review_count_label.pack(pady=(0,5), padx=10, fill=tk.X)

            # Анализ товара в колонке
            analysis_textbox = ctk.CTkTextbox(column_frame, wrap="word", font=self.fonts["result_text"], fg_color="transparent", activate_scrollbars=True, border_spacing=8)
            analysis_textbox.pack(pady=(0,10), padx=10, fill=tk.BOTH, expand=True) # Возвращаем fill=tk.BOTH
            analysis_textbox.insert("1.0", product_data["analysis"])
            analysis_textbox.configure(state=tk.DISABLED)
        
        # Контейнер для общих рекомендаций (сначала внешний, потом карточка)
        self.recommendation_outer_container.pack(fill=tk.X, expand=False, padx=0, pady=(5,0)) # Изменено
        self.recommendation_card.pack(fill=tk.X, expand=False, padx=5, pady=5) # Изменено
        
        # Заголовок рекомендаций
        self.recommendation_title_label.pack(pady=(10,5), padx=15, fill=tk.X, anchor='w')

        # Текст общих рекомендаций
        self.recommendation_textbox.pack(pady=(0,10), padx=15, fill=tk.X, expand=False) # Изменено
        self.recommendation_textbox.configure(state=tk.NORMAL)
        self.recommendation_textbox.delete("1.0", tk.END)
        self.recommendation_textbox.insert("1.0", overall_recommendation)
        self.recommendation_textbox.configure(state=tk.DISABLED)
        
        # Убедимся, что текстовое поле рекомендаций имеет достаточную высоту для содержимого,
        # но не слишком большую. Можно попробовать задать высоту по содержимому или оставить как есть (с прокруткой).
        self.recommendation_textbox.update_idletasks() # Обновить, чтобы получить актуальную высоту
        # Пример: Установить высоту на основе количества строк, но не более X
        # num_lines = int(self.recommendation_textbox.index('end-1c').split('.')[0])
        # line_height = self.fonts["result_text"].cget("size") + 4
        # desired_height = min(max(100, num_lines * line_height + 20), 300) # min 100, max 300
        # self.recommendation_textbox.configure(height=desired_height)
        # self.recommendation_card.configure(height=desired_height + 40) # + отступы и заголовок

        self.update_idletasks()
        self._update_title_wraplength() # Обновить перенос главного заголовка
        # self.after(150, self._resize_window_based_on_content) # _resize_window_based_on_content нужно будет доработать для колонок
        # Пока что установим больший размер окна для режима сравнения, если он активен
        # if self.mode_var.get() == "multi": # Уже не нужно, так как будет фулскрин
            # current_width = self.winfo_width()
            # required_height = 700 # Примерная высота для режима сравнения
            # self.geometry(f"{max(900, current_width)}x{required_height}")

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

    def go_back_to_main_from_history(self):
        """Возвращается на основной экран с экрана истории."""
        if self.state() == 'zoomed': self.state('normal')
        self.history_frame.pack_forget()
        self.main_frame.pack(expand=True, fill="both")
        self.geometry("900x650" if self.mode_var.get() == "multi" else "900x450") # <-- ИЗМЕНЕНО # Восстанавливаем размер как при обычном возврате
        self.title(APP_NAME)
        
    def _show_loading_overlay(self, message):
        """Показывает оверлей загрузки с указанным сообщением."""
        self.main_frame.pack_forget()
        self.result_frame.pack_forget()
        self.loading_overlay_label.configure(text=message)
        self.loading_overlay_frame.pack(expand=True, fill="both", padx=20, pady=20)
        self.update_idletasks() # Обновить GUI немедленно

    def _hide_loading_overlay(self):
        """Скрывает оверлей загрузки."""
        self.loading_overlay_frame.pack_forget()

    def show_history_screen(self):
        """Отображает экран истории анализов."""
        if self.state() == 'zoomed': self.state('normal')
        self.main_frame.pack_forget()
        self.result_frame.pack_forget() # Также скрываем экран результатов, если он был открыт
        self.history_frame.pack(fill=tk.BOTH, expand=True, padx=0, pady=0)
        self.title(f"{APP_NAME} - История анализов")
        self._populate_history_list() # Заполняем список при показе

    def _populate_history_list(self):
        """Заполняет/обновляет список элементов в scrollable frame истории."""
        # Очищаем предыдущие элементы
        for widget in self.history_scroll_frame.winfo_children():
            widget.destroy()

        if not self.analysis_history:
            self.no_history_label = ctk.CTkLabel(self.history_scroll_frame,
                                                 text="История анализов пока пуста.",
                                                 font=self.fonts["text"],
                                                 text_color=SECONDARY_TEXT)
            self.no_history_label.pack(pady=20, padx=10, anchor="center")
            if hasattr(self, 'clear_history_button'): # Проверка на случай раннего вызова
                self.clear_history_button.configure(state=tk.DISABLED, fg_color="#808080") # Серый фон для неактивной кнопки
            return
        elif hasattr(self, 'clear_history_button'): # Если история не пуста, кнопка активна
             self.clear_history_button.configure(state=tk.NORMAL, fg_color="#e74c3c") # Возвращаем красный фон

        # Показываем элементы в обратном порядке (новые сверху)
        for i, entry in enumerate(reversed(self.analysis_history)):
            item_frame = ctk.CTkFrame(self.history_scroll_frame, fg_color="#39393d", corner_radius=8) # Цвет чуть светлее карточки
            item_frame.pack(fill=tk.X, pady=(5, 0) if i > 0 else (0,0), padx=5)

            left_info_frame = ctk.CTkFrame(item_frame, fg_color="transparent")
            left_info_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(10,5), pady=5)

            entry_type_text = "Одиночный анализ" if entry['type'] == 'single' else "Сравнение товаров"
            title_text = entry.get('product_name', entry.get('comparison_title', 'Без названия'))
            
            type_label = ctk.CTkLabel(left_info_frame, text=entry_type_text, font=self.fonts["header"], anchor="w", text_color=ACCENT_COLOR)
            type_label.pack(fill=tk.X)

            title_label_text = f"{title_text[:60]}{'...' if len(title_text)>60 else ''}"
            title_label = ctk.CTkLabel(left_info_frame, text=title_label_text, font=self.fonts["text"], anchor="w", wraplength=450) # Ограничиваем длину
            title_label.pack(fill=tk.X)
            
            timestamp_text = entry['timestamp'].strftime('%d.%m.%Y %H:%M:%S')
            timestamp_label = ctk.CTkLabel(left_info_frame, text=timestamp_text, font=self.fonts["footer"], anchor="w", text_color=SECONDARY_TEXT)
            timestamp_label.pack(fill=tk.X)

            buttons_frame = ctk.CTkFrame(item_frame, fg_color="transparent") # Фрейм для кнопок
            buttons_frame.pack(side=tk.RIGHT, padx=10, pady=10)

            view_button = ctk.CTkButton(
                buttons_frame, text="Посмотреть", font=self.fonts["back_button"], # Используем шрифт поменьше
                width=100, height=30, corner_radius=6, # Ширина чуть меньше
                fg_color=ACCENT_COLOR, hover_color="#0069d9",
                # Используем лямбду для передачи конкретного элемента истории
                command=lambda e=entry: self._restore_analysis_from_history(e) 
            )
            view_button.pack(side=tk.LEFT, padx=(0, 5)) # Кнопка просмотра слева

            delete_button = ctk.CTkButton(
                buttons_frame, text="Удалить", font=self.fonts["back_button"],
                width=80, height=30, corner_radius=6, # Ширина поменьше
                fg_color="#e74c3c", hover_color="#c0392b", # Красный цвет для удаления
                command=lambda e=entry: self._delete_history_entry(e)
            )
            delete_button.pack(side=tk.LEFT) # Кнопка удаления справа от просмотра
            
    def _restore_analysis_from_history(self, history_entry):
        """Восстанавливает и отображает анализ из истории."""
        self.history_frame.pack_forget() # Скрываем экран истории
        self.viewing_from_history = True # Устанавливаем флаг перед показом результатов из истории

        if history_entry['type'] == 'single':
            self.show_results(
                product_name=history_entry['product_name'],
                analysis=history_entry['analysis'],
                from_history=True
            )
        elif history_entry['type'] == 'multi':
            self.show_comparison_results(
                overall_title=history_entry['comparison_title'],
                individual_analyses=history_entry['individual_product_analyses'],
                overall_recommendation=history_entry['overall_recommendation'],
                from_history=True
            )

    def _delete_history_entry(self, entry_to_delete):
        """Удаляет конкретную запись из истории анализов после подтверждения."""
        title_text = entry_to_delete.get('product_name', entry_to_delete.get('comparison_title', 'Без названия'))
        confirm_message = f"Вы действительно хотите удалить запись анализа для:\n'{title_text[:60]}{'...' if len(title_text)>60 else ''}'?"
        
        confirm = messagebox.askyesno(
            title="Подтверждение удаления",
            message=confirm_message,
            icon=messagebox.WARNING,
            parent=self # Убедимся, что диалог поверх основного окна
        )
        
        if confirm:
            try:
                # Нам нужно найти и удалить элемент. Поскольку мы храним объекты,
                # а не просто словари (datetime объекты), простое self.analysis_history.remove(entry_to_delete)
                # может не сработать надежно, если объект был как-то изменен или пересоздан.
                # Лучше найти по уникальному признаку, например, timestamp, если он уникален,
                # или просто по идентичности объекта, если он передается напрямую.
                # В данном случае entry_to_delete - это ссылка на элемент списка.
                self.analysis_history.remove(entry_to_delete)
                self._save_history_to_file()
                self._populate_history_list() # Обновить отображение
            except ValueError:
                # Это может произойти, если элемент по какой-то причине уже удален или не найден
                messagebox.showerror("Ошибка", "Не удалось найти элемент для удаления в истории.", parent=self)
                self._populate_history_list() # Все равно обновить, на всякий случай

    def _get_history_file_path(self) -> str:
        """Возвращает полный путь к файлу истории."""
        home_path = os.path.expanduser("~") # Корректный способ получить домашнюю директорию
        
        # Стандартный путь к папке "Документы" на Windows
        documents_folder_name = "Documents"
        # На некоторых локализациях Windows папка может называться "Мои документы" 
        # или иметь другое локализованное имя. Для простоты пока используем "Documents".
        # Для более надежного кроссплатформенного решения можно использовать библиотеки типа `platformdirs`.
        
        documents_path = os.path.join(home_path, documents_folder_name)
        
        base_dir_for_app_data = documents_path
        if not os.path.isdir(documents_path):
            # Если папка "Документы" не найдена, используем домашнюю директорию как резервный вариант
            print(f"Предупреждение: Папка '{documents_folder_name}' не найдена в '{home_path}'. История будет сохранена в домашней директории.")
            base_dir_for_app_data = home_path 
        
        app_history_dir = os.path.join(base_dir_for_app_data, "WB-Analyzer")
        return os.path.join(app_history_dir, "analysis_history.json")

    def _ensure_history_dir_exists(self):
        """Убеждается, что директория для файла истории существует."""
        history_dir = os.path.dirname(self.history_file_path)
        if not os.path.exists(history_dir):
            try:
                os.makedirs(history_dir)
            except OSError as e:
                print(f"Ошибка создания директории для истории: {e}")
                # Можно показать messagebox, если критично, но пока просто выводим в консоль

    def _load_history_from_file(self):
        """Загружает историю анализов из файла."""
        if not os.path.exists(self.history_file_path):
            self.analysis_history = []
            return
        try:
            with open(self.history_file_path, 'r', encoding='utf-8') as f:
                loaded_data = json.load(f)
                # Преобразуем строки времени обратно в datetime объекты
                self.analysis_history = []
                for item in loaded_data:
                    try:
                        item['timestamp'] = datetime.datetime.fromisoformat(item['timestamp'])
                        self.analysis_history.append(item)
                    except (TypeError, ValueError) as e_item:
                        print(f"Ошибка разбора элемента истории (время): {e_item} - {item}")
        except (json.JSONDecodeError, IOError, TypeError) as e:
            print(f"Ошибка загрузки файла истории: {e}. Начинаем с пустой истории.")
            self.analysis_history = [] # Начинаем с пустой истории в случае ошибки

    def _save_history_to_file(self):
        """Сохраняет текущую историю анализов в файл."""
        try:
            # Создаем копию для преобразования datetime в строки
            history_to_save = []
            for item in self.analysis_history:
                saved_item = item.copy()
                if isinstance(saved_item.get('timestamp'), datetime.datetime):
                    saved_item['timestamp'] = saved_item['timestamp'].isoformat()
                history_to_save.append(saved_item)
            
            with open(self.history_file_path, 'w', encoding='utf-8') as f:
                json.dump(history_to_save, f, ensure_ascii=False, indent=4)
        except IOError as e:
            print(f"Ошибка сохранения файла истории: {e}")
            # Можно показать messagebox пользователю
            

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
