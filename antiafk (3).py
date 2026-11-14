import ctypes
import base64
import hashlib
import io
import hmac
import math
import os
import queue
import random
import re
import sys
import threading
import time
import tkinter as tk
from ctypes import wintypes

try:
    from PIL import Image, ImageEnhance, ImageSequence, ImageTk
except Exception:
    Image = None
try:
    import cv2
except Exception:
    cv2 = None

IS_WIN = sys.platform == "win32"

# =====================================================================
#  Entrada de teclado/mouse por hardware (SendInput + scancodes)
#  Es lo que aceptan FiveM / GTA V. No requiere librerías externas.
# =====================================================================
SCAN = {}
for _ch, _sc in zip("qwertyuiop", range(0x10, 0x1A)):
    SCAN[_ch] = _sc
for _ch, _sc in zip("asdfghjkl", range(0x1E, 0x27)):
    SCAN[_ch] = _sc
for _ch, _sc in zip("zxcvbnm", range(0x2C, 0x33)):
    SCAN[_ch] = _sc
for _ch, _sc in zip("1234567890", range(0x02, 0x0C)):
    SCAN[_ch] = _sc
for _i in range(10):
    SCAN[f"f{_i + 1}"] = 0x3B + _i
SCAN.update({
    "f11": 0x57, "f12": 0x58, "space": 0x39, "enter": 0x1C, "esc": 0x01, "tab": 0x0F,
    "backspace": 0x0E, "shift": 0x2A, "ctrl": 0x1D, "alt": 0x38, "capslock": 0x3A,
    "up": 0x48, "down": 0x50, "left": 0x4B, "right": 0x4D, "home": 0x47, "end": 0x4F,
    "pageup": 0x49, "pagedown": 0x51, "insert": 0x52, "delete": 0x53,
    "-": 0x0C, "=": 0x0D, "[": 0x1A, "]": 0x1B, ";": 0x27, "'": 0x28, "`": 0x29,
    "\\": 0x2B, ",": 0x33, ".": 0x34, "/": 0x35,
})
EXTENDED = {"up", "down", "left", "right", "home", "end", "pageup", "pagedown", "insert", "delete"}


class InputBlocked(Exception):
    pass


if IS_WIN:
    user32 = ctypes.WinDLL("user32", use_last_error=True)
    shell32 = ctypes.WinDLL("shell32")
    dwmapi = ctypes.WinDLL("dwmapi")
    ULONG_PTR = ctypes.c_size_t

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", wintypes.WORD), ("wScan", wintypes.WORD), ("dwFlags", wintypes.DWORD),
                    ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", wintypes.LONG), ("dy", wintypes.LONG), ("mouseData", wintypes.DWORD),
                    ("dwFlags", wintypes.DWORD), ("time", wintypes.DWORD), ("dwExtraInfo", ULONG_PTR)]

    class _INPUTUNION(ctypes.Union):
        _fields_ = [("ki", KEYBDINPUT), ("mi", MOUSEINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", wintypes.DWORD), ("u", _INPUTUNION)]

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = wintypes.UINT
    user32.EnumWindows.argtypes = [WNDENUMPROC, wintypes.LPARAM]
    user32.GetForegroundWindow.restype = wintypes.HWND
    user32.GetWindowTextW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.GetWindowTextLengthW.argtypes = [wintypes.HWND]
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
    user32.IsWindowVisible.argtypes = [wintypes.HWND]
    user32.IsIconic.argtypes = [wintypes.HWND]
    user32.ShowWindow.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.SetForegroundWindow.argtypes = [wintypes.HWND]
    user32.GetParent.argtypes = [wintypes.HWND]
    user32.GetParent.restype = wintypes.HWND
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    user32.GetAsyncKeyState.restype = ctypes.c_short
    dwmapi.DwmSetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

    def _send(inp):
        if user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT)) == 0:
            raise InputBlocked("SendInput bloqueado")

    def key_event(name, up=False):
        flags = 0x0008 | (0x0002 if up else 0) | (0x0001 if name in EXTENDED else 0)
        inp = INPUT(1)
        inp.u.ki = KEYBDINPUT(0, SCAN[name], flags, 0, 0)
        _send(inp)

    def mouse_move(dx, dy):
        inp = INPUT(0)
        inp.u.mi = MOUSEINPUT(dx, dy, 0, 0x0001, 0, 0)
        _send(inp)

    def window_title(hwnd):
        n = user32.GetWindowTextLengthW(hwnd)
        if not n:
            return ""
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        return buf.value

    def window_class(hwnd):
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, buf, 256)
        return buf.value

    def foreground_title():
        return window_title(user32.GetForegroundWindow())

    def find_window(sub, exclude=0):
        if not sub:
            return None
        hits = []

        def cb(hwnd, lparam):
            if hwnd != exclude and user32.IsWindowVisible(hwnd) and sub in window_title(hwnd).lower():
                hits.append(hwnd)
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        for h in hits:
            if window_class(h) == "grcWindow":  # ventana del juego (GTA V / FiveM)
                return h
        return hits[0] if hits else None

    def focus_window(hwnd):
        user32.keybd_event(0x12, 0, 0, 0)  # toque de ALT: permite cambiar el foco
        user32.keybd_event(0x12, 0, 2, 0)
        if user32.IsIconic(hwnd):
            user32.ShowWindow(hwnd, 9)
        user32.SetForegroundWindow(hwnd)

    def is_admin():
        try:
            return bool(shell32.IsUserAnAdmin())
        except Exception:
            return False
else:
    def key_event(name, up=False):
        raise InputBlocked("Solo Windows")

    def mouse_move(dx, dy):
        raise InputBlocked("Solo Windows")

    def foreground_title():
        return ""

    def find_window(sub, exclude=0):
        return None

    def focus_window(hwnd):
        pass

    def is_admin():
        return False


if IS_WIN:
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                                                    ctypes.POINTER(wintypes.DWORD)]
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    user32.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowLongW.argtypes = [wintypes.HWND, ctypes.c_int]
    user32.GetWindowLongW.restype = ctypes.c_long
    dwmapi.DwmGetWindowAttribute.argtypes = [wintypes.HWND, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]

    def proc_name(hwnd):
        pid = wintypes.DWORD(0)
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        h = kernel32.OpenProcess(0x1000, False, pid.value)
        if not h:
            return "?"
        try:
            buf = ctypes.create_unicode_buffer(520)
            n = wintypes.DWORD(520)
            return os.path.basename(buf.value) if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(n)) else "?"
        finally:
            kernel32.CloseHandle(h)

    def list_windows(exclude=0):
        out = []

        def cb(hwnd, lparam):
            if hwnd != exclude and user32.IsWindowVisible(hwnd):
                t = window_title(hwnd)
                if t and not (user32.GetWindowLongW(hwnd, -20) & 0x80):
                    cloaked = ctypes.c_int(0)
                    dwmapi.DwmGetWindowAttribute(hwnd, 14, ctypes.byref(cloaked), 4)
                    if not cloaked.value and (t, proc_name(hwnd)) not in out:
                        out.append((t, proc_name(hwnd)))
            return True

        user32.EnumWindows(WNDENUMPROC(cb), 0)
        return out
else:
    def list_windows(exclude=0):
        return []


def key_down(name):
    key_event(name, False)


def key_up(name):
    key_event(name, True)


def key_tap(name):
    key_down(name)
    time.sleep(0.05)
    key_up(name)


# =====================================================================
#  Estilo y animaciones
# =====================================================================
W, H = 1120, 780          # tamaño inicial de la ventana
MIN_W, MIN_H = 1000, 720   # tamaño mínimo (se puede agrandar sin límite)
SB = 190                  # ancho de la barra lateral
PAD = 28
BAR_H = 64
BG = "#05070d"
SIDE = "#070a13"
CARD = "#0a0f1c"
BORDER = "#16213a"
ROW = "#0f1730"
KEYCAP = "#14234a"
BOX_OFF = "#1b2646"
FG = "#e8edf8"
DIM = "#6f7a96"
ACCENT = "#2b59d9"        # azul oscuro (rellenos y botones)
ACCENT_TXT = "#6b93f2"    # azul más claro para texto sobre fondo oscuro
ON_ACCENT = "#ffffff"
GREEN = "#3ecf8e"
RED = "#e5484d"
AMBER = "#e5a23d"
NAV_ON = "#0e1730"
BTN = "#0f1730"
BTN_HOVER = "#1a2748"
FONT = ("Segoe UI", 10)
MONO = ("Consolas", 8)
MAX_KEYS = 6
MODE_CAP = {"hold": "Mantener: la tecla queda presionada todo el tiempo (ej. W para caminar).",
            "tap": "Pulsar: la tecla se toca una vez cada intervalo."}
DELAYS = {"head": 0.0, "col1": 0.2, "col2": 0.4, "col3": 0.6, "foot": 0.85}
SPEED = 2.2   # multiplica la duración de todas las transiciones de color (más lento)

KEYSYM_MAP = {
    "Return": "enter", "Escape": "esc", "BackSpace": "backspace", "Tab": "tab",
    "Up": "up", "Down": "down", "Left": "left", "Right": "right",
    "Shift_L": "shift", "Shift_R": "shift", "Control_L": "ctrl", "Control_R": "ctrl",
    "Alt_L": "alt", "Alt_R": "alt", "Delete": "delete", "Home": "home", "End": "end",
    "Prior": "pageup", "Next": "pagedown", "Insert": "insert", "Caps_Lock": "capslock",
    "minus": "-", "equal": "=", "bracketleft": "[", "bracketright": "]", "semicolon": ";",
    "apostrophe": "'", "grave": "`", "backslash": "\\", "comma": ",", "period": ".", "slash": "/",
}


def _rgb(h):
    h = h.lstrip("#")
    return tuple(int(h[i:i + 2], 16) for i in (0, 2, 4))


def mix(a, b, t):
    t = max(0.0, min(1.0, t))
    ra, rb = _rgb(a), _rgb(b)
    return "#%02x%02x%02x" % tuple(int(x + (y - x) * t) for x, y in zip(ra, rb))


def ease(t):
    return 1 - (1 - t) ** 3


def fade(widget, attr, to, dur=0.16):
    """Transición suave de color de un widget."""
    dur *= SPEED
    jobs = widget.__dict__.setdefault("_fade", {})
    if attr in jobs:
        try:
            widget.after_cancel(jobs[attr])
        except Exception:
            pass
    start_col = str(widget.cget(attr))
    try:
        _rgb(start_col)
    except Exception:
        widget.config(**{attr: to})
        return
    t0 = time.time()

    def tick():
        try:
            t = min(1.0, (time.time() - t0) / dur)
            widget.config(**{attr: mix(start_col, to, ease(t))})
            if t < 1.0:
                jobs[attr] = widget.after(16, tick)
            else:
                jobs.pop(attr, None)
        except tk.TclError:
            pass

    tick()


def rpts(x1, y1, x2, y2, r):
    r = max(0, min(r, (x2 - x1) / 2, (y2 - y1) / 2))
    return [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
            x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]


class RBtn(tk.Canvas):
    """Botón de esquinas redondeadas. 'bg' y 'fg' controlan el relleno y el texto (compatible con fade)."""

    def __init__(self, parent, text, cmd, bg=BTN, fg=FG, font=("Segoe UI", 9), w=None, h=32, r=12, pbg=CARD):
        kw = {"width": w} if w else {}
        super().__init__(parent, height=h, bg=pbg, highlightthickness=0, bd=0, cursor="hand2" if cmd else "", **kw)
        self.fill, self.fgc, self.r, self.cmd = bg, fg, r, cmd
        self.shape = self.create_polygon(0, 0, 1, 0, 1, 1, smooth=True, fill=bg, outline="")
        self.label = self.create_text(0, 0, text=text, fill=fg, font=font)
        self.bind("<Configure>", self.draw)
        self.bind("<Button-1>", lambda e: self.cmd and self.cmd())

    def draw(self, e=None):
        w, h = self.winfo_width(), self.winfo_height()
        self.coords(self.shape, *rpts(0, 0, w, h, self.r))
        self.coords(self.label, w / 2, h / 2)

    def configure(self, cnf=None, **kw):
        kw.update(cnf or {})
        if "bg" in kw:
            self.fill = kw.pop("bg")
            self.itemconfigure(self.shape, fill=self.fill)
        if "fg" in kw:
            self.fgc = kw.pop("fg")
            self.itemconfigure(self.label, fill=self.fgc)
        if "text" in kw:
            self.itemconfigure(self.label, text=kw.pop("text"))
        for k in ("activebackground", "activeforeground", "command"):
            kw.pop(k, None)
        if kw:
            super().configure(**kw)

    config = configure

    def cget(self, key):
        return self.fill if key == "bg" else self.fgc if key == "fg" else super().cget(key)


class RCard(tk.Canvas):
    """Contenedor de esquinas redondeadas: se usa 'inner' para poner cosas dentro."""

    def __init__(self, parent, fill=ROW, pbg=CARD, r=12, h=44, inset=5):
        super().__init__(parent, height=h, bg=pbg, highlightthickness=0, bd=0)
        self.r, self.inset = r, inset
        self.shape = self.create_polygon(0, 0, 1, 0, 1, 1, smooth=True, fill=fill, outline="")
        self.inner = tk.Frame(self, bg=fill)
        self.win = self.create_window(inset, inset, anchor="nw", window=self.inner)
        self.bind("<Configure>", self.draw)

    def draw(self, e):
        self.coords(self.shape, *rpts(0, 0, e.width, e.height, self.r))
        self.itemconfigure(self.win, width=max(1, e.width - 2 * self.inset), height=max(1, e.height - 2 * self.inset))


def rentry(parent, var, width, justify="left", pbg=CARD, h=32):
    c = tk.Canvas(parent, width=width * 9 + 22, height=h, bg=pbg, highlightthickness=0, bd=0)
    shape = c.create_polygon(0, 0, 1, 0, 1, 1, smooth=True, fill="#0d1426", outline="#1b2744")
    e = tk.Entry(c, textvariable=var, bg="#0d1426", fg=FG, insertbackground=FG, relief="flat", bd=0,
                 highlightthickness=0, font=FONT, justify=justify)
    win = c.create_window(0, 0, window=e, anchor="center")

    def draw(ev):
        c.coords(shape, *rpts(0, 0, ev.width - 1, ev.height - 1, 11))
        c.coords(win, ev.width / 2, ev.height / 2)
        c.itemconfigure(win, width=max(10, ev.width - 22))

    c.bind("<Configure>", draw)
    e.bind("<FocusIn>", lambda ev: c.itemconfigure(shape, outline=ACCENT_TXT))
    e.bind("<FocusOut>", lambda ev: c.itemconfigure(shape, outline="#1b2744"))
    return c


class Segmented(tk.Canvas):
    """Selector de modo con indicador que se desliza."""

    def __init__(self, parent, opts, cmd, h=34):
        super().__init__(parent, height=h, bg=CARD, highlightthickness=0, bd=0, cursor="hand2")
        self.opts, self.cmd, self.sel, self.x, self.job = opts, cmd, opts[0][0], 0.0, None
        self.back = self.create_polygon(0, 0, 1, 0, 1, 1, smooth=True, fill=BTN, outline="")
        self.ind = self.create_polygon(0, 0, 1, 0, 1, 1, smooth=True, fill=ACCENT, outline="")
        self.txt = [self.create_text(0, 0, text=t, font=("Segoe UI", 9, "bold"), fill=DIM) for _, t in opts]
        self.bind("<Configure>", lambda e: self.layout())
        self.bind("<Button-1>", self.click)

    def layout(self):
        n, w, h = len(self.opts), max(1, self.winfo_width()) / len(self.opts), self.winfo_height()
        self.coords(self.back, *rpts(0, 0, w * n, h, 14))
        self.coords(self.ind, *rpts(self.x * w + 3, 3, (self.x + 1) * w - 3, h - 3, 11))
        for i, it in enumerate(self.txt):
            self.coords(it, i * w + w / 2, h / 2)
            self.itemconfigure(it, fill=mix(DIM, ON_ACCENT, max(0.0, 1 - abs(self.x - i))))

    def click(self, e):
        i = int(e.x // (max(1, self.winfo_width()) / len(self.opts)))
        self.select(self.opts[max(0, min(len(self.opts) - 1, i))][0])

    def select(self, key, animate=True, call=True):
        if key == self.sel and call:
            return
        idx, start, t0 = [k for k, _ in self.opts].index(key), self.x, time.time()
        dur, self.sel = (0.55 if animate else 0.0), key
        if self.job:
            self.after_cancel(self.job)

        def tick():
            try:
                t = min(1.0, (time.time() - t0) / dur) if dur else 1.0
                self.x = start + (idx - start) * ease(t)
                self.layout()
                self.job = self.after(16, tick) if t < 1.0 else None
            except tk.TclError:
                pass

        tick()
        if call and self.cmd:
            self.cmd(key)


def stepper(parent, var, title, desc, unit, lo, hi, step):
    box = tk.Frame(parent, bg=CARD)
    tk.Label(box, text=title, fg=FG, bg=CARD, font=("Segoe UI", 9, "bold"), anchor="w").pack(fill="x")
    row = tk.Frame(box, bg=CARD)
    row.pack(fill="x", pady=(3, 2))

    def bump(d):
        try:
            v = float(var.get().replace(",", "."))
        except ValueError:
            v = lo
        v = max(lo, min(hi, v + d))
        var.set(str(int(v)) if v == int(v) else str(v))

    small_button(row, "−", lambda: bump(-step)).pack(side="left")
    rentry(row, var, 5, "center").pack(side="left", padx=6)
    small_button(row, "+", lambda: bump(step)).pack(side="left")
    tk.Label(row, text=unit, fg=DIM, bg=CARD, font=("Segoe UI", 9)).pack(side="left", padx=(8, 0))
    tk.Label(box, text=desc, fg=DIM, bg=CARD, font=("Segoe UI", 8), anchor="w", justify="left",
             wraplength=196).pack(fill="x")
    return box


class Check(tk.Frame):
    """Casilla con transición de color."""

    def __init__(self, parent, text, var, bg=CARD):
        super().__init__(parent, bg=bg, cursor="hand2")
        self.var = var
        self.box = RBtn(self, "", None, bg=BOX_OFF, fg=ON_ACCENT, font=("Segoe UI", 8, "bold"), w=20, h=20, r=6, pbg=bg)
        self.box.pack(side="left", padx=(0, 8))
        self.lbl = tk.Label(self, text=text, bg=bg, fg=FG, font=("Segoe UI", 9))
        self.lbl.pack(side="left")
        for w in (self, self.box, self.lbl):
            w.bind("<Button-1>", lambda e: self.var.set(not self.var.get()))
        var.trace_add("write", lambda *a: self.refresh(True))
        self.refresh(False)

    def refresh(self, animate=True):
        on = self.var.get()
        self.box.config(text="✓" if on else "")
        if animate:
            fade(self.box, "bg", ACCENT if on else BOX_OFF, 0.18)
            fade(self.box, "highlightbackground", ACCENT if on else "#2a3658", 0.18)
        else:
            self.box.config(bg=ACCENT if on else BOX_OFF,
                            highlightbackground=ACCENT if on else "#2a3658")


def small_button(parent, text, cmd, w=None, pbg=CARD):
    b = RBtn(parent, text, cmd, w=w or max(36, 8 * len(text) + 30), pbg=pbg)
    b.bind("<Enter>", lambda e: fade(b, "bg", BTN_HOVER, 0.12))
    b.bind("<Leave>", lambda e: fade(b, "bg", BTN, 0.18))
    return b


def make_entry(parent, var, width, justify="left"):
    return tk.Entry(parent, textvariable=var, width=width, bg="#0d1426", fg=FG, insertbackground=FG,
                    relief="flat", highlightthickness=1, highlightbackground="#1b2744",
                    highlightcolor=ACCENT_TXT, font=FONT, justify=justify)


# =====================================================================
#  Utilidades de ventana y acceso (login)
# =====================================================================
# Solo se guardan los hashes (PBKDF2), no el usuario ni la contraseña en texto plano.
_SALT = b"launcher.v1.raika"
USER_HASH = "e80613d22be77273141018ff647a98969fbd1ba0b9fe2305246e3fd1591eefe3"
PASS_HASH = "5486005da0476b7fbf92d25e48d5ab7ea9c588ed6f57842a38a2708109d75ea0"


def _hash(s):
    return hashlib.pbkdf2_hmac("sha256", s.encode("utf-8"), _SALT, 120_000).hex()


def check_login(user, pwd):
    ok_u = hmac.compare_digest(_hash(user.strip()), USER_HASH)
    ok_p = hmac.compare_digest(_hash(pwd), PASS_HASH)
    return ok_u and ok_p


def res_path(name):
    base = getattr(sys, "_MEIPASS", None) or os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, name)


def center_window(root, w, h):
    root.update_idletasks()
    x = max(0, (root.winfo_screenwidth() - w) // 2)
    y = max(0, (root.winfo_screenheight() - h) // 2)
    root.geometry(f"{w}x{h}+{x}+{y}")


def apply_dark_titlebar(root):
    if not IS_WIN:
        return 0
    try:
        root.update_idletasks()
        hwnd = user32.GetParent(root.winfo_id()) or 0
        one = ctypes.c_int(1)
        for attr in (20, 19):  # modo oscuro de la barra de título
            dwmapi.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(one), 4)
        col = ctypes.c_int(0x0D0705)  # color de la barra (Windows 11), formato BBGGRR
        dwmapi.DwmSetWindowAttribute(hwnd, 35, ctypes.byref(col), 4)
        return hwnd
    except Exception:
        return 0


def rounded_poly(c, x1, y1, x2, y2, r=14, fill=CARD, outline=BORDER, tags=()):
    pts = [x1 + r, y1, x2 - r, y1, x2, y1, x2, y1 + r, x2, y2 - r, x2, y2, x2 - r, y2,
           x1 + r, y2, x1, y2, x1, y2 - r, x1, y1 + r, x1, y1]
    return c.create_polygon(pts, smooth=True, fill=fill, outline=outline, tags=tags)


class LoginScreen:
    # Fondo: pon "login_bg.gif" (animado) o "login_bg.png" junto a este archivo.
    DELAY_GIF = 70      # ms entre cuadros si el fondo es un GIF
    MAX_FRAMES = 150

    def __init__(self, root, on_ok):
        self.root, self.on_ok = root, on_ok
        self.alive = True
        self.busy = False
        self.fails = 0
        self.locked_until = 0.0
        self.tweens = {}
        self.card_dx = 0.0
        self.show_pw = False
        self.fi = 0
        self.frames = self.load_bg()
        iw = self.frames[0].width() if self.frames else 0
        ih = self.frames[0].height() if self.frames else 0
        self.w, self.h = max(iw, 640), max(ih, 400)

        root.title("Launcher · Acceso")
        root.resizable(False, False)
        root.configure(bg="#000000")
        center_window(root, self.w, self.h)
        self.set_alpha(0.0)
        self.v_user = tk.StringVar()
        self.v_pass = tk.StringVar()
        self.c = tk.Canvas(root, width=self.w, height=self.h, bg="#000000", highlightthickness=0, bd=0)
        self.c.pack()
        if self.frames:
            self.bg_item = self.c.create_image(self.w // 2, self.h // 2, image=self.frames[0])
        else:
            self.draw_fallback_bg()
        self.make_particles()
        self.make_glint()
        self.build_card()
        apply_dark_titlebar(root)
        root.bind("<Return>", self.submit)
        self.e_user.focus_set()

        self.t0 = self.last = time.time()
        if len(self.frames) > 1:
            root.after(self.DELAY_GIF, self.next_frame)
        self.tween("in", 1.3, self.step_in, done=self.done_in)
        self.tick()

    # ---------- utilidades ----------
    def set_alpha(self, v):
        try:
            self.root.attributes("-alpha", max(0.0, min(1.0, v)))
        except tk.TclError:
            pass

    def tween(self, key, dur, step, done=None, easing=ease):
        old = self.tweens.pop(key, None)
        if old:
            self.root.after_cancel(old)
        t0 = time.time()

        def tick():
            if not self.alive:
                return
            t = min(1.0, (time.time() - t0) / dur) if dur > 0 else 1.0
            step(easing(t))
            if t < 1.0:
                self.tweens[key] = self.root.after(16, tick)
            else:
                self.tweens.pop(key, None)
                if done:
                    done()

        tick()

    def move_card(self, dx):
        self.c.move("lcard", dx - self.card_dx, 0)
        self.card_dx = dx

    # ---------- fondo ----------
    def load_bg(self):
        for name in ("login_bg.gif", "login.gif", "login_bg.png", "login.png"):
            path = res_path(name)
            if not os.path.exists(path):
                continue
            frames = []
            try:
                if name.endswith(".gif"):
                    for i in range(self.MAX_FRAMES):
                        try:
                            frames.append(tk.PhotoImage(file=path, format=f"gif -index {i}"))
                        except tk.TclError:
                            break
                else:
                    frames.append(tk.PhotoImage(file=path))
            except tk.TclError:
                frames = []
            if frames:
                sub = max(1, math.ceil(frames[0].width() / 1000), math.ceil(frames[0].height() / 700))
                if sub > 1:
                    frames = [f.subsample(sub) for f in frames]
                return frames
        return []

    def next_frame(self):
        if not self.alive:
            return
        self.fi = (self.fi + 1) % len(self.frames)
        try:
            self.c.itemconfigure(self.bg_item, image=self.frames[self.fi])
        except tk.TclError:
            return
        self.root.after(self.DELAY_GIF, self.next_frame)

    def draw_fallback_bg(self):
        cx, cy, R = self.w * 0.7, self.h * 0.4, 360
        for i in range(12):
            r = R * (1 - i / 12)
            self.c.create_oval(cx - r, cy - r, cx + r, cy + r,
                               fill=mix("#000000", "#0e1c40", (i + 1) / 12 * 0.9), outline="")

    def make_particles(self):
        self.parts = []
        for _ in range(46):
            x, y = random.uniform(0, self.w), random.uniform(0, self.h)
            r = random.choice((1, 1, 1, 1.5, 2))
            item = self.c.create_oval(x - r, y - r, x + r, y + r, fill="#000000", outline="")
            self.parts.append([x, y, random.uniform(-6, 6), random.uniform(-16, -4),
                               r, random.uniform(0, 6.28), item])

    def make_glint(self):
        # destello diagonal que cruza la imagen cada pocos segundos
        self.glint = [self.c.create_line(0, 0, 0, 0, fill="#000000", width=w, state="hidden")
                      for w in (1, 2, 1)]

    def tick(self):
        if not self.alive:
            return
        now = time.time()
        t, dt = now - self.t0, min(0.1, now - self.last)
        self.last = now
        c = self.c
        try:
            for p in self.parts:
                p[0] += p[2] * dt + math.sin(t * 0.8 + p[5]) * 6 * dt
                p[1] += p[3] * dt
                if p[1] < -4:
                    p[1], p[0] = self.h + 4, random.uniform(0, self.w)
                if p[0] < -4:
                    p[0] = self.w + 4
                elif p[0] > self.w + 4:
                    p[0] = -4
                a = 0.12 + 0.5 * (0.5 + 0.5 * math.sin(t * 1.6 + p[5]))
                r = p[4]
                c.coords(p[6], p[0] - r, p[1] - r, p[0] + r, p[1] + r)
                c.itemconfigure(p[6], fill=mix("#000000", "#d8d8e6", a))

            u = (t % 6.5) / 1.4
            if u < 1:
                x = -140 + u * (self.w + 280)
                b = math.sin(math.pi * u) * 0.4
                for k, item in enumerate(self.glint):
                    off = (k - 1) * 6
                    c.coords(item, x + off, 0, x + off - 100, self.h)
                    c.itemconfigure(item, state="normal",
                                    fill=mix("#000000", "#ffffff", b * (1 if k == 1 else 0.5)))
            else:
                for item in self.glint:
                    c.itemconfigure(item, state="hidden")

            s = 0.5 + 0.5 * math.sin(t * 2.2)
            c.itemconfigure(self.card_glow, fill=mix("#16306b", ACCENT, s))
        except tk.TclError:
            return
        self.root.after(33, self.tick)

    # ---------- tarjeta de acceso ----------
    def build_card(self):
        c = self.c
        cw, ch = 284, 340
        x0, y0 = 30, (self.h - ch) // 2
        tag = ("lcard",)
        rounded_poly(c, x0, y0, x0 + cw, y0 + ch, tags=tag)
        self.card_glow = c.create_line(x0 + 22, y0 + 1, x0 + cw - 22, y0 + 1,
                                       fill=ACCENT, width=2, tags=tag)
        outer = tk.Frame(c, bg=CARD)
        c.create_window(x0 + 8, y0 + 8, window=outer, anchor="nw", width=cw - 16, height=ch - 16, tags=tag)
        f = tk.Frame(outer, bg=CARD)
        f.pack(fill="both", expand=True, padx=16, pady=10)

        tk.Label(f, text="◈  LAUNCHER", fg=ACCENT_TXT, bg=CARD, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x")
        tk.Label(f, text="Iniciar sesión", fg=FG, bg=CARD, font=("Segoe UI", 18, "bold"),
                 anchor="w").pack(fill="x", pady=(6, 0))
        tk.Label(f, text="Acceso privado · introduce tus datos", fg=DIM, bg=CARD,
                 font=("Segoe UI", 8), anchor="w").pack(fill="x", pady=(0, 12))

        tk.Label(f, text="USUARIO", fg=DIM, bg=CARD, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x")
        self.e_user = make_entry(f, self.v_user, 24)
        self.e_user.pack(fill="x", pady=(2, 8), ipady=5)

        tk.Label(f, text="CONTRASEÑA", fg=DIM, bg=CARD, font=("Segoe UI", 8, "bold"),
                 anchor="w").pack(fill="x")
        row = tk.Frame(f, bg=CARD)
        row.pack(fill="x", pady=(2, 0))
        eye = tk.Label(row, text="Ver", fg=DIM, bg=CARD, font=("Segoe UI", 8), cursor="hand2", width=7)
        eye.pack(side="right")
        self.e_pass = make_entry(row, self.v_pass, 20)
        self.e_pass.config(show="•")
        self.e_pass.pack(side="left", fill="x", expand=True, ipady=5)

        def toggle_pw(e=None):
            self.show_pw = not self.show_pw
            self.e_pass.config(show="" if self.show_pw else "•")
            eye.config(text="Ocultar" if self.show_pw else "Ver")

        eye.bind("<Button-1>", toggle_pw)
        eye.bind("<Enter>", lambda e: fade(eye, "fg", FG, 0.12))
        eye.bind("<Leave>", lambda e: fade(eye, "fg", DIM, 0.18))

        self.msg = tk.Label(f, text="", fg=RED, bg=CARD, font=("Segoe UI", 8), anchor="w")
        self.msg.pack(fill="x", pady=(8, 6))
        self.btn = tk.Button(f, text="Entrar", command=self.submit, relief="flat", bd=0, cursor="hand2",
                             bg=ACCENT, fg=ON_ACCENT, activebackground=ACCENT, activeforeground=ON_ACCENT,
                             font=("Segoe UI", 10, "bold"), pady=6)
        self.btn.bind("<Enter>", lambda e: fade(self.btn, "bg", mix(ACCENT, "#ffffff", 0.18), 0.12))
        self.btn.bind("<Leave>", lambda e: fade(self.btn, "bg", ACCENT, 0.18))
        self.btn.pack(fill="x")

    def say(self, text, col=RED):
        self.msg.config(text=text, fg=col)

    # ---------- animaciones ----------
    def step_in(self, e):
        self.set_alpha(e)
        self.move_card(-60 * (1 - e))

    def done_in(self):
        self.set_alpha(1.0)
        self.move_card(0.0)

    def shake(self):
        base = self.card_dx
        self.tween("shake", 0.45,
                   lambda e: self.move_card(base + 11 * math.sin(e * 6 * math.pi) * (1 - e)),
                   easing=lambda t: t)

    # ---------- validación ----------
    def submit(self, e=None):
        if self.busy or not self.alive:
            return
        now = time.time()
        if now < self.locked_until:
            self.say(f"Demasiados intentos. Espera {int(self.locked_until - now) + 1} s")
            self.shake()
            return
        if check_login(self.v_user.get(), self.v_pass.get()):
            self.success()
            return
        self.fails += 1
        self.v_pass.set("")
        if self.fails >= 5:
            self.fails = 0
            self.locked_until = now + 30
            self.say("Demasiados intentos. Espera 30 s")
        else:
            self.say("Usuario o contraseña incorrectos")
        self.shake()
        self.e_pass.focus_set()

    def success(self):
        self.busy = True
        self.say("Acceso concedido", GREEN)
        self.btn.config(text="✓", bg=GREEN, activebackground=GREEN)
        self.root.unbind("<Return>")

        def step(e):
            self.move_card(-70 * e)
            self.set_alpha(1 - e)

        self.root.after(380, lambda: self.alive and self.tween("out", 0.5, step, done=self.finish))

    def finish(self):
        self.alive = False
        for k in list(self.tweens):
            try:
                self.root.after_cancel(self.tweens.pop(k))
            except Exception:
                pass
        self.c.destroy()
        self.on_ok()


EMBED_B64 = "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"


class VideoBG:
    """Fondo de Inicio: inicio.mp4/.webm/.gif (o inicio_bg.png como imagen fija)."""

    def __init__(self):
        self.ok, self.cap, self.frames, self.still = False, None, [], None
        self.fps, self.idx, self.name = 24.0, 0, ""
        self.native = Image is None
        if self.native:
            try:
                self.still = tk.PhotoImage(data=EMBED_B64)
                self.ok, self.name = True, "(incluido)"
            except tk.TclError:
                pass
            return
        for base in ("inicio", "home", "video", "fondo"):
            for ext in ("mp4", "webm", "mov", "mkv", "avi", "gif"):
                p = res_path(f"{base}.{ext}")
                if os.path.exists(p) and self.open(p):
                    return
        for n in ("inicio_bg.png", "inicio_bg.jpg", "inicio.png", "inicio.jpg"):
            p = res_path(n)
            if os.path.exists(p):
                try:
                    self.still, self.ok, self.name = Image.open(p).convert("RGB"), True, n
                    return
                except Exception:
                    pass
        try:
            self.still = Image.open(io.BytesIO(base64.b64decode(EMBED_B64))).convert("RGB")
            self.ok, self.name = True, "(incluido)"
        except Exception:
            pass

    def open(self, p):
        try:
            if p.endswith(".gif"):
                im = Image.open(p)
                self.fps = min(30.0, 1000.0 / max(20, im.info.get("duration", 70)))
                for f in ImageSequence.Iterator(im):
                    f = f.convert("RGB")
                    f.thumbnail((960, 540))
                    self.frames.append(f)
                    if len(self.frames) >= 150:
                        break
            elif cv2 is not None:
                self.cap = cv2.VideoCapture(p)
                if not self.cap.isOpened():
                    return False
                self.fps = min(30.0, max(10.0, self.cap.get(cv2.CAP_PROP_FPS) or 24.0))
            else:
                return False
            self.ok, self.name = True, os.path.basename(p)
            return True
        except Exception:
            return False

    def next(self):
        if self.cap is not None:
            ok, fr = self.cap.read()
            if not ok:
                self.cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
                ok, fr = self.cap.read()
                if not ok:
                    return None
            return Image.fromarray(cv2.cvtColor(fr, cv2.COLOR_BGR2RGB))
        if self.frames:
            self.idx = (self.idx + 1) % len(self.frames)
            return self.frames[self.idx]
        return self.still

    def render(self, w, h, bright):
        im = self.next()
        if im is None:
            return None
        iw, ih = im.size
        s = max(w / iw, h / ih)
        cw, ch = w / s, h / s
        l, t = (iw - cw) / 2, (ih - ch) / 2
        im = im.resize((w, h), Image.BILINEAR, box=(l, t, l + cw, t + ch))
        return ImageTk.PhotoImage(ImageEnhance.Brightness(im).enhance(bright))


class El:
    """Widget colocado con place(): su posición se recalcula al cambiar el tamaño."""

    def __init__(self, w, g):
        self.w, self.g = w, g
        self.geo = (0, 0, 10, 10)
        self.dy = 0.0
        self.shape, self.r, self.inset = None, 0, 0

    def place(self):
        x, y, w, h = self.geo
        i = self.inset
        self.w.place(x=int(x + i), y=int(y + self.dy + i), width=int(w - 2 * i), height=int(h - 2 * i))

    def hide(self):
        self.w.place_forget()


class App:
    def __init__(self, root):
        self.root = root
        root.title("Launcher")
        root.configure(bg=BG)
        root.minsize(MIN_W, MIN_H)
        root.resizable(True, True)
        center_window(root, W, H)
        try:
            root.attributes("-alpha", 0.0)
        except tk.TclError:
            pass

        self.keys = [["w", "hold"]]   # [tecla, modo]: "hold" = mantener, "tap" = pulsar
        self.new_mode = "hold"
        self.state = "idle"
        self.running = False
        self.counting = False
        self.after_id = None
        self.stop_evt = threading.Event()
        self.thread = None
        self.base = 30.0
        self.q = queue.Queue()
        self.tweens = {}
        self.intro_step = None
        self.page = None
        self.sw, self.sh = W - SB, H
        self.bar_w = self.sw - 2 * PAD
        self.pg = {"main": {"els": [], "items": []}, "afk": {"els": [], "items": []}}
        self.t0 = time.time()
        self.run_start = 0.0
        self.f9_prev = False
        self.slow_last = 0.0
        self.admin = is_admin()
        self.hwnd = 0

        self.v_sched = tk.BooleanVar(value=False)
        self.v_repeat = tk.BooleanVar(value=True)
        self.v_work = tk.StringVar(value="10")
        self.v_rest = tk.StringVar(value="5")
        self.sched_on, self.repeat_on, self.phase, self.phase_end = False, True, "work", 0.0
        self.work_s = self.rest_s = 0
        self.v_mouse = tk.BooleanVar(value=False)
        self.v_random = tk.BooleanVar(value=False)
        self.interval = tk.StringVar(value="30")
        self.v_delay = tk.StringVar(value="3")
        self.delay_s = 3
        self.target = tk.StringVar(value="FiveM")
        self.mouse_on = False
        self.rand_on = False
        self.target_text = "fivem"
        self.v_mouse.trace_add("write", lambda *a: setattr(self, "mouse_on", self.v_mouse.get()))
        self.v_random.trace_add("write", lambda *a: setattr(self, "rand_on", self.v_random.get()))
        self.target.trace_add("write", lambda *a: setattr(self, "target_text", self.target.get().strip().lower()))
        self.v_delay.trace_add("write", self.on_delay)
        self.interval.trace_add("write", self.on_interval)
        for _v in (self.v_sched, self.v_repeat, self.v_work, self.v_rest):
            _v.trace_add("write", self.update_sched)
        for _v in (self.v_delay, self.interval, self.v_random, self.target):
            _v.trace_add("write", lambda *a: self.update_summary())

        self.build_sidebar()
        self.stage = tk.Canvas(root, bg=BG, highlightthickness=0, bd=0)
        self.side.place(x=0, y=0, width=SB, relheight=1)
        self.stage.place(x=SB, y=0, relwidth=1, width=-SB, relheight=1)
        self.draw_background()
        self.build_pill()
        self.build_home()
        self.build_afk()
        self.hwnd = apply_dark_titlebar(root)
        self.relayout()
        self.set_status("idle")
        self.show_page("main", animate=False)
        self.log_startup()
        self.tween("alpha", 0.9, self.set_alpha)
        root.protocol("WM_DELETE_WINDOW", self.on_close)
        self.stage.bind("<Configure>", self.on_resize)
        self.frame()
        self.video_tick()
        self.poll()

    # ---------- Utilidades de animación ----------
    def tween(self, key, dur, step, done=None, easing=ease):
        old = self.tweens.pop(key, None)
        if old:
            self.root.after_cancel(old)
        t0 = time.time()

        def tick():
            t = min(1.0, (time.time() - t0) / dur) if dur > 0 else 1.0
            step(easing(t))
            if t < 1.0:
                self.tweens[key] = self.root.after(16, tick)
            else:
                self.tweens.pop(key, None)
                if done:
                    done()

        tick()

    def cancel_tween(self, key):
        old = self.tweens.pop(key, None)
        if old:
            self.root.after_cancel(old)

    def set_alpha(self, v):
        try:
            self.root.attributes("-alpha", v)
        except tk.TclError:
            pass

    # ---------- Registro de elementos por página ----------
    def reg(self, page, item, g):
        self.pg[page]["items"].append((item, g, self.stage.itemcget(item, "fill")))
        return item

    def el(self, page, w, g, r=0, inset=8):
        e = El(w, g)
        if r:
            e.r, e.inset = r, inset
            e.shape = self.reg(page, self.stage.create_polygon(
                0, 0, 1, 0, 1, 1, smooth=True, fill=CARD, outline=BORDER, tags=(f"page_{page}",)), g)
        self.pg[page]["els"].append(e)
        return e

    def make_card(self, pad):
        outer = tk.Frame(self.stage, bg=CARD)
        inner = tk.Frame(outer, bg=CARD)
        inner.pack(fill="both", expand=True, padx=pad, pady=10)
        return outer, inner

    # ---------- Fondo animado ----------
    def draw_background(self):
        c = self.stage
        self.vid = VideoBG()
        self.vid_item = c.create_image(0, 0, anchor="nw", state="hidden")
        self.vid_photo, self.vid_key, self.vid_t0 = None, None, time.time()
        self.glows = []
        self.e_inst, self.hint_item = None, None
        if Image is None or cv2 is None:
            self.hint_item = self.reg("main", c.create_text(
                PAD, 240, anchor="w", fill=AMBER, font=("Segoe UI", 8), tags=("page_main",),
                text="Fondo fijo. Para reproducir tu video (.mp4) falta Pillow y OpenCV."), "col1")
            self.e_inst = self.el("main", small_button(c, "Instalar soporte de video", self.install_deps, pbg=BG), "col1")
        for fx, fy, k, col in ((0.18, 0.0, 0.36, "#0c1c44"), (1.0, 1.0, 0.40, "#09163a")):
            items = [c.create_oval(0, 0, 1, 1, fill=mix(BG, col, (i + 1) / 12 * 0.9), outline="", tags=("bg",))
                     for i in range(12)]
            self.glows.append((fx, fy, k, items))
        self.waves = [c.create_line(0, 0, 1, 1, smooth=True, width=1,
                                    fill=mix("#080c16", "#1a2a4e", k / 13), tags=("bg",))
                      for k in range(14)]
        if self.hint_item:
            self.stage.tag_raise(self.hint_item)

    def layout_bg(self, sw, sh):
        c = self.stage
        m = max(sw, sh)
        for fx, fy, k, items in self.glows:
            cx, cy, R = fx * sw, fy * sh, k * m
            for i, it in enumerate(items):
                r = R * (1 - i / 12)
                c.coords(it, cx - r, cy - r, cx + r, cy + r)

    def update_waves(self, t):
        sw, sh = max(1, self.sw), self.sh
        for k, item in enumerate(self.waves):
            pts = []
            for x in range(-40, sw + 81, 40):
                y = (sh * 0.54 + k * 5 + sh * 0.125 * math.sin(x / sw * 6.9 + k * 0.07 + t * 0.6)
                     + sh * 0.054 * math.sin(x / sw * 14.4 + 1 + t * 0.9))
                pts += [x, y]
            self.stage.coords(item, *pts)

    # ---------- Barra lateral ----------
    def build_sidebar(self):
        self.side = tk.Frame(self.root, bg=SIDE)
        tk.Frame(self.side, bg=BORDER, width=1).pack(side="right", fill="y")
        head = tk.Frame(self.side, bg=SIDE)
        head.pack(fill="x", padx=18, pady=(24, 18))
        tk.Label(head, text="●", fg=ACCENT, bg=SIDE, font=("Segoe UI", 11)).pack(side="left")
        tk.Label(head, text="Launcher", fg=FG, bg=SIDE, font=("Segoe UI", 10, "bold")).pack(side="left", padx=(8, 0))
        self.nav = {}
        for page, icon, name in (("main", "⌂", "Inicio"), ("afk", "◷", "Afk")):
            row = tk.Frame(self.side, bg=SIDE, cursor="hand2", height=38)
            row.pack(fill="x", padx=10, pady=2)
            row.pack_propagate(False)
            bar = tk.Frame(row, bg=SIDE, width=3)
            bar.pack(side="left", fill="y", pady=7)
            ic = tk.Label(row, text=icon, fg=DIM, bg=SIDE, font=("Segoe UI Symbol", 11), width=3)
            ic.pack(side="left")
            tx = tk.Label(row, text=name, fg=DIM, bg=SIDE, font=FONT)
            tx.pack(side="left")
            for w in (row, ic, tx):
                w.bind("<Button-1>", lambda e, p=page: self.show_page(p))
                w.bind("<Enter>", lambda e, p=page: self.nav_hover(p, True))
                w.bind("<Leave>", lambda e, p=page: self.nav_hover(p, False))
            self.nav[page] = (row, bar, ic, tx)
        foot = tk.Frame(self.side, bg=SIDE)
        foot.pack(side="bottom", fill="x", padx=18, pady=16)
        tk.Label(foot, text="v1.0", fg="#3c4764", bg=SIDE, font=("Segoe UI", 8), anchor="w").pack(side="bottom", fill="x")
        line = tk.Frame(foot, bg=SIDE)
        line.pack(side="bottom", fill="x", pady=(0, 6))
        self.side_dot = tk.Label(line, text="●", fg=DIM, bg=SIDE, font=("Segoe UI", 7))
        self.side_dot.pack(side="left")
        self.side_text = tk.Label(line, text="Buscando ventana...", fg=DIM, bg=SIDE, font=("Segoe UI", 8))
        self.side_text.pack(side="left", padx=(6, 0))

    def nav_hover(self, page, on):
        if page == self.page:
            return
        _, _, ic, tx = self.nav[page]
        for w in (ic, tx):
            fade(w, "fg", FG if on else DIM, 0.12)

    def set_nav(self, page, animate=True):
        for p, (row, bar, ic, tx) in self.nav.items():
            on = p == page
            bg = NAV_ON if on else SIDE
            fg = FG if on else DIM
            for w in (row, ic, tx):
                if animate:
                    fade(w, "bg", bg, 0.25)
                else:
                    w.config(bg=bg)
            for w in (ic, tx):
                if animate:
                    fade(w, "fg", fg, 0.25)
                else:
                    w.config(fg=fg)
            barcol = ACCENT_TXT if on else SIDE
            if animate:
                fade(bar, "bg", barcol, 0.25)
            else:
                bar.config(bg=barcol)

    # ---------- Indicador de estado (arriba a la derecha) ----------
    def build_pill(self):
        self.pill = tk.Frame(self.stage, bg=CARD)
        self.pill_bg = self.stage.create_polygon(0, 0, 1, 0, 1, 1, smooth=True, fill=CARD, outline=BORDER)
        self.pill_dot = tk.Label(self.pill, text="●", fg=DIM, bg=CARD, font=("Segoe UI", 7))
        self.pill_dot.pack(side="left", padx=(12, 6))
        self.pill_text = tk.Label(self.pill, text="DESACTIVADO", fg=DIM, bg=CARD, font=("Segoe UI", 8, "bold"))
        self.pill_text.pack(side="left", padx=(0, 14))

    # ---------- Distribución adaptable ----------
    def on_resize(self, e):
        if e.width < 50 or e.height < 50 or (e.width, e.height) == (self.sw, self.sh):
            return
        self.finish_intro()
        self.sw, self.sh = e.width, e.height
        self.relayout()

    def relayout(self):
        sw, sh = self.sw, self.sh
        self.layout_bg(sw, sh)
        self.layout_home(sw, sh)
        self.layout_afk(sw, sh)
        px, py = max(PAD, sw - PAD - 150), 24
        self.stage.coords(self.pill_bg, *rpts(px, py, px + 150, py + 30, 15))
        self.pill.place(x=px + 5, y=py + 5, width=140, height=20)
        for pg in self.pg.values():
            for e in pg["els"]:
                if e.shape:
                    x, y, w, h = e.geo
                    self.stage.coords(e.shape, *rpts(x, y, x + w, y + h, e.r))
        if self.page:
            for el in self.pg[self.page]["els"]:
                el.place()

    def layout_home(self, sw, sh):
        c = self.stage
        k = max(0.75, min(1.5, min(sw / 800, sh / 560)))
        cx, cy = sw * 0.72, sh * 0.46
        for i, it in enumerate(self.orb):
            r = (160 - i * 15) * k
            c.coords(it, cx - r, cy - r, cx + r, cy + r)
        c.coords(self.orb_text, cx, cy)
        c.itemconfigure(self.orb_text, font=("Segoe UI", int(42 * k), "bold"))
        self.e_chip.geo = (PAD, 112, 130, 28)
        if self.e_admin:
            self.e_admin.geo = (PAD, 182, 210, 28)
        self.e_card.geo = (PAD, sh - 164, min(480, sw - 2 * PAD), 88)
        c.coords(self.hint_home, PAD, sh - 52)
        if self.e_inst:
            self.e_inst.geo = (PAD, 256, 230, 30)

    def layout_afk(self, sw, sh):
        c = self.stage
        aw = sw - 2 * PAD
        gap = 14
        left_w, right_w = 244, 224
        mid_w = max(200, aw - left_w - right_w - 2 * gap)
        top = 176
        bottom = sh - PAD - BAR_H - 14
        ch = max(260, bottom - top)
        xs = (PAD, PAD + left_w + gap, PAD + left_w + gap + mid_w + gap)
        ws = (left_w, mid_w, right_w)
        for i, el in enumerate((self.e_left, self.e_mid, self.e_right)):
            el.geo = (xs[i], top, ws[i], ch)
            c.coords(self.afk_labels[i], xs[i] + 4, top - 14)
        self.e_bar.geo = (PAD, sh - PAD - BAR_H, aw, BAR_H)
        self.bar_w = aw - 18

    # ---------- Páginas y transiciones ----------
    def show_page(self, page, animate=True):
        if page == self.page:
            return
        self.finish_intro()
        c = self.stage
        old, self.page = self.page, page
        if old:
            for el in self.pg[old]["els"]:
                el.hide()
        for p in self.pg:
            c.itemconfigure(f"page_{p}", state="normal" if p == page else "hidden")
        self.set_nav(page, animate and bool(old))
        vid_on = page == "main" and self.vid.ok
        c.itemconfigure(self.vid_item, state="normal" if vid_on else "hidden")
        c.itemconfigure("bg", state="hidden" if vid_on else "normal")
        if vid_on:
            for it in self.orb + [self.orb_text]:
                c.itemconfigure(it, state="hidden")
            self.vid_t0, self.vid_key = time.time(), None
        if animate and old:
            self.play_intro(page)
        else:
            for el in self.pg[page]["els"]:
                el.dy = 0.0
                el.place()

    def play_intro(self, page):
        # Entrada escalonada: cada bloque sube y aparece con un pequeño retardo.
        self.finish_intro()
        c = self.stage
        pg = self.pg[page]
        applied = {}
        total, per = 2.0, 0.9
        full = "Mantener teclas"

        def prog(t, g):
            return max(0.0, min(1.0, (t - DELAYS[g]) / per))

        def step(e, final=False):
            t = e * total
            for it, g, base in pg["items"]:
                p = 1.0 if final else prog(t, g)
                q = ease(p)
                dy = 26 * (1 - q)
                d = dy - applied.get(it, 0.0)
                if d:
                    c.move(it, 0, d)
                    applied[it] = dy
                c.itemconfigure(it, state="normal" if p > 0 else "hidden", fill=mix(BG, base, q))
            for el in pg["els"]:
                p = 1.0 if final else prog(t, el.g)
                el.dy = 26 * (1 - ease(p))
                if p >= 0.6:
                    el.place()
                else:
                    el.hide()
            if page == "afk":
                ph = 1.0 if final else max(0.0, min(1.0, t / 1.1))
                n = len(full) if ph >= 1 else max(1, int(len(full) * ph))
                c.itemconfigure(self.afk_title, text=full[:n])
                pl = 1.0 if final else max(0.0, min(1.0, (t - 0.4) / 0.9))
                c.coords(self.afk_line, PAD, 58, PAD + 60 * ease(pl), 58)
                c.itemconfigure(self.afk_line, state="normal" if pl > 0 else "hidden")

        self.intro_step = step
        self.tween("intro", total, step, done=self._intro_done, easing=lambda t: t)

    def _intro_done(self):
        self.intro_step = None

    def finish_intro(self):
        # Si se cambia de página o de tamaño a mitad de animación, todo queda en su sitio final.
        if self.intro_step is None:
            return
        step, self.intro_step = self.intro_step, None
        self.cancel_tween("intro")
        step(1.0, final=True)

    # ---------- Página Inicio ----------
    def build_home(self):
        c, t = self.stage, ("page_main",)
        self.orb = [c.create_oval(0, 0, 1, 1, fill=BG, outline="", tags=t) for _ in range(10)]
        self.orb_text = c.create_text(0, 0, text="AFK", fill="#2a4a96", font=("Segoe UI", 42, "bold"), tags=t)
        self.update_orb(0.0)
        self.reg("main", c.create_text(PAD, 84, anchor="w", text="Anti AFK", fill=FG,
                                       font=("Segoe UI", 30, "bold"), tags=t), "head")
        chip = tk.Frame(c, bg=CARD)
        self.chip_dot = tk.Label(chip, text="●", fg=GREEN, bg=CARD, font=("Segoe UI", 7))
        self.chip_dot.pack(side="left", padx=(12, 6))
        self.chip_text = tk.Label(chip, text="Listo", fg=DIM, bg=CARD, font=("Segoe UI", 8))
        self.chip_text.pack(side="left", padx=(0, 12))
        self.e_chip = self.el("main", chip, "col1", r=14, inset=5)
        self.reg("main", c.create_text(PAD, 164, anchor="w",
                                       text="● Administrador" if self.admin else "○ Sin permisos de administrador",
                                       fill=GREEN if self.admin else AMBER, font=("Segoe UI", 9), tags=t), "col1")
        self.e_admin = None
        if not self.admin and IS_WIN:
            self.e_admin = self.el("main", small_button(c, "Reiniciar como administrador", self.relaunch_admin, pbg=BG), "col1")

        card = tk.Frame(c, bg=CARD)
        RBtn(card, "◷", None, bg=KEYCAP, fg=ACCENT_TXT, font=("Segoe UI Symbol", 14), w=52, h=40, r=12, pbg=CARD).pack(side="left", padx=(8, 12), pady=8)
        info = tk.Frame(card, bg=CARD)
        info.pack(side="left", fill="y", pady=12)
        tk.Label(info, text="Afk", fg=FG, bg=CARD, font=("Segoe UI", 10, "bold"), anchor="w").pack(fill="x")
        tk.Label(info, text="Mantener o pulsar teclas", fg=DIM, bg=CARD, font=("Segoe UI", 8),
                 anchor="w").pack(fill="x")
        small_button(card, "Abrir ↗", lambda: self.show_page("afk")).pack(side="right", padx=10, pady=12)
        self.home_status = tk.Label(card, text="Listo para usar", fg=DIM, bg=CARD, font=("Segoe UI", 8))
        self.home_status.pack(side="right", padx=8)
        self.e_card = self.el("main", card, "col2", r=18)
        self.hint_home = self.reg("main", c.create_text(PAD, 0, anchor="w", text="◈  Atajo global: F5 activar / pausar",
                                                         fill=DIM, font=("Segoe UI", 8), tags=t), "col2")

    def update_orb(self, t):
        for i, item in enumerate(self.orb):
            v = i / 9
            wave = 0.5 + 0.5 * math.sin(t * 1.4 - i * 0.55)
            col = mix(mix(BG, "#10224a", v), "#2146a0", wave * 0.35 * v)
            self.stage.itemconfigure(item, fill=col)
        wave = 0.5 + 0.5 * math.sin(t * 1.4)
        self.stage.itemconfigure(self.orb_text, fill=mix("#274a9c", "#4f7be8", wave))

    def install_deps(self):
        if getattr(sys, "frozen", False):
            self.append_log("Instala con pip")
            return
        self.e_inst.w.config(text="Instalando…")
        self.append_log("Instalando soporte")

        def run():
            try:
                import subprocess
                subprocess.run([sys.executable, "-m", "pip", "install", "pillow", "opencv-python"],
                               check=True, capture_output=True, creationflags=0x08000000 if IS_WIN else 0)
                self.q.put(("restart", None))
            except Exception:
                self.q.put(("log", "Falló la instalación"))

        threading.Thread(target=run, daemon=True).start()

    def relaunch_admin(self):
        try:
            params = "" if getattr(sys, "frozen", False) else f'"{os.path.abspath(sys.argv[0])}"'
            ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
            self.on_close()
        except Exception:
            self.append_log("No se pudo reiniciar como admin")

    # ---------- Página Afk ----------
    def build_afk(self):
        c, t = self.stage, ("page_afk",)
        self.reg("afk", c.create_text(PAD, 40, anchor="w", text="◷  AFK", fill=ACCENT_TXT,
                                      font=("Segoe UI", 8, "bold"), tags=t), "head")
        self.reg("afk", c.create_text(PAD + 52, 40, anchor="w", text="/ KEY ENGINE", fill=DIM,
                                      font=("Segoe UI", 8), tags=t), "head")
        self.afk_title = self.reg("afk", c.create_text(PAD, 88, anchor="w", text="Mantener teclas", fill=FG,
                                                       font=("Segoe UI", 26, "bold"), tags=t), "head")
        self.afk_line = c.create_line(PAD, 58, PAD + 60, 58, fill=ACCENT, width=2, tags=t)
        self.reg("afk", c.create_text(PAD, 124, anchor="w", text="Mantén pulsadas o pulsa teclas cada cierto tiempo.",
                                      fill=DIM, font=("Segoe UI", 9), tags=t), "head")
        self.afk_labels = []
        for i, txt in enumerate(("NUEVA TECLA", "TECLAS", "ACTIVIDAD")):
            self.afk_labels.append(self.reg("afk", c.create_text(0, 0, anchor="w", text=txt, fill=DIM,
                                                                 font=("Segoe UI", 8, "bold"), tags=t), f"col{i + 1}"))

        # --- izquierda: nueva tecla y ajustes
        self.win_sig, self.win_items = None, []
        outer, f = self.make_card(12)
        self.e_left = self.el("afk", outer, "col1", r=18)
        self.seg = Segmented(f, (("hold", "Mantener"), ("tap", "Pulsar")), self.set_new_mode)
        self.seg.pack(fill="x", pady=(0, 6))
        self.mode_cap = tk.Label(f, text=MODE_CAP["hold"], fg=DIM, bg=CARD, font=("Segoe UI", 8),
                                 anchor="w", justify="left", wraplength=196)
        self.mode_cap.pack(fill="x", pady=(0, 8))
        self.btn_add = small_button(f, "Agregar tecla", self.start_capture)
        self.btn_add.pack(fill="x")
        self.hint = tk.Label(f, text="Pulsa el botón y luego la tecla.", fg=DIM, bg=CARD,
                             font=("Segoe UI", 8), anchor="w")
        self.hint.pack(fill="x", pady=(5, 0))
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=8)
        stepper(f, self.v_delay, "Empezar después de", "Espera desde que activas hasta que empieza.",
                "segundos", 0, 300, 1).pack(fill="x", pady=(0, 8))
        stepper(f, self.interval, "Repetir cada", "Cada cuánto se pulsan las teclas «Pulsar» y se mueve el mouse.",
                "segundos", 1, 3600, 5).pack(fill="x", pady=(0, 8))
        Check(f, "Mover mouse", self.v_mouse).pack(anchor="w", pady=2)
        Check(f, "Intervalo aleatorio (±20%)", self.v_random).pack(anchor="w", pady=2)
        tk.Frame(f, bg=BORDER, height=1).pack(fill="x", pady=8)
        self.summary = tk.Label(f, text="", fg=ACCENT_TXT, bg=CARD, font=("Segoe UI", 8),
                                anchor="w", justify="left", wraplength=196)
        self.summary.pack(fill="x")
        self.update_summary()

        # --- centro: teclas / aplicaciones abiertas
        outer, f = self.make_card(10)
        self.e_mid = self.el("afk", outer, "col2", r=18)
        self.tabs = Segmented(f, (("keys", "Teclas"), ("apps", "Apps"), ("plan", "Horario")), self.set_tab)
        self.tabs.pack(fill="x", pady=(0, 8))
        self.tab_keys = tk.Frame(f, bg=CARD)
        self.tab_apps = tk.Frame(f, bg=CARD)
        self.tab_keys.pack(fill="both", expand=True)
        tk.Label(self.tab_keys, text=f"Máx. {MAX_KEYS} · clic en el modo para cambiarlo", fg=DIM, bg=CARD,
                 font=("Segoe UI", 8)).pack(side="bottom", anchor="w")
        self.warn = tk.Label(self.tab_keys, text="", fg=AMBER, bg=CARD, font=("Segoe UI", 8), anchor="w",
                             justify="left", wraplength=250)
        self.warn.pack(side="bottom", fill="x")
        self.rows = tk.Frame(self.tab_keys, bg=CARD)
        self.rows.pack(fill="both", expand=True)
        self.last_cap = None
        self.refresh_rows()
        top = tk.Frame(self.tab_apps, bg=CARD)
        top.pack(fill="x")
        tk.Label(top, text="Ventana objetivo", fg=FG, bg=CARD, font=("Segoe UI", 9, "bold")).pack(side="left")
        self.apps_info = tk.Label(top, text="", fg=DIM, bg=CARD, font=("Segoe UI", 8))
        self.apps_info.pack(side="right")
        rentry(self.tab_apps, self.target, 18).pack(fill="x", pady=(4, 2))
        tip = tk.Label(self.tab_apps, text="Las teclas solo se envían con esta ventana al frente. "
                       "Elige una app (puedes editar el texto).", fg=DIM, bg=CARD, font=("Segoe UI", 8),
                       anchor="w", justify="left")
        tip.pack(fill="x", pady=(0, 6))
        tip.bind("<Configure>", lambda e: tip.config(wraplength=max(120, e.width - 4)))
        self.win_list = tk.Canvas(self.tab_apps, bg=CARD, highlightthickness=0, bd=0)
        self.win_list.pack(fill="both", expand=True)
        self.win_list.bind("<Configure>", lambda e: self.win_sig and self.draw_apps())
        self.win_list.bind("<Enter>", lambda e: self.win_list.bind_all("<MouseWheel>", self.wheel))
        self.win_list.bind("<Leave>", lambda e: self.win_list.unbind_all("<MouseWheel>"))
        small_button(self.tab_apps, "Actualizar lista", lambda: self.scan_windows(True)).pack(fill="x", pady=(6, 0))

        self.tab_plan = tk.Frame(f, bg=CARD)
        Check(self.tab_plan, "Activar horario", self.v_sched).pack(anchor="w", pady=(2, 8))
        stepper(self.tab_plan, self.v_work, "Trabajar durante", "Tiempo que el anti-AFK está activo.",
                "minutos", 1, 600, 5).pack(fill="x", pady=(0, 8))
        stepper(self.tab_plan, self.v_rest, "Descansar", "Pausa en la que se sueltan todas las teclas.",
                "minutos", 0, 600, 1).pack(fill="x", pady=(0, 8))
        Check(self.tab_plan, "Repetir el ciclo", self.v_repeat).pack(anchor="w", pady=2)
        self.sched_sum = tk.Label(self.tab_plan, text="", fg=ACCENT_TXT, bg=CARD, font=("Segoe UI", 9),
                                  anchor="w", justify="left", wraplength=250)
        self.sched_sum.pack(fill="x", pady=(10, 0))
        self.update_sched()

        # --- derecha: actividad
        outer, f = self.make_card(8)
        self.e_right = self.el("afk", outer, "col3", r=18)
        self.status_lbl = tk.Label(f, text="DESACTIVADO", fg=DIM, bg=CARD, font=("Segoe UI", 13, "bold"))
        self.status_lbl.pack(pady=(8, 0))
        self.status_sub = tk.Label(f, text="", fg=DIM, bg=CARD, font=("Segoe UI", 8))
        self.status_sub.pack(pady=(0, 10))
        lc = RCard(f, "#070b14", CARD, 12, 10, 4)
        lc.pack(fill="both", expand=True)
        self.logbox = tk.Text(lc.inner, bg="#070b14", fg="#8b95b0", font=MONO, relief="flat", bd=0,
                              highlightthickness=0, wrap="none", state="disabled", padx=8, pady=6)
        self.logbox.pack(fill="both", expand=True)

        # --- barra inferior
        bar = tk.Frame(c, bg=CARD)
        self.e_bar = self.el("afk", bar, "foot", r=20)
        RBtn(bar, "F5", None, bg=KEYCAP, fg=FG, font=("Consolas", 9, "bold"), w=42, h=28, r=9, pbg=CARD).pack(side="left", padx=(10, 8))
        tk.Label(bar, text="activar / pausar", fg=DIM, bg=CARD, font=("Segoe UI", 8)).pack(side="left")
        self.btn_base = ACCENT
        self.btn_main = RBtn(bar, "Activar", self.toggle, bg=ACCENT, fg=ON_ACCENT, font=("Segoe UI", 9, "bold"), w=190, h=36, r=15, pbg=CARD)
        self.btn_main.pack(side="right", padx=6, pady=4, fill="y")
        self.btn_main.bind("<Enter>", lambda e: fade(self.btn_main, "bg", mix(self.btn_base, "#ffffff", 0.18), 0.12))
        self.btn_main.bind("<Leave>", lambda e: fade(self.btn_main, "bg", self.btn_base, 0.18))
        tk.Label(bar, text="Mantener = tecla sostenida · Pulsar = cada intervalo", fg=DIM, bg=CARD,
                 font=("Segoe UI", 8)).pack(side="right", padx=16)
        self.prog = tk.Frame(bar, bg=ACCENT)   # barra de progreso de la cuenta atrás (se coloca con place)

    def prog_set(self, f):
        w = int(self.bar_w * max(0.0, min(1.0, f)))
        if w <= 0:
            self.prog.place_forget()
        else:
            self.prog.place(x=1, y=BAR_H - 21, width=w, height=3)

    # ---------- Tiempo de inicio e intervalo editables ----------
    def start_text(self):
        return f"Activar en {self.delay_s} s" if self.delay_s > 0 else "Activar ya"

    def on_delay(self, *a):
        try:
            v = int(float(self.v_delay.get().replace(",", ".")))
        except ValueError:
            return
        self.delay_s = max(0, min(300, v))
        if self.state == "idle" and not self.counting and hasattr(self, "btn_main"):
            self.btn_main.config(text=self.start_text())

    def on_interval(self, *a):
        try:
            self.base = max(1.0, float(self.interval.get().replace(",", ".")))
        except ValueError:
            pass

    def set_new_mode(self, mode):
        self.new_mode = mode
        if hasattr(self, "mode_cap"):
            self.mode_cap.config(text=MODE_CAP[mode])

    def set_tab(self, key):
        frames = {"keys": self.tab_keys, "apps": self.tab_apps, "plan": self.tab_plan}
        for fr in frames.values():
            fr.pack_forget()
        frames[key].pack(fill="both", expand=True)
        if key == "apps":
            self.scan_windows(True)

    def scan_windows(self, force=False):
        if not force and not (self.page == "afk" and self.tabs.sel == "apps"):
            return
        wins = sorted((w for w in list_windows(self.hwnd) if w[0] not in ("Launcher", "Launcher · Acceso")),
                      key=lambda w: (w[1].lower(), w[0].lower()))
        sig = (tuple(wins), self.target_text)
        if sig == self.win_sig and not force:
            return
        self.win_sig, self.win_items = sig, wins
        self.apps_info.config(text=f"{len(wins)} abiertas")
        self.draw_apps()

    def wheel(self, e):
        self.win_list.yview_scroll(int(-e.delta / 120) * 2, "units")

    def draw_apps(self):
        c = self.win_list
        top = c.yview()[0]
        c.delete("all")
        w = max(120, c.winfo_width() - 8)
        n = max(8, int((w - 70) / 7))
        rows = [("Cualquier ventana", "Sin filtro · envía a la ventana activa", not self.target_text)]
        for t, p in self.win_items:
            rows.append((t if len(t) <= n else t[:n - 1] + "…", p, bool(self.target_text) and self.target_text in t.lower()))
        y, self.polys = 4, {}
        for i, (title, sub, hit) in enumerate(rows):
            tag, base = f"r{i}", ("#12306f" if hit else ROW)
            poly = c.create_polygon(*rpts(4, y, 4 + w, y + 42, 13), smooth=True, fill=base,
                                    outline=GREEN if hit else BORDER, tags=(tag,))
            c.create_text(20, y + 21, text="●" if hit else "○", anchor="w", fill=GREEN if hit else DIM,
                          font=("Segoe UI", 8), tags=(tag,))
            c.create_text(40, y + 14, text=title, anchor="w", fill=FG, font=("Segoe UI", 9, "bold"), tags=(tag,))
            c.create_text(40, y + 29, text=sub, anchor="w", fill=DIM, font=("Segoe UI", 8), tags=(tag,))
            c.tag_bind(tag, "<Button-1>", lambda e, i=i: self.on_pick(i))
            c.tag_bind(tag, "<Enter>", lambda e, p=poly, b=base: c.itemconfigure(p, fill=mix(b, ACCENT, 0.25)))
            c.tag_bind(tag, "<Leave>", lambda e, p=poly, b=base: c.itemconfigure(p, fill=b))
            self.polys[i] = poly
            y += 48
        c.configure(scrollregion=(0, 0, w + 8, y))
        c.yview_moveto(top)

    def on_pick(self, i):
        if i == 0:
            self.target.set("")
        else:
            t, p = self.win_items[i - 1]
            self.target.set("FiveM" if p.lower().startswith(("fivem", "gta5"))
                            else re.split(r"\s[-–—]\s", t)[-1].strip()[:40])
        self.append_log(f"Objetivo: {self.target.get() or 'ninguno'}")
        self.scan_windows(True)
        poly = self.polys.get(i)
        if poly:
            self.tween("pick", 0.8, lambda e: self.win_list.itemconfigure(poly, fill=mix(ACCENT, "#12306f", e)))

    def mins(self, var, default):
        try:
            return max(0.0, float(var.get().replace(",", ".")))
        except ValueError:
            return default

    def update_sched(self, *a):
        if not hasattr(self, "sched_sum"):
            return
        w, r = self.mins(self.v_work, 10), self.mins(self.v_rest, 5)
        if not self.v_sched.get():
            t = "Desactivado: el anti-AFK funciona hasta que lo detengas."
        elif self.v_repeat.get():
            t = f"Activo {w:g} min → descansa {r:g} min → vuelve a empezar."
        else:
            t = f"Activo {w:g} min y se detiene solo."
        self.sched_sum.config(text=t)

    def update_warn(self):
        hk = {k for k, m in self.keys if m == "hold"}
        for a, b in (("w", "s"), ("a", "d"), ("up", "down"), ("left", "right")):
            if a in hk and b in hk:
                self.warn.config(text=f"⚠ {a.upper()} y {b.upper()} en «Mantener» se cancelan: el personaje no se mueve.")
                return
        self.warn.config(text="")

    def update_summary(self):
        if not hasattr(self, "summary"):
            return
        rnd = " (±20% aleatorio)" if self.rand_on else ""
        self.summary.config(text=f"▸ Empieza {self.delay_s} s después de activar\n"
                                 f"▸ Repite cada {self.base:g} s{rnd}\n"
                                 f"▸ Ventana: {self.target.get().strip() or 'cualquiera'}")

    def refresh_rows(self, flash_last=False):
        self.update_warn()
        for w in self.rows.winfo_children():
            w.destroy()
        self.last_cap = None
        if not self.keys:
            tk.Label(self.rows, text="Sin teclas.\nAgrega una con «Agregar tecla».", fg=DIM, bg=CARD,
                     font=("Segoe UI", 9), justify="center").pack(pady=70)
            return
        for i, (k, m) in enumerate(self.keys):
            rc = RCard(self.rows, ROW, CARD, 14, 46)
            rc.pack(fill="x", pady=3)
            row = rc.inner
            cap = RBtn(row, k.upper(), None, bg=KEYCAP, fg=FG, font=("Consolas", 10, "bold"), w=80, h=30, r=10, pbg=ROW)
            cap.pack(side="left", padx=(2, 8), pady=4)
            chip = tk.Label(row, text="Mantener" if m == "hold" else "Pulsar",
                            fg=ACCENT_TXT if m == "hold" else FG, bg=ROW, font=("Segoe UI", 9), cursor="hand2")
            chip.pack(side="left", padx=6)
            chip.bind("<Button-1>", lambda e, i=i: self.toggle_mode(i))
            x = tk.Label(row, text="✕", fg=DIM, bg=ROW, font=("Segoe UI", 10), cursor="hand2")
            x.pack(side="right", padx=10)
            x.bind("<Button-1>", lambda e, i=i: self.remove_key(i))
            x.bind("<Enter>", lambda e, w=x: fade(w, "fg", RED, 0.12))
            x.bind("<Leave>", lambda e, w=x: fade(w, "fg", DIM, 0.18))
            self.last_cap = cap
        if flash_last and self.last_cap is not None:
            cap = self.last_cap
            row = cap.master.master
            cap.config(bg=ACCENT, fg=ON_ACCENT)
            fade(cap, "bg", KEYCAP, 0.6)
            fade(cap, "fg", FG, 0.6)
            row.pack_configure(padx=(90, 0))

            def slide(e):
                try:
                    row.pack_configure(padx=(int(90 * (1 - e)), 0))
                except tk.TclError:
                    pass

            self.tween("rowin", 0.8, slide)

    def toggle_mode(self, i):
        self.keys[i][1] = "tap" if self.keys[i][1] == "hold" else "hold"
        hold = self.keys[i][1] == "hold"
        self.update_warn()
        try:
            chip = self.rows.winfo_children()[i].winfo_children()[0].winfo_children()[1]
        except IndexError:
            return self.refresh_rows()
        chip.config(text="Mantener" if hold else "Pulsar", bg=ACCENT, fg=ON_ACCENT)
        fade(chip, "bg", ROW, 0.6)
        fade(chip, "fg", ACCENT_TXT if hold else FG, 0.6)

    def remove_key(self, i):
        if getattr(self, "_removing", False):
            return
        try:
            row = self.rows.winfo_children()[i]
        except IndexError:
            return
        self._removing = True

        def slide(e):
            try:
                row.pack_configure(padx=(int(170 * e), 0))
            except tk.TclError:
                pass

        def done():
            self._removing = False
            if i < len(self.keys):
                self.keys.pop(i)
            self.refresh_rows()

        self.tween("rowout", 0.45, slide, done=done)

    # ---------- Captura de teclas ----------
    def start_capture(self):
        if len(self.keys) >= MAX_KEYS:
            self.hint.config(text=f"Máximo {MAX_KEYS} teclas.", fg=RED)
            return
        self.btn_add.config(text="Pulsa una tecla...")
        fade(self.btn_add, "bg", "#22358a", 0.3)
        self.root.focus_set()  # evita que el botón reaccione a la tecla pulsada
        self.root.bind("<Key>", self.on_key)

    def on_key(self, e):
        self.root.unbind("<Key>")
        self.btn_add.config(text="Agregar tecla")
        fade(self.btn_add, "bg", BTN, 0.3)
        name = KEYSYM_MAP.get(e.keysym, e.keysym.lower())
        if name not in SCAN:
            self.hint.config(text=f"Tecla no compatible: {e.keysym}", fg=RED)
        elif any(k == name for k, _ in self.keys):
            self.hint.config(text=f"«{name}» ya está en la lista.", fg=DIM)
        else:
            self.keys.append([name, self.new_mode])
            self.refresh_rows(flash_last=True)
            self.hint.config(text=f"Agregada: {name}", fg=DIM)

    # ---------- Estado, animación de pulso y registro ----------
    def set_status(self, state):
        self.state = state
        txt, col, sub, chip, btn_txt, btn_bg = {
            "idle": ("DESACTIVADO", DIM, "F5 para activar", "Listo", self.start_text(), ACCENT),
            "wait": ("INICIANDO", ACCENT_TXT, "Preparando...", "Iniciando", None, "#1b2a55"),
            "run": ("ACTIVO", GREEN, "Activo · 00:00", "Activo", "Detener", "#c93c44"),
        }[state]
        self.status_lbl.config(text=txt)
        fade(self.status_lbl, "fg", col, 0.3)
        self.status_sub.config(text=sub)
        self.chip_text.config(text=chip)
        self.pill_text.config(text=txt)
        fade(self.pill_text, "fg", col, 0.3)
        dot = GREEN if state == "idle" else (ACCENT_TXT if state == "wait" else GREEN)
        self.chip_dot.config(fg=dot)
        self.pill_dot.config(fg=DIM if state == "idle" else dot)
        self.home_status.config(text={"idle": "Listo para usar", "wait": "Iniciando...",
                                      "run": "En ejecución"}[state])
        fade(self.home_status, "fg", GREEN if state == "run" else DIM, 0.3)
        self.btn_base = btn_bg
        fade(self.btn_main, "bg", btn_bg, 0.25)
        self.btn_main.config(fg=ON_ACCENT, activebackground=btn_bg, activeforeground=ON_ACCENT)
        if btn_txt:
            self.btn_main.config(text=btn_txt)

    def update_pulse(self, t):
        if self.state == "idle":
            return
        s = 0.5 + 0.5 * math.sin(t * 4)
        col = ACCENT_TXT if self.state == "wait" else GREEN
        cc = mix(CARD, col, 0.4 + 0.6 * s)
        self.chip_dot.config(fg=cc)
        self.pill_dot.config(fg=cc)

    def frame(self):
        t = time.time() - self.t0
        if not (self.page == "main" and self.vid.ok):
            self.update_waves(t)
            if self.page == "main":
                self.update_orb(t)
        self.update_pulse(t)
        self.root.after(40, self.frame)

    def append_log(self, msg):
        self.logbox.config(state="normal")
        self.logbox.insert("end", f"{time.strftime('%H:%M:%S')}  {msg}\n")
        if int(self.logbox.index("end-1c").split(".")[0]) > 200:
            self.logbox.delete("1.0", "2.0")
        self.logbox.see("end")
        self.logbox.config(state="disabled")

    def video_tick(self):
        try:
            if self.page == "main" and self.vid.ok and self.sw > 50 and self.root.state() != "iconic":
                if self.vid.native:
                    iw, ih = self.vid.still.width(), self.vid.still.height()
                    a = max(1, math.ceil(max(self.sw / iw, self.sh / ih) * 2))
                    if a != self.vid_key:
                        self.vid_photo, self.vid_key = self.vid.still.zoom(a).subsample(2), a
                        self.stage.itemconfigure(self.vid_item, image=self.vid_photo, anchor="center")
                    self.stage.coords(self.vid_item, self.sw / 2, self.sh / 2)
                    self.root.after(100, self.video_tick)
                    return
                f = ease(min(1.0, (time.time() - self.vid_t0) / 1.8))   # fundido lento al entrar
                key = (self.sw, self.sh, round(f, 2))
                if not (self.vid.still is not None and key == self.vid_key):
                    ph = self.vid.render(int(self.sw), int(self.sh), 0.85 * f)
                    if ph:
                        self.vid_photo, self.vid_key = ph, key
                        self.stage.itemconfigure(self.vid_item, image=ph)
        except tk.TclError:
            return
        self.root.after(int(1000 / self.vid.fps), self.video_tick)

    def log_startup(self):
        self.append_log(f"Fondo: {self.vid.name}" if self.vid.ok else "Sin fondo (falta pillow)")
        if not IS_WIN:
            self.append_log("Solo funciona en Windows")
        elif self.admin:
            self.append_log("Modo administrador")
        else:
            self.append_log("Sin admin: si FiveM no")
            self.append_log("responde, abre como admin")

    # ---------- Bucle de interfaz (cola, F5, detección de ventana) ----------
    def poll(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "log":
                    self.append_log(data)
                elif kind == "restart":
                    import subprocess
                    subprocess.Popen([sys.executable] + sys.argv)
                    self.on_close()
                    return
                elif kind == "died" and data is self.stop_evt and self.running:
                    self.running = False
                    self.set_status("idle")
        except queue.Empty:
            pass
        if IS_WIN:
            down = bool(user32.GetAsyncKeyState(0x74) & 0x8000)  # F5
            if down and not self.f9_prev:
                self.toggle()
            self.f9_prev = down
        now = time.time()
        if now - self.slow_last >= 1.0:
            self.slow_last = now
            self.slow_tick()
        self.root.after(30, self.poll)

    def slow_tick(self):
        self.scan_windows()
        if self.running:
            s = int(time.time() - self.run_start)
            if self.sched_on:
                left = max(0, int(self.phase_end - time.time()))
                s = left
                self.status_sub.config(text=f"{'Activo' if self.phase == 'work' else 'Descanso'} · quedan {s // 60:02d}:{s % 60:02d}")
            else:
                self.status_sub.config(text=f"Activo · {s // 60:02d}:{s % 60:02d}")
        name = self.target.get().strip()
        if not name:
            self.side_text.config(text="Sin ventana objetivo")
            self.side_dot.config(fg=DIM)
        elif find_window(self.target_text, self.hwnd):
            self.side_text.config(text=f"{name} detectado")
            self.side_dot.config(fg=GREEN)
        else:
            self.side_text.config(text=f"{name} no detectado")
            self.side_dot.config(fg=AMBER)

    # ---------- Control ----------
    def toggle(self):
        if self.running:
            self.stop_engine()
        elif self.counting:
            self.counting = False
            if self.after_id:
                self.root.after_cancel(self.after_id)
            self.cancel_tween("prog")
            self.prog_set(0.0)
            self.set_status("idle")
            self.append_log("Cancelado")
        else:
            if not self.keys and not self.mouse_on:
                self.append_log("Agrega teclas o activa mouse")
                return
            self.counting = True
            n = self.delay_s
            self.prog_set(0.0)
            if n > 0:
                self.tween("prog", float(n), self.prog_set, easing=lambda t: t)
            self.countdown(n)

    def countdown(self, n):
        if not self.counting:
            return
        if n > 0:
            self.set_status("wait")
            self.btn_main.config(text=f"Cancelar ({n} s)")
            self.after_id = self.root.after(1000, lambda: self.countdown(n - 1))
        else:
            self.counting = False
            self.cancel_tween("prog")
            self.prog_set(0.0)
            self.start_engine()

    def start_engine(self):
        try:
            self.base = max(1.0, float(self.interval.get().replace(",", ".")))
        except ValueError:
            self.append_log("Intervalo no válido")
            self.set_status("idle")
            return
        if self.target_text:
            h = find_window(self.target_text, self.hwnd)
            if h:
                if self.target_text not in foreground_title().lower():
                    focus_window(h)
                self.append_log("Ventana enfocada")
            else:
                self.append_log("Ventana no encontrada")
        hk = {k for k, m in self.keys if m == "hold"}
        for a, b in (("w", "s"), ("a", "d")):
            if a in hk and b in hk:
                self.append_log(f"Aviso: {a.upper()} y {b.upper()} se cancelan")
        self.sched_on, self.repeat_on = self.v_sched.get(), self.v_repeat.get()
        self.work_s, self.rest_s = int(self.mins(self.v_work, 10) * 60), int(self.mins(self.v_rest, 5) * 60)
        self.phase, self.phase_end = "work", time.time() + self.work_s
        self.stop_evt = threading.Event()
        self.running = True
        self.run_start = time.time()
        self.thread = threading.Thread(target=self.loop, args=(self.stop_evt,), daemon=True)
        self.thread.start()
        self.set_status("run")
        self.append_log("Activado")

    def stop_engine(self):
        self.running = False
        self.stop_evt.set()
        self.set_status("idle")
        self.append_log("Detenido, teclas soltadas")

    def loop(self, evt):
        down = set()
        next_tap = 0.0
        paused = False
        try:
            while not evt.is_set():
                if self.sched_on:
                    n0 = time.time()
                    if n0 >= self.phase_end:
                        if self.phase == "work":
                            if not self.repeat_on:
                                self.q.put(("log", "Tiempo cumplido"))
                                self.q.put(("died", evt))
                                break
                            self.phase, self.phase_end = "rest", n0 + self.rest_s
                            for k in list(down):
                                key_up(k)
                            down.clear()
                            self.q.put(("log", "Descanso"))
                        else:
                            self.phase, self.phase_end, next_tap = "work", n0 + self.work_s, 0.0
                            self.q.put(("log", "Nuevo ciclo"))
                    if self.phase == "rest":
                        evt.wait(0.2)
                        continue
                target = self.target_text
                if target and target not in foreground_title().lower():
                    if not paused:
                        paused = True
                        for k in list(down):
                            key_up(k)
                        down.clear()
                        self.q.put(("log", "Pausado: ventana no activa"))
                    evt.wait(0.1)
                    continue
                if paused:
                    paused = False
                    self.q.put(("log", "Reanudado"))

                keys = [tuple(k) for k in self.keys]
                hold = {k for k, m in keys if m == "hold"}
                for k in list(down - hold):
                    key_up(k)
                    down.discard(k)
                    self.q.put(("log", f"Soltar {k}"))
                for k in hold:
                    key_down(k)  # se repite cada ~30 ms, como mantener la tecla (wwwww)
                    if k not in down:
                        down.add(k)
                        self.q.put(("log", f"Mantener {k}"))

                now = time.time()
                if now >= next_tap:
                    for k in [k for k, m in keys if m == "tap"]:
                        key_tap(k)
                        self.q.put(("log", f"Pulsar {k}"))
                    if self.mouse_on:
                        for _ in range(10):
                            mouse_move(5, 0)
                            evt.wait(0.02)
                        for _ in range(10):
                            mouse_move(-5, 0)
                            evt.wait(0.02)
                        self.q.put(("log", "Mover mouse"))
                    factor = random.uniform(0.8, 1.2) if self.rand_on else 1.0
                    next_tap = now + self.base * factor
                evt.wait(0.03)
        except InputBlocked:
            self.q.put(("log", "Entrada bloqueada."))
            self.q.put(("log", "Abre como administrador"))
            self.q.put(("died", evt))
        except Exception as e:
            self.q.put(("log", f"Error: {type(e).__name__}"))
            self.q.put(("died", evt))
        finally:
            for k in down:
                try:
                    key_up(k)
                except Exception:
                    pass

    def on_close(self):
        self.counting = False
        self.stop_evt.set()
        if self.thread and self.thread.is_alive():
            self.thread.join(0.5)
        self.root.destroy()


if __name__ == "__main__":
    root = tk.Tk()
    LoginScreen(root, lambda: App(root))
    root.mainloop()
