#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""SVG Pipe Generator — builds a closed straight-segment half-profile from millimetre coordinates."""

from __future__ import annotations

import configparser
import ctypes
import re
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import List, Optional, Tuple

APP_TITLE = "SVG Pipe Generator"
SCRIPT_DIR = Path(__file__).resolve().parent
TENON_CONFIG_DEFAULT = SCRIPT_DIR / "Tenon_TConfig.ini"

# SVG path coordinates are physical millimetres: X = radius, Y = axial height.

PALETTE = {
    "bg_main": "#1b1b1b",
    "bg_input": "#0f0f0f",
    "bg_button": "#363636",
    "bg_button_hover": "#454545",
    "bg_button_active": "#282828",
    "bg_row": "#222222",
    "bg_row_selected": "#1a334d",
    "border": "#383838",
    "accent_blue": "#0088ff",
    "text_primary": "#d4d4d4",
    "text_muted": "#888888",
    "select_bg": "#0055aa",
}


def hide_console_window() -> None:
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def enable_windows_dark_titlebar(root: tk.Tk) -> None:
    try:
        root.update_idletasks()
        hwnd = ctypes.windll.user32.GetParent(root.winfo_id())
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(hwnd, 20, ctypes.byref(value), ctypes.sizeof(value))
    except Exception:
        pass


def apply_dark_theme(root: tk.Tk) -> None:
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=PALETTE["bg_main"])
    style.configure(
        ".", background=PALETTE["bg_main"], foreground=PALETTE["text_primary"],
        bordercolor=PALETTE["border"], darkcolor=PALETTE["bg_main"],
        lightcolor=PALETTE["bg_main"], troughcolor=PALETTE["bg_input"],
        focuscolor=PALETTE["accent_blue"], font=("Segoe UI", 9),
    )
    style.configure("TFrame", background=PALETTE["bg_main"])
    style.configure("TLabel", background=PALETTE["bg_main"], foreground=PALETTE["text_primary"])
    style.configure("Title.TLabel", foreground=PALETTE["accent_blue"], font=("Segoe UI", 15, "bold"))
    style.configure("Muted.TLabel", foreground=PALETTE["text_muted"], font=("Segoe UI", 8))
    style.configure(
        "TEntry", fieldbackground=PALETTE["bg_input"], foreground=PALETTE["accent_blue"],
        insertcolor=PALETTE["accent_blue"], bordercolor=PALETTE["border"],
        selectbackground=PALETTE["select_bg"], selectforeground="#ffffff", padding=(5, 3),
    )
    style.configure(
        "TButton", background=PALETTE["bg_button"], foreground=PALETTE["text_primary"],
        bordercolor=PALETTE["border"], lightcolor=PALETTE["bg_button"],
        darkcolor=PALETTE["bg_button"], relief="flat", padding=(7, 3),
    )
    style.map(
        "TButton",
        background=[("disabled", "#252525"), ("pressed", PALETTE["bg_button_active"]),
                    ("active", PALETTE["bg_button_hover"])],
        foreground=[("disabled", "#555555")],
    )
    style.configure(
        "Accent.TButton", background=PALETTE["accent_blue"], foreground="#ffffff",
        font=("Segoe UI", 9, "bold"), padding=(10, 5),
    )
    style.map("Accent.TButton", background=[("pressed", "#0066cc"), ("active", "#1a94ff")])


def safe_name(value: str) -> str:
    value = re.sub(r'[\\/:*?"<>|]+', "_", value.strip())
    return value or "Generated_Pipe"


def parse_number(value: str, label: str, row: int) -> float:
    cleaned = value.strip().replace(",", ".")
    if not cleaned:
        raise ValueError(f"{label}, строка #{row:02d}: координата не заполнена.")
    try:
        return float(cleaned)
    except ValueError:
        raise ValueError(f"{label}, строка #{row:02d}: некорректное число «{value}».")


def parse_tenon_config(path: Path) -> List[Tuple[float, float]]:
    """Читает тенон как (H, R); первая точка — опорная, H=0."""
    if not path.exists():
        raise FileNotFoundError(f"Не найден конфиг тенона: {path}")
    cfg = configparser.ConfigParser()
    cfg.read(path, encoding="utf-8")
    if "Spline" not in cfg:
        raise ValueError("Tenon TConfig должен содержать блок [Spline].")
    points: List[Tuple[float, float]] = []
    for key, value in cfg["Spline"].items():
        parts = [part.strip() for part in value.split(",")]
        if len(parts) != 2:
            raise ValueError(f"{key}: ожидается формат H, R.")
        h = parse_number(parts[0], "Tenon H", len(points) + 1)
        radius = parse_number(parts[1], "Tenon R", len(points) + 1)
        if radius < 0:
            raise ValueError(f"{key}: радиус тенона не может быть отрицательным.")
        points.append((h, radius))
    if len(points) < 2:
        raise ValueError("В Tenon TConfig должно быть минимум две точки.")
    if abs(points[0][0]) > 1e-7:
        raise ValueError("Первая точка [Spline] должна иметь H=0 — это опорная точка тенона.")
    return points


class PointRow:
    def __init__(self, parent: tk.Frame, app: "SVGPipeGeneratorApp",
                 side: str, h_value: str = "", d_value: str = ""):
        self.app = app
        self.side = side
        self.selected = False
        self.frame = tk.Frame(parent, bg=PALETTE["bg_row"], highlightthickness=1,
                              highlightbackground=PALETTE["border"])
        self.num_var = tk.StringVar(value="")
        self.h_var = tk.StringVar(value=h_value)
        self.d_var = tk.StringVar(value=d_value)
        self.num_lbl = tk.Label(self.frame, textvariable=self.num_var, width=4,
                                bg=PALETTE["bg_row"], fg=PALETTE["text_muted"],
                                font=("Consolas", 8))
        self.num_lbl.pack(side="left", padx=(5, 3))
        tk.Label(self.frame, text="H:", bg=PALETTE["bg_row"], fg=PALETTE["text_primary"]).pack(side="left")
        self.y_entry = ttk.Entry(self.frame, textvariable=self.h_var, width=9)
        self.y_entry.pack(side="left", padx=(2, 8), pady=3)
        tk.Label(self.frame, text="D:", bg=PALETTE["bg_row"], fg=PALETTE["text_primary"]).pack(side="left")
        self.x_entry = ttk.Entry(self.frame, textvariable=self.d_var, width=8)
        self.x_entry.pack(side="left", padx=(2, 5), pady=3)
        for widget in (self.frame, self.num_lbl, self.y_entry, self.x_entry):
            widget.bind("<Button-1>", lambda _e, row=self: self.app.select_row(row))
        self.app.register_entry_widget(self.y_entry)
        self.app.register_entry_widget(self.x_entry)

    def set_index(self, index: int) -> None:
        self.num_var.set(f"#{index:02d}")

    def set_selected(self, selected: bool) -> None:
        self.selected = selected
        bg = PALETTE["bg_row_selected"] if selected else PALETTE["bg_row"]
        border = PALETTE["accent_blue"] if selected else PALETTE["border"]
        self.frame.configure(bg=bg, highlightbackground=border)
        self.num_lbl.configure(bg=bg)


class SVGPipeGeneratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        root.title(APP_TITLE)
        root.geometry("760x640")
        root.minsize(720, 560)
        self.name_var = tk.StringVar(value="")
        self.config_var = tk.StringVar(value="")
        self.tenon_config_var = tk.StringVar(value="Tenon_TConfig.ini")
        self.status_var = tk.StringVar(value="Готов к работе.")
        self.internal_rows: List[PointRow] = []
        self.external_rows: List[PointRow] = []
        self.selected_row: Optional[PointRow] = None
        self._build_ui()
        self._setup_hotkeys()
        self._add_point("internal")
        self._add_point("internal")
        self._add_point("external")
        self._add_point("external")

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=12)
        outer.pack(fill="both", expand=True)
        ttk.Label(outer, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        tk.Frame(outer, height=1, bg=PALETTE["border"]).pack(fill="x", pady=(8, 9))

        name_row = ttk.Frame(outer)
        name_row.pack(fill="x", pady=(0, 7))
        ttk.Label(name_row, text="Name:", width=12).pack(side="left")
        self.name_entry = ttk.Entry(name_row, textvariable=self.name_var)
        self.name_entry.pack(side="left", fill="x", expand=True)
        self.register_entry_widget(self.name_entry)

        tenon_row = ttk.Frame(outer)
        tenon_row.pack(fill="x", pady=(0, 7))
        ttk.Label(tenon_row, text="Tenon TConfig:", width=12).pack(side="left")
        self.tenon_entry = ttk.Entry(tenon_row, textvariable=self.tenon_config_var)
        self.tenon_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.register_entry_widget(self.tenon_entry)
        ttk.Button(tenon_row, text="Обзор", command=self._browse_tenon_config).pack(side="left")

        config_row = ttk.Frame(outer)
        config_row.pack(fill="x", pady=(0, 10))
        ttk.Label(config_row, text="Import SVG Config:", width=12).pack(side="left")
        self.config_entry = ttk.Entry(config_row, textvariable=self.config_var)
        self.config_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.register_entry_widget(self.config_entry)
        ttk.Button(config_row, text="Обзор", command=self._browse_config).pack(side="left")

        toolbar = ttk.Frame(outer)
        toolbar.pack(fill="x", pady=(0, 6))
        toolbar.grid_columnconfigure(0, weight=1, uniform="split", minsize=300)
        toolbar.grid_columnconfigure(2, weight=1, uniform="split", minsize=300)
        left = ttk.Frame(toolbar)
        left.grid(row=0, column=0, sticky="ew")
        right = ttk.Frame(toolbar)
        right.grid(row=0, column=2, sticky="ew")
        for parent, side in ((left, "internal"), (right, "external")):
            ttk.Button(parent, text="Добавить", command=lambda s=side: self._add_point(s)).pack(side="left", padx=(0, 4))
            ttk.Button(parent, text="Удалить", command=lambda s=side: self._remove_point(s)).pack(side="left", padx=(0, 4))
            ttk.Button(parent, text="Очистить", command=lambda s=side: self._clear_points(s)).pack(side="left")
        ttk.Separator(toolbar, orient="vertical").grid(row=0, column=1, sticky="ns", padx=7)

        columns = ttk.Frame(outer)
        columns.pack(fill="both", expand=True)
        columns.grid_columnconfigure(0, weight=1, uniform="split", minsize=300)
        columns.grid_columnconfigure(2, weight=1, uniform="split", minsize=300)
        columns.grid_rowconfigure(0, weight=1)
        self.internal_canvas, self.internal_holder = self._make_column(
            columns, "Internal Channel", "internal", 0)
        divider = ttk.Separator(columns, orient="vertical")
        divider.grid(row=0, column=1, sticky="ns", padx=7)
        self.external_canvas, self.external_holder = self._make_column(
            columns, "External Wall", "external", 2)

        bottom = ttk.Frame(outer)
        bottom.pack(fill="x", pady=(9, 4))
        ttk.Button(bottom, text="Export Config", command=self._export_config).pack(side="left")
        ttk.Button(bottom, text="Собрать svg", style="Accent.TButton",
                   command=self._build_svg).pack(side="right")
        ttk.Label(outer, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w")

    def _make_column(self, parent: tk.Widget, title: str, side: str, column: int):
        frame = ttk.Frame(parent)
        frame.grid(row=0, column=column, sticky="nsew")
        ttk.Label(frame, text=title, style="Muted.TLabel").pack(anchor="w", pady=(0, 4))
        container = tk.Frame(frame, bg=PALETTE["bg_input"], highlightthickness=1,
                             highlightbackground=PALETTE["border"])
        container.pack(fill="both", expand=True)
        canvas = tk.Canvas(container, bg=PALETTE["bg_input"], highlightthickness=0, bd=0)
        scrollbar = ttk.Scrollbar(container, orient="vertical", command=canvas.yview)
        holder = tk.Frame(canvas, bg=PALETTE["bg_input"])
        holder.bind("<Configure>", lambda _e, c=canvas: c.configure(scrollregion=c.bbox("all")))
        window = canvas.create_window((0, 0), window=holder, anchor="nw")
        canvas.bind("<Configure>", lambda e, c=canvas, w=window: c.itemconfigure(w, width=e.width))
        canvas.configure(yscrollcommand=scrollbar.set)
        canvas.pack(side="left", fill="both", expand=True, padx=3, pady=3)
        scrollbar.pack(side="right", fill="y")
        canvas.bind("<MouseWheel>", lambda e, c=canvas: c.yview_scroll(int(-e.delta / 120), "units"))
        return canvas, holder

    def register_entry_widget(self, widget: ttk.Entry) -> None:
        menu = tk.Menu(widget, tearoff=0, bg=PALETTE["bg_button"], fg=PALETTE["text_primary"],
                       activebackground=PALETTE["accent_blue"], activeforeground="#ffffff")
        menu.add_command(label="Вырезать", command=lambda w=widget: w.event_generate("<<Cut>>"))
        menu.add_command(label="Копировать", command=lambda w=widget: w.event_generate("<<Copy>>"))
        menu.add_command(label="Вставить", command=lambda w=widget: w.event_generate("<<Paste>>"))
        menu.add_separator()
        menu.add_command(label="Выделить всё", command=lambda w=widget: self._select_all(w))
        widget.bind("<Button-3>", lambda e, m=menu, w=widget: self._show_menu(e, m, w))

    @staticmethod
    def _show_menu(event, menu, widget) -> None:
        widget.focus_set()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _select_all(widget) -> None:
        widget.focus_set()
        widget.select_range(0, "end")
        widget.icursor("end")

    def _setup_hotkeys(self) -> None:
        self.root.bind_all("<Control-KeyPress>", self._on_ctrl_key, add="+")

    def _on_ctrl_key(self, event):
        widget = self.root.focus_get()
        if not isinstance(widget, (tk.Entry, ttk.Entry)):
            return None
        key = (event.keysym or "").lower()
        if event.keycode == 65 or key in ("a", "cyrillic_ef"):
            self._select_all(widget)
            return "break"
        if event.keycode == 67 or key in ("c", "cyrillic_es"):
            widget.event_generate("<<Copy>>")
            return "break"
        if event.keycode == 86 or key in ("v", "cyrillic_em"):
            widget.event_generate("<<Paste>>")
            return "break"
        if event.keycode == 88 or key in ("x", "cyrillic_che"):
            widget.event_generate("<<Cut>>")
            return "break"
        return None

    def _rows(self, side: str) -> List[PointRow]:
        return self.internal_rows if side == "internal" else self.external_rows

    def _holder(self, side: str) -> tk.Frame:
        return self.internal_holder if side == "internal" else self.external_holder

    def _add_point(self, side: str, h_value: str = "", d_value: str = "") -> None:
        rows = self._rows(side)
        row = PointRow(self._holder(side), self, side, h_value, d_value)
        row.frame.pack(fill="x", padx=3, pady=2)
        rows.append(row)
        self._renumber(side)
        self.status_var.set(f"{'Internal' if side == 'internal' else 'External'}: {len(rows)} точек")

    def _renumber(self, side: str) -> None:
        for index, row in enumerate(self._rows(side), start=1):
            row.set_index(index)

    def select_row(self, target: PointRow) -> None:
        for row in self.internal_rows + self.external_rows:
            row.set_selected(row is target)
        self.selected_row = target

    def _remove_point(self, side: str) -> None:
        rows = self._rows(side)
        if not rows:
            return
        target = self.selected_row if self.selected_row in rows else rows[-1]
        rows.remove(target)
        target.frame.destroy()
        if self.selected_row is target:
            self.selected_row = None
        self._renumber(side)

    def _clear_points(self, side: str) -> None:
        rows = self._rows(side)
        for row in rows:
            row.frame.destroy()
        rows.clear()
        if self.selected_row and self.selected_row.side == side:
            self.selected_row = None
        self.status_var.set(f"{'Internal' if side == 'internal' else 'External'}: список очищен")

    def _resolve_path(self, raw: str) -> Path:
        path = Path(raw.strip())
        return path if path.is_absolute() else SCRIPT_DIR / path

    def _browse_tenon_config(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Выберите Tenon TConfig",
            initialdir=str(SCRIPT_DIR),
            filetypes=[("TConfig / INI / TXT", "*.ini *.txt"), ("All files", "*.*")],
        )
        if not chosen:
            return
        path = Path(chosen)
        try:
            stored = str(path.relative_to(SCRIPT_DIR))
        except ValueError:
            stored = str(path)
        self.tenon_config_var.set(stored)

    def _browse_config(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Выберите SVG Config", initialdir=str(SCRIPT_DIR),
            filetypes=[("INI files", "*.ini"), ("All files", "*.*")],
        )
        if not chosen:
            return
        path = Path(chosen)
        try:
            stored = str(path.relative_to(SCRIPT_DIR))
        except ValueError:
            stored = str(path)
        self.config_var.set(stored)
        self._load_config(stored)

    def _load_config(self, selected_path: Optional[str] = None) -> None:
        path = self._resolve_path(selected_path or self.config_var.get())
        if not path.exists():
            messagebox.showerror("Import Config", f"Файл не найден:\n{path}")
            return
        cfg = configparser.ConfigParser()
        try:
            cfg.read(path, encoding="utf-8")
            if "Internal" not in cfg or "External" not in cfg:
                raise ValueError("Конфиг должен содержать блоки [Internal] и [External].")
            self._clear_points("internal")
            self._clear_points("external")
            for side in ("Internal", "External"):
                key = "internal" if side == "Internal" else "external"
                for _, value in cfg[side].items():
                    parts = [p.strip() for p in value.split(",")]
                    if len(parts) != 2:
                        raise ValueError(f"{side}: ожидается формат H, D.")
                    self._add_point(key, parts[0], parts[1])
            self.status_var.set(f"Конфигурация загружена: {path.name}")
        except Exception as exc:
            messagebox.showerror("Ошибка чтения конфига", str(exc))

    def _collect(self, side: str) -> List[Tuple[float, float]]:
        rows = self._rows(side)
        label = "Internal" if side == "internal" else "External"
        if len(rows) < 2:
            raise ValueError(f"{label}: нужно минимум две точки.")
        result = []
        for index, row in enumerate(rows, start=1):
            h = parse_number(row.h_var.get(), label, index)
            diameter = parse_number(row.d_var.get(), label, index)
            if diameter < 0:
                raise ValueError(f"{label}, строка #{index:02d}: D (диаметр) не может быть отрицательным.")
            result.append((h, diameter / 2.0))
        return result

    @staticmethod
    def _fmt(value: float) -> str:
        return f"{value:.4f}"

    def _build_svg(self) -> None:
        try:
            internal = self._collect("internal")  # левый столбец (Internal Channel)
            external = self._collect("external")  # правый столбец (External Wall)
            tenon_path = self._resolve_path(self.tenon_config_var.get() or TENON_CONFIG_DEFAULT.name)
            tenon = parse_tenon_config(tenon_path)

            # Опорная точка тенона (H=0) привязывается к первой точке левого столбца (internal[0])
            anchor_h = internal[0][0]
            tenon_shifted = [(h + anchor_h, radius) for h, radius in tenon]

            # Последовательность сборки замкнутого контура:
            # 1. От первой точки левого столбца (internal[0]) к опорной точке тенона (tenon_shifted[0])
            # 2. Вдоль тенона от опорной точки (tenon_shifted[0]) до противоположной точки (tenon_shifted[-1])
            # 3. От противоположной точки тенона (tenon_shifted[-1]) к первой точке правого столбца (external[0])
            # 4. Вдоль правого столбца от первой точки (external[0]) к последней (external[-1])
            # 5. От последней точки правого столбца (external[-1]) к последней точке левого (internal[-1])
            # 6. Вдоль левого столбца от последней точки (internal[-1]) обратно к первой (internal[0], замыкание Z)
            contour = list(tenon_shifted) + list(external) + list(reversed(internal))
            clean: List[Tuple[float, float]] = []
            for point in contour:
                if not clean or abs(point[0] - clean[-1][0]) > 1e-7 or abs(point[1] - clean[-1][1]) > 1e-7:
                    clean.append(point)
            if len(clean) < 4:
                raise ValueError("Получился слишком короткий контур.")

            path_lines = [f"M {self._fmt(clean[0][1])} {self._fmt(clean[0][0])}"]
            for height, radius in clean[1:]:
                path_lines.append(f"L {self._fmt(radius)} {self._fmt(height)}")
            path_data = "\n             ".join(path_lines) + "\n             Z"

            min_h = min(point[0] for point in clean)
            max_h = max(point[0] for point in clean)
            min_r = min(point[1] for point in clean)
            max_r = max(point[1] for point in clean)
            if max_h <= min_h or max_r <= min_r:
                raise ValueError("Контур имеет нулевой размер по высоте или радиусу.")
            if min_h < -1e-6 or min_r < -1e-6:
                raise ValueError("Профиль должен иметь неотрицательные H и R. Проверь порядок координат.")

            name = safe_name(self.name_var.get())
            out_path = SCRIPT_DIR / f"{name}_Spline.svg"
            svg = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<svg xmlns="http://www.w3.org/2000/svg" width="{self._fmt(max_h)}" height="{self._fmt(max_r)}" '
                f'viewBox="0 0 {self._fmt(max_h)} {self._fmt(max_r)}">\n'
                f'  <g transform="rotate(90) translate(0 -{self._fmt(max_h)})">\n'
                f'    <path id="closed-revolution-section" d="{path_data}" '
                'fill="#f2f2f2" stroke="#000000" stroke-width="0.2"/>\n'
                '  </g>\n'
                '</svg>\n'
            )
            out_path.write_text(svg, encoding="utf-8")
            self.status_var.set(f"SVG создан: {out_path.name}")
            messagebox.showinfo(
                "Собрать SVG",
                f"SVG успешно создан:\n{out_path}\n\n"
                f"Internal: {len(internal)} точек | External: {len(external)} точек | Tenon: {len(tenon)} точек",
            )
        except Exception as exc:
            messagebox.showerror("Ошибка сборки SVG", str(exc))

    def _export_config(self) -> None:
        try:
            internal = self._collect("internal")
            external = self._collect("external")
            cfg = configparser.ConfigParser()
            cfg["Internal"] = {}
            cfg["External"] = {}
            for index, (h, radius) in enumerate(internal, start=1):
                cfg["Internal"][f"Point_{index:02d}"] = f"{h:g}, {radius * 2.0:g}"
            for index, (h, radius) in enumerate(external, start=1):
                cfg["External"][f"Point_{index:02d}"] = f"{h:g}, {radius * 2.0:g}"
            name = safe_name(self.name_var.get())
            out_path = SCRIPT_DIR / f"{name}_SVGConfig.ini"
            with out_path.open("w", encoding="utf-8") as stream:
                cfg.write(stream)
            self.status_var.set(f"Конфиг сохранён: {out_path.name}")
            messagebox.showinfo("Export Config", f"Конфигурация сохранена:\n{out_path}")
        except Exception as exc:
            messagebox.showerror("Ошибка экспорта конфига", str(exc))


def main() -> None:
    hide_console_window()
    root = tk.Tk()
    apply_dark_theme(root)
    enable_windows_dark_titlebar(root)
    SVGPipeGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
