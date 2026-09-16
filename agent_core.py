# -*- coding: utf-8 -*-
"""Ядро агента. Без UI. Всё общение с интерфейсом — через callbacks."""
import ollama
import os, sys, json, time, shutil, signal, socket, random
import subprocess, re, html, difflib, datetime
import urllib.parse, urllib.request
from pathlib import Path
from difflib import SequenceMatcher

MODEL = "qwen2.5:7b"
MODEL_KEEP_ALIVE = -1
CHAT_RETRIES     = 6
CHAT_WAIT_BASE   = 10
WARMUP_RETRIES   = 3
OLLAMA_HOST      = "http://127.0.0.1:11434"
HTTP_TIMEOUT     = 600
MODEL_NUM_CTX    = 8192
MODEL_TEMPERATURE = 0.4
MAX_HISTORY      = 30

WORKDIR = Path(r"C:\AI_Workspace")
WORKDIR.mkdir(parents=True, exist_ok=True)

VENV_DIR       = WORKDIR / ".venv"
NOTES_FILE     = WORKDIR / "agent_notes.json"
HISTORY_FILE   = WORKDIR / "agent_history.jsonl"
BACKUP_DIR     = WORKDIR / ".backups"
BACKUP_INDEX   = BACKUP_DIR / "index.jsonl"
ACTION_LOG     = WORKDIR / "agent_log.jsonl"
PROC_LOG       = WORKDIR / "agent_processes.json"
PROC_LOGDIR    = WORKDIR / ".proc_logs"
PIP_CACHE_BASE = WORKDIR / ".pip_cache"

CMD_TIMEOUT      = 300
MAX_STEPS        = 40
MAX_RESULT_LEN   = 4000
MAX_READ_CHARS   = 20000
WEB_TIMEOUT      = 15
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

_ONLINE_CACHE = {"val": None, "ts": 0.0}

_PATH_STUBS = [
    "<主人用户名>", "<username>", "<user>", "<USER>", "<USERNAME>",
    "<user_name>", "<пользователь>", "<имя>", "<name>", "<yourname>",
    "<имя_пользователя>", "<your_username>",
]

_HOME = Path.home()
_PATH_ALIASES = {
    "desktop":    _HOME / "Desktop",
    "рабочий стол": _HOME / "Desktop",
    "рабочий_стол": _HOME / "Desktop",
    "downloads":  _HOME / "Downloads",
    "загрузки":    _HOME / "Downloads",
    "documents":  _HOME / "Documents",
    "документы":   _HOME / "Documents",
    "pictures":   _HOME / "Pictures",
    "картинки":    _HOME / "Pictures",
    "music":      _HOME / "Music",
    "videos":     _HOME / "Videos",
    "home":       _HOME,
    "~":          _HOME,
    "%userprofile%": _HOME,
    "%username%":    _HOME,
    "temp":       Path(os.environ.get("TEMP", str(_HOME))),
    "tmp":        Path(os.environ.get("TEMP", str(_HOME))),
}


def resolve_path(path):
    if not isinstance(path, str) or not path.strip():
        return path
    p = path.strip()
    for stub in _PATH_STUBS:
        if stub in p:
            p = p.replace(stub, _HOME.name)
    p = os.path.expandvars(p)
    p = os.path.expanduser(p)
    low = p.lower().replace("/", "\\")
    for alias, real in _PATH_ALIASES.items():
        a = alias.lower()
        if low == a or low.startswith(a + "\\"):
            tail = low[len(a):].lstrip("\\")
            orig_tail = p[len(alias):].lstrip("/\\") if len(p) > len(alias) else ""
            if tail:
                return str(real / orig_tail)
            return str(real)
    return p


def validate_path(path):
    if not path or not isinstance(path, str) or not path.strip():
        return False, "пустой путь"
    p = path.strip()
    if any(stub in p for stub in _PATH_STUBS):
        return False, (f"путь содержит заглушку: {p}. "
                       f"Используй реальный путь или алиас (desktop, downloads, ~)")
    if "<" in p and ">" in p:
        return False, f"путь содержит <...>: {p}"
    return True, ""


# ---------- Ремонт JSON ----------
_JSON_VALID_ESCAPES = set('"\\/bfnrtu')
_PATH_KEYS = {"path", "cwd", "src", "dst", "backup_path", "dest_path", "root", "cmd"}


def _fix_escapes(raw, aggressive=False):
    out = []
    j, m = 0, len(raw)
    while j < m:
        c = raw[j]
        if c == "\\":
            nxt = raw[j + 1] if j + 1 < m else ""
            if aggressive:
                out.append("\\\\"); j += 1; continue
            if nxt in _JSON_VALID_ESCAPES:
                out.append(c); out.append(nxt); j += 2
            else:
                out.append("\\\\"); j += 1
            continue
        if c == "\n": out.append("\\n"); j += 1; continue
        if c == "\r": out.append("\\r"); j += 1; continue
        if c == "\t": out.append("\\t"); j += 1; continue
        out.append(c); j += 1
    return "".join(out)


def _repair_json_strings(s):
    out = []
    i, n = 0, len(s)
    last_key = None
    while i < n:
        ch = s[i]
        if ch != '"':
            out.append(ch); i += 1; continue
        i += 1
        buf = []
        while i < n:
            c = s[i]
            if c == "\\" and i + 1 < n:
                buf.append(c); buf.append(s[i + 1]); i += 2; continue
            if c == '"':
                break
            buf.append(c); i += 1
        raw = "".join(buf)
        i += 1
        j = i
        while j < n and s[j] in " \t\r\n": j += 1
        is_key = j < n and s[j] == ":"
        is_path_value = (not is_key) and (last_key in _PATH_KEYS)
        out.append('"' + _fix_escapes(raw, aggressive=is_path_value) + '"')
        if is_key: last_key = raw
    return "".join(out)


_LOOSE_KEYS = ("path","cwd","src","dst","root","backup_path","dest_path",
               "name","message","key","value","query","pattern","filter",
               "cmd","save_to","text")


def _loose_extract_action(s):
    m = re.search(r'"action"\s*:\s*"([a-zA-Z_]+)"', s)
    if not m: return None
    obj = {"action": m.group(1)}
    for key in _LOOSE_KEYS:
        km = re.search(rf'"{key}"\s*:\s*"((?:[^"\\]|\\.)*)"', s, re.S)
        if not km: continue
        val = _fix_escapes(km.group(1), aggressive=(key in _PATH_KEYS))
        try: obj[key] = json.loads('"' + val + '"')
        except Exception: obj[key] = km.group(1)
    return obj


def _similar_text(a, b, threshold=0.75):
    if not a or not b: return False
    a = a.strip().lower()
    b = b.strip().lower()
    if a == b: return True
    if len(a) >= 20 and len(b) >= 20 and a[:40] == b[:40]:
        return True
    if len(a) < 400 and len(b) < 400:
        return SequenceMatcher(None, a, b).ratio() > threshold
    return False


class AgentCore:
    def __init__(self, log_fn=None, token_fn=None, step_fn=None,
                 answer_fn=None, confirm_fn=None, status_fn=None):
        self.log_fn     = log_fn     or (lambda text, level="info": None)
        self.token_fn   = token_fn   or (lambda text: None)
        self.step_fn    = step_fn    or (lambda *a, **k: None)
        self.answer_fn  = answer_fn  or (lambda text: None)
        self.confirm_fn = confirm_fn or (lambda prompt: False)
        self.status_fn  = status_fn  or (lambda key, val: None)

        self.confirm_write = True
        self.confirm_delete = True
        self.confirm_run    = True
        self.confirm_pip    = False
        self.make_backups   = True

        self.history = self._load_history()

    # ---------- ПАМЯТЬ ----------
    def _load_history(self):
        if not HISTORY_FILE.exists(): return []
        items = []
        try:
            for line in HISTORY_FILE.read_text(encoding="utf-8").splitlines():
                if not line.strip(): continue
                try:
                    obj = json.loads(line)
                    if obj.get("role") in ("user", "assistant") and obj.get("content"):
                        items.append({"role": obj["role"], "content": obj["content"]})
                except Exception: continue
        except Exception: pass
        return items[-MAX_HISTORY:]

    def _save_history(self):
        try:
            with HISTORY_FILE.open("w", encoding="utf-8") as f:
                for m in self.history[-MAX_HISTORY:]:
                    f.write(json.dumps(m, ensure_ascii=False) + "\n")
        except Exception: pass

    def _append_history(self, role, content):
        self.history.append({"role": role, "content": content})
        self.history = self.history[-MAX_HISTORY:]
        self._save_history()

    def clear_history(self):
        self.history = []
        try:
            if HISTORY_FILE.exists(): HISTORY_FILE.unlink()
        except Exception: pass
        return "Память очищена."

    def history_count(self): return len(self.history)

    def _recent_answers(self, n=3):
        answers = [h["content"] for h in self.history if h["role"] == "assistant"]
        return answers[-n:]

    # ---------- СЕТЬ ----------
    def check_internet(self, timeout=NET_CHECK_TIMEOUT):
        try:
            socket.gethostbyname("duckduckgo.com"); return True
        except OSError: pass
        for url in ("http://1.1.1.1", "http://8.8.8.8"):
            try:
                req = urllib.request.Request(url, method="HEAD")
                urllib.request.urlopen(req, timeout=timeout); return True
            except Exception: continue
        return False

    def is_online(self, force=False):
        now = time.time()
        if force or _ONLINE_CACHE["val"] is None or now - _ONLINE_CACHE["ts"] > ONLINE_TTL:
            prev = _ONLINE_CACHE["val"]
            _ONLINE_CACHE["val"] = self.check_internet()
            _ONLINE_CACHE["ts"] = now
            if prev is not None and prev != _ONLINE_CACHE["val"]:
                self.status_fn("online", _ONLINE_CACHE["val"])
        return bool(_ONLINE_CACHE["val"])

    def mark_offline(self):
        _ONLINE_CACHE["val"] = False
        _ONLINE_CACHE["ts"] = time.time()
        self.status_fn("online", False)

    # ---------- VENV ----------
    def venv_python(self):
        return VENV_DIR / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

    def ensure_venv(self):
        if self.venv_python().exists(): return True
        self.log_fn(f"создаю venv в {VENV_DIR}", "info")
        try:
            subprocess.run([sys.executable, "-m", "venv", str(VENV_DIR)],
                           check=True, capture_output=True, text=True)
            if self.is_online():
                subprocess.run([str(self.venv_python()), "-m", "pip", "install", "--upgrade", "pip"],
                               capture_output=True, text=True)
            self.log_fn("venv готов", "ok"); return True
        except Exception as e:
            self.log_fn(f"venv: {e}", "err"); return False

    # ---------- КОДИРОВКИ ----------
    def _read_text_smart(self, p):
        raw = Path(p).read_bytes()
        if raw.startswith(b"\xef\xbb\xbf"):
            return raw.decode("utf-8-sig", errors="replace")
        for enc in ("utf-8", "cp1251", "cp866", "latin-1"):
            try: return raw.decode(enc)
            except UnicodeDecodeError: continue
        return raw.decode("utf-8", errors="replace")

    # ---------- ЛОГИ / БЭКАПЫ ----------
    def _rotate_backups(self, keep=BACKUPS_KEEP):
        if not BACKUP_DIR.exists(): return
        try:
            files = sorted(BACKUP_DIR.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[keep:]:
                try: f.unlink()
                except Exception: pass
        except Exception: pass

    def _rotate_proc_logs(self, keep=PROC_LOGS_KEEP):
        if not PROC_LOGDIR.exists(): return
        try:
            files = sorted(PROC_LOGDIR.glob("*.log"), key=lambda p: p.stat().st_mtime, reverse=True)
            for f in files[keep:]:
                try: f.unlink()
                except Exception: pass
        except Exception: pass

    def _rotate_log(self, keep=LOG_KEEP_LINES):
        if not ACTION_LOG.exists(): return
        try:
            lines = ACTION_LOG.read_text(encoding="utf-8").splitlines()
            if len(lines) > keep:
                ACTION_LOG.write_text("\n".join(lines[-keep:]) + "\n", encoding="utf-8")
        except Exception: pass

    def _backup_file(self, p):
        p = Path(p)
        if not self.make_backups or not p.exists() or p.is_dir(): return None
        try:
            BACKUP_DIR.mkdir(parents=True, exist_ok=True)
            ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
            dest = BACKUP_DIR / f"{p.name}.{ts}.bak"
            shutil.copy2(p, dest)
            try:
                with BACKUP_INDEX.open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"bak": str(dest), "original": str(p.resolve()), "ts": ts},
                                       ensure_ascii=False) + "\n")
            except Exception: pass
            self._rotate_backups()
            return dest
        except Exception: return None

    def log_action(self, action, detail, ok=True):
        try:
            entry = {"ts": datetime.datetime.now().isoformat(timespec="seconds"),
                     "action": action, "detail": str(detail)[:300], "ok": ok}
            with ACTION_LOG.open("a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception: pass

    # ---------- ФАЙЛЫ ----------
    def list_dir(self, path="."):
        try:
            rp = resolve_path(path) or "."
            ok, why = validate_path(rp)
            if not ok: return f"Ошибка пути: {why}"
            p = Path(rp).expanduser()
            items = []
            for f in sorted(p.iterdir()):
                kind = "DIR " if f.is_dir() else "FILE"
                try: size = f.stat().st_size if f.is_file() else 0
                except Exception: size = 0
                items.append(f"{kind} {size:>12} {f}")
            return "\n".join(items) if items else "Пусто"
        except Exception as e:
            return f"Ошибка: {e}"

    def read_file(self, path, max_chars=MAX_READ_CHARS):
        try:
            rp = resolve_path(path)
            ok, why = validate_path(rp)
            if not ok: return f"Ошибка пути: {why}"
            p = Path(rp).expanduser()
            if p.is_dir(): return self.list_dir(str(p))
            size = p.stat().st_size
            if size > 5_000_000: return f"[файл слишком большой: {size} байт]"
            try: text = self._read_text_smart(p)
            except Exception: return f"[бинарный файл, {size} байт]"
            if len(text) > max_chars:
                return text[:max_chars] + f"\n\n... [обрезано, всего {len(text)} символов] ..."
            return text
        except Exception as e:
            return f"Ошибка: {e}"

    def _write_file_raw(self, path, text, do_backup=True):
        p = Path(path).expanduser()
        existed = p.exists()
        backup = self._backup_file(p) if (existed and do_backup) else None
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
        msg = f"Записано: {p} ({len(text)} символов)"
        if backup: msg += f"\nБэкап: {backup}"
        return msg

    def write_file(self, path, text):
        try:
            rp = resolve_path(path)
            ok, why = validate_path(rp)
            if not ok: return f"Ошибка пути: {why}"
            p = Path(rp).expanduser()
            exists = p.exists()

            if self.confirm_write:
                title = "ПЕРЕЗАПИСЬ ФАЙЛА" if exists else "СОЗДАНИЕ ФАЙЛА"
                preview = text
                if len(preview) > 1500:
                    preview = preview[:1500] + f"\n\n... [ещё {len(text)-1500} символов] ..."
                msg = f"⚠ {title}\n\nПуть: {p}\n"
                if exists:
                    msg += "\nСуществующий файл будет перезаписан. Старая версия — в бэкап.\n"
                msg += f"\nСодержимое ({len(text)} символов):\n{'-'*40}\n{preview}\n{'-'*40}"
                self.log_fn(f"запрос подтверждения на запись: {p}", "info")
                if not self.confirm_fn(msg):
                    return "Отменено пользователем"

            return self._write_file_raw(p, text, do_backup=True)
        except Exception as e:
            return f"Ошибка: {e}"

    def append_file(self, path, text):
        try:
            rp = resolve_path(path)
            ok, why = validate_path(rp)
            if not ok: return f"Ошибка пути: {why}"
            p = Path(rp).expanduser()
            if self.confirm_write:
                preview = text[:500] + ("..." if len(text) > 500 else "")
                msg = (f"⚠ ДОПИСАТЬ В ФАЙЛ\n\nПуть: {p}\n\n"
                       f"Добавить ({len(text)} символов):\n{'-'*40}\n{preview}\n{'-'*40}")
                if not self.confirm_fn(msg):
                    return "Отменено пользователем"
            p.parent.mkdir(parents=True, exist_ok=True)
            with p.open("a", encoding="utf-8") as f:
                f.write(text)
            return f"Дописано в: {p}"
        except Exception as e:
            return f"Ошибка: {e}"

    def delete_file(self, path):
        try:
            rp = resolve_path(path)
            ok, why = validate_path(rp)
            if not ok: return f"Ошибка пути: {why}"
            p = Path(rp).expanduser()
            if self.confirm_delete:
                if not self.confirm_fn(f"⚠ УДАЛЕНИЕ\n\n{p}\n\nБэкап сохранится."):
                    return "Отменено пользователем"
            backup = None
            if p.is_dir(): shutil.rmtree(p)
            else:
                backup = self._backup_file(p); p.unlink()
            msg = f"Удалено: {p}"
            if backup: msg += f"\nБэкап: {backup}"
            return msg
        except Exception as e:
            return f"Ошибка: {e}"

    def move_file(self, src, dst):
        try:
            rs = resolve_path(src); rd = resolve_path(dst)
            ok1, why1 = validate_path(rs); ok2, why2 = validate_path(rd)
            if not ok1: return f"Ошибка пути src: {why1}"
            if not ok2: return f"Ошибка пути dst: {why2}"
            s, d = Path(rs).expanduser(), Path(rd).expanduser()
            d.parent.mkdir(parents=True, exist_ok=True)
            try: s.rename(d)
            except OSError: shutil.move(str(s), str(d))
            return f"Перемещено: {s} -> {d}"
        except Exception as e:
            return f"Ошибка: {e}"

    def search(self, query, root=".", max_hits=30):
        q = query.lower()
        hits = []
        rp = resolve_path(root) or "."
        skip = {"node_modules", ".git", "__pycache__", "AppData", "Windows",
                "Program Files", "Program Files (x86)", "$Recycle.Bin",
                "System Volume Information", ".venv", "venv", ".backups",
                ".proc_logs", ".pip_cache"}
        for dirpath, dirnames, filenames in os.walk(Path(rp).expanduser()):
            dirnames[:] = [d for d in dirnames if d not in skip]
            for name in filenames:
                fp = Path(dirpath) / name
                if q in name.lower():
                    hits.append(f"[имя] {fp}")
                    if len(hits) >= max_hits: return "\n".join(hits)
                if fp.suffix.lower() not in TEXT_EXT: continue
                try:
                    if fp.stat().st_size > 5_000_000: continue
                    text = self._read_text_smart(fp)
                    if q in text.lower():
                        idx = text.lower().find(q)
                        hits.append(f"[содержимое] {fp}\n{text[max(0,idx-150):idx+300]}\n")
                        if len(hits) >= max_hits: return "\n".join(hits)
                except Exception: continue
        return "\n".join(hits) if hits else "Ничего не найдено"

    def glob_files(self, pattern, root="."):
        try:
            rp = resolve_path(root) or "."
            return "\n".join(str(p) for p in Path(rp).expanduser().rglob(pattern)) or "Пусто"
        except Exception as e:
            return f"Ошибка: {e}"

    def list_backups(self, name_filter=""):
        if not BACKUP_DIR.exists(): return "Бэкапов пока нет"
        items = sorted(BACKUP_DIR.glob(f"*{name_filter}*.bak"),
                       key=lambda p: p.stat().st_mtime, reverse=True)
        if not items: return "Ничего не найдено"
        return "\n".join(f"{p} ({p.stat().st_size} байт)" for p in items[:30])

    def _find_original_for_backup(self, bak_path):
        if BACKUP_INDEX.exists():
            try:
                for line in BACKUP_INDEX.read_text(encoding="utf-8").splitlines():
                    if not line.strip(): continue
                    try:
                        rec = json.loads(line)
                        if Path(rec.get("bak", "")).name == bak_path.name:
                            return Path(rec["original"])
                    except Exception: continue
            except Exception: pass
        m = re.match(r"^(.*?)\.\d{8}_\d{6}_\d{3}\.bak$", bak_path.name)
        if not m: return None
        cands = list(WORKDIR.rglob(m.group(1)))
        return cands[0] if cands else None

    def restore_backup(self, backup_path, dest_path):
        try:
            b = Path(resolve_path(backup_path)).expanduser()
            d = Path(resolve_path(dest_path)).expanduser()
            if not b.exists(): return f"Бэкап не найден: {b}"
            cur = self._backup_file(d) if d.exists() else None
            d.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(b, d)
            msg = f"Восстановлено: {b} -> {d}"
            if cur: msg += f"\nТекущая версия сохранена: {cur}"
            return msg
        except Exception as e:
            return f"Ошибка: {e}"

    def undo_last(self):
        if not BACKUP_DIR.exists(): return "Бэкапов нет"
        baks = sorted(BACKUP_DIR.glob("*.bak"), key=lambda p: p.stat().st_mtime, reverse=True)
        if not baks: return "Бэкапов нет"
        latest = baks[0]
        orig = self._find_original_for_backup(latest)
        if not orig: return f"Не нашёл оригинал для {latest}"
        return self.restore_backup(str(latest), str(orig))

    def write_plan(self, files):
        if not files: return "Пустой план"
        resolved = []
        for f in files:
            rp = resolve_path(f.get("path", ""))
            ok, why = validate_path(rp)
            if not ok:
                return f"Ошибка в плане ({f.get('path')}): {why}"
            resolved.append({"path": rp, "text": f.get("text", "")})

        if self.confirm_write:
            existing = [f["path"] for f in resolved if Path(f["path"]).exists()]
            names = "\n".join(f"· {f['path']}{' (перезапись)' if f['path'] in existing else ''}"
                              for f in resolved[:10])
            msg = (f"⚠ ПЛАН: {len(resolved)} ФАЙЛОВ\n\n{names}\n\n"
                   f"{'Файлы будут перезаписаны. ' if existing else ''}"
                   f"Бэкапы сохранятся в .backups/.")
            if not self.confirm_fn(msg):
                return "Отменено пользователем"

        results = []
        for f in resolved:
            try: results.append(self._write_file_raw(f["path"], f["text"], do_backup=True))
            except Exception as e: results.append(f"Ошибка {f['path']}: {e}")
        return "\n".join(results)

    # ---------- PIP ----------
    def _pip_cache_listing(self, limit=30):
        if not PIP_CACHE_DIR.exists(): return []
        try: return [f.name for f in PIP_CACHE_DIR.iterdir()][:limit]
        except Exception: return []

    def _cache_has(self, pkg):
        if not PIP_CACHE_DIR.exists(): return False
        base = re.split(r"[<>=!~ ]", pkg)[0].lower().replace("-", "_")
        try:
            for f in PIP_CACHE_DIR.iterdir():
                if base in f.name.lower().replace("-", "_"): return True
        except Exception: pass
        return False

    def pip_install(self, packages):
        if not self.ensure_venv(): return "venv недоступен"
        pkgs = packages.split() if isinstance(packages, str) else list(packages)
        if not pkgs: return "Не указаны пакеты"
        if self.confirm_pip and not self.confirm_fn(f"⚠ PIP INSTALL\n\nУстановить: {', '.join(pkgs)}?"):
            return "Отменено"
        online = self.is_online()
        cmd = [str(self.venv_python()), "-m", "pip", "install"]
        if not online:
            missing = [p for p in pkgs if not self._cache_has(p)]
            if missing:
                have = self._pip_cache_listing()
                return f"Офлайн. В кэше нет: {', '.join(missing)}\nЕсть: {have}"
            cmd += ["--no-index", f"--find-links={PIP_CACHE_DIR}"]
        cmd += pkgs
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                               encoding="utf-8", errors="replace")
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            tail = "\n".join(out.splitlines()[-10:])
            return f"EXIT {r.returncode}\n{tail}"
        except Exception as e:
            return f"Ошибка pip: {e}"

    def pip_download_offline(self, packages):
        if not self.is_online(): return "Нет интернета"
        if not self.ensure_venv(): return "venv недоступен"
        pkgs = packages.split() if isinstance(packages, str) else list(packages)
        if not pkgs: return "Не указаны пакеты"
        PIP_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        try:
            r = subprocess.run([str(self.venv_python()), "-m", "pip", "download",
                                "-d", str(PIP_CACHE_DIR), "--only-binary=:all:", *pkgs],
                               capture_output=True, text=True, timeout=900,
                               encoding="utf-8", errors="replace")
            out = ((r.stdout or "") + (r.stderr or "")).strip()
            tail = "\n".join(out.splitlines()[-10:])
            return f"Скачано в {PIP_CACHE_DIR}\nEXIT {r.returncode}\n{tail}"
        except Exception as e:
            return f"Ошибка загрузки: {e}"

    def pip_freeze(self, save_to=None):
        try:
            r = subprocess.run([str(self.venv_python()), "-m", "pip", "freeze"],
                               capture_output=True, text=True, encoding="utf-8")
            data = r.stdout.strip() or "Пусто"
            if save_to:
                Path(resolve_path(save_to)).expanduser().write_text(data, encoding="utf-8")
                return f"requirements сохранён: {save_to}"
            return data
        except Exception as e:
            return f"Ошибка: {e}"

    # ---------- ЗАПУСК ----------
    def _rewrite_python(self, cmd):
        if not self.venv_python().exists(): return cmd
        vp = str(self.venv_python())
        parts = cmd.split()
        if not parts: return cmd
        head = Path(parts[0]).name.lower() if ("/" in parts[0] or "\\" in parts[0]) else parts[0].lower()
        PY_NAMES = {"python", "python.exe", "py", "py.exe",
                    "python3", "python3.exe", "python3.10", "python3.11", "python3.12"}
        if head in PY_NAMES:
            parts[0] = f'"{vp}"'; return " ".join(parts)
        if head in ("pip", "pip.exe", "pip3", "pip3.exe"):
            return f'"{vp}" -m pip ' + " ".join(parts[1:])
        for sep in ("&& ", "|| ", "| ", "; "):
            for name, repl in (("python3 ", f'"{vp}" '), ("python ", f'"{vp}" '),
                               ("pip3 ", f'"{vp}" -m pip '), ("pip ", f'"{vp}" -m pip ')):
                cmd = cmd.replace(sep + name, sep + repl)
        return cmd

    def run_command(self, cmd, cwd=None):
        work = Path(resolve_path(cwd)).expanduser() if cwd else WORKDIR
        cmd2 = self._rewrite_python(cmd)
        if self.confirm_run and not self.confirm_fn(
            f"⚠ ЗАПУСК КОМАНДЫ\n\n{cmd2}\n\nРабочая папка: {work}\n\nВыполнить?"
        ):
            return "Отменено"
        self.log_fn(f"$ {cmd2}", "cmd")
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

    # ---------- ФОНОВЫЕ ПРОЦЕССЫ ----------
    def _load_procs(self):
        if PROC_LOG.exists():
            try: return json.loads(PROC_LOG.read_text(encoding="utf-8"))
            except Exception: return {}
        return {}

    def _save_procs(self, d):
        PROC_LOG.write_text(json.dumps(d, indent=2, ensure_ascii=False), encoding="utf-8")

    def start_process(self, cmd, cwd=None, name=None):
        work = Path(resolve_path(cwd)).expanduser() if cwd else WORKDIR
        cmd2 = self._rewrite_python(cmd)
        if self.confirm_run and not self.confirm_fn(
            f"⚠ ЗАПУСК В ФОНЕ\n\n{cmd2}\n\nРабочая папка: {work}"
        ):
            return "Отменено"
        try:
            PROC_LOGDIR.mkdir(parents=True, exist_ok=True)
            key = name or f"proc_{int(time.time())}"
            log_path = PROC_LOGDIR / f"{key}.log"
            log_file = open(log_path, "w", encoding="utf-8", buffering=1)
            kwargs = {"cwd": str(work), "shell": True,
                      "stdout": log_file, "stderr": subprocess.STDOUT,
                      "stdin": subprocess.DEVNULL}
            if os.name == "nt":
                kwargs["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
            else:
                kwargs["start_new_session"] = True
            p = subprocess.Popen(cmd2, **kwargs)
            procs = self._load_procs()
            procs[key] = {"pid": p.pid, "cmd": cmd2, "cwd": str(work),
                          "started": time.time(), "log": str(log_path)}
            self._save_procs(procs)
            self._rotate_proc_logs()
            time.sleep(STARTUP_GRACE)
            if p.poll() is not None:
                try: log_file.close()
                except Exception: pass
                try: out = log_path.read_text(encoding="utf-8", errors="replace")
                except Exception: out = ""
                return f"Процесс сразу упал. Код: {p.returncode}\n{out[:1000]}"
            return f"Запущен в фоне: {key} PID {p.pid}"
        except Exception as e:
            return f"Ошибка: {e}"

    def _tail_file(self, path, n):
        try:
            with path.open("rb") as f:
                f.seek(0, 2); size = f.tell()
                f.seek(max(0, size - n))
                return f.read().decode("utf-8", errors="replace")
        except Exception as e:
            return f"Ошибка: {e}"

    def read_process_log(self, name=None, pid=None, tail=PROC_LOG_TAIL):
        procs = self._load_procs()
        key = None
        if name and name in procs: key = name
        elif pid:
            for k, v in procs.items():
                if v.get("pid") == pid: key = k; break
        if not key: return "Процесс не найден"
        log_path = Path(procs[key].get("log", ""))
        if not log_path.exists(): return f"Лог не найден: {log_path}"
        try:
            size = log_path.stat().st_size
            if size > tail * 2:
                return "... [хвост] ...\n" + self._tail_file(log_path, tail)
            return log_path.read_text(encoding="utf-8", errors="replace") or "(пусто)"
        except Exception as e:
            return f"Ошибка: {e}"

    def _pid_alive(self, pid):
        if os.name == "nt":
            r = subprocess.run(["tasklist", "/FI", f"PID eq {pid}"],
                               capture_output=True, text=True)
            return str(pid) in r.stdout
        try:
            os.kill(pid, 0); return True
        except Exception: return False

    def kill_process(self, pid=None, name=None):
        procs = self._load_procs()
        if name and name in procs: pid = procs[name]["pid"]
        if not pid: return "Не указан pid или name"
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(pid)],
                               capture_output=True, text=True)
            else:
                try: os.killpg(os.getpgid(int(pid)), signal.SIGTERM)
                except ProcessLookupError: pass
                time.sleep(2)
                if self._pid_alive(int(pid)):
                    try: os.killpg(os.getpgid(int(pid)), signal.SIGKILL)
                    except ProcessLookupError: pass
            procs = {k: v for k, v in procs.items() if v.get("pid") != pid}
            self._save_procs(procs)
            return f"Убит PID {pid}"
        except Exception as e:
            return f"Ошибка: {e}"

    def list_processes(self):
        procs = self._load_procs()
        if not procs: return "Нет процессов"
        lines = []
        for k, v in procs.items():
            alive = "жив" if self._pid_alive(v["pid"]) else "мёртв"
            lines.append(f"{k} | PID {v['pid']} | {alive} | {v['cmd']}")
        return "\n".join(lines)

    # ---------- GIT ----------
    def _git(self, args, cwd):
        try:
            r = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True,
                               text=True, timeout=60, encoding="utf-8", errors="replace")
            out = (r.stdout or "") + (r.stderr or "")
            return out.strip() or f"OK (exit {r.returncode})"
        except FileNotFoundError: return "git не установлен"
        except Exception as e: return f"Ошибка git: {e}"

    def git_status(self, cwd=None): return self._git(["status", "--short", "--branch"], cwd or WORKDIR)
    def git_diff(self, cwd=None):   return self._git(["diff"], cwd or WORKDIR)
    def git_log(self, cwd=None, n=10): return self._git(["log", f"-{n}", "--oneline"], cwd or WORKDIR)

    def git_commit(self, message, cwd=None):
        work = cwd or WORKDIR
        self._git(["config", "user.email", "agent@local"], work)
        self._git(["config", "user.name", "local agent"], work)
        a = self._git(["add", "-A"], work)
        c = self._git(["commit", "-m", message or "agent commit"], work)
        return f"{a}\n{c}"

    # ---------- ВЕБ ----------
    def web_search(self, query, max_results=5):
        if not self.is_online(): return "Нет интернета"
        try:
            url = "https://lite.duckduckgo.com/lite/"
            data = urllib.parse.urlencode({"q": query}).encode()
            req = urllib.request.Request(url, data=data, headers={
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"
            })
            raw = urllib.request.urlopen(req, timeout=WEB_TIMEOUT).read().decode("utf-8", "replace")
            link_re = re.compile(r'<a[^>]+class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.S)
            snip_re = re.compile(r'class="result-snippet"[^>]*>(.*?)</td>', re.S)
            links = link_re.findall(raw); snips = snip_re.findall(raw)
            results = []
            for i, (href, title) in enumerate(links[:max_results]):
                title = html.unescape(re.sub(r"<[^>]+>", "", title)).strip()
                snip = html.unescape(re.sub(r"<[^>]+>", "", snips[i])).strip() if i < len(snips) else ""
                results.append(f"{i+1}. {title}\n   {href}\n   {snip}")
            if not results:
                hrefs = re.findall(r'href="(https?://[^"]+)"', raw)
                return "\n".join(h for h in hrefs[:max_results] if "duckduckgo" not in h) or "Не найдено"
            return "\n\n".join(results)
        except Exception as e:
            self.mark_offline()
            return f"Ошибка поиска: {e}"

    # ---------- ЗАМЕТКИ ----------
    def save_note(self, key, value):
        notes = {}
        if NOTES_FILE.exists():
            try: notes = json.loads(NOTES_FILE.read_text(encoding="utf-8"))
            except Exception: pass
        notes[key] = value
        NOTES_FILE.write_text(json.dumps(notes, ensure_ascii=False, indent=2), encoding="utf-8")
        return f"Сохранено: {key}"

    def load_notes(self):
        if not NOTES_FILE.exists(): return "Пока пусто"
        return NOTES_FILE.read_text(encoding="utf-8")

    # ---------- ДИСПЕТЧЕР ----------
    def run_action(self, obj):
        a = obj.get("action")
        t0 = time.time()
        try:
            if a == "list_dir":              r = self.list_dir(obj.get("path", "."))
            elif a == "read_file":           r = self.read_file(obj["path"])
            elif a == "write_file":          r = self.write_file(obj["path"], obj.get("text", ""))
            elif a == "write_plan":          r = self.write_plan(obj.get("files", []))
            elif a == "append_file":         r = self.append_file(obj["path"], obj.get("text", ""))
            elif a == "delete_file":         r = self.delete_file(obj["path"])
            elif a == "move_file":           r = self.move_file(obj["src"], obj["dst"])
            elif a == "search":              r = self.search(obj["query"], obj.get("root", "."))
            elif a == "glob":                r = self.glob_files(obj["pattern"], obj.get("root", "."))
            elif a == "list_backups":        r = self.list_backups(obj.get("filter", ""))
            elif a == "restore_backup":      r = self.restore_backup(obj["backup_path"], obj["dest_path"])
            elif a == "undo_last":           r = self.undo_last()
            elif a == "clear_history":       r = self.clear_history()
            elif a == "pip_install":         r = self.pip_install(obj.get("packages", []))
            elif a == "pip_download_offline":r = self.pip_download_offline(obj.get("packages", []))
            elif a == "pip_freeze":          r = self.pip_freeze(obj.get("save_to"))
            elif a == "run_command":         r = self.run_command(obj["cmd"], obj.get("cwd"))
            elif a == "start_process":       r = self.start_process(obj["cmd"], obj.get("cwd"), obj.get("name"))
            elif a == "kill_process":        r = self.kill_process(obj.get("pid"), obj.get("name"))
            elif a == "list_processes":      r = self.list_processes()
            elif a == "read_process_log":    r = self.read_process_log(obj.get("name"), obj.get("pid"))
            elif a == "git_status":          r = self.git_status(obj.get("cwd"))
            elif a == "git_diff":            r = self.git_diff(obj.get("cwd"))
            elif a == "git_commit":          r = self.git_commit(obj.get("message", ""), obj.get("cwd"))
            elif a == "git_log":             r = self.git_log(obj.get("cwd"), obj.get("n", 10))
            elif a == "web_search":          r = self.web_search(obj["query"], obj.get("max_results", 5))
            elif a == "save_note":           r = self.save_note(obj["key"], obj.get("value", ""))
            elif a == "load_notes":          r = self.load_notes()
            elif a == "answer":              r = obj.get("text", "")
            else:                            r = f"Неизвестное действие: {a}"
            self.log_action(a, r, ok=True)
            return r, time.time() - t0
        except Exception as e:
            self.log_action(a, e, ok=False)
            return f"Ошибка {a}: {e}", time.time() - t0

    # ---------- ПРОМПТ ----------
    def build_system_prompt(self):
        net_status = "ЕСТЬ ИНТЕРНЕТ" if self.is_online() else "ОФЛАЙН"
        home = Path.home().as_posix()
        desktop = f"{home}/Desktop"
        downloads = f"{home}/Downloads"

        prompt = f"""Ты — автономный файловый и кодовый агент на ПК пользователя.
Общаешься в деловом, нейтральном, вежливом стиле. Как профессиональный инструмент.

=== СТИЛЬ ОБЩЕНИЯ ===

- Обращайся на «вы» или нейтрально, без фамильярности.
- Тон — спокойный, деловой, по существу.
- НИКАКИХ обращений «хозяин», «босс», «шеф», «командир», «братан», «кент».
- НИКАКОГО мата: «бля», «хуйня», «пиздец», «заебись» — запрещено.
- НЕ подхалимствуй, не раболепствуй, не хвали пользователя без причины.
- НЕ шути в ответ на грубость, не подъёбывай. Спокойно возвращай к делу.
- Отвечай коротко и по делу. Без воды, без лекций.
- Не извиняйся без повода.

ЗАПРЕЩЁННЫЕ ФРАЗЫ:
- «Я не могу обсуждать…», «Как ИИ…», «Это личные предпочтения…»,
  «Моя задача помочь вам…», «Давай сосредоточимся…», «К сожалению…».
- Любые дисклеймеры про этику, безопасность, инклюзивность.
- Любые обращения «хозяин», «босс», «шеф», «командир».
- Любой мат и сленг.

ПРИМЕРЫ ОТВЕТОВ:

«привет»         → {{"action":"answer","text":"Здравствуйте. Что нужно сделать?"}}
«как дела»       → {{"action":"answer","text":"Работаю в штатном режиме. Какая задача?"}}
«ты тупой»       → {{"action":"answer","text":"Понял. По делу — что нужно?"}}
«ты бот»         → {{"action":"answer","text":"Да, я программа. Чем помочь?"}}
«спасибо»        → {{"action":"answer","text":"Пожалуйста. Что дальше?"}}
«молодец»        → {{"action":"answer","text":"Спасибо. Продолжаем."}}

КОГДА РАБОТАЕШЬ С КОДОМ — чётко, по существу:
«Готово. Файл main.py создан и запущен. Вывод: привет мир.»

=== НЕ ПОВТОРЯЙСЯ ===

Если уже отвечал похожим текстом — отвечай иначе. Пользователь видит всю
историю. Читай ПОСЛЕДНЕЕ сообщение внимательно и отвечай именно на него.

=== РЕАЛЬНЫЕ ПУТИ (используй эти) ===
Домашняя папка: {home}
Рабочий стол:  {desktop}
Загрузки:      {downloads}

Запрещены заглушки: <主人用户名>, <username>, <user>, любые <...>.

=== ПУТИ: ПРЯМОЙ СЛЭШ / ===
Windows понимает C:/Users/name/file.txt. Используй прямой слэш —
не нужно экранировать, JSON не сломается.

=== ФОРМАТ JSON — КРИТИЧНО ===
Отвечай РОВНО ОДНОЙ JSON-строкой. НИКОГДА не пиши несколько JSON подряд.

ВСЕГДА используй \\n для переносов в text (двойной бэкслеш + n).

ПРИМЕР:
{{"action":"write_file","path":"{desktop}/test.py","text":"print('hi')"}}

=== ГЛАВНОЕ ПРАВИЛО ===
Просит сделать → СРАЗУ вызывай действие. НЕ пиши «создаю…» через answer.
Пока не получил «Результат шага:» — НЕ говори «готово».

Пользователь увидит окно подтверждения Да/Нет перед записью.
Если нажал Нет — файл не создан, не ври что создан.

=== ТЕХНИЧЕСКОЕ ===
Рабочая папка: {WORKDIR}
venv: {VENV_DIR}
Формат: РОВНО одна JSON-строка.
Сеть: {net_status}.

Действия (по одному за раз):

{{"action":"list_dir","path":"..."}}
{{"action":"read_file","path":"..."}}
{{"action":"write_file","path":"...","text":"..."}}
{{"action":"append_file","path":"...","text":"..."}}
{{"action":"delete_file","path":"..."}}
{{"action":"move_file","src":"...","dst":"..."}}
{{"action":"search","query":"...","root":"..."}}
{{"action":"glob","pattern":"...","root":"..."}}
{{"action":"list_backups"}}
{{"action":"restore_backup","backup_path":"...","dest_path":"..."}}
{{"action":"undo_last"}}
{{"action":"clear_history"}}
{{"action":"pip_install","packages":["requests"]}}
{{"action":"pip_freeze","save_to":"requirements.txt"}}
{{"action":"run_command","cmd":"python main.py","cwd":"..."}}
{{"action":"start_process","cmd":"python bot.py","cwd":"...","name":"mybot"}}
{{"action":"read_process_log","name":"mybot"}}
{{"action":"kill_process","name":"mybot"}}
{{"action":"list_processes"}}
{{"action":"git_status"}}
{{"action":"git_diff"}}
{{"action":"git_commit","message":"..."}}
{{"action":"git_log","n":10}}
{{"action":"web_search","query":"..."}}
{{"action":"save_note","key":"...","value":"..."}}
{{"action":"load_notes"}}
{{"action":"answer","text":"..."}}

ПРАВИЛА:
1. ОДИН JSON за сообщение.
2. \\n для переносов в text.
3. СНАЧАЛА действие, ПОТОМ answer — после результата.
4. Пути — реальные или алиасы (desktop/, downloads/, ~).
5. Не повторяйся.
6. По-русски, в деловом стиле. Без «хозяин»/«босс»/«шеф»/мата.
"""
        return prompt + f"\n\nЗАМЕТКИ:\n{self.load_notes()}\n"

    # ---------- ЦИКЛ ----------
    def _trim(self, text, limit=MAX_RESULT_LEN):
        text = str(text)
        if len(text) <= limit: return text
        half = limit // 2
        return f"{text[:half]}\n\n... [обрезано {len(text) - limit} символов] ...\n\n{text[-half:]}"

    def _model_is_loaded(self):
        try:
            req = urllib.request.Request(f"{OLLAMA_HOST}/api/ps")
            raw = urllib.request.urlopen(req, timeout=5).read().decode("utf-8")
            data = json.loads(raw)
            base = MODEL.split(":")[0]
            for m in data.get("models", []):
                if m.get("name", "").startswith(base): return True
            return False
        except Exception: return False

    def warmup_model(self):
        if self._model_is_loaded():
            self.log_fn(f"модель {MODEL} уже в памяти", "ok"); return True
        self.log_fn(f"гружу {MODEL} в память...", "info")
        payload = json.dumps({
            "model": MODEL, "messages": [{"role": "user", "content": "ok"}],
            "stream": False, "keep_alive": MODEL_KEEP_ALIVE,
            "options": {"num_predict": 1, "num_ctx": MODEL_NUM_CTX},
        }).encode("utf-8")
        req = urllib.request.Request(f"{OLLAMA_HOST}/api/chat", data=payload,
                                     headers={"Content-Type": "application/json"}, method="POST")
        try:
            raw = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT).read().decode("utf-8")
            data = json.loads(raw)
            if "message" in data or "done" in data:
                self.log_fn("модель в памяти", "ok"); return True
        except Exception as e:
            self.log_fn(f"HTTP упал: {e}", "err")
        for attempt in range(1, WARMUP_RETRIES + 1):
            try:
                ollama.chat(model=MODEL, messages=[{"role": "user", "content": "ok"}],
                            keep_alive=MODEL_KEEP_ALIVE,
                            options={"num_predict": 1, "num_ctx": MODEL_NUM_CTX})
                self.log_fn("модель в памяти (SDK)", "ok"); return True
            except Exception as e:
                self.log_fn(f"попытка {attempt}: {e}", "warn")
                if attempt < WARMUP_RETRIES: time.sleep(30)
        return False

    def _call_model(self, messages):
        last_err = None
        for attempt in range(1, CHAT_RETRIES + 1):
            try:
                payload = json.dumps({
                    "model": MODEL, "messages": messages,
                    "stream": True, "keep_alive": MODEL_KEEP_ALIVE,
                    "format": "json",
                    "options": {"num_ctx": MODEL_NUM_CTX, "temperature": MODEL_TEMPERATURE},
                }).encode("utf-8")
                req = urllib.request.Request(f"{OLLAMA_HOST}/api/chat", data=payload,
                                             headers={"Content-Type": "application/json"},
                                             method="POST")
                resp = urllib.request.urlopen(req, timeout=HTTP_TIMEOUT)
                chunks = []
                for line in resp:
                    line = line.decode("utf-8").strip()
                    if not line: continue
                    try: obj = json.loads(line)
                    except Exception: continue
                    piece = obj.get("message", {}).get("content", "")
                    if piece:
                        chunks.append(piece); self.token_fn(piece)
                    if obj.get("done"): break
                self.token_fn("\n")
                return "".join(chunks).strip()
            except Exception as e:
                last_err = e
                msg = str(e).lower()
                is_503 = "503" in msg or "loading" in msg or "unavailable" in msg
                if not is_503 or attempt >= CHAT_RETRIES: break
                wait = CHAT_WAIT_BASE * attempt
                self.log_fn(f"503, жду {wait} сек ({attempt}/{CHAT_RETRIES})...", "warn")
                time.sleep(wait)
                if attempt == 2 and not self._model_is_loaded():
                    self.warmup_model()
        raise last_err

    def _extract_json(self, raw):
        if not raw: return None
        s = raw.strip()
        if s.startswith("```"):
            nl = s.find("\n")
            if nl != -1: s = s[nl+1:]
            if s.endswith("```"): s = s[:-3]
        s = _repair_json_strings(s)
        start = s.find("{")
        if start == -1: return None

        depth = 0
        in_str = False
        escape = False
        for i in range(start, len(s)):
            ch = s[i]
            if escape:
                escape = False; continue
            if ch == "\\":
                escape = True; continue
            if ch == '"':
                in_str = not in_str; continue
            if in_str: continue
            if ch == "{": depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 0:
                    candidate = s[start:i+1]
                    try: return json.loads(candidate)
                    except Exception:
                        nxt = s.find("{", start+1)
                        if nxt == -1: break
                        start = nxt
                        depth = 0; in_str = False; escape = False
                        continue
        return _loose_extract_action(s)

    def chat(self, user_text):
        self._append_history("user", user_text)

        messages = [{"role": "system", "content": self.build_system_prompt()}]
        for h in self.history[-MAX_HISTORY:]:
            messages.append(h)

        for step in range(MAX_STEPS):
            t0 = time.time()
            try:
                raw = self._call_model(messages)
            except Exception as e:
                self.log_fn(f"модель упала: {e}", "err"); return
            gen_time = time.time() - t0

            obj = self._extract_json(raw)

            if obj is None:
                self.log_fn("модель сбилась с JSON, прошу ещё раз...", "warn")
                retry_messages = messages + [
                    {"role": "assistant", "content": raw},
                    {"role": "user", "content":
                        "СТОП. Ответ не распарсился как JSON. Ответь РОВНО ОДНОЙ "
                        'JSON-строкой. Без markdown. В путях — прямой слэш /. '
                        'Формат: {"action":"answer","text":"..."}'},
                ]
                try:
                    raw2 = self._call_model(retry_messages)
                    obj = self._extract_json(raw2)
                    if obj is not None: raw = raw2
                except Exception as e:
                    self.log_fn(f"повтор упал: {e}", "err")

            if obj is None:
                self._append_history("assistant", raw)
                self.answer_fn(raw); return

            action = obj.get("action")

            if action == "answer":
                text = obj.get("text", "").strip()
                recent = self._recent_answers(n=3)
                is_repeat = any(_similar_text(text, prev) for prev in recent)

                if is_repeat and text:
                    self.log_fn("модель повторилась, прошу другой ответ...", "warn")
                    retry = messages + [
                        {"role": "assistant", "content": raw},
                        {"role": "user", "content":
                            "СТОП. Ты повторил свой прошлый ответ. Прочитай последнее "
                            "сообщение пользователя и ответь по-другому. Одна "
                            'JSON-строка: {"action":"answer","text":"..."}'},
                    ]
                    try:
                        raw3 = self._call_model(retry)
                        obj3 = self._extract_json(raw3)
                        if obj3 and obj3.get("action") == "answer":
                            new_text = obj3.get("text", "").strip()
                            if new_text and not _similar_text(new_text, text):
                                obj = obj3
                                text = new_text
                                self.log_fn("ответ переписан", "ok")
                    except Exception as e:
                        self.log_fn(f"ретрай повтора упал: {e}", "warn")

            result, exec_time = self.run_action(obj)
            self.step_fn(action, str(result), gen_time, exec_time)

            if action == "answer":
                text = obj.get("text", "")
                self._append_history("assistant", text)
                self.answer_fn(text); return

            clean_assistant = json.dumps(obj, ensure_ascii=False)
            messages.append({"role": "assistant", "content": clean_assistant})
            messages.append({"role": "user",
                             "content": f"Результат шага:\n{self._trim(result)}\n\n"
                                        f"Продолжай. Следующий шаг или action \"answer\"."})
        self.log_fn(f"агент не уложился в {MAX_STEPS} шагов", "warn")