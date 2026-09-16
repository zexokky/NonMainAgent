# -*- coding: utf-8 -*-
"""GUI на CustomTkinter для агента NonMainAI."""
import customtkinter as ctk
import threading, queue, time, sys, os, json, tkinter as tk
from pathlib import Path
from agent_core import AgentCore, MODEL, WORKDIR, MAX_HISTORY


def _set_app_user_model_id():
    if os.name != "nt":
        return
    try:
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            "zexokky.nonmainai.1")
    except Exception:
        pass


_set_app_user_model_id()

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")


THEMES = {
    "dark": {
        "name": "Тёмная", "icon": "◐",
        "bg_dark":  "#18181c", "bg_mid": "#1e1e24", "bg_light": "#28282f",
        "bg_hover": "#33333c", "border": "#2a2a32",
        "text":     "#e8e8ee", "text_dim": "#8a8a95",
        "accent":   "#e878c0", "accent2": "#a86ad0", "send_text": "#1a1a1f",
    },
    "black": {
        "name": "Чёрная", "icon": "●",
        "bg_dark":  "#000000", "bg_mid": "#050507", "bg_light": "#101013",
        "bg_hover": "#1a1a1e", "border": "#15151a",
        "text":     "#d0d0d0", "text_dim": "#5a5a60",
        "accent":   "#e878c0", "accent2": "#a86ad0", "send_text": "#000000",
    },
    "light": {
        "name": "Светлая", "icon": "○",
        "bg_dark":  "#f4f4f8", "bg_mid": "#ebebf0", "bg_light": "#dcdce4",
        "bg_hover": "#c8c8d2", "border": "#d0d0d8",
        "text":     "#1a1a1f", "text_dim": "#6a6a75",
        "accent":   "#c850a0", "accent2": "#7a4a90", "send_text": "#ffffff",
    },
}

GREEN        = "#7ec87e"
GREEN_BRIGHT = "#a8f0a8"
YELLOW       = "#e8c87e"
RED          = "#e87e7e"
CYAN         = "#7ec8e8"

SPLASH_KEY_COLOR = "#fe01fe"

THEME_FILE = WORKDIR / "agent_theme.json"


def _load_saved_theme():
    try:
        if THEME_FILE.exists():
            data = json.loads(THEME_FILE.read_text(encoding="utf-8"))
            t = data.get("theme", "dark")
            if t in THEMES:
                return t
    except Exception:
        pass
    return "dark"


def _save_theme(name):
    try:
        THEME_FILE.write_text(
            json.dumps({"theme": name}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


def _find_icon():
    """Ищет Icon.ico: сначала во временной папке PyInstaller (_MEIPASS),
    потом рядом со скриптом/exe, потом в WORKDIR и cwd."""
    names = ["Icon.ico", "icon.ico", "ICON.ICO"]
    dirs = []

    # 1) если запущено из PyInstaller-бандла
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            dirs.append(Path(meipass))
        # рядом с exe
        dirs.append(Path(sys.executable).parent)

    # 2) обычные места
    try:
        dirs.append(Path(__file__).parent)
    except NameError:
        pass
    dirs.append(WORKDIR)
    dirs.append(Path.cwd())
    try:
        dirs.append(Path(__file__).parent.parent)
    except NameError:
        pass

    for d in dirs:
        for n in names:
            p = d / n
            try:
                if p.exists() and p.is_file():
                    return p
            except Exception:
                continue
    return None


ICON_PATH = _find_icon()


class AgentGUI(ctk.CTk):
    def __init__(self):
        super().__init__()

        self.withdraw()

        self.title("NonMainAI - by zexokky")
        self.geometry("1100x760")
        self.minsize(760, 500)

        self._icon_ctk = None
        self._icon_ctk_big = None
        self._icon_photo = None
        self._set_window_icon()

        self.theme_name = _load_saved_theme()
        self.theme = THEMES[self.theme_name]
        self._themed = []

        self.events = queue.Queue()
        self.confirm_event = threading.Event()
        self.confirm_result = None

        self.logs_window = None
        self.logs_text = None
        self.actions_popup = None
        self.ctx_popup = None  # кастомное контекстное меню
        self.log_buffer = []

        self._pulse_state = 0
        self._gen_dots = 0
        self._is_generating = False

        self.splash = None
        self.splash_canvas = None
        self._spin_arc = None
        self._spin_angle = 0
        self._spin_job = None
        self._inet_started = 0.0

        self._menu_just_opened = False
        self._global_click_bound = False

        self.core = AgentCore(
            log_fn=self._cb_log,
            token_fn=self._cb_token,
            step_fn=self._cb_step,
            answer_fn=self._cb_answer,
            confirm_fn=self._cb_confirm,
            status_fn=self._cb_status,
        )

        self._build_ui()
        self._load_history_to_chat()

        self.after(50, self._poll_events)
        self.after(150, self._start_background)
        self.after(300, self._animate_tick)
        self.after(100, self._run_splash)

    # ============ ИКОНКА ============
    def _set_window_icon(self):
        if not ICON_PATH:
            print("[icon] Icon.ico не найден")
            return
        print(f"[icon] найден: {ICON_PATH}")

        def apply_iconbitmap():
            try:
                self.iconbitmap(default=str(ICON_PATH))
            except Exception:
                try:
                    self.iconbitmap(str(ICON_PATH))
                except Exception as e:
                    print(f"[icon] iconbitmap ошибка: {e}")

        apply_iconbitmap()
        self.after(100, apply_iconbitmap)
        self.after(500, apply_iconbitmap)

        try:
            from PIL import Image, ImageTk
            img = Image.open(str(ICON_PATH)).convert("RGBA")
            self._icon_photo = ImageTk.PhotoImage(img)
            try:
                self.wm_iconphoto(True, self._icon_photo)
            except Exception:
                self.wm_iconphoto(self._icon_photo)
        except Exception as e:
            print(f"[icon] iconphoto ошибка: {e}")

        try:
            from PIL import Image
            img = Image.open(str(ICON_PATH))
            self._icon_ctk = ctk.CTkImage(
                light_image=img, dark_image=img, size=(28, 28))
        except Exception:
            self._icon_ctk = None

        try:
            from PIL import Image
            img = Image.open(str(ICON_PATH))
            self._icon_ctk_big = ctk.CTkImage(
                light_image=img, dark_image=img, size=(190, 190))
        except Exception:
            self._icon_ctk_big = None

    # ============ SPLASH ============
    def _build_splash_card(self, greeting_mode=False):
        if not self.splash or not self.splash.winfo_exists():
            return

        t = self.theme

        for w in self.splash.winfo_children():
            try: w.destroy()
            except Exception: pass

        card = ctk.CTkFrame(
            self.splash,
            fg_color=t["bg_dark"],
            corner_radius=48,
            border_width=1,
            border_color=t["border"],
        )
        card.pack(fill="both", expand=True, padx=4, pady=4)

        if greeting_mode:
            if self._icon_ctk_big is not None:
                logo = ctk.CTkLabel(card, text="", image=self._icon_ctk_big)
                logo.pack(pady=(40, 14))

            user = (os.environ.get("USERNAME")
                    or os.environ.get("USER")
                    or Path.home().name
                    or "хозяин")

            greet = ctk.CTkLabel(
                card,
                text=f"Приветствую {user},\nхорошего дня!",
                font=ctk.CTkFont(size=26, weight="bold"),
                text_color=t["accent"],
                justify="center",
            )
            greet.pack(expand=True, pady=(0, 26))
        else:
            if self._icon_ctk_big is not None:
                logo = ctk.CTkLabel(card, text="", image=self._icon_ctk_big)
                logo.pack(pady=(54, 6))
            else:
                logo = ctk.CTkLabel(card, text="✿",
                                    font=ctk.CTkFont(size=110, weight="bold"),
                                    text_color=t["accent"])
                logo.pack(pady=(54, 6))

            # НАДПИСЬ "NonMainAI" УБРАНА — она уже на логотипе
            by = ctk.CTkLabel(card, text="by zexokky",
                              font=ctk.CTkFont(size=13),
                              text_color=t["text_dim"])
            by.pack(pady=(4, 22))

            self.splash_canvas = tk.Canvas(
                card, width=58, height=58,
                bg=t["bg_dark"], highlightthickness=0, bd=0)
            self.splash_canvas.pack()

            self.splash_canvas.create_oval(8, 8, 50, 50,
                                           outline=t["bg_light"], width=3)
            self._spin_arc = self.splash_canvas.create_arc(
                8, 8, 50, 50, start=0, extent=90,
                style="arc", width=3, outline=t["accent"])

            status = ctk.CTkLabel(card, text="проверяю соединение...",
                                  font=ctk.CTkFont(size=11),
                                  text_color=t["text_dim"])
            status.pack(pady=(8, 0))

            self._spin_angle = 0
            if self._spin_job:
                try: self.after_cancel(self._spin_job)
                except Exception: pass
            self._spin_tick()

    def _run_splash(self):
        W, H = 620, 440
        splash = tk.Toplevel(self)
        splash.overrideredirect(True)
        splash.configure(bg=SPLASH_KEY_COLOR)
        try:
            splash.attributes("-transparentcolor", SPLASH_KEY_COLOR)
        except Exception as e:
            print(f"[splash] transparentcolor недоступен: {e}")
        splash.attributes("-topmost", True)
        splash.attributes("-alpha", 0.0)

        sw = splash.winfo_screenwidth()
        sh = splash.winfo_screenheight()
        x = (sw - W) // 2
        y = (sh - H) // 2
        splash.geometry(f"{W}x{H}+{x}+{y}")

        self.splash = splash
        self._build_splash_card(greeting_mode=False)
        self._fade(splash, 0.0, 1.0, 340, on_done=self._start_inet_check)

    def _spin_tick(self):
        if not self.splash or not self.splash.winfo_exists():
            return
        if not self.splash_canvas or not self.splash_canvas.winfo_exists():
            return
        try:
            self._spin_angle = (self._spin_angle - 14) % 360
            self.splash_canvas.itemconfig(self._spin_arc,
                                          start=self._spin_angle)
        except Exception:
            return
        self._spin_job = self.after(35, self._spin_tick)

    def _start_inet_check(self):
        self._inet_started = time.time()

        def worker():
            online = False
            try:
                online = self.core.is_online(force=True)
            except Exception:
                online = False
            self.after(0, lambda: self._on_inet_checked(online))

        threading.Thread(target=worker, daemon=True).start()

    def _on_inet_checked(self, online):
        elapsed = time.time() - self._inet_started
        wait_ms = int(max(0.0, 1.5 - elapsed) * 1000)

        def after_min_time():
            self._stop_spin()
            self._show_greeting(online)

        self.after(wait_ms, after_min_time)

    def _stop_spin(self):
        if self._spin_job:
            try: self.after_cancel(self._spin_job)
            except Exception: pass
            self._spin_job = None

    def _show_greeting(self, online):
        if not self.splash or not self.splash.winfo_exists():
            return

        def swap_content():
            if not self.splash or not self.splash.winfo_exists():
                return
            self._build_splash_card(greeting_mode=True)
            self.splash.attributes("-alpha", 0.0)
            self._fade(self.splash, 0.0, 1.0, 340,
                       on_done=lambda: self.after(2000, self._finish_splash))

        self._fade(self.splash, 1.0, 0.0, 320, on_done=swap_content)

    def _finish_splash(self):
        if not self.splash or not self.splash.winfo_exists():
            self._show_main_window()
            return

        def destroy_splash():
            try:
                if self.splash and self.splash.winfo_exists():
                    self.splash.destroy()
            except Exception:
                pass
            self.splash = None
            self.splash_canvas = None
            self._show_main_window()

        self._fade(self.splash, 1.0, 0.0, 320, on_done=destroy_splash)

    def _show_main_window(self):
        try:
            self.deiconify()
            self.attributes("-topmost", True)
            self.after(200, lambda: self.attributes("-topmost", False))
            self.lift()
            self.focus_force()
        except Exception:
            pass

    def _fade(self, win, a_from, a_to, duration_ms, on_done=None, steps=20):
        if not win or not win.winfo_exists():
            if on_done: on_done()
            return
        delay = max(1, duration_ms // steps)
        delta = (a_to - a_from) / steps

        def step(i):
            if not win or not win.winfo_exists():
                if on_done: on_done()
                return
            a = a_from + delta * i
            try:
                win.attributes("-alpha", max(0.0, min(1.0, a)))
            except Exception:
                pass
            if i < steps:
                win.after(delay, lambda: step(i + 1))
            else:
                if on_done: on_done()

        step(0)

    # ============ ТЕМА ============
    def _reg(self, w, **styles):
        self._themed.append((w, styles))
        self._apply_widget(w, styles)
        return w

    def _apply_widget(self, w, styles):
        kwargs = {}
        for attr, key in styles.items():
            kwargs[attr] = self.theme.get(key, key)
        try: w.configure(**kwargs)
        except Exception: pass

    def _apply_theme(self, name):
        if name not in THEMES: return
        self.theme_name = name
        self.theme = THEMES[name]
        _save_theme(name)

        self.configure(fg_color=self.theme["bg_dark"])
        for w, styles in self._themed:
            self._apply_widget(w, styles)

        if self.logs_window and self.logs_window.winfo_exists():
            try:
                self.logs_window.configure(fg_color=self.theme["bg_dark"])
                if self.logs_text is not None:
                    self.logs_text.configure(
                        fg_color=self.theme["bg_dark"],
                        text_color=self.theme["text"])
            except Exception:
                pass

        self._rebuild_tags()
        self._refresh_theme_buttons()
        self._rebuild_chat()

    def _rebuild_tags(self):
        t = self.theme
        if self.logs_text is not None:
            self.logs_text.tag_config("info",     foreground=t["text_dim"])
            self.logs_text.tag_config("ok",       foreground=GREEN)
            self.logs_text.tag_config("warn",     foreground=YELLOW)
            self.logs_text.tag_config("err",      foreground=RED)
            self.logs_text.tag_config("cmd",      foreground=t["accent2"])
            self.logs_text.tag_config("step_ok",  foreground=GREEN)
            self.logs_text.tag_config("step_err", foreground=RED)
            self.logs_text.tag_config("stream",   foreground=CYAN)

    def _refresh_theme_buttons(self):
        for name, btn in self._theme_btns.items():
            if name == self.theme_name:
                btn.configure(fg_color=self.theme["accent"],
                              text_color=self.theme["send_text"])
            else:
                btn.configure(fg_color=self.theme["bg_light"],
                              text_color=self.theme["text"])

    def _animate_tick(self):
        try:
            if self.core.is_online():
                self._pulse_state = 1 - self._pulse_state
                color = GREEN_BRIGHT if self._pulse_state else GREEN
                self.net_indicator.configure(text="●", text_color=color)
            else:
                self.net_indicator.configure(text="●", text_color=YELLOW)
        except Exception: pass
        try:
            if self._is_generating:
                self._gen_dots = (self._gen_dots + 1) % 4
                dots = "·" * self._gen_dots + " " * (3 - self._gen_dots)
                self.gen_label.configure(text=f"печатает {dots}")
            else:
                self.gen_label.configure(text="")
        except Exception: pass
        self.after(400, self._animate_tick)

    # ============ UI ============
    def _build_ui(self):
        self.grid_columnconfigure(0, weight=1)
        self.grid_rowconfigure(1, weight=1)

        t = self.theme

        top = ctk.CTkFrame(self, height=58, corner_radius=0,
                           fg_color=t["bg_mid"])
        top.grid(row=0, column=0, sticky="ew")
        top.grid_propagate(False)
        self._reg(top, fg_color="bg_mid")

        if self._icon_ctk is not None:
            self.logo_label = ctk.CTkLabel(top, text="", image=self._icon_ctk)
            self.logo_label.pack(side="left", padx=(20, 8))
            self._themed.append((self.logo_label, {}))
        else:
            self.logo_label = ctk.CTkLabel(top, text="✿",
                                           font=ctk.CTkFont(size=20, weight="bold"),
                                           text_color=t["accent"])
            self.logo_label.pack(side="left", padx=(20, 6))
            self._reg(self.logo_label, text_color="accent")

        self.brand_label = ctk.CTkLabel(
            top, text="NonMainAI  ",
            font=ctk.CTkFont(size=15, weight="bold"),
            text_color=t["text"])
        self.brand_label.pack(side="left", padx=(0, 0))
        self._reg(self.brand_label, text_color="text")

        self.by_label = ctk.CTkLabel(top, text="by zexokky",
                                     font=ctk.CTkFont(size=12),
                                     text_color=t["text_dim"])
        self.by_label.pack(side="left", padx=(0, 16))
        self._reg(self.by_label, text_color="text_dim")

        self.model_label = ctk.CTkLabel(top, text=MODEL,
                                        font=ctk.CTkFont(size=11),
                                        text_color=t["text_dim"])
        self.model_label.pack(side="left", padx=(0, 12))
        self._reg(self.model_label, text_color="text_dim")

        self.gen_label = ctk.CTkLabel(top, text="",
                                      font=ctk.CTkFont(size=11, slant="italic"),
                                      text_color=t["accent"])
        self.gen_label.pack(side="left", padx=4)
        self._reg(self.gen_label, text_color="accent")

        self.net_indicator = ctk.CTkLabel(top, text="●",
                                          text_color=GREEN,
                                          font=ctk.CTkFont(size=14, weight="bold"))
        self.net_indicator.pack(side="right", padx=(0, 18))

        theme_box = ctk.CTkFrame(top, fg_color="transparent")
        theme_box.pack(side="right", padx=(0, 8))
        self._theme_btns = {}
        for tname in ("light", "dark", "black"):
            th = THEMES[tname]
            b = ctk.CTkButton(theme_box, text=th["icon"], width=30, height=30,
                              corner_radius=8,
                              font=ctk.CTkFont(size=14, weight="bold"),
                              fg_color=t["bg_light"],
                              hover_color=t["bg_hover"],
                              text_color=t["text"],
                              command=lambda n=tname: self._apply_theme(n))
            b.pack(side="left", padx=2)
            self._reg(b, fg_color="bg_light", hover_color="bg_hover",
                      text_color="text")
            self._theme_btns[tname] = b

        self.copy_btn = ctk.CTkButton(top, text="📋", width=36, height=30,
                                      corner_radius=8,
                                      font=ctk.CTkFont(size=14),
                                      fg_color=t["bg_light"],
                                      hover_color=t["bg_hover"],
                                      text_color=t["text"],
                                      command=self._copy_last_agent)
        self.copy_btn.pack(side="right", padx=(0, 6))
        self._reg(self.copy_btn, fg_color="bg_light", hover_color="bg_hover",
                  text_color="text")

        self.logs_btn = ctk.CTkButton(top, text="≡  ЛОГИ", width=90, height=30,
                                      corner_radius=8,
                                      font=ctk.CTkFont(size=12, weight="bold"),
                                      fg_color=t["bg_light"],
                                      hover_color=t["bg_hover"],
                                      text_color=t["text"],
                                      command=self._toggle_logs)
        self.logs_btn.pack(side="right", padx=(0, 6))
        self._reg(self.logs_btn, fg_color="bg_light", hover_color="bg_hover",
                  text_color="text")

        self.mem_label = ctk.CTkLabel(top, text=f"память {len(self.core.history)}",
                                      font=ctk.CTkFont(size=11),
                                      text_color=t["text_dim"])
        self.mem_label.pack(side="right", padx=(0, 14))
        self._reg(self.mem_label, text_color="text_dim")

        sep1 = ctk.CTkFrame(self, height=1, corner_radius=0,
                            fg_color=t["border"])
        sep1.grid(row=0, column=0, sticky="sew")
        self._reg(sep1, fg_color="border")

        chat_wrap = ctk.CTkFrame(self, corner_radius=0, fg_color=t["bg_dark"])
        chat_wrap.grid(row=1, column=0, sticky="nsew")
        self._reg(chat_wrap, fg_color="bg_dark")

        self.chat_area = ctk.CTkScrollableFrame(
            chat_wrap,
            fg_color=t["bg_dark"],
            corner_radius=0,
            scrollbar_button_color=t["bg_light"],
            scrollbar_button_hover_color=t["bg_hover"],
        )
        self.chat_area.pack(fill="both", expand=True, padx=0, pady=0)
        self._reg(self.chat_area, fg_color="bg_dark")

        input_wrap = ctk.CTkFrame(self, height=1, corner_radius=0,
                                  fg_color=t["border"])
        input_wrap.grid(row=2, column=0, sticky="ew")
        self._reg(input_wrap, fg_color="border")

        bottom = ctk.CTkFrame(self, height=88, corner_radius=0,
                              fg_color=t["bg_mid"])
        bottom.grid(row=3, column=0, sticky="ew")
        bottom.grid_propagate(False)
        self._reg(bottom, fg_color="bg_mid")

        row = ctk.CTkFrame(bottom, fg_color="transparent")
        row.pack(fill="x", expand=True, padx=18, pady=18)

        self.menu_btn = ctk.CTkButton(
            row, text="⋯", width=46, height=46, corner_radius=23,
            font=ctk.CTkFont(size=22, weight="bold"),
            fg_color=t["bg_light"], hover_color=t["bg_hover"],
            text_color=t["text"],
            command=self._toggle_actions_menu,
        )
        self.menu_btn.pack(side="left", padx=(0, 10))
        self._reg(self.menu_btn, fg_color="bg_light", hover_color="bg_hover",
                  text_color="text")

        self.input_entry = ctk.CTkEntry(
            row, placeholder_text="напиши хозяин чё надо...",
            height=46, corner_radius=23, border_width=0,
            font=ctk.CTkFont(size=14),
            fg_color=t["bg_light"], text_color=t["text"],
        )
        self.input_entry.pack(side="left", fill="x", expand=True, padx=(0, 10))
        self.input_entry.bind("<Return>", lambda e: self._send_message())
        self.input_entry.bind("<Button-3>", self._input_context_menu)
        self._reg(self.input_entry, fg_color="bg_light", text_color="text")

        self.send_btn = ctk.CTkButton(
            row, text="→", width=46, height=46, corner_radius=23,
            font=ctk.CTkFont(size=20, weight="bold"),
            fg_color=t["accent"], hover_color=t["accent2"],
            text_color=t["send_text"],
            command=self._send_message,
        )
        self.send_btn.pack(side="right")
        self._reg(self.send_btn, fg_color="accent", hover_color="accent2",
                  text_color="send_text")

        self._rebuild_tags()
        self._refresh_theme_buttons()

    # ============ КАСТОМНОЕ КОНТЕКСТНОЕ МЕНЮ ============
    def _close_ctx_popup(self):
        if self.ctx_popup and self.ctx_popup.winfo_exists():
            try: self.ctx_popup.destroy()
            except Exception: pass
        self.ctx_popup = None

    def _show_custom_menu(self, x_root, y_root, items):
        """items: список (icon, label, callback) или ("---", None, None) для разделителя."""
        self._close_ctx_popup()
        self._close_actions_menu()

        t = self.theme

        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(fg_color=t["bg_mid"])
        self.ctx_popup = popup

        # скруглённая рамка
        wrap = ctk.CTkFrame(popup, fg_color=t["border"], corner_radius=12)
        wrap.pack(padx=1, pady=1)
        inner = ctk.CTkFrame(wrap, fg_color=t["bg_mid"], corner_radius=11)
        inner.pack(padx=1, pady=1, fill="both", expand=True)

        def close_and(fn):
            def run():
                self._close_ctx_popup()
                try:
                    fn()
                except Exception as e:
                    print(f"[ctx] ошибка: {e}")
            return run

        for icon, label, cb in items:
            if label is None:
                # разделитель
                sep_frame = ctk.CTkFrame(inner, fg_color=t["border"],
                                         height=1, corner_radius=0)
                sep_frame.pack(fill="x", padx=8, pady=4)
                continue

            btn = ctk.CTkButton(
                inner,
                text=f"  {icon}  {label}" if icon else f"  {label}",
                anchor="w",
                height=34,
                width=260,
                corner_radius=8,
                fg_color="transparent",
                hover_color=t["bg_hover"],
                text_color=t["text"],
                font=ctk.CTkFont(size=12),
                command=close_and(cb),
            )
            btn.pack(fill="x", padx=6, pady=1)

        # позиционирование
        popup.update_idletasks()
        w = popup.winfo_reqwidth()
        h = popup.winfo_reqheight()
        sw = popup.winfo_screenwidth()
        sh = popup.winfo_screenheight()

        # если вылезает за экран — сдвигаем
        x = x_root
        y = y_root
        if x + w > sw:
            x = sw - w - 8
        if y + h > sh:
            y = sh - h - 8

        popup.geometry(f"+{x}+{y}")
        popup.lift()

        # закрытие по клику вне
        self.after(50, lambda: self._bind_ctx_close(popup))

    def _bind_ctx_close(self, popup):
        def on_click(event):
            if not (popup and popup.winfo_exists()):
                return
            try:
                x, y = event.x_root, event.y_root
                px = popup.winfo_rootx()
                py = popup.winfo_rooty()
                pw = popup.winfo_width()
                ph = popup.winfo_height()
                inside = (px <= x <= px + pw) and (py <= y <= py + ph)
                if not inside:
                    self._close_ctx_popup()
            except Exception:
                pass

        try:
            popup.bind_all("<Button-1>", on_click, add="+")
        except Exception:
            pass

    def _bind_bubble_menu(self, widget, text):
        def show_menu(event):
            items = [
                ("📋", "Копировать сообщение",
                 lambda: (self.clipboard_clear(),
                          self.clipboard_append(text))),
                ("📄", "Копировать последний ответ агента",
                 self._copy_last_agent),
                (None, None, None),  # разделитель
                ("🗑", "Очистить чат", self._cmd_clear),
            ]
            self._show_custom_menu(event.x_root, event.y_root, items)

        def bind_rec(w):
            try:
                w.bind("<Button-3>", show_menu)
            except Exception:
                pass
            for child in w.winfo_children():
                bind_rec(child)

        bind_rec(widget)

    def _append_chat(self, who, text, save=True):
        try:
            t = self.theme
            now = time.strftime("%H:%M")

            if who == "user":
                bubble_color = t["accent"]
                text_color = t["send_text"]
                side = "right"
                name = "Ты"
                avatar = "🧑"
            else:
                bubble_color = t["bg_light"]
                text_color = t["text"]
                side = "left"
                name = "NonMainAI"
                avatar = "✿"

            row = ctk.CTkFrame(self.chat_area, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(6, 6))

            bubble = ctk.CTkFrame(
                row,
                fg_color=bubble_color,
                corner_radius=20,
            )
            if side == "right":
                bubble.pack(side="right", padx=(80, 0))
            else:
                bubble.pack(side="left", padx=(0, 80))

            label = ctk.CTkLabel(
                bubble,
                text=text,
                font=ctk.CTkFont(size=14),
                text_color=text_color,
                wraplength=560,
                justify="left",
                anchor="w",
            )
            label.pack(padx=16, pady=(12, 4), anchor="w")

            meta = ctk.CTkLabel(
                bubble,
                text=f"{avatar} {name} · {now}",
                font=ctk.CTkFont(size=10),
                text_color=text_color,
                anchor="e",
            )
            meta.pack(padx=16, pady=(0, 8), anchor="e")

            self._bind_bubble_menu(bubble, text)
            self._bind_bubble_menu(label, text)
            self._bind_bubble_menu(meta, text)

            self.after(20, lambda: self._scroll_to_bottom())

            if save:
                self.core._append_history(who, text)

        except Exception as e:
            print(f"[chat] ошибка рендера пузыря: {e}")

    def _scroll_to_bottom(self):
        try:
            canvas = self.chat_area._parent_canvas
            canvas.update_idletasks()
            canvas.yview_moveto(1.0)
        except Exception:
            pass

    def _load_history_to_chat(self):
        self._rebuild_chat()

    def _clear_chat_widgets(self):
        try:
            for w in self.chat_area.winfo_children():
                w.destroy()
        except Exception:
            pass

        def _rebuild_chat(self):
        self._clear_chat_widgets()
        hist = self.core.history
        if not hist:
            self._append_chat("agent", "здарова, хозяин. Чё делаем?", save=False)
            return
        for m in hist[-60:]:
            self._append_chat(m["role"], m["content"], save=False)

    # ============ КОНТЕКСТНОЕ МЕНЮ INPUT ============
    def _input_context_menu(self, event):
        items = [
            ("📥", "Вставить", self._paste_to_input),
            ("📋", "Копировать", self._copy_from_input),
            ("✂", "Вырезать", self._cut_from_input),
        ]
        self._show_custom_menu(event.x_root, event.y_root, items)

    def _paste_to_input(self):
        try: txt = self.clipboard_get()
        except Exception: return
        cur = self.input_entry.get()
        self.input_entry.delete(0, "end")
        self.input_entry.insert(0, cur + txt)

    def _copy_from_input(self):
        try: sel = self.input_entry.selection_get()
        except Exception: sel = self.input_entry.get()
        self.clipboard_clear()
        self.clipboard_append(sel)

    def _cut_from_input(self):
        self._copy_from_input()
        try: self.input_entry.delete("sel.first", "sel.last")
        except Exception: self.input_entry.delete(0, "end")

    def _copy_last_agent(self):
        for m in reversed(self.core.history):
            if m["role"] == "assistant":
                self.clipboard_clear()
                self.clipboard_append(m["content"])
                self._flash_copy_btn()
                return

    def _flash_copy_btn(self):
        try:
            self.copy_btn.configure(fg_color=self.theme["accent"],
                                    text_color=self.theme["send_text"])
            self.after(400, lambda: self.copy_btn.configure(
                fg_color=self.theme["bg_light"],
                text_color=self.theme["text"]))
        except Exception: pass

    # ============ МЕНЮ ДЕЙСТВИЙ ============
    def _close_actions_menu(self):
        if self.actions_popup and self.actions_popup.winfo_exists():
            try: self.actions_popup.destroy()
            except Exception: pass
        self.actions_popup = None

    def _global_click_handler(self, event):
        if self._menu_just_opened:
            return
        if not (self.actions_popup and self.actions_popup.winfo_exists()):
            return
        try:
            x, y = event.x_root, event.y_root
            px = self.actions_popup.winfo_rootx()
            py = self.actions_popup.winfo_rooty()
            pw = self.actions_popup.winfo_width()
            ph = self.actions_popup.winfo_height()
            inside = (px <= x <= px + pw) and (py <= y <= py + ph)
            if not inside:
                self._close_actions_menu()
        except Exception:
            pass

    def _toggle_actions_menu(self):
        if self.actions_popup and self.actions_popup.winfo_exists():
            self._close_actions_menu()
            return

        popup = ctk.CTkToplevel(self)
        popup.overrideredirect(True)
        popup.attributes("-topmost", True)
        popup.configure(fg_color=self.theme["bg_mid"])
        self.actions_popup = popup

        wrap = ctk.CTkFrame(popup, fg_color=self.theme["border"], corner_radius=14)
        wrap.pack(padx=1, pady=1)
        inner = ctk.CTkFrame(wrap, fg_color=self.theme["bg_mid"], corner_radius=12)
        inner.pack(padx=1, pady=1)

        title = ctk.CTkLabel(inner, text="ДЕЙСТВИЯ",
                             font=ctk.CTkFont(size=11, weight="bold"),
                             text_color=self.theme["text_dim"])
        title.pack(pady=(10, 6))

        btns = [
            ("заметки",   self._cmd_notes),
            ("бэкапы",    self._cmd_backups),
            ("процессы",  self._cmd_procs),
            ("сеть",      self._cmd_net),
            ("откат",     self._cmd_undo),
            ("память",    self._cmd_memory),
            ("очистить",  self._cmd_clear),
            ("сброс",     self._cmd_clear_history),
            ("выход",     self._cmd_exit),
        ]
        grid = ctk.CTkFrame(inner, fg_color="transparent")
        grid.pack(padx=10, pady=(0, 10))

        def make_action(fn):
            def run():
                self._close_actions_menu()
                try: fn()
                except Exception as e:
                    print(f"[menu] ошибка: {e}")
            return run

        for i, (label, cmd) in enumerate(btns):
            r, c = divmod(i, 3)
            b = ctk.CTkButton(grid, text=label, width=92, height=34,
                              corner_radius=8,
                              fg_color=self.theme["bg_light"],
                              hover_color=self.theme["bg_hover"],
                              text_color=self.theme["text"],
                              font=ctk.CTkFont(size=12),
                              command=make_action(cmd))
            b.grid(row=r, column=c, padx=3, pady=3)

        self.update_idletasks()
        btn_x = self.menu_btn.winfo_rootx()
        btn_y = self.menu_btn.winfo_rooty()
        popup.update_idletasks()
        h = popup.winfo_reqheight()
        popup.geometry(f"+{btn_x}+{btn_y - h - 10}")

        self._menu_just_opened = True
        self.after(250, lambda: setattr(self, '_menu_just_opened', False))

        popup.lift()
        popup.attributes("-topmost", True)

        if not self._global_click_bound:
            try:
                self.bind_all("<Button-1>", self._global_click_handler, add="+")
                self._global_click_bound = True
            except Exception:
                pass

    # ============ ЛОГИ ============
    def _toggle_logs(self):
        if self.logs_window and self.logs_window.winfo_exists():
            self.logs_window.lift()
            self.logs_window.focus_force()
            return

        win = ctk.CTkToplevel(self)
        win.title("NonMainAI - логи")
        win.geometry("720x500")
        win.configure(fg_color=self.theme["bg_dark"])

        if ICON_PATH:
            def set_icon():
                try:
                    win.iconbitmap(str(ICON_PATH))
                except Exception:
                    pass
            win.after(100, set_icon)
            win.after(500, set_icon)
        if self._icon_photo is not None:
            try:
                win.wm_iconphoto(True, self._icon_photo)
            except Exception:
                try: win.wm_iconphoto(self._icon_photo)
                except Exception: pass

        self.logs_window = win

        header = ctk.CTkFrame(win, height=48, corner_radius=0,
                              fg_color=self.theme["bg_mid"])
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        h_title = ctk.CTkLabel(header, text="  ЛОГИ NonMainAI",
                               font=ctk.CTkFont(size=13, weight="bold"),
                               text_color=self.theme["text_dim"])
        h_title.pack(side="left", padx=14)

        clear_btn = ctk.CTkButton(header, text="очистить", width=90, height=30,
                                  corner_radius=8,
                                  fg_color=self.theme["bg_light"],
                                  hover_color=self.theme["bg_hover"],
                                  text_color=self.theme["text"],
                                  font=ctk.CTkFont(size=12),
                                  command=self._clear_logs)
        clear_btn.pack(side="right", padx=14)

        self.logs_text = ctk.CTkTextbox(
            win, fg_color=self.theme["bg_dark"],
            text_color=self.theme["text"],
            font=ctk.CTkFont(family="Consolas", size=11),
            wrap="word", corner_radius=0, border_width=0,
            padx=14, pady=12,
        )
        self.logs_text.pack(fill="both", expand=True)
        self._rebuild_tags()

        for text, tag in self.log_buffer:
            self.logs_text.insert("end", text + "\n", tag)
        self.logs_text.see("end")

        self.logs_btn.configure(fg_color=self.theme["accent"],
                                text_color=self.theme["send_text"])

        def on_close():
            try:
                self.logs_btn.configure(fg_color=self.theme["bg_light"],
                                        text_color=self.theme["text"])
            except Exception: pass
            self.logs_window.destroy()
            self.logs_window = None
            self.logs_text = None
        win.protocol("WM_DELETE_WINDOW", on_close)

    def _clear_logs(self):
        self.log_buffer = []
        if self.logs_text is not None:
            self.logs_text.delete("1.0", "end")

    # ============ CALLBACKS ============
    def _cb_log(self, text, level="info"): self.events.put(("log", text, level))
    def _cb_token(self, text): self.events.put(("token", text))
    def _cb_step(self, action, result, gen_time, exec_time):
        self.events.put(("step", action, result, gen_time, exec_time))
    def _cb_answer(self, text): self.events.put(("answer", text))
    def _cb_status(self, key, val): self.events.put(("status", key, val))

    def _cb_confirm(self, prompt):
        self.confirm_result = None
        self.confirm_event.clear()
        self.events.put(("confirm", prompt))
        self.confirm_event.wait()
        return bool(self.confirm_result)

    def _poll_events(self):
        try:
            while True:
                ev = self.events.get_nowait()
                kind = ev[0]
                if kind == "log": self._log(ev[1], ev[2])
                elif kind == "token": self._stream_token(ev[1])
                elif kind == "step": self._log_step(*ev[1:])
                elif kind == "answer":
                    self._append_chat("agent", ev[1], save=False)
                    self.mem_label.configure(text=f"память {len(self.core.history)}")
                    self._is_generating = False
                elif kind == "status":
                    if ev[1] == "online":
                        self._set_online(ev[2])
                elif kind == "confirm": self._show_confirm(ev[1])
        except queue.Empty: pass
        self.after(50, self._poll_events)

    def _set_online(self, online):
        if online: self.net_indicator.configure(text="●", text_color=GREEN)
        else: self.net_indicator.configure(text="●", text_color=YELLOW)

    def _log(self, text, level="info"):
        tag = level if level in ("ok","warn","err","cmd","info") else "info"
        self.log_buffer.append((text, tag))
        if len(self.log_buffer) > 5000:
            self.log_buffer = self.log_buffer[-5000:]
        if self.logs_text is not None:
            self.logs_text.insert("end", text + "\n", tag)
            self.logs_text.see("end")

    def _stream_token(self, text):
        if self.logs_text is not None:
            self.logs_text.insert("end", text, "stream")
            self.logs_text.see("end")

    def _log_step(self, action, result, gen_time, exec_time):
        ok = not str(result).startswith(("Ошибка", "Отменено"))
        short = str(result).replace("\n", " ")[:120]
        icon = "✓" if ok else "✗"
        tag = "step_ok" if ok else "step_err"
        if self.logs_text is not None:
            self.logs_text.insert("end", f"\n{icon} {action}", tag)
            self.logs_text.insert("end", f"  [{gen_time:.1f}s / {exec_time:.2f}s]\n", "info")
            self.logs_text.insert("end", f"   {short}\n", "info")
            self.logs_text.see("end")

    # ============ ПОДТВЕРЖДЕНИЕ ============
    def _show_confirm(self, prompt):
        t = self.theme
        dialog = ctk.CTkToplevel(self)
        dialog.title("NonMainAI - подтверждение")
        dialog.configure(fg_color=t["bg_mid"])
        dialog.resizable(False, False)
        dialog.attributes("-topmost", True)
        dialog.lift()

        if ICON_PATH:
            def set_icon():
                try:
                    dialog.iconbitmap(str(ICON_PATH))
                except Exception:
                    pass
            dialog.after(100, set_icon)
            dialog.after(400, set_icon)
        if self._icon_photo is not None:
            try: dialog.wm_iconphoto(True, self._icon_photo)
            except Exception:
                try: dialog.wm_iconphoto(self._icon_photo)
                except Exception: pass

        W, H = 700, 500
        self.update_idletasks()
        px = self.winfo_x() + (self.winfo_width() - W) // 2
        py = self.winfo_y() + (self.winfo_height() - H) // 2
        dialog.geometry(f"{W}x{H}+{px}+{py}")

        bar = ctk.CTkFrame(dialog, fg_color=YELLOW, height=4, corner_radius=0)
        bar.pack(fill="x", side="top")

        head = ctk.CTkLabel(dialog, text="⚠  ПОДТВЕРДИ ДЕЙСТВИЕ",
                            font=ctk.CTkFont(size=15, weight="bold"),
                            text_color=YELLOW)
        head.pack(pady=(20, 8))

        body = ctk.CTkTextbox(dialog, fg_color=t["bg_dark"], text_color=t["text"],
                              font=ctk.CTkFont(family="Consolas", size=12),
                              wrap="word", corner_radius=10, border_width=0,
                              padx=14, pady=12)
        body.pack(fill="both", expand=True, padx=24, pady=(0, 12))
        body.insert("1.0", prompt)
        body.configure(state="disabled")

        bf = ctk.CTkFrame(dialog, fg_color=t["bg_mid"], height=70)
        bf.pack(fill="x", side="bottom", padx=24, pady=(0, 20))
        bf.pack_propagate(False)

        def finish(a):
            self.confirm_result = a
            try: dialog.grab_release()
            except Exception: pass
            dialog.destroy()
            self.confirm_event.set()

        yb = ctk.CTkButton(bf, text="✓  ДА", width=180, height=46, corner_radius=10,
                           fg_color=GREEN, hover_color="#5fa85f",
                           text_color="#1a1a1f",
                           font=ctk.CTkFont(size=15, weight="bold"),
                           command=lambda: finish(True))
        yb.pack(side="left", expand=True, padx=(0, 8))

        nb = ctk.CTkButton(bf, text="✗  НЕТ", width=180, height=46, corner_radius=10,
                           fg_color=RED, hover_color="#b85f5f",
                           text_color="#1a1a1f",
                           font=ctk.CTkFont(size=15, weight="bold"),
                           command=lambda: finish(False))
        nb.pack(side="right", expand=True, padx=(8, 0))

        dialog.protocol("WM_DELETE_WINDOW", lambda: finish(False))
        dialog.bind("<Escape>", lambda e: finish(False))
        dialog.bind("<Return>", lambda e: finish(True))
        dialog.bind("<KP_Enter>", lambda e: finish(True))

        def do_grab():
            try:
                dialog.grab_set()
                yb.focus_set()
            except Exception: pass
        dialog.after(100, do_grab)
        dialog.after(200, lambda: (dialog.attributes("-topmost", True),
                                    dialog.lift(), dialog.focus_force()))

    # ============ ДЕЙСТВИЯ ============
    def _send_message(self):
        text = self.input_entry.get().strip()
        if not text: return
        self._append_chat("user", text, save=True)
        self.input_entry.delete(0, "end")
        self._is_generating = True
        threading.Thread(target=self._run_chat, args=(text,), daemon=True).start()

    def _run_chat(self, text):
        try:
            self.core.chat(text)
        except Exception as e:
            self._cb_log(f"ошибка: {e}", "err")
        finally:
            self._is_generating = False

    def _run_quick(self, fn, *args):
        def task():
            try: self._cb_answer(fn(*args))
            except Exception as e: self._cb_log(f"ошибка: {e}", "err")
        threading.Thread(target=task, daemon=True).start()

    def _cmd_notes(self): self._run_quick(self.core.load_notes)
    def _cmd_backups(self): self._run_quick(self.core.list_backups)
    def _cmd_procs(self): self._run_quick(self.core.list_processes)

    def _cmd_net(self):
        online = self.core.is_online(force=True)
        self._set_online(online)
        self._append_chat("agent", "онлайн, хозяин" if online else "офлайн", save=False)

    def _cmd_undo(self): self._run_quick(self.core.undo_last)

    def _cmd_memory(self):
        n = self.core.history_count()
        self._append_chat("agent", f"в памяти {n} сообщений (лимит {MAX_HISTORY})", save=False)
        if n > 0:
            lines = []
            for m in self.core.history[-10:]:
                role = "Ты" if m["role"] == "user" else "Я"
                preview = m["content"].replace("\n", " ")[:100]
                lines.append(f"{role}: {preview}")
            self._log("память:\n" + "\n".join(lines), "info")

    def _cmd_clear(self):
        self._clear_chat_widgets()
        self._append_chat("agent", "почистил экран, хозяин. Память сохранилась.", save=False)

    def _cmd_clear_history(self):
        msg = self.core.clear_history()
        self.mem_label.configure(text="память 0")
        self._clear_chat_widgets()
        self._append_chat("agent", f"хозяин, {msg}", save=False)

    def _cmd_exit(self):
        try: self.core._save_history()
        except Exception: pass
        self.destroy()

    def _start_background(self):
        def init():
            try:
                self.core.ensure_venv()
                self._log("прогреваю модель...", "info")
                self.core.warmup_model()
                self._log("готов к работе", "ok")
            except Exception as e:
                self._log(f"ошибка инициализации: {e}", "err")
        threading.Thread(target=init, daemon=True).start()


if __name__ == "__main__":
    app = AgentGUI()
    app.mainloop()