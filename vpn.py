# --- START OF FILE tray_vpn.py ---

import tkinter as tk
from tkinter import ttk, messagebox, font as tkfont, scrolledtext, filedialog
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
import configparser
import psutil
import subprocess
import os # Cần cho os._exit
import time
import sys
import requests
import winreg
import ctypes
import threading
import queue # Mặc dù queue không được sử dụng trực tiếp, nhưng để lại nếu cần sau này
import base64
import io

# --- System Tray and Icon Libraries ---
try:
    from pystray import Icon as TrayIcon, Menu as TrayMenu, MenuItem as TrayMenuItem
    PYSTRAY_AVAILABLE = True
except ImportError:
    PYSTRAY_AVAILABLE = False
    print("FATAL ERROR: pystray library not found. Install it using 'pip install pystray'")
    # Thoát sớm nếu thiếu thư viện cốt lõi
    # Sử dụng os._exit thay vì sys.exit để nhất quán với cách thoát cuối cùng
    try:
        # Cố gắng hiển thị lỗi trước khi thoát
        root_err = tk.Tk(); root_err.withdraw(); messagebox.showerror("Missing Library", "pystray not found!"); root_err.destroy()
    except: pass
    os._exit(1)


try:
    from PIL import Image, ImageDraw, ImageFont
    PIL_AVAILABLE = True
except ImportError:
    PIL_AVAILABLE = False
    print("WARNING: Pillow (PIL) library not found. Icon generation will fail.")
    print("Install it using 'pip install Pillow'")
    # Không thoát ở đây, nhưng create_icon_image sẽ thất bại và thoát sau đó

# --- Pywinauto (Optional for Auto-Login) ---
try:
    from pywinauto.application import Application, ProcessNotFoundError
    from pywinauto.findwindows import ElementNotFoundError
    PYWINAUTO_AVAILABLE = True
    print("pywinauto loaded successfully.")
except ImportError:
    PYWINAUTO_AVAILABLE = False
    print("Warning: pywinauto not found. Install it using 'pip install pywinauto' for Auto-Login functionality.")
    class ElementNotFoundError(Exception): pass
    class ProcessNotFoundError(Exception): pass

# --- Constants ---
CONFIG_FILE = 'vpn.ini'
BVSSH_EXE_PATH = r"C:\Program Files (x86)\Bitvise SSH Client\BvSsh.exe" # Vẫn giữ nếu cần tham khảo, dù không dùng trực tiếp
BVSSH_PROCESS_NAME = "BvSsh.exe"
DEFAULT_TLP_FILE_PATH = os.path.join(os.path.expanduser("~"), "Desktop", "ditucogivui.tlp")
IPIFY_URL = "https://api64.ipify.org/?format=json"
DEFAULT_IP_CHECK_INTERVAL_MIN = 1 # Giá trị này có thể đọc từ file config
DEFAULT_VPN_TEXT_FONT_SIZE = 12 # Có thể không còn dùng trực tiếp nếu không có label chính
DEFAULT_THEME = 'solar'
# --- CẬP NHẬT HẰNG SỐ THEO YÊU CẦU CỦA BẠN ---
DEFAULT_LOGIN_DELAY_SECONDS = 1
ICON_TEXT = "☢"
# ---------------------------------------------
DEFAULT_FONT_FAMILY = "Segoe UI"
DEFAULT_FONT_SIZE = 9
APP_TITLE = "VPN Control"


# --- Windows API Constants ---
INTERNET_OPTION_SETTINGS_CHANGED = 39
INTERNET_OPTION_REFRESH = 37
WINDOWS_PROXY_AVAILABLE = False
if sys.platform == 'win32':
    try:
        wininet = ctypes.windll.wininet
        internet_set_option = wininet.InternetSetOptionW
        internet_set_option.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_void_p, ctypes.c_ulong]
        internet_set_option.restype = ctypes.c_bool
        WINDOWS_PROXY_AVAILABLE = True
    except (AttributeError, OSError) as e:
        print(f"Warning: Could not load wininet.dll. Proxy setting disabled. Error: {e}")
else:
    print("Warning: This application heavily relies on Windows features.")

# --- Global Tkinter Root (Hidden) ---
hidden_root = None
def get_hidden_root():
    global hidden_root
    # Lấy theme mặc định từ hằng số trước khi tạo root
    theme = DEFAULT_THEME
    try:
        # Thử đọc theme từ config nếu file tồn tại sớm
        if os.path.exists(CONFIG_FILE):
            temp_conf = configparser.ConfigParser(interpolation=None)
            temp_conf.read(CONFIG_FILE, encoding='utf-8')
            theme = temp_conf.get('Appearance', 'theme', fallback=DEFAULT_THEME)
    except Exception:
        pass # Bỏ qua lỗi đọc config sớm, dùng default

    if hidden_root is None or not hidden_root.winfo_exists():
        hidden_root = ttk.Window(themename=theme)
        hidden_root.withdraw()
    return hidden_root

# --- Helper Functions ---
def is_process_running(process_name):
    for proc in psutil.process_iter(['pid', 'name']):
        try:
            if proc.info['name'].lower() == process_name.lower():
                return True, proc.info['pid']
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            pass
    return False, None

def terminate_process(process_name):
    print(f"Attempting to terminate process: {process_name}")
    is_running_before, pid = is_process_running(process_name)
    if not is_running_before:
        print(f"Process {process_name} not found or already terminated.")
        return True

    try:
        if sys.platform == 'win32':
            creationflags = subprocess.CREATE_NO_WINDOW
            cmd = ['taskkill', '/F', '/T', '/IM', process_name] # Use /T to kill child processes too
            result = subprocess.run(cmd, capture_output=True, text=True, check=False, creationflags=creationflags)
            # Không cần in stdout/stderr của taskkill trừ khi debug
            # print(f"Taskkill Output:\nSTDOUT: {result.stdout}\nSTDERR: {result.stderr}")
            time.sleep(0.5) # Chờ một chút để process thực sự bị kill
            is_running_after, _ = is_process_running(process_name)
            if not is_running_after:
                print(f"Process {process_name} successfully terminated.")
                return True
            else:
                # Thử chờ thêm chút nữa
                print(f"Warning: Process {process_name} still detected after taskkill. Waiting slightly longer...")
                time.sleep(0.5) # Tăng nhẹ thời gian chờ thêm
                is_running_after_extra, _ = is_process_running(process_name)
                if not is_running_after_extra:
                    print(f"Process {process_name} confirmed terminated after extra wait.")
                    return True
                else:
                    print(f"Error: Failed to terminate {process_name} after multiple attempts.")
                    return False
        else:
            print(f"Termination on non-Windows for {process_name} not supported in this version.")
            return False
    except FileNotFoundError:
        print("Error: 'taskkill' command not found. Cannot terminate Bitvise automatically.")
        return False
    except Exception as e:
        print(f"An unexpected error occurred during process termination: {e}")
        return False

def format_speed(speed_bytes_per_sec):
    if speed_bytes_per_sec < 1024:
        return f"{speed_bytes_per_sec:.3f} B/s"
    elif speed_bytes_per_sec < 1024**2:
        return f"{speed_bytes_per_sec / 1024:.3f} KB/s"
    elif speed_bytes_per_sec < 1024**3:
        return f"{speed_bytes_per_sec / (1024**2):.3f} MB/s"
    else:
        return f"{speed_bytes_per_sec / (1024**3):.3f} GB/s"

def format_total_data(total_bytes):
    if total_bytes < 1024:
        return f"{total_bytes} B"
    elif total_bytes < 1024**2:
        return f"{total_bytes / 1024:.3f} KB"
    elif total_bytes < 1024**3:
        return f"{total_bytes / (1024**2):.3f} MB"
    elif total_bytes < 1024**4:
        return f"{total_bytes / (1024**3):.3f} GB"
    else:
        return f"{total_bytes / (1024**4):.3f} TB"

# --- Configuration Handling ---
def create_default_config(filepath):
    print(f"Creating default configuration file: {filepath}")
    config = configparser.ConfigParser(interpolation=None)
    # Lấy giá trị mặc định từ hằng số đã cập nhật
    default_proxy_ip = "127.0.0.1"
    default_proxy_port = "9999"
    default_tlp = DEFAULT_TLP_FILE_PATH
    default_ip_interval = DEFAULT_IP_CHECK_INTERVAL_MIN
    default_login_delay = DEFAULT_LOGIN_DELAY_SECONDS # Sử dụng hằng số đã cập nhật
    default_font_family = DEFAULT_FONT_FAMILY
    default_font_size = DEFAULT_FONT_SIZE
    default_theme_name = DEFAULT_THEME

    config.add_section('Appearance')
    config.set('Appearance', 'font_family', default_font_family)
    config.set('Appearance', 'font_size', str(default_font_size))
    config.set('Appearance', 'theme', default_theme_name)

    config.add_section('VPN')
    config.set('VPN', 'tlp_path', default_tlp)

    config.add_section('Proxy')
    config.set('Proxy', 'ip', default_proxy_ip)
    config.set('Proxy', 'port', str(default_proxy_port))

    config.add_section('General')
    config.set('General', 'ip_check_interval_minutes', str(default_ip_interval))

    config.add_section('Automation')
    config.set('Automation', 'login_delay_seconds', str(default_login_delay))

    try:
        with open(filepath, 'w', encoding='utf-8') as cf:
            config.write(cf)
        print("Default config file created.")
    except IOError as e:
        print(f"Error creating config file {filepath}: {e}")

def ensure_config_exists():
    if not os.path.exists(CONFIG_FILE):
        create_default_config(CONFIG_FILE)
    else:
        # Validation cơ bản
        try:
            temp_config = configparser.ConfigParser(interpolation=None)
            temp_config.read(CONFIG_FILE, encoding='utf-8')
            required_sections = ['Appearance', 'VPN', 'Proxy', 'General', 'Automation']
            missing = [s for s in required_sections if not temp_config.has_section(s)]
            if missing:
                raise ValueError(f"Missing sections: {', '.join(missing)}")
            # Kiểm tra các key cần thiết
            temp_config.get('VPN', 'tlp_path')
            temp_config.get('Proxy', 'ip')
            temp_config.get('Proxy', 'port')
            # --- FIX: Use getfloat for validation ---
            temp_config.getfloat('Automation', 'login_delay_seconds') # Kiểm tra kiểu dữ liệu float
            # --- END FIX ---
            print(f"Config file {CONFIG_FILE} exists and seems valid.")
        except Exception as e:
            print(f"Config file {CONFIG_FILE} potentially invalid or outdated ({e}). Recreating default.")
            try:
                backup_path = CONFIG_FILE + f".corrupted_bak_{int(time.time())}"
                os.rename(CONFIG_FILE, backup_path)
                print(f"Backed up potentially invalid config to {backup_path}")
            except Exception as bak_e:
                print(f"Could not back up config: {bak_e}")
            create_default_config(CONFIG_FILE)

# --- Info Window Class ---
class InfoWindow(tk.Toplevel):
    def __init__(self, master, controller):
        super().__init__(master)
        self.controller = controller
        self.title("VPN status")
        # --- CỐ ĐỊNH KÍCH THƯỚC: Không cho thay đổi kích thước bằng tay ---
        self.resizable(False, False)

        # Set theme sử dụng ttkbootstrap style trên Toplevel
        try:
            theme = self.controller.theme_var.get()
            self.style = ttk.Style(theme)
        except Exception: # Fallback nếu controller hoặc theme chưa sẵn sàng
            self.style = ttk.Style(DEFAULT_THEME)

        # Định nghĩa fonts dựa trên cài đặt của controller
        try:
            base_family = self.controller.font_family_var.get()
            base_size = self.controller.font_size_var.get()
        except Exception: # Fonts dự phòng
            base_family = DEFAULT_FONT_FAMILY
            base_size = DEFAULT_FONT_SIZE

        label_font = tkfont.Font(family=base_family, size=base_size)
        value_font = tkfont.Font(family=base_family, size=base_size + 1, weight='bold')
        ip_font = tkfont.Font(family=base_family, size=base_size + 2, weight='bold')
        speed_font = tkfont.Font(family=base_family, size=base_size + 1)

        padding = {'padx': 10, 'pady': 5}
        frame = ttk.Frame(self, padding=15)
        frame.pack(expand=True, fill="both") # Dùng pack để frame lấp đầy Toplevel

        # --- CỐ ĐỊNH KÍCH THƯỚC: Đặt chiều rộng cố định cho các Label giá trị ---
        # Điều chỉnh các giá trị width này nếu cần để chứa chuỗi dài nhất
        label_width = 20 # Chiều rộng chung (tính bằng ký tự trung bình)
        speed_width = 32 # Chiều rộng riêng cho label tốc độ

        # Dùng grid để sắp xếp các widget bên trong frame
        frame.columnconfigure(1, weight=1) # Cho phép cột giá trị mở rộng một chút nếu cần

        # Public IP
        ttk.Label(frame, text="Public IP:", font=label_font).grid(row=0, column=0, sticky="w", **padding)
        ip_label = ttk.Label(frame, textvariable=self.controller.ip_address_var_info, font=ip_font, width=label_width, anchor='w')
        ip_label.grid(row=0, column=1, sticky="ew", **padding) # sticky='ew' để nó căn trong cột
        try: ip_label.config(foreground=self.style.colors.primary)
        except Exception: pass

        # Status
        ttk.Label(frame, text="Status:", font=label_font).grid(row=1, column=0, sticky="w", **padding)
        ttk.Label(frame, textvariable=self.controller.vpn_status_text_var, font=value_font, width=label_width, anchor='w').grid(row=1, column=1, sticky="ew", **padding)

        # Connected Time
        ttk.Label(frame, text="Connected Time:", font=label_font).grid(row=2, column=0, sticky="w", **padding)
        ttk.Label(frame, textvariable=self.controller.vpn_timer_var_info, font=value_font, width=label_width, anchor='w').grid(row=2, column=1, sticky="ew", **padding)

        # Separator
        ttk.Separator(frame, orient=tk.HORIZONTAL).grid(row=3, column=0, columnspan=2, sticky="ew", pady=10)

        # Current Speed
        ttk.Label(frame, text="Speed:", font=label_font).grid(row=4, column=0, sticky="w", **padding)
        speed_label = ttk.Label(frame, textvariable=self.controller.network_speed_var_info, font=speed_font, width=speed_width, anchor='w')
        speed_label.grid(row=4, column=1, sticky="ew", **padding)
        try: speed_label.config(foreground=self.style.colors.info)
        except Exception: pass

        # Total Download
        ttk.Label(frame, text="Total Download:", font=label_font).grid(row=5, column=0, sticky="w", **padding)
        ttk.Label(frame, textvariable=self.controller.total_download_var_info, font=speed_font, width=label_width, anchor='w').grid(row=5, column=1, sticky="ew", **padding)

        # Total Upload
        ttk.Label(frame, text="Total Upload:", font=label_font).grid(row=6, column=0, sticky="w", **padding)
        ttk.Label(frame, textvariable=self.controller.total_upload_var_info, font=speed_font, width=label_width, anchor='w').grid(row=6, column=1, sticky="ew", **padding)

        # Close button
        close_button = ttk.Button(frame, text="Close", command=self.on_close, bootstyle=SECONDARY) # Gọi on_close thay vì destroy trực tiếp
        close_button.grid(row=7, column=0, columnspan=2, pady=(15, 0)) # Đặt nút ở giữa

        # Handle window close event (X button)
        self.protocol("WM_DELETE_WINDOW", self.on_close)

        # --- CỐ ĐỊNH KÍCH THƯỚC: Cập nhật để tính kích thước yêu cầu ---
        self.update_idletasks()
        # Optional: Lấy kích thước yêu cầu và đặt lại để cố định hoàn toàn
        # req_w = self.winfo_reqwidth()
        # req_h = self.winfo_reqheight()
        # self.geometry(f"{req_w}x{req_h}")

        # Position near center (Optional)
        self.after(10, self.center_window) # Gọi hàm định vị sau một khoảng trễ nhỏ

    def center_window(self):
        """Attempts to center the window relative to the (potentially hidden) master."""
        try:
            self.update_idletasks() # Đảm bảo kích thước là mới nhất
            master = self.master # Lấy master (hidden_root)
            if master is None: return # Không có master để căn chỉnh

            master_x = master.winfo_rootx()
            master_y = master.winfo_rooty()
            master_w = master.winfo_width()
            master_h = master.winfo_height()
            win_w = self.winfo_width()
            win_h = self.winfo_height()

            # Fallback về giữa màn hình nếu master không hợp lệ
            if master_w < 10 or master_h < 10 :
                 screen_w = self.winfo_screenwidth()
                 screen_h = self.winfo_screenheight()
                 x = (screen_w // 2) - (win_w // 2)
                 y = (screen_h // 2) - (win_h // 2)
            else:
                 x = master_x + (master_w // 2) - (win_w // 2)
                 y = master_y + (master_h // 2) - (win_h // 2)

            # Đảm bảo không ra ngoài màn hình
            x = max(0, min(x, self.winfo_screenwidth() - win_w))
            y = max(0, min(y, self.winfo_screenheight() - win_h))
            self.geometry(f"+{x}+{y}")
            # print(f"Centered InfoWindow at +{x}+{y}") # Debug
        except Exception as pos_err:
            print(f"Could not center InfoWindow: {pos_err}")
            # Để hệ điều hành tự đặt vị trí nếu có lỗi

    def on_close(self):
        """Handles closing the window."""
        if self.controller:
            self.controller.info_window = None # Notify controller
        try:
            # Hủy các lệnh after nếu có để tránh lỗi
            for after_id in self.tk.eval('after info').split():
                self.after_cancel(after_id)
            self.destroy()
        except tk.TclError:
            # print("InfoWindow already destroyed.")
            pass # Bỏ qua lỗi nếu cửa sổ đã bị hủy
        except Exception as e:
             print(f"Error during InfoWindow close: {e}")

# --- Settings Window Class ---
class SettingsWindow(tk.Toplevel):
    # ... (Nội dung lớp SettingsWindow giữ nguyên) ...
    def __init__(self, master, controller):
        super().__init__(master)
        self.controller = controller
        self.title("⚙️VPN Settings")
        # self.resizable(False, False) # Cho phép thay đổi kích thước nếu muốn
        try:
            theme = self.controller.theme_var.get()
            self.style = ttk.Style(theme)
        except Exception:
            self.style = ttk.Style(DEFAULT_THEME)

        # --- Tạo biến tạm để người dùng sửa, chỉ áp dụng khi bấm Save ---
        self.font_family_var = tk.StringVar(value=self.controller.font_family_var.get())
        self.font_size_var = tk.IntVar(value=self.controller.font_size_var.get())
        self.theme_var = tk.StringVar(value=self.controller.theme_var.get())
        self.ip_interval_var = tk.IntVar(value=self.controller.ip_check_interval_min_var.get())
        self.proxy_ip_var = tk.StringVar(value=self.controller.proxy_ip_var.get())
        self.proxy_port_var = tk.StringVar(value=self.controller.proxy_port_var.get())
        self.tlp_path_var = tk.StringVar(value=self.controller.tlp_file_path_var.get())
        # Chuyển đổi sang FloatVar để cho phép giá trị lẻ, nhưng Spinbox dùng IntVar
        self.login_delay_var = tk.DoubleVar(value=self.controller.login_delay_seconds_var.get())

        # --- Build the UI ---
        frame = ttk.Frame(self, padding=(20, 10))
        frame.pack(expand=True, fill="both")
        frame.columnconfigure(1, weight=1)
        current_row = 0

        # --- Font Chữ ---
        font_frame = ttk.LabelFrame(frame, text="Font Chữ (Giao diện Info/Settings)", padding=(10, 5))
        font_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=5)
        font_frame.columnconfigure(1, weight=1)
        ttk.Label(font_frame, text="Font:").grid(row=0, column=0, padx=(0, 5), sticky='w')
        try: available_fonts = sorted(list(tkfont.families()))
        except: available_fonts = ["Arial", "Segoe UI", "Times New Roman", "Verdana"]
        ttk.Combobox(font_frame, textvariable=self.font_family_var, values=available_fonts, state="readonly").grid(row=0, column=1, padx=(0, 10), sticky='ew')
        ttk.Label(font_frame, text="Cỡ:").grid(row=0, column=2, padx=(10, 5), sticky='w')
        ttk.Spinbox(font_frame, from_=8, to=72, increment=1, textvariable=self.font_size_var, width=5).grid(row=0, column=3, sticky='w')
        current_row += 1

        # --- Giao diện (Theme) ---
        theme_frame = ttk.LabelFrame(frame, text="Giao diện (Theme)", padding=(10, 5))
        theme_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=5)
        theme_frame.columnconfigure(0, weight=1)
        try: theme_names = ttk.Style().theme_names()
        except: theme_names = [DEFAULT_THEME]
        ttk.Combobox(theme_frame, textvariable=self.theme_var, values=theme_names, state="readonly").grid(row=0, column=0, sticky='ew')
        current_row += 1

        # --- File Profile Bitvise ---
        tlp_frame = ttk.LabelFrame(frame, text="File Profile Bitvise (.tlp)", padding=(10, 5))
        tlp_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=5)
        tlp_frame.columnconfigure(0, weight=1)
        ttk.Entry(tlp_frame, textvariable=self.tlp_path_var).grid(row=0, column=0, sticky="ew", padx=(0, 5))
        ttk.Button(tlp_frame, text="Chọn...", command=self.browse_tlp_file, width=8).grid(row=0, column=1, sticky="e")
        current_row += 1

        # --- Proxy Server (SOCKS) ---
        proxy_frame = ttk.LabelFrame(frame, text="Proxy Server (SOCKS)", padding=(10, 5))
        proxy_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=5)
        proxy_frame.columnconfigure(1, weight=1)
        ttk.Label(proxy_frame, text="IP:").grid(row=0, column=0, padx=(0, 5), sticky='w')
        ttk.Entry(proxy_frame, textvariable=self.proxy_ip_var).grid(row=0, column=1, padx=(0, 10), sticky='ew')
        ttk.Label(proxy_frame, text="Port:").grid(row=0, column=2, padx=(10, 5), sticky='w')
        ttk.Entry(proxy_frame, textvariable=self.proxy_port_var, width=7).grid(row=0, column=3, sticky='w')
        current_row += 1

        # --- Tự động Login ---
        login_delay_frame = ttk.LabelFrame(frame, text="Tự động Login (Requires pywinauto)", padding=(10, 5))
        login_delay_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Label(login_delay_frame, text="Chờ:").pack(side=tk.LEFT, padx=(0, 5))
        # Spinbox hỗ trợ số thực với format và increment phù hợp
        ttk.Spinbox(login_delay_frame, from_=0.0, to=60.0, increment=0.1, format="%.1f", textvariable=self.login_delay_var, width=5).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(login_delay_frame, text="giây before clicking Login & Minimize").pack(side=tk.LEFT)
        current_row += 1

        # --- Kiểm tra IP Public ---
        ip_check_frame = ttk.LabelFrame(frame, text="Kiểm tra IP Public", padding=(10, 5))
        ip_check_frame.grid(row=current_row, column=0, columnspan=2, sticky="ew", pady=5)
        ttk.Label(ip_check_frame, text="Mỗi:").pack(side=tk.LEFT, padx=(0, 5))
        ttk.Spinbox(ip_check_frame, from_=0, to=1440, increment=1, textvariable=self.ip_interval_var, width=5).pack(side=tk.LEFT, padx=(0, 5))
        ttk.Label(ip_check_frame, text="phút (0 = disable periodic check)").pack(side=tk.LEFT)
        current_row += 1

        # --- Buttons Frame ---
        button_frame = ttk.Frame(frame)
        button_frame.grid(row=current_row, column=0, columnspan=2, pady=15)

        apply_button = ttk.Button(button_frame, text="Apply & Save", command=self.apply_and_save, bootstyle=PRIMARY)
        apply_button.pack(side=tk.LEFT, padx=10)

        cancel_button = ttk.Button(button_frame, text="Cancel", command=self.on_close, bootstyle=SECONDARY) # Gọi on_close thay vì destroy trực tiếp
        cancel_button.pack(side=tk.LEFT, padx=10)

        self.protocol("WM_DELETE_WINDOW", self.on_close)

    def browse_tlp_file(self):
        # ... (Giữ nguyên) ...
        current_path = self.tlp_path_var.get()
        initial_dir = os.path.dirname(current_path) if current_path and os.path.exists(os.path.dirname(current_path)) else os.path.expanduser("~")
        file_path = filedialog.askopenfilename(
            title="Select Bitvise Profile (.tlp)",
            initialdir=initial_dir,
            filetypes=(("Bitvise Profiles", "*.tlp"), ("All files", "*.*")),
            parent=self # Make dialog modal to this settings window
        )
        if file_path:
            self.tlp_path_var.set(file_path)


    def apply_and_save(self):
        # ... (Giữ nguyên, đảm bảo nó cập nhật login_delay_seconds_var là float) ...
        print("Applying and saving settings from SettingsWindow...")
        # Update controller's variables from the settings window's variables
        self.controller.font_family_var.set(self.font_family_var.get())
        self.controller.font_size_var.set(self.font_size_var.get())
        new_theme = self.theme_var.get()
        self.controller.theme_var.set(new_theme) # Cập nhật theme trong controller
        self.controller.ip_check_interval_min_var.set(self.ip_interval_var.get())
        self.controller.proxy_ip_var.set(self.proxy_ip_var.get())
        self.controller.proxy_port_var.set(self.proxy_port_var.get())
        self.controller.tlp_file_path_var.set(self.tlp_path_var.get())
        self.controller.login_delay_seconds_var.set(self.login_delay_var.get()) # Cập nhật giá trị float

        # Apply theme change to hidden root and settings window
        try:
            get_hidden_root().style.theme_use(new_theme)
            self.style.theme_use(new_theme) # Áp dụng cho chính cửa sổ settings
            # Cập nhật lại style cho các Toplevel khác nếu đang mở? (Info window)
            if self.controller.info_window and self.controller.info_window.winfo_exists():
                self.controller.info_window.style.theme_use(new_theme)
                # Có thể cần re-configure các widget trong InfoWindow nếu màu sắc thay đổi nhiều
        except tk.TclError as theme_err:
            print(f"Warning: Could not apply theme '{new_theme}': {theme_err}")
            messagebox.showwarning("Theme Error", f"Could not apply theme '{new_theme}'.\nKeeping previous theme.", parent=self)
            # Reset combobox về theme cũ
            self.theme_var.set(self.controller.style.theme_use())


        self.controller.save_settings()
        self.controller.reschedule_ip_check() # Gọi lại để áp dụng interval mới

        messagebox.showinfo("Settings Saved", "Settings have been applied and saved.", parent=self)
        self.on_close() # Đóng cửa sổ

    def on_close(self):
        if self.controller:
            self.controller.settings_window = None # Notify controller
        try:
            self.destroy()
        except tk.TclError:
            pass # Ignore error if already destroyed

# --- Main Application Class (Tray Controller) ---
class TrayVpnApp:
    def __init__(self):
        print("Initializing TrayVpnApp...")
        get_hidden_root() # Tạo root Tkinter ẩn trước

        ensure_config_exists()
        self.config = configparser.ConfigParser(interpolation=None)
        self.info_window = None
        self.settings_window = None
        self.tray_icon = None
        self._stop_event = threading.Event()
        self._update_thread = None
        self._auto_login_thread = None
        self._bvssh_pid = None
        self._is_exiting = False
        # Event để trì hoãn check IP cho đến khi auto-login xong
        self._auto_login_finished_event = threading.Event()

        # --- Tkinter Variables ---
        self.vpn_status = tk.BooleanVar(value=False)
        self.vpn_status_text_var = tk.StringVar(value="Disconnected")
        self.vpn_timer_var_info = tk.StringVar(value="00:00:00")
        self.network_speed_var_info = tk.StringVar(value="Down: --- / Up: ---")
        self.ip_address_var_info = tk.StringVar(value="IP: Pending...") # Trạng thái chờ ban đầu
        self.total_download_var_info = tk.StringVar(value="Total Down: ---")
        self.total_upload_var_info = tk.StringVar(value="Total Up: ---")

        # Configurable settings variables
        self.ip_check_interval_min_var = tk.IntVar()
        self.proxy_ip_var = tk.StringVar()
        self.proxy_port_var = tk.StringVar()
        self.tlp_file_path_var = tk.StringVar()
        # Sử dụng DoubleVar để lưu giá trị delay (có thể lẻ)
        self.login_delay_seconds_var = tk.DoubleVar()
        self.font_family_var = tk.StringVar()
        self.font_size_var = tk.IntVar()
        self.theme_var = tk.StringVar()

        # Network calculation state
        self.elapsed_seconds = 0
        self.last_net_io = None
        self.last_net_time = None
        self.initial_net_io = None

        # Load initial settings
        self.load_settings()

        # Apply theme to hidden root (đã được gọi trong get_hidden_root nếu root mới)
        root = get_hidden_root()
        try:
            # Đảm bảo theme được áp dụng lại nếu root đã tồn tại
            if root.style.theme_use() != self.theme_var.get():
                root.style.theme_use(self.theme_var.get())
        except tk.TclError as theme_err:
             print(f"Warning: Could not apply initial theme '{self.theme_var.get()}': {theme_err}")
             current_theme = root.style.theme_use()
             self.theme_var.set(current_theme)
             print(f"Using theme: {current_theme}")

    def create_icon_image(self):
        # ... (Giữ nguyên logic tạo icon) ...
        if not PIL_AVAILABLE:
            messagebox.showerror("Fatal Error", "Pillow library (PIL) is required for the tray icon.\nPlease install it: pip install Pillow")
            os._exit(1) # Thoát nếu không tạo được icon

        width = 64
        height = 64
        try:
            font = ImageFont.truetype("seguiemj.ttf", int(height * 0.75)) # Thử tăng cỡ chữ icon
        except IOError:
            print("Warning: Segoe UI Emoji font not found. Using default font.")
            try: font = ImageFont.load_default()
            except Exception as e:
                 print(f"Error loading any default font: {e}")
                 messagebox.showerror("Fatal Error", "Could not load font for tray icon.")
                 os._exit(1)

        image = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(image)

        try: bbox = draw.textbbox((0, 0), ICON_TEXT, font=font)
        except AttributeError:
             try: text_width, text_height = draw.textsize(ICON_TEXT, font=font)
             except AttributeError: text_width, text_height = width // 2, height // 2
             bbox = (0, 0, text_width, text_height)

        text_width = bbox[2] - bbox[0]
        text_height = bbox[3] - bbox[1]
        x = (width - text_width) / 2
        y = (height - text_height) / 2 - (height * 0.05)

        draw.text((x, y), ICON_TEXT, fill="white", font=font, anchor="lt") # Thử anchor='lt'

        return image

    def load_settings(self):
        # ... (Giữ nguyên, đảm bảo đọc login_delay_seconds là float) ...
        print("Loading settings...")
        try:
            self.config.read(CONFIG_FILE, encoding='utf-8')

            self.font_family_var.set(self.config.get('Appearance', 'font_family', fallback=DEFAULT_FONT_FAMILY))
            self.font_size_var.set(self.config.getint('Appearance', 'font_size', fallback=DEFAULT_FONT_SIZE))
            self.theme_var.set(self.config.get('Appearance', 'theme', fallback=DEFAULT_THEME))

            self.tlp_file_path_var.set(self.config.get('VPN', 'tlp_path', fallback=DEFAULT_TLP_FILE_PATH))

            self.proxy_ip_var.set(self.config.get('Proxy', 'ip', fallback="127.0.0.1"))
            self.proxy_port_var.set(self.config.get('Proxy', 'port', fallback="9999"))

            self.ip_check_interval_min_var.set(self.config.getint('General', 'ip_check_interval_minutes', fallback=DEFAULT_IP_CHECK_INTERVAL_MIN))

            # Đọc giá trị delay là float
            self.login_delay_seconds_var.set(self.config.getfloat('Automation', 'login_delay_seconds', fallback=DEFAULT_LOGIN_DELAY_SECONDS))

            print(f"Settings loaded. Theme: {self.theme_var.get()}, Login Delay: {self.login_delay_seconds_var.get()}s")

        except Exception as e:
            print(f"Error loading settings from {CONFIG_FILE}: {e}. Using defaults.")
            # Apply defaults explicitly
            self.font_family_var.set(DEFAULT_FONT_FAMILY)
            self.font_size_var.set(DEFAULT_FONT_SIZE)
            self.theme_var.set(DEFAULT_THEME)
            self.tlp_file_path_var.set(DEFAULT_TLP_FILE_PATH)
            self.proxy_ip_var.set("127.0.0.1")
            self.proxy_port_var.set("9999")
            self.ip_check_interval_min_var.set(DEFAULT_IP_CHECK_INTERVAL_MIN)
            self.login_delay_seconds_var.set(DEFAULT_LOGIN_DELAY_SECONDS) # Đặt lại giá trị mặc định (float)

    def save_settings(self):
        # ... (Giữ nguyên, đảm bảo lưu login_delay_seconds là float) ...
        print("Saving settings...")
        try:
            if not self.config.has_section('Appearance'): self.config.add_section('Appearance')
            if not self.config.has_section('VPN'): self.config.add_section('VPN')
            if not self.config.has_section('Proxy'): self.config.add_section('Proxy')
            if not self.config.has_section('General'): self.config.add_section('General')
            if not self.config.has_section('Automation'): self.config.add_section('Automation')

            self.config.set('Appearance', 'font_family', self.font_family_var.get())
            self.config.set('Appearance', 'font_size', str(self.font_size_var.get()))
            self.config.set('Appearance', 'theme', self.theme_var.get())
            self.config.set('VPN', 'tlp_path', self.tlp_file_path_var.get())
            self.config.set('Proxy', 'ip', self.proxy_ip_var.get())
            self.config.set('Proxy', 'port', self.proxy_port_var.get())
            self.config.set('General', 'ip_check_interval_minutes', str(self.ip_check_interval_min_var.get()))
            # Lưu giá trị delay là float, định dạng nếu cần
            self.config.set('Automation', 'login_delay_seconds', f"{self.login_delay_seconds_var.get():.1f}") # Lưu 1 chữ số thập phân

            with open(CONFIG_FILE, 'w', encoding='utf-8') as cf:
                self.config.write(cf)
            print("Settings saved.")
        except Exception as e:
            print(f"Error saving settings: {e}")
            if self.settings_window and self.settings_window.winfo_exists():
                 messagebox.showerror("Save Error", f"Failed to save settings:\n{e}", parent=self.settings_window)

    def set_windows_proxy(self, enable=True):
        # ... (Giữ nguyên logic set proxy) ...
        if not WINDOWS_PROXY_AVAILABLE:
            print("Proxy setting unavailable.")
            return False

        proxy_ip = self.proxy_ip_var.get().strip()
        proxy_port_str = self.proxy_port_var.get().strip()

        if enable and (not proxy_ip or not proxy_port_str):
            print("Proxy IP or Port missing in settings.")
            # Không hiển thị messagebox khi đang tự động chạy, chỉ in log
            # messagebox.showerror("Proxy Error", "Proxy IP or Port missing.", parent=get_hidden_root())
            return False

        if enable:
            try:
                proxy_port = int(proxy_port_str)
                if not (0 < proxy_port < 65536): raise ValueError("Port out of range")
                proxy_server_reg = f"{proxy_ip}:{proxy_port}"
                proxy_enable_value = 1
                print(f"Setting Windows proxy ENABLED (Server: {proxy_server_reg})")
            except ValueError as e:
                print(f"Invalid Proxy Port: {e}")
                # messagebox.showerror("Proxy Error", f"Invalid Proxy Port: {e}", parent=get_hidden_root())
                return False
        else:
            proxy_server_reg = ""
            proxy_enable_value = 0
            print("Setting Windows proxy DISABLED.")

        try:
            key_path = r"Software\Microsoft\Windows\CurrentVersion\Internet Settings"
            # Sử dụng with để đảm bảo key được đóng
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, key_path, 0, winreg.KEY_WRITE) as key:
                winreg.SetValueEx(key, "ProxyEnable", 0, winreg.REG_DWORD, proxy_enable_value)
                if enable:
                    winreg.SetValueEx(key, "ProxyServer", 0, winreg.REG_SZ, proxy_server_reg)
                else:
                     try: winreg.DeleteValue(key, "ProxyServer")
                     except FileNotFoundError: pass
                override_str = "<local>" # Giữ override cho local
                winreg.SetValueEx(key, "ProxyOverride", 0, winreg.REG_SZ, override_str)
            print("Registry updated.")

            # Notify system
            success_notify = internet_set_option(None, INTERNET_OPTION_SETTINGS_CHANGED, None, 0)
            success_refresh = internet_set_option(None, INTERNET_OPTION_REFRESH, None, 0)
            if success_notify and success_refresh:
                print("Internet settings change notification sent.")
            else:
                print("Warning: Failed to send Internet settings change notification.")
            return True

        except PermissionError:
             print("ERROR: Permission denied writing to registry. Run as Administrator?")
             # messagebox.showerror("Registry Error", "Permission denied writing to registry.", parent=get_hidden_root())
             return False
        except Exception as e:
            print(f"Error setting proxy via Registry: {e}")
            # messagebox.showerror("Proxy Error", f"Failed to set proxy via Registry:\n{e}", parent=get_hidden_root())
            return False

    # --- VPN Start/Stop Logic ---
    def start_vpn_sequence(self):
        # ... (Cập nhật để reset event _auto_login_finished_event) ...
        if self.vpn_status.get():
            print("VPN already running or starting.")
            return

        print("Starting VPN sequence...")
        self.vpn_status.set(True) # Đặt trạng thái đang chạy ngay lập tức để tránh gọi lại
        self.vpn_status_text_var.set("Initializing...")

        tlp_path = self.tlp_file_path_var.get()
        if not os.path.exists(tlp_path):
            print(f"TLP file not found: {tlp_path}")
            messagebox.showerror("Error", f"Bitvise profile not found:\n{tlp_path}", parent=get_hidden_root())
            self.request_exit()
            return

        # Reset auto-login finished signal
        self._auto_login_finished_event.clear()

        # 1. Set Proxy
        if not self.set_windows_proxy(enable=True):
            print("Failed to set proxy. Aborting startup.")
            self.vpn_status.set(False)
            self.vpn_status_text_var.set("Proxy Failed")
            self.request_exit() # Thoát nếu không set được proxy khi khởi động
            return

        # 2. Launch Bitvise
        try:
            print(f"Opening TLP profile: {tlp_path}")
            os.startfile(tlp_path)
            self.vpn_status_text_var.set("Connecting...")
            print("TLP launched.")

            # Chờ và kiểm tra process
            time.sleep(0.5) # Giảm nhẹ thời gian chờ ban đầu
            is_running, self._bvssh_pid = is_process_running(BVSSH_PROCESS_NAME)

            if not is_running or self._bvssh_pid is None:
                print("Warning: Bitvise process not detected shortly after launch. Will proceed.")
                # messagebox.showwarning("Warning", f"Couldn't confirm {BVSSH_PROCESS_NAME} running.", parent=get_hidden_root())
                self._bvssh_pid = None # Đảm bảo PID là None nếu không tìm thấy
            else:
                 print(f"Bitvise process detected (PID: {self._bvssh_pid}).")

            # 3. Start Background Update Thread
            self.start_update_thread()

            # 4. Attempt Auto-Login
            if self._bvssh_pid and PYWINAUTO_AVAILABLE:
                self.start_auto_login_thread()
            elif not PYWINAUTO_AVAILABLE:
                 print("Auto-login skipped: pywinauto not available.")
                 self._auto_login_finished_event.set() # Cho phép check IP nếu không có auto-login
            else:
                 print("Auto-login skipped: Bitvise PID not confirmed.")
                 self._auto_login_finished_event.set() # Cho phép check IP nếu không có auto-login

        except Exception as e:
            print(f"Error launching Bitvise: {e}")
            messagebox.showerror("Error", f"Failed to launch Bitvise:\n{e}", parent=get_hidden_root())
            self.set_windows_proxy(enable=False) # Hoàn tác proxy
            self.vpn_status.set(False)
            self.vpn_status_text_var.set("Launch Failed")
            self.request_exit() # Thoát

    def stop_vpn_sequence(self):
        # --- GIỮ NGUYÊN PHIÊN BẢN ĐÃ SỬA VỚI os._exit(0) ---
        if self._is_exiting: return
        self._is_exiting = True
        print("Stopping VPN sequence...")

        self._stop_event.set()

        print("Attempting to terminate Bitvise...")
        if not terminate_process(BVSSH_PROCESS_NAME):
            print("Warning: Failed to terminate Bitvise process automatically.")

        print("Attempting to disable proxy...")
        if not self.set_windows_proxy(enable=False):
            print("Warning: Failed to disable proxy automatically.")

        self.vpn_status.set(False) # Cập nhật trạng thái trực quan

        threads_to_join = []
        if self._update_thread and self._update_thread.is_alive(): threads_to_join.append(self._update_thread)
        if self._auto_login_thread and self._auto_login_thread.is_alive(): threads_to_join.append(self._auto_login_thread)

        if threads_to_join:
            print(f"Waiting briefly for {len(threads_to_join)} background thread(s)...")
            for t in threads_to_join:
                try: t.join(timeout=0.5)
                except Exception as join_err: print(f"Ignoring error joining thread {t.name}: {join_err}")

        print("Background thread cleanup attempted.")

        global hidden_root
        if hidden_root and hidden_root.winfo_exists():
            print("Requesting Tkinter mainloop quit...")
            try: hidden_root.quit()
            except Exception as e_quit: print(f"Ignoring error during Tk root quit: {e_quit}")

        if self.tray_icon:
             print("Stopping tray icon...")
             try: self.tray_icon.stop()
             except Exception as e_tray_stop: print(f"Ignoring error during tray icon stop: {e_tray_stop}")

        print("Forcing process exit using os._exit(0)...")
        os._exit(0)
        print("!!! This line should NOT be printed if os._exit worked !!!")

    # --- Threading ---
    def start_update_thread(self):
        # ... (Giữ nguyên) ...
        if self._update_thread and self._update_thread.is_alive():
            print("Update thread already running.")
            return
        self._stop_event.clear()
        self.elapsed_seconds = 0
        self.initial_net_io = None
        self.last_net_io = None
        self.last_net_time = None
        # Không gọi fetch_public_ip() ở đây nữa, chờ tín hiệu từ auto-login

        self._update_thread = threading.Thread(target=self._update_loop, name="UpdateThread", daemon=True)
        self._update_thread.start()
        print("Update thread started.")


    def _update_loop(self):
        # --- GIỮ NGUYÊN PHIÊN BẢN ĐÃ SỬA VỚI _auto_login_finished_event ---
        print("Update loop running...")
        ip_check_timer = 0
        # Đọc interval ban đầu, sẽ cập nhật nếu thay đổi
        ip_check_interval_sec = self.ip_check_interval_min_var.get() * 60
        first_ip_check_done_after_login = False # Cờ kiểm tra IP lần đầu

        while not self._stop_event.is_set():
            now = time.time()

            # --- Update Timer ---
            self.elapsed_seconds += 1
            hours, rem = divmod(self.elapsed_seconds, 3600)
            mins, secs = divmod(rem, 60)
            self.vpn_timer_var_info.set(f"{hours:02}:{mins:02}:{secs:02}")

            # --- Update Network Stats ---
            try:
                current_io = psutil.net_io_counters()
                current_time = time.time()
                if self.initial_net_io is None: self.initial_net_io = current_io

                # Speed Calculation
                if self.last_net_io and self.last_net_time:
                    time_diff = current_time - self.last_net_time
                    if time_diff > 0.1: # Ngưỡng tránh chia cho 0 hoặc số quá nhỏ
                        sent_diff = current_io.bytes_sent - self.last_net_io.bytes_sent
                        recv_diff = current_io.bytes_recv - self.last_net_io.bytes_recv
                        # Đảm bảo không âm (có thể xảy ra khi bộ đếm reset?)
                        up_speed = max(0, sent_diff) / time_diff
                        down_speed = max(0, recv_diff) / time_diff
                        self.network_speed_var_info.set(f"Down: {format_speed(down_speed)} / Up: {format_speed(up_speed)}")
                else:
                     self.network_speed_var_info.set("Down: Init... / Up: Init...")

                # Total Data Calculation
                total_down = current_io.bytes_recv - self.initial_net_io.bytes_recv
                total_up = current_io.bytes_sent - self.initial_net_io.bytes_sent
                self.total_download_var_info.set(f"Total Down: {format_total_data(total_down)}")
                self.total_upload_var_info.set(f"Total Up: {format_total_data(total_up)}")

                self.last_net_io = current_io
                self.last_net_time = current_time

                # Update Status Text
                if self.elapsed_seconds > 5: # Cho thời gian ổn định
                    if self.vpn_status_text_var.get() == "Connecting...": # Chỉ cập nhật nếu đang connecting
                       # Heuristic đơn giản: có tốc độ down > 0 coi như connected
                       if down_speed > 10: # Cần tốc độ nhỏ để xác nhận
                           self.vpn_status_text_var.set("Connected")
                       elif self.elapsed_seconds > 20: # Sau 20s vẫn connecting ->疑 vấn
                            self.vpn_status_text_var.set("Connected (No Traffic?)")


            except (psutil.NoSuchProcess, psutil.AccessDenied):
                # Bỏ qua lỗi nếu process mạng không còn
                 self.network_speed_var_info.set("Down: N/A / Up: N/A")
            except Exception as e:
                print(f"Error updating network stats: {e}")
                self.network_speed_var_info.set("Down: Error / Up: Error")

            # --- Check Public IP Periodically (AFTER Auto-Login Attempt) ---
            if self._auto_login_finished_event.is_set():
                current_interval_sec = self.ip_check_interval_min_var.get() * 60

                if not first_ip_check_done_after_login:
                    print("Auto-login finished signal received. Performing initial IP check.")
                    self.fetch_public_ip()
                    first_ip_check_done_after_login = True
                    ip_check_timer = 0 # Reset

                elif current_interval_sec > 0:
                    ip_check_timer += 1
                    if ip_check_timer >= current_interval_sec:
                        print("Performing scheduled IP check...")
                        self.fetch_public_ip()
                        ip_check_timer = 0
                    # Cập nhật interval nếu thay đổi
                    elif current_interval_sec != ip_check_interval_sec:
                         ip_check_interval_sec = current_interval_sec
                         ip_check_timer = 0 # Reset timer on change

            # --- Sleep ---
            sleep_duration = 0.5 # Tần suất cập nhật chung (giây)
            # Kiểm tra stop event thường xuyên hơn
            for _ in range(int(sleep_duration / 0.1)): # Check mỗi 100ms
                if self._stop_event.is_set():
                    break
                time.sleep(0.1)
            if self._stop_event.is_set():
                 break # Thoát vòng lặp chính

        print("Update loop finished.")


    def fetch_public_ip(self):
        # ... (Giữ nguyên) ...
        print("Fetching public IP...")
        self.ip_address_var_info.set("IP: Checking...")
        try:
            response = requests.get(IPIFY_URL, timeout=10) # Tăng nhẹ timeout
            response.raise_for_status()
            ip = response.json().get("ip")
            if ip:
                self.ip_address_var_info.set(f"IP: {ip}")
                print(f"Public IP: {ip}")
            else:
                self.ip_address_var_info.set("IP: Format Error")
                print("IP Check: IP not found in response.")
        except requests.exceptions.Timeout:
            self.ip_address_var_info.set("IP: Timeout")
            print("IP Check: Timeout")
        except requests.exceptions.RequestException as e:
            self.ip_address_var_info.set("IP: Network Error")
            # In lỗi chi tiết hơn
            print(f"IP Check: Network Error - {e}")
        except Exception as e:
            self.ip_address_var_info.set("IP: Error")
            print(f"IP Check: Unexpected Error - {e}")


    def reschedule_ip_check(self):
        # ... (Giữ nguyên) ...
        print("IP check interval potentially updated by settings change.")
        # Logic cập nhật interval đã được tích hợp trong _update_loop

    def start_auto_login_thread(self):
        # ... (Giữ nguyên) ...
        if not PYWINAUTO_AVAILABLE or not self._bvssh_pid:
            print("Cannot start auto-login: pywinauto unavailable or PID missing.")
            self._auto_login_finished_event.set() # Báo hiệu để check IP có thể bắt đầu
            return
        if self._auto_login_thread and self._auto_login_thread.is_alive():
            print("Auto-login thread already running.")
            return

        # self._auto_login_finished_event đã được clear trong start_vpn_sequence
        self._auto_login_thread = threading.Thread(target=self._auto_login_task,
                                                   args=(self._bvssh_pid,),
                                                   name="AutoLoginThread",
                                                   daemon=True)
        self._auto_login_thread.start()
        print("Auto-login thread started.")

    def _auto_login_task(self, pid_to_watch):
        # --- GIỮ NGUYÊN PHIÊN BẢN ĐÃ SỬA VỚI _auto_login_finished_event.set() trong finally ---
        if not PYWINAUTO_AVAILABLE: return

        # Lấy giá trị delay là float
        delay_sec = self.login_delay_seconds_var.get()
        print(f"Auto-login task: Waiting {delay_sec:.1f} seconds...") # Định dạng hiển thị

        wait_start_time = time.time()
        while time.time() - wait_start_time < delay_sec:
            if self._stop_event.is_set():
                print("Auto-login cancelled during initial wait.")
                self._auto_login_finished_event.set() # Vẫn báo hiệu hoàn tất nếu bị hủy
                return
            time.sleep(0.1) # Check thường xuyên hơn

        if self._stop_event.is_set():
            print("Auto-login cancelled before execution.")
            self._auto_login_finished_event.set() # Vẫn báo hiệu
            return

        print(f"Auto-login task: Attempting automation for PID {pid_to_watch}...")
        app = None # Khởi tạo để kiểm tra trong finally
        try:
            # --- Stage 1: Connect and Click Login ---
            print("Connecting to Bitvise process via pywinauto...")
            app = Application(backend="uia").connect(process=pid_to_watch, timeout=30)
            print("Finding initial Bitvise window...")
            login_window = app.window(title_re="Bitvise SSH Client.*", top_level_only=True)
            login_window.wait('visible', timeout=25)
            print(f"Login window found: '{login_window.window_text()}'")

            print("Finding 'Log in' button...")
            login_button = login_window.child_window(title="Log in", control_type="Button")
            login_button.wait('enabled', timeout=20)
            print("Button 'Log in' found and enabled.")

            if self._stop_event.is_set():
                print("Auto-login cancelled just before clicking.")
                # Không return ở đây, để finally chạy và set event
            else:
                print("Clicking 'Log in' button...")
                login_button.click_input()
                print("'Log in' clicked.")

                # --- Stage 2: Find and Minimize ---
                minimize_wait_sec = 0.5 # Thời gian chờ sau khi click login
                print(f"Waiting {minimize_wait_sec:.1f} seconds before attempting minimize...")
                wait_start_time = time.time()
                while time.time() - wait_start_time < minimize_wait_sec:
                    if self._stop_event.is_set(): break # Thoát chờ nếu có tín hiệu dừng
                    time.sleep(0.1)

                if self._stop_event.is_set():
                    print("Minimize attempt cancelled during wait.")
                else:
                    print("Attempting to find and minimize Bitvise window...")
                    try:
                        # Không cần connect lại nếu app object vẫn hợp lệ
                        # app_after = Application(backend="uia").connect(process=pid_to_watch, timeout=15)
                        all_top_windows = app.windows(top_level_only=True) # Dùng lại app object
                        suitable_windows = []
                        print(f"Found {len(all_top_windows)} top-level windows. Filtering...")
                        for win in all_top_windows:
                            try:
                                if win.is_visible() and win.is_enabled(): suitable_windows.append(win)
                            except Exception: pass # Bỏ qua lỗi khi kiểm tra cửa sổ

                        if not suitable_windows:
                            print("Minimize Warning: No suitable window found after login.")
                        else:
                            main_window = suitable_windows[0]
                            print(f"Found window to minimize: '{main_window.window_text()}'")
                            if not main_window.is_minimized():
                                main_window.minimize()
                                print("Minimize command sent.")
                            else:
                                print("Window already minimized.")

                    except ProcessNotFoundError: print("Minimize Warning: Bitvise process disappeared.")
                    except ElementNotFoundError: print("Minimize Warning: Could not find window element.")
                    except Exception as min_e:
                         print(f"Minimize Warning: Error during minimize: {min_e}")
                         # traceback.print_exc() # Bỏ comment nếu cần debug sâu

        except ProcessNotFoundError:
             print(f"Auto-login Error: Bitvise process (PID: {pid_to_watch}) not found.")
             # Không cần messagebox ở đây, log là đủ
        except ElementNotFoundError:
             print("Auto-login Error: Could not find Bitvise window or 'Log in' button.")
        except Exception as e_auto:
             print(f"Auto-login Error: Unexpected error: {e_auto}")
             # traceback.print_exc() # Bỏ comment nếu cần debug sâu
        finally:
             # --- LUÔN SET EVENT KHI TASK KẾT THÚC ---
             print("Signaling that auto-login attempt is complete.")
             self._auto_login_finished_event.set()
             # Ngắt kết nối pywinauto nếu được tạo
             if app:
                 try: app.disconnect()
                 except Exception: pass
             print("Auto-login task finished.")

    # --- Tray Icon Callbacks ---
    def show_info_window(self):
        # ... (Giữ nguyên) ...
        if self.info_window and self.info_window.winfo_exists():
            print("Info window already open. Bringing to front.")
            self.info_window.lift()
            self.info_window.focus_force()
        else:
            print("Creating Info window...")
            # Đảm bảo có root trước khi tạo Toplevel
            root = get_hidden_root()
            if root and root.winfo_exists():
                self.info_window = InfoWindow(root, self)
                self.info_window.lift()
            else:
                print("Error: Cannot create Info window, hidden root missing.")

    def show_settings_window(self):
        # ... (Giữ nguyên) ...
        if self.settings_window and self.settings_window.winfo_exists():
            print("Settings window already open. Bringing to front.")
            self.settings_window.lift()
            self.settings_window.focus_force()
        else:
            print("Creating Settings window...")
            root = get_hidden_root()
            if root and root.winfo_exists():
                self.settings_window = SettingsWindow(root, self)
                self.settings_window.lift()
            else:
                 print("Error: Cannot create Settings window, hidden root missing.")

    def request_exit(self):
        # ... (Giữ nguyên) ...
        print("Exit requested from menu.")
        self.stop_vpn_sequence() # Gọi hàm xử lý thoát

    # --- Main Execution Method ---
    def run(self):
        # ... (Giữ nguyên) ...
        if not PYSTRAY_AVAILABLE: return # Đã xử lý ở __main__

        icon_image = self.create_icon_image()
        if icon_image is None: return # Đã xử lý ở create_icon_image

        menu = TrayMenu(
            TrayMenuItem('Show Info', self.show_info_window, default=True),
            TrayMenuItem('Settings', self.show_settings_window),
            TrayMenu.SEPARATOR,
            TrayMenuItem('Exit', self.request_exit)
        )

        self.tray_icon = TrayIcon(
            APP_TITLE,
            icon=icon_image,
            title=APP_TITLE,
            menu=menu
        )

        # Bắt đầu trình tự VPN *trước* khi chạy vòng lặp icon/tk
        self.start_vpn_sequence()

        # Chạy pystray tách rời và bắt đầu vòng lặp Tkinter
        print("Starting pystray icon loop (detached)...")
        self.tray_icon.run_detached()
        print("Starting hidden Tkinter mainloop...")
        try:
            get_hidden_root().mainloop()
            print("Tkinter mainloop finished normally.") # Sẽ chạy nếu root.quit() được gọi
        except Exception as tk_loop_err:
             print(f"Error in Tkinter mainloop: {tk_loop_err}")
             # Vẫn cố gắng thoát bằng os._exit nếu mainloop lỗi
             if not self._is_exiting:
                 self.request_exit()


# --- Main Execution ---
if __name__ == '__main__':
    # --- GIỮ NGUYÊN PHIÊN BẢN ĐÃ SỬA CUỐI CÙNG ---
    # Đã bao gồm import os, ctypes, tk, messagebox
    # Đã bao gồm kiểm tra thư viện, quyền admin
    # Đã bao gồm khối try/except quanh việc tạo và chạy app
    # Đã bao gồm xử lý SystemExit và Exception
    # Đã bao gồm logic cleanup khi có lỗi
    # KHÔNG có lệnh exit ở cuối cùng

    print(f"Starting {APP_TITLE}...")

    if not PYSTRAY_AVAILABLE:
        print("\nFATAL: 'pystray' library is required...")
        # ... (Code hiển thị lỗi và os._exit(1)) ...
        try: root = tk.Tk(); root.withdraw(); messagebox.showerror("Missing Library", "pystray not found!"); root.destroy()
        except: pass
        os._exit(1)

    if not PIL_AVAILABLE:
        print("\nWARNING: 'Pillow' library not found...")
        # ... (Không thoát ở đây) ...

    if not PYWINAUTO_AVAILABLE:
        print("\nWARNING: 'pywinauto' not found...")
        # ... (Không thoát ở đây) ...

    if sys.platform == 'win32':
        # ... (Code kiểm tra quyền admin) ...
        try: is_admin = ctypes.windll.shell32.IsUserAnAdmin() != 0
        except Exception as admin_check_err: is_admin = False; print(f"Admin check warning: {admin_check_err}")
        if is_admin: print("INFO: Running with Admin privileges.")
        else: print("INFO: Running without Admin privileges.")

    app_controller = None
    try:
        print("Initializing application controller...")
        app_controller = TrayVpnApp()
        print("Running application...")
        app_controller.run()
        print("Application run method has exited.")

    except SystemExit as se:
        print(f"Process exiting with code: {se.code}")

    except Exception as e:
        print(f"\n--- FATAL APPLICATION ERROR ---")
        import traceback
        traceback.print_exc()
        print(f"Error: {e}")
        print("---------------------------------\n")
        try:
             root_err = tk.Tk(); root_err.withdraw(); messagebox.showerror("Fatal Error", f"Critical error:\n{e}"); root_err.destroy()
        except Exception as msg_err: print(f"CRITICAL: Could not display error message: {msg_err}")

        if app_controller and hasattr(app_controller, '_is_exiting') and not app_controller._is_exiting:
             print("Attempting cleanup after error...")
             try: app_controller.request_exit()
             except SystemExit: print("Cleanup initiated exit.")
             except Exception as final_exit_err: print(f"Cleanup error: {final_exit_err}"); os._exit(1)
        else:
             print("Exiting immediately due to error.")
             os._exit(1)

    print("Main script execution scope finished (likely bypassed by os._exit).")
    # KHÔNG CÓ LỆNH EXIT Ở ĐÂY.