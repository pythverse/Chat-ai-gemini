# -*- coding: utf-8 -*-

import customtkinter as ctk
import google.generativeai as genai
import google.ai.generativelanguage as glm
import threading
import os
from dotenv import load_dotenv
import tkinter as tk
from tkinter import messagebox, simpledialog, font, filedialog, Menu
import configparser
import pyperclip
import json
import datetime
import mimetypes
import re
from PIL import Image

# --- Configuration ---
CONFIG_FILE = "config.ini"; HISTORY_FILE = "chat_history.json"
SUPPORTED_FILE_TYPES = [
    ("All files", "*.*"),
    ("Text files", "*.txt *.py *.js *.html *.css *.json *.md *.log *.csv *.xml"),
    ("Documents", "*.pdf *.docx *.rtf"),
    ("Image files", "*.png *.jpg *.jpeg *.webp *.gif"),
    ("Audio files", "*.mp3 *.wav *.ogg"), ("Video files", "*.mp4 *.mov *.avi")]
USER_BG_COLOR = ("#DCF8C6", "#2a3942"); GEMINI_BG_COLOR = ("#FFFFFF", "#3b4a54")
CODE_BG_COLOR = ("#f0f0f0", "#202020"); THINKING_BG_COLOR = ("#e0e0e0", "#404040")
TIMESTAMP_COLOR = ("gray50", "gray65"); ATTACHMENT_BG = ("gray88", "gray18")
COPY_ICON_PATH = "copy_icon.png"; OPTIONS_ICON_PATH = "options_icon.png"

# --- Helper Functions ---
def load_api_key_from_config():
    config = configparser.ConfigParser();
    if os.path.exists(CONFIG_FILE): config.read(CONFIG_FILE); return config.get("API", "key", fallback=None)
    return None
def save_api_key_to_config(api_key):
    config = configparser.ConfigParser(); config["API"] = {"key": api_key}
    try:
        with open(CONFIG_FILE, "w") as configfile: config.write(configfile)
    except IOError as e: print(f"Lỗi lưu config: {e}"); messagebox.showerror("Lỗi", f"Không thể lưu API Key.\nLỗi: {e}")
def load_chat_history():
    if os.path.exists(HISTORY_FILE):
        try:
            with open(HISTORY_FILE, "r", encoding="utf-8") as f: data = json.load(f)
            if "chat_sessions" not in data: data["chat_sessions"] = []
            for session in data["chat_sessions"]: session.setdefault("pinned", False)
            return data
        except Exception as e: print(f"Lỗi tải history: {e}"); return {"chat_sessions": []}
    return {"chat_sessions": []}
def save_chat_history(history_data):
    try:
        with open(HISTORY_FILE, "w", encoding="utf-8") as f: json.dump(history_data, f, indent=4, ensure_ascii=False)
    except IOError as e: print(f"Lỗi lưu history: {e}"); messagebox.showerror("Lỗi", f"Không thể lưu lịch sử.\nLỗi: {e}")
def generate_chat_id(): return datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")
def format_history_for_saving(gemini_history, user_ts=None, gemini_ts=None):
    formatted = []
    for i, item in enumerate(gemini_history):
        parts_content = []
        if hasattr(item, 'parts') and item.parts:
             if isinstance(item.parts, (list, tuple)): parts_content = [part.text if hasattr(part, 'text') else str(part) for part in item.parts]
             elif hasattr(item.parts, 'text'): parts_content = [item.parts.text]
             else: parts_content = [str(item.parts)]
        msg_data = {"role": item.role, "parts": parts_content}
        timestamp = None
        if i == len(gemini_history) - 1: timestamp = user_ts if item.role == 'user' else gemini_ts
        elif i == len(gemini_history) - 2: timestamp = gemini_ts if item.role == 'model' else user_ts
        elif hasattr(item,'_timestamp'): timestamp = item._timestamp
        if timestamp: msg_data["timestamp"] = timestamp
        formatted.append(msg_data)
    return formatted
def format_history_for_loading(saved_history):
    loaded = []
    for item in saved_history:
        parts_list = item.get("parts", []);
        if not isinstance(parts_list, list): parts_list = [str(parts_list)]
        try:
             processed_parts = [part.replace('\\n', '\n') for part in parts_list]
             content = glm.Content(role=item.get("role"), parts=[glm.Part(text=part_text) for part_text in processed_parts])
             if "timestamp" in item: setattr(content, '_timestamp', item["timestamp"])
             loaded.append(content)
        except Exception as e: print(f"Lỗi tạo Content khi load: {e} với item: {item}")
    return loaded

# --- Load API Key, Gemini Setup, History Data ---
load_dotenv(); API_KEY = os.getenv("GEMINI_API_KEY");
if not API_KEY: API_KEY = load_api_key_from_config()
gemini_model = None; chat_session = None; last_gemini_response = ""; current_chat_id = None
chat_history_data = load_chat_history()

# --- Configure Gemini ---
def configure_gemini(api_key):
    global gemini_model, API_KEY, chat_session, current_chat_id
    gemini_model = None; chat_session = None; current_chat_id = None
    if not api_key: messagebox.showerror("Lỗi", "API Key chưa cung cấp."); return False
    try:
        genai.configure(api_key=api_key); gemini_model = genai.GenerativeModel('gemini-1.5-flash')
        API_KEY = api_key; print("Gemini API cấu hình OK!"); return True
    except Exception as e: messagebox.showerror("Lỗi", f"Lỗi cấu hình Gemini:\n{e}"); API_KEY = None; return False

# --- GUI Application ---
class GeminiChatApp(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Gemini Chat")
        self.geometry("1100x750")
        self.attached_file_paths = [] # <<< THAY ĐỔI: List để chứa nhiều file path
        self.attached_file_widgets = {} # <<< THÊM: Dict để lưu widget hiển thị file {path: frame}
        self.thinking_bubble_ref = None

        self._initialize_fonts()
        self._load_icons()

        # --- Tạo Tabview ---
        self.tab_view = ctk.CTkTabview(self, anchor="nw")
        self.tab_view.pack(expand=True, fill="both", padx=5, pady=5)
        self.tab_view.add("Chat"); self.tab_view.add("Cài đặt"); self.tab_view.set("Chat")

        self._create_chat_tab()
        self._create_settings_tab()

        # --- Initialization ---
        if API_KEY:
            if not configure_gemini(API_KEY): self.after(100, self.show_initial_api_key_prompt)
        else: self.after(100, self.show_initial_api_key_prompt)
        self._update_history_list(); self.protocol("WM_DELETE_WINDOW", self._on_closing)

    def _initialize_fonts(self):
        # ... (Giữ nguyên) ...
        default_font_family = "Segoe UI" if os.name == 'nt' else "Helvetica"; code_font_family = "Consolas" if os.name == 'nt' else "monospace"
        desired_font_family = "Arial"; font_size = 13; status_font_size = font_size - 2; timestamp_font_size = font_size - 3
        try: _ = font.Font(family=desired_font_family, size=font_size); base_family = desired_font_family
        except tk.TclError:
            try: _ = font.Font(family=default_font_family, size=font_size); base_family = default_font_family
            except tk.TclError: base_family = font.nametofont("TkDefaultFont").actual()["family"]
        self.base_font_tuple = (base_family, font_size); print(f"Font base: {base_family}")
        self.bold_font_tuple = (base_family, font_size, "bold")
        try: _ = font.Font(family=code_font_family, size=font_size -1); code_family = code_font_family
        except tk.TclError: code_family = "Courier"
        self.code_font_tuple = (code_family, font_size - 1); print(f"Font code: {code_family}")
        self.status_font_tuple = (base_family, status_font_size)
        self.timestamp_font_tuple = (base_family, timestamp_font_size)

    def _load_icons(self):
        # ... (Giữ nguyên) ...
        self.copy_icon_image = None; self.options_icon_image = None
        try:
            if os.path.exists(COPY_ICON_PATH): self.copy_icon_image = ctk.CTkImage(Image.open(COPY_ICON_PATH), size=(16, 16)); print("Icon copy OK.")
            else: print(f"Warning: '{COPY_ICON_PATH}' not found.")
            if os.path.exists(OPTIONS_ICON_PATH): self.options_icon_image = ctk.CTkImage(Image.open(OPTIONS_ICON_PATH), size=(16, 16)); print("Icon options OK.")
            else: print(f"Warning: '{OPTIONS_ICON_PATH}' not found.")
        except Exception as e: print(f"Lỗi tải icon: {e}")


    def _create_chat_tab(self):
        chat_tab_frame = self.tab_view.tab("Chat")
        chat_tab_frame.grid_columnconfigure(0, weight=0, minsize=220); chat_tab_frame.grid_columnconfigure(1, weight=1)
        chat_tab_frame.grid_rowconfigure(0, weight=1); chat_tab_frame.grid_rowconfigure(1, weight=0) # Row 0 là main area, Row 1 là input

        # Sidebar
        self.sidebar_frame = ctk.CTkFrame(chat_tab_frame, width=220, corner_radius=0); self.sidebar_frame.grid(row=0, column=0, rowspan=2, sticky="nsw"); self.sidebar_frame.grid_rowconfigure(1, weight=1)
        self.new_chat_button = ctk.CTkButton(self.sidebar_frame, text="💬   New Chat", command=self.start_new_chat, anchor="w"); self.new_chat_button.grid(row=0, column=0, padx=10, pady=10, sticky="ew")
        self.history_list_frame = ctk.CTkScrollableFrame(self.sidebar_frame, label_text="Lịch sử Chat"); self.history_list_frame.grid(row=1, column=0, padx=10, pady=(0, 10), sticky="nsew"); self.history_list_frame.grid_columnconfigure(0, weight=1); self.history_items = {}

        # Main Chat Area (chứa Header, Attachments, Scroll)
        self.main_chat_area_frame = ctk.CTkFrame(chat_tab_frame, fg_color="transparent"); self.main_chat_area_frame.grid(row=0, column=1, sticky="nsew")
        # <<< THAY ĐỔI LAYOUT GRID >>>
        self.main_chat_area_frame.grid_rowconfigure(0, weight=0) # Header
        self.main_chat_area_frame.grid_rowconfigure(1, weight=0) # Attachment display
        self.main_chat_area_frame.grid_rowconfigure(2, weight=1) # Chat scroll frame giãn ra
        self.main_chat_area_frame.grid_columnconfigure(0, weight=1)

        # Chat Header
        self.chat_header_frame = ctk.CTkFrame(self.main_chat_area_frame, fg_color=("gray85", "gray20"), corner_radius=0, height=40); self.chat_header_frame.grid(row=0, column=0, sticky="ew")
        self.chat_header_frame.grid_columnconfigure(0, weight=1)
        self.chat_title_label = ctk.CTkLabel(self.chat_header_frame, text="New Chat", font=self.bold_font_tuple, anchor="w"); self.chat_title_label.grid(row=0, column=0, padx=15, pady=5, sticky="w")
        self.token_label = ctk.CTkLabel(self.chat_header_frame, text="Tokens: -", font=self.status_font_tuple, anchor="e"); self.token_label.grid(row=0, column=1, padx=15, pady=5, sticky="e")

        # <<< THÊM: Khu vực hiển thị file đính kèm >>>
        self.attached_files_display_frame = ctk.CTkScrollableFrame(
            self.main_chat_area_frame,
            height=60, # Chiều cao cố định hoặc tự động? Tạm cố định
            fg_color=ATTACHMENT_BG,
            label_text="File đính kèm:",
            label_font=self.timestamp_font_tuple,
            orientation="horizontal" # Cuộn ngang
        )
        # Grid nó vào vị trí mới, ban đầu ẩn hoặc không có nội dung
        self.attached_files_display_frame.grid(row=1, column=0, sticky="ew", padx=0, pady=(5, 0))
        self.attached_files_display_frame.grid_remove() # Ẩn đi ban đầu

        # Chat Scroll Frame (giờ ở row 2)
        self.chat_scroll_frame = ctk.CTkScrollableFrame(self.main_chat_area_frame, fg_color=("gray90", "gray10")); self.chat_scroll_frame.grid(row=2, column=0, sticky="nsew")
        self.chat_scroll_frame.grid_columnconfigure(0, weight=1)

        # Input Area (vẫn ở row 1 của chat_tab_frame)
        self.input_controls_frame = ctk.CTkFrame(chat_tab_frame, fg_color="transparent"); self.input_controls_frame.grid(row=1, column=1, padx=10, pady=(5, 10), sticky="ew"); self.input_controls_frame.grid_columnconfigure(0, weight=1); self.input_controls_frame.grid_columnconfigure(1, weight=0)
        self.prompt_input = ctk.CTkTextbox(self.input_controls_frame, height=80, font=self.base_font_tuple, wrap=tk.WORD, border_width=1, fg_color=("white", "gray25")); self.prompt_input.grid(row=0, column=0, padx=(0, 10), pady=(0, 5), sticky="nsew")
        self.prompt_input.bind("<Shift-Return>", self.insert_newline_event)
        self.button_action_frame = ctk.CTkFrame(self.input_controls_frame, fg_color="transparent"); self.button_action_frame.grid(row=0, column=1, rowspan=2, padx=0, pady=0, sticky="se")
        self.send_button = ctk.CTkButton(self.button_action_frame, text="Gửi", width=80, command=self.send_message_event); self.send_button.pack(side=tk.TOP, padx=0, pady=(0, 5))
        self.attach_button = ctk.CTkButton(self.button_action_frame, text="📎 Đính kèm", width=80, command=self.attach_file); self.attach_button.pack(side=tk.BOTTOM, padx=0, pady=0)

    # --- Các hàm khác: _create_settings_tab, _change..., _save_all_settings, show_initial... (Giữ nguyên) ---
    # ... (Copy từ phiên bản trước) ...
    def _create_settings_tab(self):
        # ... (Giữ nguyên code tạo tab settings) ...
        settings_tab_frame = self.tab_view.tab("Cài đặt"); settings_tab_frame.grid_columnconfigure(0, weight=1)
        main_settings_frame = ctk.CTkScrollableFrame(settings_tab_frame); main_settings_frame.pack(expand=True, fill="both", padx=20, pady=20); main_settings_frame.grid_columnconfigure(1, weight=1)
        row_idx = 0
        api_frame = ctk.CTkFrame(main_settings_frame, fg_color="transparent"); api_frame.grid(row=row_idx, column=0, columnspan=2, pady=(0, 20), sticky="ew"); row_idx += 1; api_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(api_frame, text="API Key:", font=self.bold_font_tuple).grid(row=0, column=0, padx=(0,10), sticky="w")
        self.settings_api_key_entry = ctk.CTkEntry(api_frame, show="*", width=300); self.settings_api_key_entry.grid(row=0, column=1, sticky="ew");
        if API_KEY: self.settings_api_key_entry.insert(0, API_KEY)
        appearance_frame = ctk.CTkFrame(main_settings_frame, fg_color="transparent"); appearance_frame.grid(row=row_idx, column=0, columnspan=2, pady=10, sticky="ew"); row_idx += 1; appearance_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(appearance_frame, text="Giao diện:", font=self.bold_font_tuple).grid(row=0, column=0, padx=(0,10), pady=5, sticky="w")
        self.appearance_mode_menu = ctk.CTkOptionMenu(appearance_frame, values=["Light", "Dark", "System"], command=self._change_appearance_mode); self.appearance_mode_menu.grid(row=0, column=1, padx=0, pady=5, sticky="w"); self.appearance_mode_menu.set(ctk.get_appearance_mode())
        ctk.CTkLabel(appearance_frame, text="Theme màu:", font=self.bold_font_tuple).grid(row=1, column=0, padx=(0,10), pady=5, sticky="w")
        self.color_theme_menu = ctk.CTkOptionMenu(appearance_frame, values=["blue", "dark-blue", "green"], command=self._change_color_theme); self.color_theme_menu.grid(row=1, column=1, padx=0, pady=5, sticky="w");
        try: self.color_theme_menu.set(ctk.ThemeManager.theme["color"]["fg_button"])
        except: self.color_theme_menu.set("blue")
        font_frame = ctk.CTkFrame(main_settings_frame, fg_color="transparent"); font_frame.grid(row=row_idx, column=0, columnspan=2, pady=10, sticky="ew"); row_idx += 1; font_frame.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(font_frame, text="Cỡ chữ cơ bản:", font=self.bold_font_tuple).grid(row=0, column=0, padx=(0,10), sticky="w")
        self.font_size_slider = ctk.CTkSlider(font_frame, from_=10, to=18, number_of_steps=8); self.font_size_slider.grid(row=0, column=1, sticky="ew"); self.font_size_slider.set(self.base_font_tuple[1])
        self.font_size_label = ctk.CTkLabel(font_frame, text=f"{self.base_font_tuple[1]}pt"); self.font_size_label.grid(row=0, column=2, padx=(5,0)); self.font_size_slider.configure(command=lambda value: self.font_size_label.configure(text=f"{int(value)}pt"))
        save_settings_button = ctk.CTkButton(main_settings_frame, text="Lưu Cài Đặt", command=self._save_all_settings); save_settings_button.grid(row=row_idx, column=0, columnspan=2, pady=30)
    def _change_appearance_mode(self, new_mode: str): ctk.set_appearance_mode(new_mode); print(f"Appearance mode: {new_mode}")
    def _change_color_theme(self, new_theme: str):
        try:
             script_dir = os.path.dirname(os.path.abspath(__file__)); theme_path = os.path.join(script_dir, "assets", f"{new_theme}.json")
             if os.path.exists(theme_path): ctk.set_default_color_theme(theme_path); print(f"Color theme: {new_theme}")
             elif new_theme in ["blue", "dark-blue", "green"]: ctk.set_default_color_theme(new_theme); print(f"Basic theme: {new_theme}")
             else: ctk.set_default_color_theme("blue"); print("Fallback theme: blue")
        except Exception as e: print(f"Lỗi đổi theme: {e}")
    def _save_all_settings(self):
        print("Lưu cài đặt..."); new_api_key = self.settings_api_key_entry.get().strip(); key_changed = False
        if new_api_key and new_api_key != API_KEY:
            if configure_gemini(new_api_key): save_api_key_to_config(new_api_key); key_changed = True; print("Lưu API Key mới OK.")
            else: messagebox.showerror("Lỗi", "API Key mới không hợp lệ.", parent=self.tab_view.tab("Cài đặt")); return
        elif not new_api_key: messagebox.showwarning("Thiếu", "API Key không được trống.", parent=self.tab_view.tab("Cài đặt")); return
        config = configparser.ConfigParser(); config.read(CONFIG_FILE)
        if "Appearance" not in config: config["Appearance"] = {}; config["Appearance"]["mode"] = self.appearance_mode_menu.get(); config["Appearance"]["theme"] = self.color_theme_menu.get()
        if "Font" not in config: config["Font"] = {}; config["Font"]["base_size"] = str(int(self.font_size_slider.get()))
        try:
            with open(CONFIG_FILE, "w") as configfile: config.write(configfile)
            msg = "Đã lưu cài đặt." + (" Khởi động lại để áp dụng." if key_changed else "")
            messagebox.showinfo("Thành công", msg, parent=self.tab_view.tab("Cài đặt"))
        except IOError as e: messagebox.showerror("Lỗi", f"Lỗi lưu config:\n{e}", parent=self.tab_view.tab("Cài đặt"))
    def show_initial_api_key_prompt(self): messagebox.showinfo("Yêu cầu", "Nhập API Key trong tab 'Cài đặt'."); self.tab_view.set("Cài đặt")
    def _get_value_for_mode(self, light_value, dark_value):
        if ctk.get_appearance_mode() == "Dark": return dark_value
        else: return light_value

    # --- Các hàm quản lý lịch sử (Giữ nguyên) ---
    def _update_history_list(self):
        for widget in self.history_list_frame.winfo_children(): widget.destroy()
        self.history_items.clear()
        try: sorted_sessions = sorted(chat_history_data.get("chat_sessions", []), key=lambda x: (not x.get("pinned", False), x.get("id", "")), reverse=True)
        except Exception as e: print(f"Lỗi sort history: {e}"); sorted_sessions = chat_history_data.get("chat_sessions", [])
        for session in sorted_sessions:
            chat_id = session.get("id"); title = session.get("title", f"Chat {chat_id}"); is_pinned = session.get("pinned", False)
            display_title = f"{'📌 ' if is_pinned else ''}{title}"
            display_title_short = (display_title[:22] + '...') if len(display_title) > 22 else display_title
            item_frame = ctk.CTkFrame(self.history_list_frame, fg_color="transparent"); item_frame.pack(fill="x", padx=0, pady=1); item_frame.grid_columnconfigure(0, weight=1)
            title_label = ctk.CTkLabel(item_frame, text=display_title_short, anchor="w", cursor="hand2"); title_label.grid(row=0, column=0, padx=(5,0), pady=2, sticky="ew")
            title_label.bind("<Button-1>", lambda event, c_id=chat_id: self.load_chat(c_id))
            options_button = ctk.CTkButton(item_frame, text="..." if not self.options_icon_image else "", image=self.options_icon_image, width=25, height=25, fg_color="transparent", hover_color=("gray80", "gray35"), command=lambda c_id=chat_id, btn=item_frame: self._show_history_menu(c_id, btn)); options_button.grid(row=0, column=1, padx=(0, 5), pady=0, sticky="e")
            self.history_items[chat_id] = item_frame
            if chat_id == current_chat_id: item_frame.configure(fg_color=("gray80", "gray30"))
    def _show_history_menu(self, chat_id, anchor_widget):
        session = next((s for s in chat_history_data.get("chat_sessions", []) if s.get("id") == chat_id), None);
        if not session: return
        is_pinned = session.get("pinned", False); pin_label = "Bỏ ghim" if is_pinned else "Ghim"
        menu = Menu(self, tearoff=0, background=self._get_value_for_mode("gray85", "gray20"), fg=self._get_value_for_mode("black", "white"), activebackground=self._get_value_for_mode("gray75", "gray35"))
        menu.add_command(label="Sửa tên", command=lambda: self._rename_chat(chat_id)); menu.add_command(label=pin_label, command=lambda: self._toggle_pin_chat(chat_id)); menu.add_separator(); menu.add_command(label="Xóa", command=lambda: self._delete_chat(chat_id))
        x = anchor_widget.winfo_rootx() + anchor_widget.winfo_width() - 5; y = anchor_widget.winfo_rooty() + anchor_widget.winfo_height() // 2; menu.tk_popup(x, y)
    def _rename_chat(self, chat_id):
        session = next((s for s in chat_history_data["chat_sessions"] if s.get("id") == chat_id), None);
        if not session: return
        dialog = ctk.CTkInputDialog(text="Nhập tên mới:", title="Đổi tên Chat", entry_fg_color = ("white", "black"), entry_text_color = ("black", "white")); new_title = dialog.get_input()
        if new_title is not None:
            new_title = new_title.strip();
            if new_title:
                session["title"] = new_title
                save_chat_history(chat_history_data)
                self._update_history_list()
                if current_chat_id == chat_id:
                    self.chat_title_label.configure(text=new_title) # Sửa thụt lề ở đây
            else: messagebox.showwarning("Tên trống", "Tên không được trống.", parent=self)
    def _toggle_pin_chat(self, chat_id):
        session = next((s for s in chat_history_data["chat_sessions"] if s.get("id") == chat_id), None);
        if not session: return
        session["pinned"] = not session.get("pinned", False); save_chat_history(chat_history_data); self._update_history_list()
    def _delete_chat(self, chat_id):
        confirm = messagebox.askyesno("Xác nhận", f"Xóa cuộc trò chuyện này?", parent=self)
        if confirm:
            original_length = len(chat_history_data["chat_sessions"])
            chat_history_data["chat_sessions"] = [s for s in chat_history_data["chat_sessions"] if s.get("id") != chat_id]
            if len(chat_history_data["chat_sessions"]) < original_length:
                save_chat_history(chat_history_data);
                if current_chat_id == chat_id: self.start_new_chat(confirm_save=False)
                self._update_history_list()
            else: messagebox.showerror("Lỗi", "Không tìm thấy chat.", parent=self)

    # --- Các hàm logic chính ---
    def start_new_chat(self, confirm_save=True):
        global chat_session, current_chat_id, last_gemini_response; print("Bắt đầu chat mới...");
        if confirm_save: self.save_current_chat()
        if not gemini_model: messagebox.showerror("Lỗi", "Gemini chưa cấu hình.", parent=self); return
        for widget in self.chat_scroll_frame.winfo_children(): widget.destroy()
        self._clear_all_attachments() # Xóa cả file đính kèm
        self.prompt_input.delete("1.0", tk.END); self.prompt_input.configure(state="normal")
        self.send_button.configure(state="normal", text="Gửi"); self.token_label.configure(text="Tokens: -")
        self.chat_title_label.configure(text="New Chat")
        last_gemini_response = ""; current_chat_id = None;
        try: chat_session = gemini_model.start_chat(history=[]); print("Session mới OK.")
        except Exception as e: messagebox.showerror("Lỗi", f"Lỗi tạo session:\n{e}", parent=self); chat_session = None; return
        self._update_history_list(); self.prompt_input.focus()
    def load_chat(self, chat_id):
        global chat_session, current_chat_id, last_gemini_response; print(f"Đang tải chat ID: {chat_id}")
        if current_chat_id != chat_id: self.save_current_chat()
        session_to_load = next((s for s in chat_history_data.get("chat_sessions", []) if s.get("id") == chat_id), None)
        if not session_to_load: messagebox.showerror("Lỗi", f"Không tìm thấy chat ID: {chat_id}", parent=self); return
        if not gemini_model: messagebox.showerror("Lỗi", "Gemini chưa cấu hình.", parent=self); return
        for widget in self.chat_scroll_frame.winfo_children(): widget.destroy()
        self._clear_all_attachments(); last_gemini_response = ""; self.token_label.configure(text="Tokens: -")
        self.chat_title_label.configure(text=session_to_load.get("title", "Chat"))
        saved_history_list = session_to_load.get("history", [])
        try:
            formatted_history = format_history_for_loading(saved_history_list)
            chat_session = gemini_model.start_chat(history=formatted_history)
            current_chat_id = chat_id
            for item in formatted_history:
                 role = item.role; full_message = "\n".join([part.text for part in item.parts if hasattr(part, 'text')])
                 is_user = (role == "user")
                 timestamp = getattr(item, '_timestamp', None)
                 self.add_message_bubble(full_message, is_user, timestamp=timestamp)
            print(f"Tải chat OK: {chat_id}")
            self.after(100, self._scroll_to_bottom)
        except Exception as e: messagebox.showerror("Lỗi", f"Lỗi tải history:\n{e}", parent=self); self.start_new_chat(confirm_save=False); return
        self._update_history_list(); self.prompt_input.configure(state="normal"); self.send_button.configure(state="normal", text="Gửi"); self.prompt_input.focus()
    def save_current_chat(self, user_ts=None, gemini_ts=None):
        global chat_history_data, current_chat_id
        if not chat_session or not hasattr(chat_session, 'history') or not chat_session.history: return
        current_history_gemini = chat_session.history
        current_history_json = format_history_for_saving(current_history_gemini, user_ts, gemini_ts)
        if not current_history_json: return
        updated = False
        if current_chat_id:
            for session in chat_history_data["chat_sessions"]:
                if session.get("id") == current_chat_id:
                    session["history"] = current_history_json
                    if not session.get("title") or session.get("title", "").startswith("Chat"): session["title"] = self._generate_chat_title(current_history_json)
                    updated = True; print(f"Đã cập nhật chat ID: {current_chat_id}"); break
            if not updated: current_chat_id = None
        if not current_chat_id:
            new_id = generate_chat_id(); new_title = self._generate_chat_title(current_history_json)
            chat_history_data["chat_sessions"].append({"id": new_id, "title": new_title, "history": current_history_json, "pinned": False})
            current_chat_id = new_id; print(f"Đã lưu chat mới ID: {new_id}")
        save_chat_history(chat_history_data); self._update_history_list()
    def _generate_chat_title(self, history_list):
        first_user_message = "Chat không tiêu đề"
        for msg in history_list:
            if msg.get("role") == "user" and msg.get("parts") and isinstance(msg["parts"], list) and msg["parts"]:
                 first_user_message = str(msg["parts"][0]).strip(); break
        title = first_user_message.split('\n')[0]
        return (title[:30] + '...') if len(title) > 30 else title

    # --- Hàm xử lý file đính kèm (ĐÃ THAY ĐỔI) ---
    def attach_file(self):
        """Mở dialog để chọn nhiều file và hiển thị chúng."""
        filepaths = filedialog.askopenfilenames(title="Chọn file đính kèm", filetypes=SUPPORTED_FILE_TYPES)
        if filepaths:
            self._clear_all_attachments() # Xóa các file cũ trước khi thêm mới
            self.attached_file_paths.extend(filepaths) # Thêm các đường dẫn mới vào list
            if self.attached_file_paths:
                self.attached_files_display_frame.grid() # Hiển thị frame chứa file
                for path in self.attached_file_paths:
                    self._display_attached_file(path)
                print(f"Đã đính kèm {len(filepaths)} file.")
            else:
                 self.attached_files_display_frame.grid_remove() # Ẩn nếu không có file nào
        # Không làm gì nếu user cancel

    def _display_attached_file(self, filepath):
        """Tạo widget hiển thị cho một file đính kèm."""
        filename = os.path.basename(filepath)
        display_name = (filename[:25] + '...') if len(filename) > 25 else filename

        file_item_frame = ctk.CTkFrame(self.attached_files_display_frame, fg_color=("gray80", "gray25"), height=30)
        # Pack ngang trong scrollable frame
        file_item_frame.pack(side=tk.LEFT, padx=5, pady=5, fill="y")

        file_label = ctk.CTkLabel(file_item_frame, text=display_name, font=self.timestamp_font_tuple)
        file_label.pack(side=tk.LEFT, padx=(8, 5), pady=5)

        remove_button = ctk.CTkButton(
            file_item_frame, text="✕", width=20, height=20, text_color=("gray20", "gray80"),
            fg_color="transparent", hover_color=("gray70", "gray40"),
            command=lambda p=filepath, f=file_item_frame: self._remove_attached_file(p, f)
        )
        remove_button.pack(side=tk.RIGHT, padx=(0, 8), pady=5)

        self.attached_file_widgets[filepath] = file_item_frame # Lưu widget để xóa sau

    def _remove_attached_file(self, filepath, frame_widget):
        """Xóa một file khỏi danh sách đính kèm và khỏi UI."""
        if filepath in self.attached_file_paths:
            self.attached_file_paths.remove(filepath)
            print(f"Đã xóa file: {os.path.basename(filepath)}")
        if filepath in self.attached_file_widgets:
            frame_widget.destroy()
            del self.attached_file_widgets[filepath]
        # Ẩn frame display nếu không còn file nào
        if not self.attached_file_paths:
            self.attached_files_display_frame.grid_remove()

    def _clear_all_attachments(self):
        """Xóa tất cả file đính kèm và widget hiển thị."""
        self.attached_file_paths.clear()
        for widget in self.attached_files_display_frame.winfo_children():
            widget.destroy()
        self.attached_file_widgets.clear()
        self.attached_files_display_frame.grid_remove() # Ẩn frame đi
        print("Đã xóa tất cả file đính kèm.")


    def add_message_bubble(self, message, is_user, timestamp=None, is_thinking=False):
        message = str(message).replace('\\n', '\n')
        if not message and not is_thinking: return
        bubble_color = USER_BG_COLOR if is_user else (THINKING_BG_COLOR if is_thinking else GEMINI_BG_COLOR)
        anchor_side = "e" if is_user else "w"
        outer_bubble_frame = ctk.CTkFrame(self.chat_scroll_frame, fg_color="transparent")
        outer_bubble_frame.pack(anchor=anchor_side, padx=10, pady=(5, 0 if is_thinking or not timestamp else 5), fill='x')
        if is_thinking: self.thinking_bubble_ref = outer_bubble_frame
        content_frame_kwargs = {"fg_color": bubble_color, "corner_radius": 10}
        if is_thinking: content_frame_kwargs["border_width"] = 1; content_frame_kwargs["border_color"] = ("gray70", "gray40")
        bubble_content_frame = ctk.CTkFrame(outer_bubble_frame, **content_frame_kwargs)
        bubble_content_frame.pack(anchor=anchor_side, padx=0, pady=0, fill='x', expand=True, ipadx=5, ipady=3)
        if is_thinking:
             thinking_label = ctk.CTkLabel(bubble_content_frame, text="Đang suy nghĩ...", font=self.base_font_tuple, text_color=TIMESTAMP_COLOR); thinking_label.pack(padx=10, pady=8)
        else:
            pattern = r"(\*\*\*.+?\*\*\*)|(```(?:[a-zA-Z]*\n)?(.+?)```)"
            last_index = 0; widget_added = False
            for match in re.finditer(pattern, message, re.DOTALL):
                widget_added = True; start, end = match.span()
                if start > last_index: self._add_text_widget(bubble_content_frame, message[last_index:start], is_user)
                bold_content = match.group(1); code_content = match.group(3)
                if bold_content: self._add_text_widget(bubble_content_frame, bold_content[3:-3], is_user, is_bold=True)
                elif code_content: self._add_code_widget(bubble_content_frame, code_content.strip('\n'), is_user)
                last_index = end
            if not widget_added: self._add_text_widget(bubble_content_frame, message, is_user)
            elif last_index < len(message): self._add_text_widget(bubble_content_frame, message[last_index:], is_user)
        if timestamp and not is_thinking:
            ts_text = "";
            try: dt_obj = datetime.datetime.fromisoformat(timestamp); ts_text = dt_obj.strftime("%H:%M %d/%m/%Y")
            except: ts_text = str(timestamp)
            timestamp_label = ctk.CTkLabel(outer_bubble_frame, text=ts_text, font=self.timestamp_font_tuple, text_color=TIMESTAMP_COLOR); timestamp_label.pack(anchor=anchor_side, padx=5, pady=(0, 5))
        self._scroll_to_bottom(); return outer_bubble_frame
    def _add_text_widget(self, parent_content_frame, text, is_user, is_bold=False):
        if not text.strip(): return
        font_tuple = self.bold_font_tuple if is_bold else self.base_font_tuple
        text_color = ("#000000", "#ffffff")
        textbox = ctk.CTkTextbox(parent_content_frame, font=font_tuple, wrap="word", activate_scrollbars=False, border_width=0, fg_color="transparent", text_color=text_color, height=10)
        textbox.pack(padx=10, pady=(5 if parent_content_frame.winfo_children() else 8, 5), fill="both", expand=True)
        textbox.insert("1.0", text); textbox.configure(state="disabled")
        self.after(30, lambda tb=textbox: self._adjust_textbox_height(tb))
    def _add_code_widget(self, parent_content_frame, code_text, is_user):
        if not code_text.strip(): return
        code_frame = ctk.CTkFrame(parent_content_frame, fg_color=CODE_BG_COLOR, border_width=1, border_color=("gray70", "gray40"), corner_radius=8)
        code_frame.pack(padx=10, pady=(5 if parent_content_frame.winfo_children() else 8, 5), fill='both', expand=True)
        code_frame.grid_columnconfigure(0, weight=1)
        textbox = ctk.CTkTextbox(code_frame, font=self.code_font_tuple, wrap="none", activate_scrollbars=True, border_width=0, fg_color="transparent", text_color=("#1e1e1e", "#d4d4d4"), height=10)
        textbox.grid(row=0, column=0, padx=(8,0), pady=(8, 8), sticky="nsew"); textbox.insert("1.0", code_text); textbox.configure(state="disabled")
        copy_button = ctk.CTkButton(code_frame, text="", image=self.copy_icon_image, width=28, height=28, fg_color=("gray75", "gray30"), hover_color=("gray65", "gray40"), command=lambda c=code_text: self._copy_to_clipboard(c, "Mã nguồn"))
        copy_button.grid(row=0, column=1, padx=(5, 8), pady=(8, 5), sticky="ne")
        self.after(30, lambda tb=textbox: self._adjust_textbox_height(tb, is_code=True))
    def _adjust_textbox_height(self, textbox, is_code=False):
        try:
            font_tuple = textbox.cget("font"); actual_font = font.Font(family=font_tuple[0], size=font_tuple[1]); font_height = actual_font.metrics("linespace")
            line_count_str = textbox.index("end-1c").split('.')[0]; line_count = int(line_count_str) if line_count_str.isdigit() else 1
            internal_padding = 10; new_height = (line_count * font_height) + internal_padding
            max_h = 600
            final_height = min(new_height, max_h)
            current_height = textbox.winfo_reqheight()
            if abs(final_height - current_height) > font_height * 0.5 :
                 textbox.configure(height=final_height)
                 parent = textbox.master # container frame
                 if parent: parent.update_idletasks()
                 outer_parent = parent.master # outer_bubble_frame
                 if outer_parent: outer_parent.update_idletasks()
                 self.chat_scroll_frame.update_idletasks()
        except Exception as e: print(f"Lỗi chỉnh height: {e}")
    def _copy_to_clipboard(self, text_to_copy, type_name="Nội dung"):
        try:
            pyperclip.copy(text_to_copy); print(f"{type_name} đã copy!")
            original_text = self.token_label.cget("text")
            self.token_label.configure(text=f"Đã copy {type_name.lower()}!")
            self.after(2000, lambda: self.token_label.configure(text=original_text) if "Đã copy" in self.token_label.cget("text") else None)
        except Exception as e: messagebox.showerror("Lỗi", f"Lỗi copy {type_name.lower()}:\n{e}", parent=self)
    def _scroll_to_bottom(self):
         self.after(50, lambda: self.chat_scroll_frame._parent_canvas.yview_moveto(1.0))
    def _remove_thinking_bubble(self):
         if self.thinking_bubble_ref and self.thinking_bubble_ref.winfo_exists():
              self.thinking_bubble_ref.destroy(); self.thinking_bubble_ref = None

    # --- send_message_event (ĐÃ THAY ĐỔI: Gửi list file paths) ---
    def send_message_event(self, event=None):
        global chat_session
        prompt = self.prompt_input.get("1.0", tk.END).strip()
        # <<< THAY ĐỔI: Lấy list file paths >>>
        current_file_paths = list(self.attached_file_paths) # Tạo bản sao list

        if not prompt and not current_file_paths:
            messagebox.showwarning("Thiếu", "Nhập tin nhắn hoặc đính kèm file.", parent=self); return
        if not chat_session:
            if not gemini_model: messagebox.showerror("Lỗi", "Gemini chưa cấu hình.", parent=self); return
            print("Session chưa có, tạo mới..."); self.start_new_chat(confirm_save=False)
            if not chat_session: messagebox.showerror("Lỗi", "Không thể tạo session.", parent=self); return

        # Hiển thị tin nhắn user (chỉ prompt, thông tin file đã ở khu vực riêng)
        current_timestamp = datetime.datetime.now().isoformat()
        if prompt:
            self.add_message_bubble(prompt, is_user=True, timestamp=current_timestamp)

        self.prompt_input.delete("1.0", tk.END)
        self._clear_all_attachments() # Xóa file khỏi UI và list sau khi lấy giá trị

        # Disable controls
        self.prompt_input.configure(state="disabled"); self.send_button.configure(state="disabled", text="..."); self.attach_button.configure(state="disabled")
        self._remove_thinking_bubble(); self.add_message_bubble("", is_user=False, is_thinking=True)
        self.token_label.configure(text="Đang gửi...")

        # <<< THAY ĐỔI: Truyền list file paths vào thread >>>
        thread = threading.Thread(target=self._send_to_gemini, args=(prompt, current_file_paths, current_timestamp), daemon=True); thread.start()

    def insert_newline_event(self, event=None):
        self.prompt_input.insert(tk.INSERT, "\n"); return "break"

    # --- _send_to_gemini (ĐÃ THAY ĐỔI: Nhận và xử lý list file paths) ---
    def _send_to_gemini(self, prompt_text, file_paths, user_timestamp): # Nhận list file_paths
        global last_gemini_response, chat_session
        total_tokens = None; uploaded_file_refs = [] # <<< THAY ĐỔI: List để chứa các ref file
        processing_failed = False; gemini_response_timestamp = None

        try:
            if not chat_session: raise ValueError("Session không hợp lệ.")
            content_parts = []

            # 1. Upload tất cả file trong list
            if file_paths:
                self.after(0, lambda: self.token_label.configure(text=f"Uploading {len(file_paths)} file(s)..."))
                for f_path in file_paths:
                    filename = os.path.basename(f_path); print(f"Uploading: {filename}")
                    try:
                        mime_type, _ = mimetypes.guess_type(f_path); mime_type = mime_type or "application/octet-stream"
                        uploaded_file = genai.upload_file(path=f_path, mime_type=mime_type)
                        uploaded_file_refs.append(uploaded_file) # Thêm ref vào list
                        print(f"Upload OK: {uploaded_file.name}")
                    except Exception as upload_error:
                        error_msg = f"Lỗi upload '{filename}': {upload_error}"; print(error_msg)
                        self.after(0, self._update_chat_with_error_bubble, error_msg); processing_failed = True
                        break # Dừng upload nếu có lỗi
                if not processing_failed: self.after(0, lambda: self.token_label.configure(text=f"Uploaded {len(uploaded_file_refs)} file(s)"))
                content_parts.extend(uploaded_file_refs) # Thêm tất cả ref vào content

            # 2. Thêm prompt text
            if prompt_text and not processing_failed:
                content_parts.append(prompt_text)

            # 3. Gửi message
            if content_parts and not processing_failed:
                print(f"Gửi {len(content_parts)} phần..."); self.after(0, lambda: self.token_label.configure(text="Chờ Gemini..."))
                send_time = datetime.datetime.now()
                response = chat_session.send_message(content_parts)
                receive_time = datetime.datetime.now(); gemini_response_timestamp = receive_time.isoformat(); print(f"Time: {receive_time - send_time}")
                self.after(0, self._remove_thinking_bubble)
                if response and hasattr(response, 'text'):
                    response_text = response.text; last_gemini_response = response_text
                    if hasattr(response, 'usage_metadata') and response.usage_metadata: total_tokens = response.usage_metadata.total_token_count
                    self.after(10, self._update_chat_with_response_bubble, response_text, gemini_response_timestamp, total_tokens)
                else: error_message = "Gemini không trả về text."; print(error_message); last_gemini_response = ""; self.after(10, self._update_chat_with_error_bubble, error_message); processing_failed = True
            elif not content_parts and not processing_failed: print("Chỉ gửi file.")
        except Exception as e: error_message = f"Lỗi API: {e}"; print(error_message); last_gemini_response = ""; self.after(0, self._remove_thinking_bubble); self.after(10, self._update_chat_with_error_bubble, error_message); processing_failed = True
        finally:
             self.after(50, self._enable_input)
             # Chỉ lưu nếu không lỗi VÀ có nội dung gửi đi (prompt hoặc file upload thành công)
             if not processing_failed and (prompt_text or uploaded_file_refs):
                 self.after(60, lambda ts_u=user_timestamp, ts_g=gemini_response_timestamp: self.save_current_chat(user_ts=ts_u, gemini_ts=ts_g))

    def _update_chat_with_response_bubble(self, response_text, timestamp, tokens=None):
        self.add_message_bubble(response_text, is_user=False, timestamp=timestamp)
        if tokens is not None: self.token_label.configure(text=f"Tokens: {tokens}")
        else: self.token_label.configure(text="Tokens: -")
        global last_gemini_response; last_gemini_response = response_text
    def _update_chat_with_error_bubble(self, error_message):
        self.add_message_bubble(f"Lỗi Hệ thống:\n{error_message}", is_user=False, timestamp=datetime.datetime.now().isoformat())
        self.token_label.configure(text="Tokens: Lỗi")
    def _enable_input(self):
        self.prompt_input.configure(state="normal"); self.send_button.configure(state="normal", text="Gửi"); self.attach_button.configure(state="normal")
    def copy_last_response(self):
        if last_gemini_response:
            try: pyperclip.copy(last_gemini_response); messagebox.showinfo("OK", "Phản hồi cuối đã sao chép.", parent=self)
            except Exception as e: messagebox.showerror("Lỗi", f"Lỗi copy: {e}", parent=self)
        else: messagebox.showwarning("Chưa có", "Chưa có phản hồi.", parent=self)
    def open_settings(self): self.tab_view.set("Cài đặt")
    def _on_closing(self): print("Đóng ứng dụng..."); self.save_current_chat(); self.destroy()

# --- Main Execution ---
if __name__ == "__main__":
    try: from ctypes import windll; windll.shcore.SetProcessDpiAwareness(1); print("DPI awareness OK (Windows).")
    except: pass
    config = configparser.ConfigParser(); config_mode = "System"; config_theme="blue"
    if os.path.exists(CONFIG_FILE):
        try: config.read(CONFIG_FILE); config_mode = config.get("Appearance", "mode", fallback="System"); config_theme = config.get("Appearance", "theme", fallback="blue")
        except Exception as e: print(f"Lỗi đọc config: {e}")
    try:
        ctk.set_appearance_mode(config_mode)
        script_dir = os.path.dirname(os.path.abspath(__file__)); theme_path = os.path.join(script_dir, "assets", f"{config_theme}.json")
        if os.path.exists(theme_path): ctk.set_default_color_theme(theme_path)
        elif config_theme in ["blue", "dark-blue", "green"]: ctk.set_default_color_theme(config_theme)
        else: ctk.set_default_color_theme("blue")
    except Exception as e: print(f"Lỗi set theme: {e}")
    app = GeminiChatApp()
    app.mainloop()
