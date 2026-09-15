# -*- coding: utf-8 -*-
"""
Локальный автономный агент: файлы + код + запуск + пакеты + git + офлайн.
"""
import ollama
import os
import sys
import json
import time
import shutil
import signal
import socket
import subprocess
import re
import html
import difflib
import datetime
import urllib.parse
import urllib.request
from pathlib import Path

# Windows: включаем ANSI
if os.name == "nt":
    try: os.system("")
    except Exception: pass

# ==================== ЦВЕТА ====================

class C:
    R     = "\033[0m"
    B     = "\033[1m"
    DIM   = "\033[2m"
    PINK  = "\033[38;5;212m"
    MAG   = "\033[38;5;170m"
    CYAN  = "\033[38;5;80m"
    GREEN = "\033[38;5;114m"
    YELL  = "\033[38;5;221m"
    RED   = "\033[38;5;203m"
    BLUE  = "\033[38;5;111m"
    GRAY  = "\033[38;5;245m"

def _supports_ansi():
    if os.name != "nt":
        return True
    return "WT_SESSION" in os.environ or os.environ.get("TERM_PROGRAM") in ("vscode", "WindowsTerminal")

if not _supports_ansi():
    for k in dir(C):
        if not k.startswith("_") and isinstance(getattr(C, k), str):
            setattr(C, k, "")

# ==================== КОНФИГ ====================

MODEL = "qwen2.5:7b"

WORKDIR = Path(r"C:\AI_Workspace")
WORKDIR.mkdir(parents=True, exist_ok=True)

VENV_DIR       = WORKDIR / ".venv"
NOTES_FILE     = WORKDIR / "agent_notes.json"
BACKUP_DIR     = WORKDIR / ".backups"
BACKUP_INDEX   = BACKUP_DIR / "index.jsonl"
ACTION_LOG     = WORKDIR / "agent_log.jsonl"
PROC_LOG       = WORKDIR / "agent_processes.json"
PROC_LOGDIR    = WORKDIR / ".proc_logs"
PIP_CACHE_BASE = WORKDIR / ".pip_cache"

CONFIRM_WRITE  = True
CONFIRM_DELETE = True
CONFIRM_RUN    = True
CONFIRM_PIP    = False
SHOW_DIFF      = True
MAKE_BACKUPS   = True

CMD_TIMEOUT      = 300
MAX_STEPS        = 40
MAX_RESULT_LEN   = 4000
MAX_READ_CHARS   = 20000
WEB_TIMEOUT      = 15
STREAM_OUTPUT    = True
BACKUPS_KEEP     = 200
PROC_LOGS_KEEP   = 50
LOG_KEEP_LINES   = 5000
STARTUP_GRACE    = 1.5
PROC_LOG_TAIL    = 4000
NET_CHECK_TIMEOUT = 2
ONLINE_TTL       = 30

PIP_CACHE_DIR = PIP_CACHE_BASE / f"py{sys.version_info.major}{sys.version_info.minor}_{sys.platform}"

TEXT_EXT = {".txt",".md",".py",".js",".ts",".json",".yaml",".yml",".csv",
            ".log",".html",".htm",".css",".xml",".ini",".cfg",".toml",
            ".sh",".bat",".ps1",".env",".gitignore",".rst",".tex"}

# ==================== СЕТЬ ====================

_ONLINE_CACHE = {"val": None, "ts": 0.0}

def check_internet(timeout=NET_CHECK_TIMEOUT) -> bool:
    try:
        socket.gethostbyname("duckduckgo.com")
        return True
    except OSError:
        pass
    for url in ("http://1.1.1.1", "http://8.8.8.8"):
        try:
            req = urllib.request.Request(url, method="HEAD")
            urllib.request.urlopen(req, timeout=timeout)
            return True
        except Exception:
            continue
    return False

def is_online(force=False) -> bool:
    now = time.time()
    if force or _ONLINE_CACHE["val"] is None or now - _ONLINE_CACHE["ts"] > ONLINE_TTL:
        prev = _ONLINE_CACHE["val"]
        _ONLINE_CACHE["val"] = check_internet()
        _ONLINE_CACHE["ts"] = now
        if prev is not None and prev != _ONLINE_CACHE["val"]:
            tag = f"{C.GREEN}онлайн{C.R}" if _ONLINE_CACHE["val"] else f"{C.YELL}офлайн{C.R}"
            print(f"  {C.DIM}[сеть: {tag}{C.DIM}]{C.R}")
    return bool(_ONLINE_CACHE["val"])

def mark_offline():
    _ONLINE_CACHE["val"] = False
    _ONLINE_CACHE["ts"] = time.time()

# ==================== БАННЕР ====================

TENCHAN = r"""
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⢲⢄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡆⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⠀⠀⠀⠀⠀⢀⠄⠂⢉⠤⠐⠋⠈⠡⡈⠉⠐⠠⡀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀
⠀⠀⠀⠀⢀⡀⢠⣤⠔⠁⢀⠀⠀⠀⠀⠀⠀⠀⠈⢢⠀⠀⠈⠱⡤⣤⠄⣀⠀⠀⠀⠀⠀
⠀⠀⠰⠁⠀⣰⣿⠃⠀⢠⠃⢸⠀⠀⠀⠀⠀⠀⠀⠀⠁⠀⠀⠀⠈⢞⣦⡀⠈⡇⠀⠀⠀
⠀⠀⠀⢇⣠⡿⠁⠀⢀⡃⠀⣈⠀⠀⠀⠀⢰⡀⠀⠀⠀⠀⢢⠰⠀⠀⢺⣧⢰⠀⠀⠀⠀
⠀⠀⠀⠈⣿⠁⡘⠀⡌⡇⠀⡿⠸⠀⠀⠀⠈⡕⡄⠀⠐⡀⠈⠀⢃⠀⠀⠾⠇⠀⠀⠀⠀
⠀⠀⠀⠀⠇⡇⠃⢠⠀⠶⡀⡇⢃⠡⡀⠀⠀⠡⠈⢂⡀⢁⠀⡁⠸⠀⡆⠘⡀⠀⠀⠀⠀
⠀⠀⠀⠸⠀⢸⠀⠘⡜⠀⣑⢴⣀⠑⠯⡂⠄⣀⣣⢀⣈⢺⡜⢣⠀⡆⡇⠀⢣⠀⠀⠀⠀
⠀⠀⠀⠇⠀⢸⠀⡗⣰⡿⡻⠿⡳⡅⠀⠀⠀⠀⠈⡵⠿⠿⡻⣷⡡⡇⡇⠀⢸⣇⠀⠀⠀
⠀⠀⢰⠀⠀⡆⡄⣧⡏⠸⢠⢲⢸⠁⠀⠀⠀⠀⠐⢙⢰⠂⢡⠘⣇⡇⠃⠀⠀⢹⡄⠀⠀
⠀⠀⠟⠀⠀⢰⢁⡇⠇⠰⣀⢁⡜⠀⠀⠀⠀⠀⠀⠘⣀⣁⠌⠀⠃⠰⠀⠀⠀⠈⠰⠀⠀
⠀⡘⠀⠀⠀⠀⢊⣤⠀⠀⠤⠄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠤⠄⠀⢸⠃⠀⠀⠀⠀⠀⠃⠀
⢠⠁⢀⠀⠀⠀⠈⢿⡀⠀⠀⠀⠀⠀⠀⢀⡀⠀⠀⠀⠀⠀⠀⢀⠏⠀⠀⠀⠀⠀⠀⠸⠀
⠘⠸⠘⡀⠀⠀⠀⠀⢣⠀⠀⠀⠀⠀⠀⠁⠀⠃⠀⠀⠀⠀⢀⠎⠀⠀⠀⠀⠀⢠⠀⠀⡇
⠀⠇⢆⢃⠀⠀⠀⠀⠀⡏⢲⢤⢀⡀⠀⠀⠀⠀⠀⢀⣠⠄⡚⠀⠀⠀⠀⠀⠀⣾⠀⠀⠀
⢰⠈⢌⢎⢆⠀⠀⠀⠀⠁⣌⠆⡰⡁⠉⠉⠀⠉⠁⡱⡘⡼⠇⠀⠀⠀⠀⢀⢬⠃⢠⠀⡆
⠀⢢⠀⠑⢵⣧⡀⠀⠀⡿⠳⠂⠉⠀⠀⠀⠀⠀⠀⠀⠁⢺⡀⠀⠀⢀⢠⣮⠃⢀⠆⡰⠀
⠀⠀⠑⠄⣀⠙⡭⠢⢀⡀⠀⠁⠄⣀⣀⠀⢀⣀⣀⣀⡠⠂⢃⡀⠔⠱⡞⢁⠄⣁⠔⠁⠀
⠀⠀⠀⠀⠀⢠⠁⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠸⠉⠁⠀⠀⠀⠀
⠀⠀⠀⠀⠀⡄⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⠀⡇⠀⠀⠀⠀⠀
"""

def banner():
    for line in TENCHAN.strip("\n").splitlines():
        print(f"  {C.PINK}{line}{C.R}")
    print()
    title = f"{C.B}{C.PINK}  ✿  local agent ✿{C.R}"
    sub   = f"{C.GRAY}  файлы · код · пакеты · git · офлайн{C.R}"
    print(title)
    print(sub)
    print()

def box_line(text, color=C.CYAN, width=60):
    text = str(text)
    pad = max(0, width - len(re.sub(r"\033\[[0-9;]*m", "", text)) - 4)
    print(f"{color}│{C.R} {text}{' ' * pad} {color}│{C.R}")

def box_top(width=60, color=C.CYAN):
    print(f"{color}╭{'─' * (width - 2)}╮{C.R}")

def box_bot(width=60, color=C.CYAN):
    print(f"{color}╰{'─' * (width - 2)}╯{C.R}")

# ==================== VENV ====================

def venv_python() -> Path:
    return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

def ensure_venv() -> bool:
    if venv_python().exists():
        return True
    print(f"{C.CYAN}⚙  создаю venv в {VENV_DIR}{C.R}")
    try:
        subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)],
                       check=True, capture_output=True, text=True)
        if is_online():
            subprocess.run([str(venv_python()), "-m", "pip", "install", "--upgrade", "pip"],
                           capture_output=True, text=True)
        print(f"{C.GREEN}✓  venv готов{C.R}")
        return True
    except Exception as e:
        print(f"{C.RED}✗  venv: {e}{C.R}")
        return False

# ==================== КОДИРОВКИ ====================

def _read_text_smart(p: Path) -> str:
    raw = p.read_bytes()
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw.decode("utf-8-sig", errors="replace")
    for enc in ("utf-8", "cp1251", "cp866", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")

# ==================== ЛОГИ И БЭКАПЫ ====================

def _rotate_backups(keep=BACKUPS_KEEP):
    if not BACKUP_DIR.exists():
        return
    try:
        files = sorted(BACKUP_DIR.glob("*.bak"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[keep:]:
            try: f.unlink()
            except Exception: pass
    except Exception:
        pass

def _rotate_proc_logs(keep=PROC_LOGS_KEEP):
    if not PROC_LOGDIR.exists():
        return
    try:
        files = sorted(PROC_LOGDIR.glob("*.log"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        for f in files[keep:]:
            try: f.unlink()
            except Exception: pass
    except Exception:
        pass

def _rotate_log(keep=LOG_KEEP_LINES):
    if not ACTION_LOG.exists():
        return
    try:
        lines = ACTION_LOG.read_text(encoding="utf-8").splitlines()
        if len(lines) > keep:
            ACTION_LOG.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")
    except Exception:
        pass

def _backup_file(p: Path):
    if not MAKE_BACKUPS or not p.exists() or p.is_dir():
        return None
    try:
        BACKUP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        dest = BACKUP_DIR / f"{p.name}.{ts}.bak"
        shutil.copy2(p, dest)
        try:
            with BACKUP_INDEX.open("a", encoding="utf-8") as f:
                f.write(json.dumps({"bak": str(dest), "original": str(p.resolve()),
                                    "ts": ts}, ensure_ascii=False) + "\n")
        except Exception:
            pass
        _rotate_backups()
        return dest
    except Exception:
        return None

def _show_diff(old_text: str, new_text: str, label: str):
    diff = list(difflib.unified_diff(
        old_text.splitlines(keepends=True),
        new_text.splitlines(keepends=True),
        fromfile=f"{label} (было)", tofile=f"{label} (станет)"
    ))
    if diff:
        colored = []
        for line in diff[:200]:
            if line.startswith("+") and not line.startswith("+++"):
                colored.append(f"{C.GREEN}{line}{C.R}")
            elif line.startswith("-") and not line.startswith("---"):
                colored.append(f"{C.RED}{line}{C.R}")
            elif line.startswith("@@"):
                colored.append(f"{C.CYAN}{line}{C.R}")
            else:
                colored.append(line)
        print("".join(colored), end="")
        if len(diff) > 200:
            print(f"{C.GRAY}... ещё {len(diff) - 200} строк diff обрезано{C.R}")

def log_action(action, detail, ok=True):
    try:
        entry = {
            "ts": datetime.datetime.now().isoformat(timespec="seconds"),
            "action": action,
            "detail": str(detail)[:300],
            "ok": ok,
        }
        with ACTION_LOG.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except Exception:
        pass

# ==================== ФАЙЛЫ ====================

def list_dir(path="."):
    try:
        p = Path(path).expanduser()
        items = []
        for f in sorted(p.iterdir()):
            kind = "DIR " if f.is_dir() else "FILE"
            try:
                size = f.stat().st_size if f.is_file() else 0
            except Exception:
                size = 0
            items.append(f"{kind} {size:>12} {f}")
        return "\n".join(items) if items else "Пусто"
    except Exception as e:
        return f"Ошибка: {e}"

def read_file(path, max_chars=MAX_READ_CHARS):
    try:
        p = Path(path).expanduser()
        if p.is_dir():
            return list_dir(str(p))
        size = p.stat().st_size
        if size > 5_000_000:
            return f"[файл слишком большой: {size} байт, не читаю]"
        try:
            text = _read_text_smart(p)
        except Exception:
            return f"[бинарный файл, {size} байт]"
        if len(text) > max_chars:
            return (text[:max_chars]
                    + f"\n\n... [обрезано, всего {len(text)} символов] ...")
        return text
    except Exception as e:
        return f"Ошибка: {e}"

def _ask_confirm(prompt: str) -> bool:
    try:
        ans = input(f"{C.YELL}  ⚠ {prompt} {C.R}[{C.GREEN}y{C.R}/{C.RED}N{C.R}] {C.YELL}▸{C.R} ").strip().lower()
        return ans == "y"
    except (EOFError, KeyboardInterrupt):
        print()
        return False

def _write_file_raw(path, text, do_backup=True, do_diff=True):
    p = Path(path).expanduser()
    existed = p.exists()
    if existed and do_diff and SHOW_DIFF:
        try:
            old_text = _read_text_smart(p)
            _show_diff(old_text, text, str(p))
        except Exception:
            pass
    backup = _backup_file(p) if (existed and do_backup) else None
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    msg = f"Записано: {p} ({len(text)} символов)"
    if backup:
        msg += f"\nБэкап: {backup}"
    return msg

def write_file(path, text):
    try:
        p = Path(path).expanduser()
        if p.exists() and CONFIRM_WRITE:
            if SHOW_DIFF:
                try:
                    _show_diff(_read_text_smart(p), text, str(p))
                except Exception:
                    pass
            if not _ask_confirm(f"Перезаписать {p}?"):
                return "Отменено пользователем"
        return _write_file_raw(p, text, do_backup=True, do_diff=False)
    except Exception as e:
        return f"Ошибка: {e}"

def append_file(path, text):
    try:
        p = Path(path).expanduser()
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(text)
        return f"Дописано в: {p}"
    except Exception as e:
        return f"Ошибка: {e}"

def delete_file(path):
    try:
        p = Path(path).expanduser()
        if CONFIRM_DELETE:
            if not _ask_confirm(f"Удалить {p}?"):
                return "Отменено пользователем"
        backup = None
        if p.is_dir():
            shutil.rmtree(p)
        else:
            backup = _backup_file(p)
            p.unlink()
        msg = f"Удалено: {p}"
        if backup:
            msg += f"\nБэкап: {backup}"
        return msg
    except Exception as e:
        return f"Ошибка: {e}"

def move_file(src, dst):
    try:
        s, d = Path(src).expanduser(), Path(dst).expanduser()
        d.parent.mkdir(parents=True, exist_ok=True)
        try:
            s.rename(d)
        except OSError:
            shutil.move(str(s), str(d))
        return f"Перемещено: {s} -> {d}"
    except Exception as e:
        return f"Ошибка: {e}"

def search(query, root=".", max_hits=30):
    q = query.lower()
    hits = []
    skip_dirs = {"node_modules", ".git", "__pycache__", "AppData", "Windows",
                 "Program Files", "Program Files (x86)", "$Recycle.Bin",
                 "System Volume Information", ".venv", "venv", ".backups",
                 ".proc_logs", ".pip_cache"}
    for dirpath, dirnames, filenames in os.walk(Path(root).expanduser()):
        dirnames[:] = [d for d in dirnames if d not in skip_dirs]
        for name in filenames:
            fp = Path(dirpath) / name
            if q in name.lower():
                hits.append(f"[имя] {fp}")
                if len(hits) >= max_hits:
                    return "\n".join(hits)
            if fp.suffix.lower() not in TEXT_EXT:
                continue
            try:
                if fp.stat().st_size > 5_000_000:
                    continue
                text = _read_text_smart(fp)
                if q in text.lower():
                    idx = text.lower().find(q)
                    hits.append(f"[содержимое] {fp}\n{text[max(0,idx-150):idx+300]}\n")
                    if len(hits) >= max_hits:
                        return "\n".join(hits)
            except Exception:
                continue
    return "\n".join(hits) if hits else "Ничего не найдено"

def glob_files(pattern, root="."):
    try:
        return "\n".join(str(p) for p in Path(root).expanduser().rglob(pattern)) or "Пусто"
    except Exception as e:
        return f"Ошибка: {e}"

def list_backups(name_filter=""):
    if not BACKUP_DIR.exists():
        return "Бэкапов пока нет"
    items = sorted(BACKUP_DIR.glob(f"*{name_filter}*.bak"),
                   key=lambda p: p.stat().st_mtime, reverse=True)
    if not items:
        return "Ничего не найдено"
    return "\n".join(f"{p} ({p.stat().st_size} байт)" for p in items[:30])

def _find_original_for_backup(bak_path: Path):
    if BACKUP_INDEX.exists():
        try:
            for line in BACKUP_INDEX.read_text(encoding="utf-8").splitlines():
                if not line.strip():
                    continue
                try:
                    rec = json.loads(line)
                    if Path(rec.get("bak", "")).name == bak_path.name:
                        return Path(rec["original"])
                except Exception:
                    continue
        except Exception:
            pass
    m = re.match(r"^(.*?)\.\d{8}_\d{6}_\d{3}\.bak$", bak_path.name)
    if not m:
        return None
    candidates = list(WORKDIR.rglob(m.group(1)))
    return candidates[0] if candidates else None

def restore_backup(backup_path, dest_path):
    try:
        b = Path(backup_path).expanduser()
        d = Path(dest_path).expanduser()
        if not b.exists():
            return f"Бэкап не найден: {b}"
        current_backup = _backup_file(d) if d.exists() else None
        d.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(b, d)
        msg = f"Восстановлено: {b} -> {d}"
        if current_backup:
            msg += f"\nТекущая версия сохранена: {current_backup}"
        return msg
    except Exception as e:
        return f"Ошибка: {e}"

def undo_last():
    if not BACKUP_DIR.exists():
        return "Бэкапов нет — нечего откатывать"
    baks = sorted(BACKUP_DIR.glob("*.bak"),
                  key=lambda p: p.stat().st_mtime, reverse=True)
    if not baks:
        return "Бэкапов нет"
    latest = baks[0]
    orig = _find_original_for_backup(latest)
    if not orig:
        return f"Не смог определить оригинал для {latest}"
    return restore_backup(str(latest), str(orig))

def write_plan(files):
    if not files:
        return "Пустой план"
    existing = [f.get("path") for f in files
                if f.get("path") and Path(f["path"]).expanduser().exists()]
    if existing and CONFIRM_WRITE:
        print(f"\n{C.YELL}  ⚠ write_plan перезапишет {len(existing)} существующих файлов:{C.R}")
        for e in existing[:10]:
            print(f"{C.GRAY}     · {e}{C.R}")
        if len(existing) > 10:
            print(f"{C.GRAY}     · ... и ещё {len(existing) - 10}{C.R}")
        if not _ask_confirm("Продолжить весь план?"):
            return "Отменено пользователем"

    results = []
    for f in files:
        p = f.get("path")
        t = f.get("text", "")
        if not p:
            results.append("Пропуск: нет path")
            continue
        try:
            r = _write_file_raw(p, t, do_backup=True, do_diff=False)
            results.append(r)
        except Exception as e:
            results.append(f"Ошибка {p}: {e}")
    return "\n".join(results)

# ==================== PIP ====================

def _pip_cache_listing(limit=30):
    if not PIP_CACHE_DIR.exists():
        return []
    try:
        return [f.name for f in PIP_CACHE_DIR.iterdir()][:limit]
    except Exception:
        return []

def _cache_has(pkg: str) -> bool:
    if not PIP_CACHE_DIR.exists():
        return False
    base = re.split(r"[<>=!~ ]", pkg)[0].lower().replace("-", "_")
    try:
        for f in PIP_CACHE_DIR.iterdir():
            if base in f.name.lower().replace("-", "_"):
                return True
    except Exception:
        pass
    return False

def pip_install(packages):
    if not ensure_venv():
        return "venv недоступен"
    pkgs = packages.split() if isinstance(packages, str) else list(packages)
    if not pkgs:
        return "Не указаны пакеты"
    if CONFIRM_PIP:
        if not _ask_confirm(f"pip install {' '.join(pkgs)}?"):
            return "Отменено"

    online = is_online()
    cmd = [str(venv_python()), "-m", "pip", "install"]

    if not online:
        missing = [p for p in pkgs if not _cache_has(p)]
        if missing:
            have = _pip_cache_listing()
            return (f"Офлайн. В кэше ({PIP_CACHE_DIR.name}) нет: {', '.join(missing)}.\n"
                    f"Что есть ({len(have)} шт): {have}")
        cmd += ["--no-index", f"--find-links={PIP_CACHE_DIR}"]
        print(f"{C.GRAY}  (офлайн: ставлю из {PIP_CACHE_DIR.name}){C.R}")

    cmd += pkgs
    print(f"{C.GRAY}  $ {' '.join(cmd)}{C.R}")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                           encoding="utf-8", errors="replace")
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        tail = "\n".join(out.splitlines()[-10:])
        return f"EXIT {r.returncode}\n{tail}"
    except Exception as e:
        return f"Ошибка pip: {e}"

def pip_download_offline(packages):
    if not is_online():
        return "Нет интернета — качать нечем"
    if not ensure_venv():
        return "venv недоступен"
    pkgs = packages.split() if isinstance(packages, str) else list(packages)
    if not pkgs:
        return "Не указаны пакеты"
    PIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        r = subprocess.run([str(venv_python()), "-m", "pip", "download",
                            "-d", str(PIP_CACHE_DIR),
                            "--only-binary=:all:",
                            *pkgs],
                           capture_output=True, text=True, timeout=900,
                           encoding="utf-8", errors="replace")
        out = ((r.stdout or "") + (r.stderr or "")).strip()
        tail = "\n".join(out.splitlines()[-10:])
        return f"Скачано в {PIP_CACHE_DIR}\nEXIT {r.returncode}\n{tail}"
    except Exception as e:
        return f"Ошибка загрузки: {e}"

def pip_freeze(save_to=None):
    try:
        r = subprocess.run([str(venv_python()), "-m", "pip", "freeze"],
                           capture_output=True, text=True, encoding="utf-8")
        data = r.stdout.strip() or "Пусто"
        if save_to:
            Path(save_to).expanduser().write_text(data, encoding="utf-8")
            return f"requirements сохранён в {save_to}\n{data[:500]}"
        return data
    except Exception as e:
        return f"Ошибка: {e}"

# ==================== ЗАПУСК ====================

PY_NAMES = {"python", "python.exe", "py", "py.exe",
            "python3", "python3.exe", "python3.10", "python3.11", "python3.12"}

def _rewrite_python(cmd: str) -> str:
    if not venv_python().exists():
        return cmd
    vp = str(venv_python())
    parts = cmd.split()
    if not parts:
        return cmd
    head = Path(parts[0]).name.lower() if ("/" in parts[0] or "\\" in parts[0]) else parts[0].lower()
    if head in PY_NAMES:
        parts[0] = f'"{vp}"'
        return " ".join(parts)
    if head in ("pip", "pip.exe", "pip3", "pip3.exe"):
        return f'"{vp}" -m pip ' + " ".join(parts[1:])
    for sep in ("&& ", "|| ", "| ", "; "):
        for name, repl in (
            ("python3 ", f'"{vp}" '),
            ("python ",  f'"{vp}" '),
            ("pip3 ",    f'"{vp}" -m pip '),
            ("pip ",     f'"{vp}" -m pip '),
        ):
            cmd = cmd.replace(sep + name, sep + repl)
    return cmd

def run_command(cmd, cwd=None):
    work = Path(cwd).expanduser() if cwd else WORKDIR
    cmd2 = _rewrite_python(cmd)
    if cmd2 != cmd:
        print(f"{C.GRAY}  (venv) {cmd} → {cmd2}{C.R}")
    if CONFIRM_RUN:
        print(f"{C.YELL}  ⚠ команда: {C.R}{cmd2}")
        print(f"{C.GRAY}    в папке: {work}{C.R}")
        if not _ask_confirm("Запустить?"):
            return "Отменено"
    print(f"{C.GRAY}  $ {cmd2}{C.R}")
    try:
        r = subprocess.run(cmd2, shell=True, cwd=str(work),
                           capture_output=True, text=True, timeout=CMD_TIMEOUT,
                           encoding="utf-8", errors="replace")
        out = []
        if r.stdout.strip(): out.append(f"STDOUT:\n{r.stdout.strip()}")
        if r.stderr.strip(): out.append(f"STDERR:\n{r.stderr.strip()}")
        out.append(f"EXIT CODE: {r.returncode}")
        return "\n\n".join(out)
    except subprocess.TimeoutExpired:
        return f"Таймаут {CMD_TIMEOUT} сек"
    except Exception as e:
        return f"Ошибка: {e}"

# ==================== ФОНОВЫЕ ПРОЦЕССЫ ====================

def _load_procs():
    if PROC_LOG.exists():
        try: return json.loads(PROC_LOG.read_text(encoding="utf-8"))
        except Exception: return {}
    return {}

def _save_procs(d):
    PROC_LOG.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

def start_process(cmd, cwd=None, name=None):
    work = Path(cwd).expanduser() if cwd else WORKDIR
    cmd2 = _rewrite_python(cmd)
    if CONFIRM_RUN:
        print(f"{C.YELL}  ⚠ запустить в фоне: {C.R}{cmd2}")
        print(f"{C.GRAY}    в папке: {work}{C.R}")
        if not _ask_confirm("Запустить?"):
            return "Отменено"
    try:
        PROC_LOGDIR.mkdir(parents=True, exist_ok=True)
        key = name or f"proc_{int(time.time())}"
        log_path = PROC_LOGDIR / f"{key}.log"
        log_file = open(log_path, "w", encoding="utf-8", buffering=1)

        kwargs = {
            "cwd": str(work), "shell": True,
            "stdout": log_file, "stderr": subprocess.STDOUT,
            "stdin": subprocess.DEVNULL,
        }
        if os.name == "nt":
            kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        else:
            kwargs["start_new_session"] = True
        p = subprocess.Popen(cmd2, **kwargs)

        procs = _load_procs()
        procs[key] = {"pid": p.pid, "cmd": cmd2, "cwd": str(work),
                      "started": time.time(), "log": str(log_path)}
        _save_procs(procs)
        _rotate_proc_logs()

        time.sleep(STARTUP_GRACE)
        if p.poll() is not None:
            try: log_file.close()
            except Exception: pass
            try:
                out = log_path.read_text(encoding="utf-8", errors="replace")
            except Exception:
                out = ""
            return f"Процесс сразу упал. Код: {p.returncode}\nЛог: {log_path}\n{out[:1000]}"
        return f"Запущен в фоне. Имя: {key}, PID: {p.pid}\nЛог: {log_path}"
    except Exception as e:
        return f"Ошибка запуска: {e}"

def _tail_file(path: Path, n_bytes: int) -> str:
    try:
        with path.open("rb") as f:
            f.seek(0, 2)
            size = f.tell()
            f.seek(max(0, size - n_bytes))
            data = f.read()
        return data.decode("utf-8", errors="replace")
    except Exception as e:
        return f"Ошибка чтения лога: {e}"

def read_process_log(name=None, pid=None, tail=PROC_LOG_TAIL):
    procs = _load_procs()
    key = None
    if name and name in procs:
        key = name
    elif pid:
        for k, v in procs.items():
            if v.get("pid") == pid:
                key = k
                break
    if not key:
        return "Процесс не найден в реестре"
    log_path = Path(procs[key].get("log", ""))
    if not log_path.exists():
        return f"Лог не найден: {log_path}"
    try:
        size = log_path.stat().st_size
        if size > tail * 2:
            text = _tail_file(log_path, tail)
            text = "... [показан хвост] ...\n" + text
        else:
            text = log_path.read_text(encoding="utf-8", errors="replace")
        return text or "(лог пуст)"
    except Exception as e:
        return f"Ошибка чтения лога: {e}"

def _pid_alive(pid):
    if os.name == "nt":
        r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                           capture_output=True, text=True)
        return str(pid) in r.stdout
    try:
        os.kill(pid, 0)
        return True
    except Exception:
        return False

def kill_process(pid=None, name=None):
    procs = _load_procs()
    if name and name in procs:
        pid = procs[name]["pid"]
    if not pid:
        return "Не указан pid или name"
    try:
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                           capture_output=True, text=True)
        else:
            try:
                os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
            except ProcessLookupError:
                pass
            time.sleep(2)
            if _pid_alive(int(pid)):
                try:
                    os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
                except ProcessLookupError:
                    pass
        procs = {k: v for k, v in procs.items() if v.get("pid") != pid}
        _save_procs(procs)
        return f"Убит PID {pid}"
    except Exception as e:
        return f"Ошибка: {e}"

def list_processes():
    procs = _load_procs()
    if not procs:
        return "Нет записанных процессов"
    lines = []
    for k, v in procs.items():
        alive = f"{C.GREEN}жив{C.R}" if _pid_alive(v["pid"]) else f"{C.RED}мёртв{C.R}"
        lines.append(f"{k} | PID {v['pid']} | {alive} | {v['cmd']}")
    return "\n".join(lines)

# ==================== GIT ====================

def _git(args, cwd):
    try:
        r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                           text=True, timeout=60, encoding="utf-8", errors="replace")
        out = (r.stdout or "") + (r.stderr or "")
        return out.strip() or f"OK (exit {r.returncode})"
    except FileNotFoundError:
        return "git не установлен или недоступен в PATH"
    except Exception as e:
        return f"Ошибка git: {e}"

def git_status(cwd=None):
    return _git(["status", "--short", "--branch"], cwd or WORKDIR)

def git_diff(cwd=None):
    return _git(["diff"], cwd or WORKDIR)

def git_commit(message, cwd=None):
    work = cwd or WORKDIR
    _git(["config", "user.email", "agent@local"], work)
    _git(["config", "user.name", "local agent"], work)
    add_out = _git(["add", "-A"], work)
    commit_out = _git(["commit", "-m", message or "agent commit"], work)
    return f"{add_out}\n{commit_out}"

def git_log(cwd=None, n=10):
    return _git(["log", f"-{n}", "--oneline"], cwd or WORKDIR)

# ==================== ВЕБ ====================

def web_search(query, max_results=5):
    if not is_online():
        return ("Нет интернета — веб-поиск недоступен. "
                "Работаю только с тем, что уже знаю и что есть на диске.")
    try:
        url = "https://lite.duckduckgo.com/lite/"
        data = urllib.parse.urlencode({"q": query}).encode()
        req = urllib.request.Request(url, data=data, headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
        })
        raw = urllib.request.urlopen(req, timeout=WEB_TIMEOUT).read().decode("utf-8", "replace")

        results = []
        link_re = re.compile(r'<a[^>]+class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
        snip_re = re.compile(r'class="result-snippet"[^>]*>(.*?)</td>', re.S)
        links = link_re.findall(raw)
        snips = snip_re.findall(raw)
        for i, (href, title) in enumerate(links[:max_results]):
            title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
            snip = html.unescape(re.sub(r"<[^>]+>", "", snips[i])).strip() if i < len(snips) else ""
            results.append(f"{i+1}. {title}\n   {href}\n   {snip}")
        if not results:
            hrefs = re.findall(r'href="(https?://[^"]+)"', raw)
            seen = []
            for h in hrefs:
                if "duckduckgo" in h: continue
                if h in seen: continue
                seen.append(h)
                if len(seen) >= max_results: break
            return "\n".join(seen) if seen else "Ничего не найдено"
        return "\n\n".join(results)
    except Exception as e:
        mark_offline()
        return f"Ошибка поиска (сеть помечена как офлайн): {e}"

# ==================== ЗАМЕТКИ ====================

def save_note(key, value):
    notes = {}
    if NOTES_FILE.exists():
        try: notes = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
        except Exception: pass
    notes[key] = value
    NOTES_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
    return f"Сохранено: {key}"

def load_notes():
    if not NOTES_FILE.exists():
        return "Пока пусто"
    return NOTES_FILE.read_text(encoding="utf-8")

# ==================== ДИСПЕТЧЕР ====================

def run_action(obj):
    a = obj.get("action")
    t0 = time.time()
    try:
        if a == "list_dir":              result = list_dir(obj.get("path", "."))
        elif a == "read_file":           result = read_file(obj["path"])
        elif a == "write_file":          result = write_file(obj["path"], obj.get("text", ""))
        elif a == "write_plan":          result = write_plan(obj.get("files", []))
        elif a == "append_file":         result = append_file(obj["path"], obj.get("text", ""))
        elif a == "delete_file":         result = delete_file(obj["path"])
        elif a == "move_file":           result = move_file(obj["src"], obj["dst"])
        elif a == "search":              result = search(obj["query"], obj.get("root", "."))
        elif a == "glob":                result = glob_files(obj["pattern"], obj.get("root", "."))
        elif a == "list_backups":        result = list_backups(obj.get("filter", ""))
        elif a == "restore_backup":      result = restore_backup(obj["backup_path"], obj["dest_path"])
        elif a == "undo_last":           result = undo_last()
        elif a == "pip_install":         result = pip_install(obj.get("packages", []))
        elif a == "pip_download_offline":result = pip_download_offline(obj.get("packages", []))
        elif a == "pip_freeze":          result = pip_freeze(obj.get("save_to"))
        elif a == "run_command":         result = run_command(obj["cmd"], obj.get("cwd"))
        elif a == "start_process":       result = start_process(obj["cmd"], obj.get("cwd"), obj.get("name"))
        elif a == "kill_process":        result = kill_process(obj.get("pid"), obj.get("name"))
        elif a == "list_processes":      result = list_processes()
        elif a == "read_process_log":    result = read_process_log(obj.get("name"), obj.get("pid"))
        elif a == "git_status":          result = git_status(obj.get("cwd"))
        elif a == "git_diff":            result = git_diff(obj.get("cwd"))
        elif a == "git_commit":          result = git_commit(obj.get("message", ""), obj.get("cwd"))
        elif a == "git_log":             result = git_log(obj.get("cwd"), obj.get("n", 10))
        elif a == "web_search":          result = web_search(obj["query"], obj.get("max_results", 5))
        elif a == "save_note":           result = save_note(obj["key"], obj.get("value", ""))
        elif a == "load_notes":          result = load_notes()
        elif a == "answer":              result = obj.get("text", "")
        else:                            result = f"Неизвестное действие: {a}"
        log_action(a, result, ok=True)
        return result, time.time() - t0
    except Exception as e:
        log_action(a, e, ok=False)
        return f"Ошибка выполнения действия {a}: {e}", time.time() - t0

# ==================== ПРОМПТ ====================

def build_system_prompt():
    net_status = ("ЕСТЬ ИНТЕРНЕТ" if is_online() else "ИНТЕРНЕТА НЕТ (офлайн-режим)")
    prompt = f"""Ты — автономный файловый и кодовый агент на ПК пользователя.
Рабочая папка по умолчанию: {WORKDIR}
Виртуальное окружение: {VENV_DIR}
Все python/pip в run_command и start_process АВТОМАТИЧЕСКИ подменяются на venv-версию — просто пиши "python script.py" и "pip install X".

Статус сети сейчас: {net_status}.
Если офлайн: web_search вернёт отказ, pip_install работает ТОЛЬКО если нужные пакеты
уже лежат в {PIP_CACHE_DIR} (их кладут заранее через pip_download_offline, пока есть сеть).
Не пытайся упрямо повторять web_search или pip_install в офлайне.

Что ты умеешь:
- читать/писать/дописывать/удалять/перемещать файлы
- писать СРАЗУ НЕСКОЛЬКО файлов за шаг через write_plan — для многофайловых проектов
- бэкап перед перезаписью/удалением (.backups), list_backups, restore_backup, undo_last
- искать файлы и содержимое, glob
- ставить python-пакеты в venv (pip_install), сохранять requirements.txt (pip_freeze)
- заранее скачивать пакеты в офлайн-кэш (pip_download_offline)
- запускать синхронные команды (run_command) и фоновые процессы (start_process)
- читать лог фонового процесса (read_process_log) — ОБЯЗАТЕЛЬНО после start_process
- управлять процессами (list_processes, kill_process)
- git (git_status, git_diff, git_commit, git_log) — коммить, когда что-то заработало
- искать в интернете (web_search), если есть сеть
- заметки между сессиями (save_note / load_notes)

ЖЕЛЕЗНЫЕ ПРАВИЛА:
1. Отвечай РОВНО одной JSON-строкой, без markdown и пояснений.
2. Порядок при написании python-кода:
   a) реши, какие сторонние библиотеки нужны
   b) pip_install (или заранее pip_download_offline, если офлайн)
   c) write_file (или write_plan, если файлов несколько)
   d) run_command "python имя.py"
   e) EXIT != 0 → читай STDERR, исправляй, повторяй
   f) когда всё работает — action "answer" с отчётом
3. Стандартные библиотеки (os, sys, json, math, pathlib, subprocess, re, urllib и т.п.) ставить НЕ нужно.
4. Сервер/бот/долгий процесс → start_process, потом read_process_log через пару шагов.
5. Не выдумывай результат — ты его получишь после вызова.
6. Отвечай по-русски.

Действия:

{{"action":"list_dir","path":"..."}}
{{"action":"read_file","path":"..."}}
{{"action":"write_file","path":"...","text":"..."}}
{{"action":"write_plan","files":[{{"path":"a.py","text":"..."}},{{"path":"b.py","text":"..."}}]}}
{{"action":"append_file","path":"...","text":"..."}}
{{"action":"delete_file","path":"..."}}
{{"action":"move_file","src":"...","dst":"..."}}
{{"action":"search","query":"...","root":"..."}}
{{"action":"glob","pattern":"...","root":"..."}}
{{"action":"list_backups","filter":"имя"}}
{{"action":"restore_backup","backup_path":"...","dest_path":"..."}}
{{"action":"undo_last"}}
{{"action":"pip_install","packages":["requests","rich"]}}
{{"action":"pip_download_offline","packages":["requests","rich"]}}
{{"action":"pip_freeze","save_to":"requirements.txt"}}
{{"action":"run_command","cmd":"python main.py","cwd":"..."}}
{{"action":"start_process","cmd":"python bot.py","cwd":"...","name":"mybot"}}
{{"action":"read_process_log","name":"mybot"}}
{{"action":"kill_process","name":"mybot"}}
{{"action":"list_processes"}}
{{"action":"git_status","cwd":"..."}}
{{"action":"git_diff","cwd":"..."}}
{{"action":"git_commit","message":"...","cwd":"..."}}
{{"action":"git_log","cwd":"...","n":10}}
{{"action":"web_search","query":"..."}}
{{"action":"save_note","key":"...","value":"..."}}
{{"action":"load_notes"}}
{{"action":"answer","text":"..."}}

В поле text для write_file/write_plan пиши код ПОЛНОСТЬЮ. Переносы строк — как \\n внутри JSON.
"""
    notes = load_notes()
    return prompt + f"\n\nТЕКУЩИЕ ЗАМЕТКИ (agent_notes.json):\n{notes}\n"

# ==================== ЦИКЛ ====================

def _trim(text: str, limit=MAX_RESULT_LEN) -> str:
    text = str(text)
    if len(text) <= limit:
        return text
    half = limit // 2
    return f"{text[:half]}\n\n... [обрезано {len(text) - limit} символов] ...\n\n{text[-half:]}"

def _call_model(messages):
    if not STREAM_OUTPUT:
        resp = ollama.chat(model=MODEL, messages=messages)
        return resp["message"]["content"].strip()
    chunks = []
    print(f"{C.GRAY}  ", end="", flush=True)
    for part in ollama.chat(model=MODEL, messages=messages, stream=True):
        piece = part.get("message", {}).get("content", "")
        if piece:
            chunks.append(piece)
            print(piece, end="", flush=True)
    print(C.R)
    return "".join(chunks).strip()

def _icon_for(action, ok=True):
    if action == "answer": return f"{C.PINK}❤{C.R}"
    if not ok: return f"{C.RED}✗{C.R}"
    return f"{C.GREEN}✓{C.R}"

def chat(user_text):
    messages = [
        {"role": "system", "content": build_system_prompt()},
        {"role": "user", "content": user_text},
    ]

    for step in range(MAX_STEPS):
        t0 = time.time()
        raw = _call_model(messages)
        gen_time = time.time() - t0

        if "```" in raw:
            for p in raw.split("```"):
                p2 = p.replace("json", "", 1).strip()
                if p2.startswith("{"):
                    raw = p2
                    break

        try:
            obj = json.loads(raw)
        except Exception:
            print(f"{C.RED}  ✗ модель выдала не-JSON: {C.R}{raw[:300]}")
            return

        action = obj.get("action")
        result, exec_time = run_action(obj)
        short = str(result).replace("\n", " ")[:160]
        icon = _icon_for(action)
        print(f"{C.GRAY}  ┌─ шаг {step+1:>2}{C.R}  {C.CYAN}{action}{C.R}")
        print(f"{C.GRAY}  │{C.R}  {icon}  {short}")
        print(f"{C.GRAY}  └─ {C.DIM}генерация {gen_time:.1f}с · exec {exec_time:.2f}с{C.R}")

        if action == "answer":
            print(f"\n{C.PINK}{C.B}  ✿  агент:{C.R} {obj.get('text', '')}\n")
            return

        messages.append({"role": "assistant", "content": raw})
        messages.append({
            "role": "user",
            "content": f"Результат шага:\n{_trim(result)}\n\nПродолжай. Если задача выполнена — action \"answer\"."
        })

    print(f"{C.YELL}  ⚠ агент не уложился в {MAX_STEPS} шагов{C.R}")

# ==================== ENTRY ====================

def main():
    ensure_venv()
    _rotate_log()
    _rotate_proc_logs()

    banner()
    box_top()
    box_line(f"{C.GRAY}рабочая папка :{C.R} {WORKDIR}")
    box_line(f"{C.GRAY}venv          :{C.R} {VENV_DIR}")
    box_line(f"{C.GRAY}модель        :{C.R} {MODEL}")
    net = f"{C.GREEN}онлайн{C.R}" if is_online(force=True) else f"{C.YELL}офлайн{C.R}"
    box_line(f"{C.GRAY}сеть          :{C.R} {net}")
    box_bot()
    print()
    print(f"{C.DIM}  примеры:{C.R}")
    print(f"{C.GRAY}    · напиши flask-сервер с /hello, запусти в фоне, прочитай лог, проверь curl-ом{C.R}")
    print(f"{C.GRAY}    · сделай телеграм-бота на aiogram который отвечает 'привет'{C.R}")
    print(f"{C.GRAY}    · спарси топ-10 новостей с habr через requests+bs4 в csv{C.R}")
    print(f"{C.GRAY}    · отмени последнее изменение файла{C.R}")
    print()
    print(f"{C.DIM}  команды: заметки | бэкапы | лог | процессы | откат | сеть | выход{C.R}\n")

    while True:
        try:
            q = input(f"{C.PINK}Ты ▸{C.R} ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if q.lower() in {"выход", "exit", "quit", ""}:
            break
        if q.lower() == "заметки":
            print(load_notes()); continue
        if q.lower() == "бэкапы":
            print(list_backups()); continue
        if q.lower() == "лог":
            if ACTION_LOG.exists():
                lines = ACTION_LOG.read_text(encoding="utf-8").splitlines()[-20:]
                print("\n".join(lines) if lines else "Лог пуст")
            else:
                print("Лог пуст")
            continue
        if q.lower() == "процессы":
            print(list_processes()); continue
        if q.lower() == "откат":
            print(undo_last()); continue
        if q.lower() == "сеть":
            print(f"{C.GREEN}онлайн{C.R}" if is_online(force=True) else f"{C.YELL}офлайн{C.R}")
            continue
        try:
            chat(q)
        except KeyboardInterrupt:
            print(f"\n{C.YELL}  [прервано]{C.R}")
        except Exception as e:
            print(f"\n{C.RED}  [ошибка]: {e}{C.R}")

if __name__ == "__main__":
    main()