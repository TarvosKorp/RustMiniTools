#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
RepoLinker — экспорт структуры, RAW-ссылок и единого бандла исходного кода
публичного GitHub-репозитория.
Windows 10/11, Python 3.9+, только стандартная библиотека.
"""

from __future__ import annotations

import concurrent.futures
import ctypes
import json
import queue
import re
import threading
import time
import traceback
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, ttk


APP_NAME = "RepoLinker"
APP_VERSION = "1.2.0"
API_BASE = "https://api.github.com"
USER_AGENT = f"{APP_NAME}/{APP_VERSION}"
API_VERSION = "2022-11-28"
DEFAULT_URL = ""
SCRIPT_DIR = Path(__file__).resolve().parent

# Максимальный размер одного файла для включения в бандл исходников (512 КБ)
MAX_BUNDLE_FILE_SIZE = 512 * 1024

# Расширения, которые гарантированно являются бинарными и пропускаются при сборке кода
BINARY_EXTENSIONS = {
    ".exe", ".dll", ".so", ".dylib", ".bin", ".obj", ".o", ".a", ".lib",
    ".ico", ".png", ".jpg", ".jpeg", ".gif", ".bmp", ".webp", ".tiff", ".psd",
    ".mp3", ".wav", ".ogg", ".flac", ".mp4", ".avi", ".mkv", ".mov", ".webm",
    ".zip", ".tar", ".gz", ".7z", ".rar", ".xz", ".bz2",
    ".pdf", ".doc", ".docx", ".xls", ".xlsx", ".ppt", ".pptx",
    ".ttf", ".otf", ".woff", ".woff2", ".eot",
    ".db", ".sqlite", ".sqlite3", ".pyc", ".pyo", ".class", ".jar",
}


# Цветовая палитра (снята с референса egui / UniDownloader); тёмная тема — единственная
PALETTE = {
    "bg_main": "#1b1b1b",        # Основной тёмный фон окна
    "bg_input": "#0f0f0f",       # Почти чёрный фон полей ввода и лога
    "bg_button": "#363636",      # Тёмно-серый фон кнопок
    "bg_button_hover": "#454545",
    "bg_button_active": "#282828",
    "border": "#383838",         # Тонкая серая рамка
    "accent_blue": "#0088ff",    # Фирменный голубой (заголовок, текст в полях, прогресс-бар)
    "text_primary": "#d4d4d4",   # Основной светло-серый текст
    "text_muted": "#888888",     # Приглушённый текст подсказок
    "select_bg": "#0055aa",      # Фон выделения текста
}


def hide_console_window() -> None:
    """Скрывает консольное окно, открывающееся на фоне при запуске через python.exe."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def enable_windows_dark_titlebar(root: tk.Tk) -> None:
    """Включает тёмную системную шапку окна в Windows 10 (build 19041+) и Windows 11."""
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def apply_egui_dark_theme(root: tk.Tk) -> None:
    """Применяет тёмную тему в стиле egui ко всем элементам tkinter и ttk."""
    style = ttk.Style(root)
    # Тема 'clam' обязательна, так как 'vista' игнорирует кастомные цвета кнопок и полей
    style.theme_use("clam")

    root.configure(bg=PALETTE["bg_main"])

    # Базовые настройки
    style.configure(
        ".",
        background=PALETTE["bg_main"],
        foreground=PALETTE["text_primary"],
        bordercolor=PALETTE["border"],
        darkcolor=PALETTE["bg_main"],
        lightcolor=PALETTE["bg_main"],
        troughcolor=PALETTE["bg_input"],
        focuscolor=PALETTE["accent_blue"],
        font=("Segoe UI", 10),
    )

    # Фреймы и заголовки
    style.configure("TFrame", background=PALETTE["bg_main"])
    style.configure("TLabel", background=PALETTE["bg_main"], foreground=PALETTE["text_primary"])
    style.configure(
        "Title.TLabel",
        background=PALETTE["bg_main"],
        foreground=PALETTE["accent_blue"],
        font=("Segoe UI", 20, "bold"),
    )
    style.configure(
        "Muted.TLabel",
        background=PALETTE["bg_main"],
        foreground=PALETTE["text_muted"],
        font=("Segoe UI", 9),
    )

    # Рамка группы (Параметры экспорта)
    style.configure(
        "TLabelframe",
        background=PALETTE["bg_main"],
        bordercolor=PALETTE["border"],
        relief="solid",
        borderwidth=1,
    )
    style.configure(
        "TLabelframe.Label",
        background=PALETTE["bg_main"],
        foreground=PALETTE["text_primary"],
    )

    # Поля ввода (чёрный фон + голубой текст, как в egui)
    style.configure(
        "TEntry",
        fieldbackground=PALETTE["bg_input"],
        foreground=PALETTE["accent_blue"],
        insertcolor=PALETTE["accent_blue"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["accent_blue"],
        darkcolor=PALETTE["border"],
        selectbackground=PALETTE["select_bg"],
        selectforeground="#ffffff",
        padding=(6, 5),
    )
    style.map(
        "TEntry",
        bordercolor=[("focus", PALETTE["accent_blue"])],
    )

    # Кнопки (тёмно-серые плоские кнопки с лёгкой подсветкой при наведении)
    style.configure(
        "TButton",
        background=PALETTE["bg_button"],
        foreground=PALETTE["text_primary"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["bg_button"],
        darkcolor=PALETTE["bg_button"],
        relief="flat",
        padding=(12, 6),
    )
    style.map(
        "TButton",
        background=[
            ("disabled", "#252525"),
            ("pressed", PALETTE["bg_button_active"]),
            ("active", PALETTE["bg_button_hover"]),
        ],
        foreground=[("disabled", "#555555")],
    )

    # Чекбоксы
    style.configure(
        "TCheckbutton",
        background=PALETTE["bg_main"],
        foreground=PALETTE["text_primary"],
        indicatorbackground=PALETTE["bg_input"],
        indicatorforeground=PALETTE["accent_blue"],
    )
    style.map(
        "TCheckbutton",
        background=[("active", PALETTE["bg_main"])],
        indicatorbackground=[("selected", PALETTE["bg_input"]), ("active", "#222222")],
    )

    # Прогресс-бар (голубой бегунок на чёрном треке)
    style.configure(
        "Horizontal.TProgressbar",
        background=PALETTE["accent_blue"],
        troughcolor=PALETTE["bg_input"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["accent_blue"],
        darkcolor=PALETTE["accent_blue"],
        thickness=8,
    )


class RepoLinkerError(Exception):
    pass


@dataclass
class RepoInfo:
    owner: str
    name: str
    full_name: str
    html_url: str
    default_branch: str
    description: str
    private: bool
    archived: bool
    size_kb: int
    created_at: str
    updated_at: str
    pushed_at: str
    stars: int
    forks: int
    open_issues: int
    license_name: str
    branch_commit_sha: str
    branch_commit_url: str
    commit_date: str
    commit_message: str
    tree_sha: str


@dataclass
class TreeEntry:
    path: str
    kind: str
    mode: str
    sha: str
    size: Optional[int]
    url: str


class GitHubClient:
    def __init__(self, token: str = "", log=None):
        self.token = token.strip()
        self.log = log or (lambda _message: None)

    def _headers(self, accept: str = "application/vnd.github+json") -> Dict[str, str]:
        headers = {
            "Accept": accept,
            "User-Agent": USER_AGENT,
            "X-GitHub-Api-Version": API_VERSION,
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _request_json(self, url: str) -> Dict[str, Any]:
        request = urllib.request.Request(url, headers=self._headers(), method="GET")
        last_error = None

        for attempt in range(4):
            try:
                with urllib.request.urlopen(request, timeout=35) as response:
                    raw = response.read()
                    return json.loads(raw.decode("utf-8"))
            except urllib.error.HTTPError as exc:
                body = ""
                try:
                    body = exc.read().decode("utf-8", errors="replace")
                except Exception:
                    pass

                if exc.code in (403, 429):
                    remaining = exc.headers.get("X-RateLimit-Remaining", "")
                    reset = exc.headers.get("X-RateLimit-Reset", "")
                    if remaining == "0" and reset.isdigit():
                        wait = max(1, min(60, int(reset) - int(time.time()) + 1))
                        if attempt < 3:
                            self.log(f"Лимит GitHub API исчерпан. Ожидание {wait} сек...")
                            time.sleep(wait)
                            continue

                if exc.code in (500, 502, 503, 504) and attempt < 3:
                    wait = 2 ** attempt
                    self.log(f"Временная ошибка GitHub ({exc.code}). Повтор через {wait} сек...")
                    time.sleep(wait)
                    continue

                if exc.code == 404:
                    raise RepoLinkerError(
                        "GitHub вернул 404. Проверь ссылку, название репозитория "
                        "и доступность репозитория без авторизации."
                    )
                if exc.code == 401:
                    raise RepoLinkerError("GitHub отклонил токен (401). Проверь Personal Access Token.")
                if exc.code == 403:
                    raise RepoLinkerError(
                        "GitHub запретил запрос (403). Возможно, исчерпан лимит API. "
                        "Добавь GitHub-токен в поле Token и повтори."
                    )
                raise RepoLinkerError(
                    f"Ошибка GitHub API: HTTP {exc.code}\n{body[:700]}"
                )
            except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
                last_error = exc
                if attempt < 3:
                    wait = 2 ** attempt
                    self.log(f"Сетевая ошибка. Повтор через {wait} сек...")
                    time.sleep(wait)
                    continue
                break

        raise RepoLinkerError(f"Не удалось получить данные от GitHub: {last_error}")

    def download_text_file(self, url: str) -> Tuple[Optional[str], Optional[str]]:
        """
        Скачивает файл по RAW-ссылке и возвращает (текст, причина_пропуска).
        """
        request = urllib.request.Request(
            url,
            headers={"User-Agent": USER_AGENT},
            method="GET",
        )
        for attempt in range(3):
            try:
                with urllib.request.urlopen(request, timeout=25) as response:
                    raw = response.read(MAX_BUNDLE_FILE_SIZE + 1)
                    if len(raw) > MAX_BUNDLE_FILE_SIZE:
                        return None, f"превышен лимит {human_size(MAX_BUNDLE_FILE_SIZE)}"
                    if b"\x00" in raw[:4096]:
                        return None, "бинарный файл (обнаружены нулевые байты)"
                    try:
                        return raw.decode("utf-8-sig"), None
                    except UnicodeDecodeError:
                        return raw.decode("cp1251"), None
            except UnicodeDecodeError:
                return None, "не удалось декодировать как текст (UTF-8 / CP1251)"
            except Exception as exc:
                if attempt < 2:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                return None, f"ошибка загрузки: {exc}"
        return None, "неизвестная ошибка"

    @staticmethod
    def parse_repo_url(value: str) -> Tuple[str, str]:
        value = value.strip()
        if not value:
            raise RepoLinkerError("Вставь ссылку на GitHub-репозиторий.")

        if "://" not in value and value.startswith("github.com/"):
            value = "https://" + value

        parsed = urllib.parse.urlparse(value)
        if parsed.scheme not in ("http", "https") or parsed.netloc.lower() not in (
            "github.com", "www.github.com"
        ):
            raise RepoLinkerError("Нужна ссылка вида https://github.com/OWNER/REPOSITORY")

        parts = [p for p in parsed.path.split("/") if p]
        if len(parts) < 2:
            raise RepoLinkerError("В ссылке должны присутствовать владелец и название репозитория.")

        owner, repo = parts[0], parts[1]
        if repo.endswith(".git"):
            repo = repo[:-4]

        if not re.fullmatch(r"[A-Za-z0-9_.-]+", owner) or not re.fullmatch(
            r"[A-Za-z0-9_.-]+", repo
        ):
            raise RepoLinkerError("Не удалось распознать владельца или название репозитория.")

        return owner, repo

    def get_repo_info(self, owner: str, repo: str) -> RepoInfo:
        encoded_owner = urllib.parse.quote(owner, safe="")
        encoded_repo = urllib.parse.quote(repo, safe="")
        data = self._request_json(f"{API_BASE}/repos/{encoded_owner}/{encoded_repo}")

        default_branch = data.get("default_branch") or "main"
        branch_data = self._request_json(
            f"{API_BASE}/repos/{encoded_owner}/{encoded_repo}/branches/"
            f"{urllib.parse.quote(default_branch, safe='')}"
        )
        commit = branch_data.get("commit") or {}
        commit_data = commit.get("commit") or {}
        tree_sha = (commit_data.get("tree") or {}).get("sha")
        commit_sha = commit.get("sha", "")

        if not tree_sha or not commit_sha:
            raise RepoLinkerError("GitHub не вернул SHA коммита или корневого дерева.")

        license_data = data.get("license") or {}
        return RepoInfo(
            owner=owner,
            name=repo,
            full_name=data.get("full_name", f"{owner}/{repo}"),
            html_url=data.get("html_url", f"https://github.com/{owner}/{repo}"),
            default_branch=default_branch,
            description=data.get("description") or "",
            private=bool(data.get("private", False)),
            archived=bool(data.get("archived", False)),
            size_kb=int(data.get("size") or 0),
            created_at=data.get("created_at") or "",
            updated_at=data.get("updated_at") or "",
            pushed_at=data.get("pushed_at") or "",
            stars=int(data.get("stargazers_count") or 0),
            forks=int(data.get("forks_count") or 0),
            open_issues=int(data.get("open_issues_count") or 0),
            license_name=license_data.get("spdx_id") or license_data.get("name") or "Не указана",
            branch_commit_sha=commit_sha,
            branch_commit_url=commit.get("html_url") or "",
            commit_date=(commit_data.get("committer") or {}).get("date", ""),
            commit_message=(commit_data.get("message") or "").splitlines()[0]
            if commit_data.get("message") else "",
            tree_sha=tree_sha,
        )

    def get_complete_tree(self, owner: str, repo: str, root_tree_sha: str) -> List[TreeEntry]:
        """
        Сначала пробуем один recursive-запрос. Если GitHub пометил результат
        truncated, обходим дерево по каталогам отдельными non-recursive запросами.
        Так не теряем файлы в очень больших репозиториях.
        """
        base = f"{API_BASE}/repos/{urllib.parse.quote(owner, safe='')}/{urllib.parse.quote(repo, safe='')}"
        recursive_url = f"{base}/git/trees/{root_tree_sha}?recursive=1"
        self.log("Получаю дерево репозитория...")

        data = self._request_json(recursive_url)
        if not data.get("truncated", False):
            return self._convert_entries(data.get("tree") or [])

        self.log("GitHub ограничил размер рекурсивного ответа. Перехожу на обход каталогов...")
        all_entries: List[TreeEntry] = []
        pending = [("", root_tree_sha)]
        visited = set()

        while pending:
            prefix, tree_sha = pending.pop()
            if tree_sha in visited:
                continue
            visited.add(tree_sha)
            url = f"{base}/git/trees/{tree_sha}"
            node = self._request_json(url)

            for raw in node.get("tree") or []:
                path = raw.get("path", "")
                full_path = f"{prefix}/{path}" if prefix else path
                kind = raw.get("type", "")
                entry = self._convert_one(raw, full_path)
                all_entries.append(entry)
                if kind == "tree":
                    pending.append((full_path, raw.get("sha", "")))

            self.log(f"Обход каталогов: найдено элементов {len(all_entries)}")

        return all_entries

    @staticmethod
    def _convert_one(raw: Dict[str, Any], path: str) -> TreeEntry:
        return TreeEntry(
            path=path,
            kind=raw.get("type", ""),
            mode=raw.get("mode", ""),
            sha=raw.get("sha", ""),
            size=raw.get("size"),
            url=raw.get("url", ""),
        )

    @classmethod
    def _convert_entries(cls, items: List[Dict[str, Any]]) -> List[TreeEntry]:
        return [cls._convert_one(item, item.get("path", "")) for item in items]


def human_size(size: Optional[int]) -> str:
    if size is None:
        return "—"
    value = float(size)
    units = ("Б", "КБ", "МБ", "ГБ", "ТБ")
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "Б" else f"{int(value)} Б"
        value /= 1024
    return f"{value:.1f} ТБ"


def format_date(value: str) -> str:
    if not value:
        return "—"
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone().strftime("%Y-%m-%d %H:%M:%S %Z")
    except Exception:
        return value


def is_likely_binary(entry: TreeEntry) -> Optional[str]:
    if entry.mode == "120000":
        return "символическая ссылка"
    suffix = Path(entry.path).suffix.lower()
    if suffix in BINARY_EXTENSIONS:
        return f"бинарное расширение ({suffix})"
    if entry.size is not None and entry.size > MAX_BUNDLE_FILE_SIZE:
        return f"слишком большой файл ({human_size(entry.size)})"
    return None


def build_outputs(
    repo: RepoInfo,
    entries: List[TreeEntry],
    output_dir: Path,
    client: Optional[GitHubClient] = None,
    include_bundle: bool = True,
    log=None,
) -> Dict[str, Path]:
    log = log or (lambda _msg: None)
    output_dir.mkdir(parents=True, exist_ok=True)

    files = [e for e in entries if e.kind == "blob"]
    directories = [e for e in entries if e.kind == "tree"]
    submodules = [e for e in entries if e.kind == "commit"]
    symlinks = [e for e in entries if e.mode == "120000"]

    entries_sorted = sorted(entries, key=lambda e: (e.path.lower(), e.kind))
    files_sorted = sorted(files, key=lambda e: e.path.lower())

    raw_base = f"https://raw.githubusercontent.com/{repo.owner}/{repo.name}/{repo.branch_commit_sha}"
    branch_base = (
        f"https://raw.githubusercontent.com/{repo.owner}/{repo.name}/"
        f"{urllib.parse.quote(repo.default_branch, safe='/')}"
    )

    # Компактный список актуальных (по ветке) RAW-ссылок: одна строка на файл — URL + размер.
    raw_lines = []
    for entry in files_sorted:
        quoted_path = urllib.parse.quote(entry.path, safe="/")
        raw_lines.append(f"{branch_base}/{quoted_path} {human_size(entry.size)}")

    tree_lines = [
        f"{repo.full_name} — структура репозитория",
        f"Ветка: {repo.default_branch}",
        f"Коммит: {repo.branch_commit_sha}",
        "",
    ]
    for entry in entries_sorted:
        depth = entry.path.count("/")
        name = entry.path.rsplit("/", 1)[-1]
        if entry.kind == "tree":
            suffix = "/"
        elif entry.kind == "commit":
            suffix = " [submodule]"
        elif entry.mode == "120000":
            suffix = " [symlink]"
        else:
            suffix = ""
        tree_lines.append(f"{'    ' * depth}{name}{suffix}")

    total_size = sum(e.size or 0 for e in files)
    metadata_lines = [
        f"{APP_NAME} {APP_VERSION}",
        f"Отчёт создан: {datetime.now().astimezone().isoformat(timespec='seconds')}",
        "",
        f"Репозиторий: {repo.full_name}",
        f"URL: {repo.html_url}",
        f"Описание: {repo.description or '—'}",
        f"Ветка по умолчанию: {repo.default_branch}",
        f"Коммит: {repo.branch_commit_sha}",
        f"Страница коммита: {repo.branch_commit_url or '—'}",
        f"Дата коммита: {format_date(repo.commit_date)}",
        f"Сообщение коммита: {repo.commit_message or '—'}",
        f"SHA корневого дерева: {repo.tree_sha}",
        f"Лицензия: {repo.license_name}",
        f"Приватный: {'да' if repo.private else 'нет'}",
        f"Архивный: {'да' if repo.archived else 'нет'}",
        f"Размер репозитория по GitHub API: {human_size(repo.size_kb * 1024)}",
        f"Звёзды: {repo.stars}",
        f"Форки: {repo.forks}",
        f"Открытые issues: {repo.open_issues}",
        f"Создан: {format_date(repo.created_at)}",
        f"Обновлён: {format_date(repo.updated_at)}",
        f"Последний push: {format_date(repo.pushed_at)}",
        "",
        "СТАТИСТИКА ЭКСПОРТА",
        f"Файлов (blob): {len(files)}",
        f"Каталогов (tree): {len(directories)}",
        f"Подмодулей (commit): {len(submodules)}",
        f"Символических ссылок: {len(symlinks)}",
        f"Суммарный размер известных файлов: {human_size(total_size)}",
        "",
        "Примечание: размер может отсутствовать для отдельных типов объектов.",
        "LFS-файлы представлены в Git-дереве как обычные небольшие pointer-файлы.",
        "Содержимое submodule не включается: это отдельный Git-репозиторий.",
    ]

    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "", repo.name).strip(".") or "repository"
    outputs = {
        "links": output_dir / f"{safe_name}_RAW_LINKS.txt",
        "tree": output_dir / f"{safe_name}_REPOSITORY_TREE.txt",
        "metadata": output_dir / f"{safe_name}_REPOSITORY_METADATA.txt",
    }

    outputs["links"].write_text("\n".join(raw_lines), encoding="utf-8-sig")
    outputs["tree"].write_text("\n".join(tree_lines), encoding="utf-8-sig")
    outputs["metadata"].write_text("\n".join(metadata_lines), encoding="utf-8-sig")

    if include_bundle and client is not None:
        bundle_path = output_dir / f"{safe_name}_SOURCE_BUNDLE.txt"
        to_download: List[TreeEntry] = []
        skipped: List[Tuple[str, str]] = []

        for entry in files_sorted:
            reason = is_likely_binary(entry)
            if reason:
                skipped.append((entry.path, reason))
            else:
                to_download.append(entry)

        log(f"Загрузка исходников: {len(to_download)} текстовых файлов (пропущено {len(skipped)})...")

        downloaded_texts: Dict[str, str] = {}
        if to_download:
            def fetch(entry: TreeEntry) -> Tuple[str, Optional[str], Optional[str]]:
                url = f"{raw_base}/{urllib.parse.quote(entry.path, safe='/')}"
                text, err = client.download_text_file(url)
                return entry.path, text, err

            with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
                futures = [pool.submit(fetch, e) for e in to_download]
                done_count = 0
                for future in concurrent.futures.as_completed(futures):
                    path, text, err = future.result()
                    done_count += 1
                    if text is not None:
                        downloaded_texts[path] = text
                    else:
                        skipped.append((path, err or "неизвестная причина"))
                    if done_count % 10 == 0 or done_count == len(to_download):
                        log(f"Загружено файлов: {done_count}/{len(to_download)}")

        skipped.sort(key=lambda item: item[0].lower())

        bundle_lines = [
            f"РЕПОЗИТОРИЙ: {repo.full_name}",
            f"ВЕТКА: {repo.default_branch} | КОММИТ: {repo.branch_commit_sha}",
            f"СОБРАНО ФАЙЛОВ: {len(downloaded_texts)} | ПРОПУЩЕНО: {len(skipped)}",
            "=" * 80,
            "",
            "СТРУКТУРА РЕПОЗИТОРИЯ:",
            *tree_lines[4:],
            "",
            "=" * 80,
            "",
        ]

        if skipped:
            bundle_lines.append("ПРОПУЩЕННЫЕ ФАЙЛЫ (бинарные или слишком большие):")
            for path, reason in skipped:
                bundle_lines.append(f"  - {path} [{reason}]")
            bundle_lines.extend(["", "=" * 80, ""])

        for entry in to_download:
            if entry.path not in downloaded_texts:
                continue
            content = downloaded_texts[entry.path].rstrip("\r\n")
            bundle_lines.extend([
                f"<<< FILE: {entry.path} ({human_size(entry.size)}) >>>",
                content,
                f"<<< END OF FILE: {entry.path} >>>",
                "",
            ])

        bundle_path.write_text("\n".join(bundle_lines), encoding="utf-8-sig")
        outputs["bundle"] = bundle_path

    return outputs


class RepoLinkerApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(f"{APP_NAME} {APP_VERSION}")
        self.root.geometry("550x620")
        self.root.minsize(550, 620)

        self.events: "queue.Queue[Tuple[str, Any]]" = queue.Queue()
        self.busy = False

        self.url_var = tk.StringVar(value=DEFAULT_URL)
        self.token_var = tk.StringVar(value="")
        self.bundle_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Готов к работе.")
        self.progress_var = tk.DoubleVar(value=0)

        self._build_ui()
        self._setup_clipboard_and_hotkeys()
        self.root.after(100, self._poll_events)

    def _build_ui(self):
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        title = ttk.Label(outer, text="RepoLinker", style="Title.TLabel")
        title.pack(anchor="w")
        ttk.Label(
            outer,
            text="Получение структуры GitHub-репозитория, RAW-ссылок и единого файла с исходным кодом",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 12))

        tk.Frame(outer, height=1, bg=PALETTE["border"]).pack(fill="x", pady=(0, 12))

        ttk.Label(outer, text="Ссылка на GitHub-репозиторий:").pack(anchor="w")
        self.url_entry = ttk.Entry(outer, textvariable=self.url_var)
        self.url_entry.pack(fill="x", pady=(5, 10))

        ttk.Label(outer, text="GitHub Personal Access Token (необязательно):").pack(anchor="w")
        token_row = ttk.Frame(outer)
        token_row.pack(fill="x", pady=(5, 4))
        self.token_entry = ttk.Entry(token_row, textvariable=self.token_var, show="•")
        self.token_entry.pack(side="left", fill="x", expand=True)
        ttk.Button(token_row, text="Показать", command=self._toggle_token).pack(side="left", padx=(8, 0))
        ttk.Label(
            outer,
            text="Для публичных репозиториев токен не нужен. Он повышает лимит запросов API. "
                 "Токен сохраняется только в памяти программы.",
            style="Muted.TLabel",
            wraplength=730,
        ).pack(anchor="w", pady=(0, 10))

        options = ttk.LabelFrame(outer, text="Параметры экспорта", padding=10)
        options.pack(fill="x", pady=(0, 12))
        ttk.Checkbutton(
            options,
            text="Собрать единый файл с исходным кодом (*_SOURCE_BUNDLE.txt) для удобной отправки в AI-чат",
            variable=self.bundle_var,
        ).pack(anchor="w", pady=(0, 6))
        for line in (
            "• RAW_LINKS — актуальные RAW-ссылки на файлы по ветке, по одной строке: URL и размер",
            "• REPOSITORY_TREE — дерево каталогов и файлов",
            "• REPOSITORY_METADATA — сведения о репозитории, коммите и статистика",
            "• SOURCE_BUNDLE — весь текстовый код проекта в одном файле (без бинарников и .exe)",
        ):
            ttk.Label(options, text=line).pack(anchor="w", pady=1)

        self.run_button = ttk.Button(outer, text="Исследовать репозиторий и создать отчёты", command=self._start)
        self.run_button.pack(fill="x", ipady=5)

        self.progress = ttk.Progressbar(outer, variable=self.progress_var, mode="indeterminate")
        self.progress.pack(fill="x", pady=(10, 6))

        ttk.Label(outer, textvariable=self.status_var).pack(anchor="w")
        self.log_box = tk.Text(
            outer,
            height=9,
            wrap="word",
            state="disabled",
            font=("Consolas", 9),
            bg=PALETTE["bg_input"],
            fg=PALETTE["accent_blue"],
            insertbackground=PALETTE["accent_blue"],
            selectbackground=PALETTE["select_bg"],
            selectforeground="#ffffff",
            relief="flat",
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            highlightcolor=PALETTE["accent_blue"],
            padx=8,
            pady=6,
        )
        self.log_box.pack(fill="both", expand=True, pady=(6, 0))

    def _setup_clipboard_and_hotkeys(self):
        """
        Добавляет контекстное меню ПКМ и поддержку Ctrl+C/V/X/A
        независимо от текущей раскладки клавиатуры (EN / RU).
        """
        entry_widgets = [self.url_entry, self.token_entry]
        for widget in entry_widgets:
            menu = tk.Menu(
                widget,
                tearoff=0,
                bg=PALETTE["bg_button"],
                fg=PALETTE["text_primary"],
                activebackground=PALETTE["accent_blue"],
                activeforeground="#ffffff",
                borderwidth=1,
            )
            menu.add_command(label="Вырезать", command=lambda w=widget: w.event_generate("<<Cut>>"))
            menu.add_command(label="Копировать", command=lambda w=widget: w.event_generate("<<Copy>>"))
            menu.add_command(label="Вставить", command=lambda w=widget: w.event_generate("<<Paste>>"))
            menu.add_separator()
            menu.add_command(label="Выделить всё", command=lambda w=widget: self._select_all_entry(w))
            widget.bind("<Button-3>", lambda e, m=menu, w=widget: self._show_context_menu(e, m, w))

        log_menu = tk.Menu(
            self.log_box,
            tearoff=0,
            bg=PALETTE["bg_button"],
            fg=PALETTE["text_primary"],
            activebackground=PALETTE["accent_blue"],
            activeforeground="#ffffff",
            borderwidth=1,
        )
        log_menu.add_command(label="Копировать", command=lambda: self.log_box.event_generate("<<Copy>>"))
        log_menu.add_separator()
        log_menu.add_command(label="Выделить всё", command=self._select_all_text)
        self.log_box.bind("<Button-3>", lambda e: self._show_context_menu(e, log_menu, self.log_box))

        # Обработка Ctrl + клавиша по физическому keycode (Windows VK codes: A=65, C=67, V=86, X=88)
        self.root.bind_all("<Control-KeyPress>", self._on_ctrl_keypress, add="+")

    @staticmethod
    def _show_context_menu(event: tk.Event, menu: tk.Menu, widget: tk.Widget):
        widget.focus_set()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _select_all_entry(widget: ttk.Entry):
        widget.focus_set()
        widget.select_range(0, "end")
        widget.icursor("end")

    def _select_all_text(self):
        self.log_box.focus_set()
        self.log_box.tag_add("sel", "1.0", "end")

    def _on_ctrl_keypress(self, event: tk.Event):
        # Игнорируем, если зажат Alt (AltGr в некоторых раскладках эмулирует Ctrl+Alt)
        if event.state & 0x20000 or event.state & 0x0008:
            return None

        widget = self.root.focus_get()
        if widget is None:
            return None

        # Физические коды клавиш на стандартной клавиатуре (не зависят от раскладки RU/EN)
        vk = event.keycode
        keysym = (event.keysym or "").lower()
        is_a = vk == 65 or keysym in ("a", "cyrillic_ef")
        is_c = vk == 67 or keysym in ("c", "cyrillic_es")
        is_v = vk == 86 or keysym in ("v", "cyrillic_em")
        is_x = vk == 88 or keysym in ("x", "cyrillic_che")

        if isinstance(widget, (tk.Entry, ttk.Entry)):
            if is_a:
                self._select_all_entry(widget)
                return "break"
            if is_c:
                widget.event_generate("<<Copy>>")
                return "break"
            if is_v:
                widget.event_generate("<<Paste>>")
                return "break"
            if is_x:
                widget.event_generate("<<Cut>>")
                return "break"
        elif isinstance(widget, tk.Text):
            if is_a:
                self._select_all_text()
                return "break"
            if is_c:
                widget.event_generate("<<Copy>>")
                return "break"
        return None

    def _toggle_token(self):
        self.token_entry.configure(show="" if self.token_entry.cget("show") else "•")

    def _log(self, message: str):
        self.events.put(("log", message))

    def _start(self):
        if self.busy:
            return
        try:
            GitHubClient.parse_repo_url(self.url_var.get())
        except RepoLinkerError as exc:
            messagebox.showerror("Некорректная ссылка", str(exc))
            return

        output_dir = SCRIPT_DIR / "Reports"

        self.busy = True
        self.run_button.configure(state="disabled")
        self.progress.start(12)
        self.status_var.set("Подключение к GitHub…")
        self._append_log("Начало работы.")
        args = (
            self.url_var.get().strip(),
            output_dir,
            self.token_var.get().strip(),
            self.bundle_var.get(),
        )
        threading.Thread(target=self._worker, args=args, daemon=True).start()

    def _worker(self, url: str, output_dir: Path, token: str, include_bundle: bool):
        try:
            owner, repo_name = GitHubClient.parse_repo_url(url)
            client = GitHubClient(token, log=self._log)
            self._log(f"Репозиторий: {owner}/{repo_name}")
            repo = client.get_repo_info(owner, repo_name)
            self._log(f"Ветка: {repo.default_branch}")
            self._log(f"Коммит: {repo.branch_commit_sha}")
            entries = client.get_complete_tree(owner, repo_name, repo.tree_sha)
            self._log(f"Получено элементов: {len(entries)}")
            repo_dir = output_dir / repo.name
            self._log(f"Папка результатов: {repo_dir}")
            outputs = build_outputs(
                repo,
                entries,
                repo_dir,
                client=client,
                include_bundle=include_bundle,
                log=self._log,
            )
            self.events.put(("success", outputs))
        except Exception as exc:
            self.events.put(("error", str(exc)))
            self._log(traceback.format_exc())

    def _append_log(self, message: str):
        self.log_box.configure(state="normal")
        self.log_box.insert("end", message + "\n")
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _poll_events(self):
        try:
            while True:
                kind, payload = self.events.get_nowait()
                if kind == "log":
                    self._append_log(str(payload))
                elif kind == "success":
                    self.busy = False
                    self.progress.stop()
                    self.run_button.configure(state="normal")
                    self.status_var.set("Готово. Отчёты успешно созданы.")
                    self._append_log("Экспорт завершён:")
                    for path in payload.values():
                        self._append_log(f"  {path}")
                    messagebox.showinfo(
                        "RepoLinker — готово",
                        "Репозиторий исследован.\n\nСозданы файлы:\n" +
                        "\n".join(str(p) for p in payload.values()),
                    )
                elif kind == "error":
                    self.busy = False
                    self.progress.stop()
                    self.run_button.configure(state="normal")
                    self.status_var.set("Ошибка. Подробности в журнале.")
                    messagebox.showerror("RepoLinker — ошибка", str(payload))
        except queue.Empty:
            pass
        self.root.after(100, self._poll_events)


def main():
    hide_console_window()
    root = tk.Tk()
    apply_egui_dark_theme(root)
    enable_windows_dark_titlebar(root)
    RepoLinkerApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
