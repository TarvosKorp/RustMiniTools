#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Universal Spline to Model MS-script Generator
Генерация MAXScript (.ms) из SVG-сечения с параметрическими игровыми отверстиями
и опциональным Auto-Boolean (ProBoolean) для 3ds Max.
Windows 10/11, Python 3.9+, только стандартная библиотека.
"""

from __future__ import annotations

import configparser
import ctypes
import math
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk


APP_TITLE = "Universal Spline to Model MS-script Generator"
SCRIPT_DIR = Path(__file__).resolve().parent

# Новый SVG хранит фактические координаты в миллиметрах:
# X = радиус, Y = высота вдоль оси вращения.

# Цветовая палитра (тёмная тема с голубыми акцентами)
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
    """Скрывает консольное окно Windows при запуске через python.exe."""
    try:
        hwnd = ctypes.windll.kernel32.GetConsoleWindow()
        if hwnd:
            ctypes.windll.user32.ShowWindow(hwnd, 0)
    except Exception:
        pass


def enable_windows_dark_titlebar(root: tk.Tk) -> None:
    """Включает тёмную системную шапку окна в Windows 10/11."""
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


def apply_dark_theme(root: tk.Tk) -> None:
    """Применяет тёмную тему с голубыми элементами ко всем виджетам."""
    style = ttk.Style(root)
    style.theme_use("clam")
    root.configure(bg=PALETTE["bg_main"])

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

    style.configure("TFrame", background=PALETTE["bg_main"])
    style.configure("TLabel", background=PALETTE["bg_main"], foreground=PALETTE["text_primary"])
    style.configure(
        "Title.TLabel",
        background=PALETTE["bg_main"],
        foreground=PALETTE["accent_blue"],
        font=("Segoe UI", 16, "bold"),
    )
    style.configure(
        "Muted.TLabel",
        background=PALETTE["bg_main"],
        foreground=PALETTE["text_muted"],
        font=("Segoe UI", 9),
    )

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
        padding=(5, 4),
    )
    style.map("TEntry", bordercolor=[("focus", PALETTE["accent_blue"])])

    style.configure(
        "TButton",
        background=PALETTE["bg_button"],
        foreground=PALETTE["text_primary"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["bg_button"],
        darkcolor=PALETTE["bg_button"],
        relief="flat",
        padding=(10, 5),
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

    style.configure(
        "Accent.TButton",
        background=PALETTE["accent_blue"],
        foreground="#ffffff",
        font=("Segoe UI", 10, "bold"),
        padding=(12, 7),
    )
    style.map(
        "Accent.TButton",
        background=[
            ("disabled", "#253b52"),
            ("pressed", "#0066cc"),
            ("active", "#1a94ff"),
        ],
    )

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


@dataclass
class KnotData:
    z: float
    r: float
    ktype: str  # "#corner" or "#bezierCorner"
    in_z: float
    in_r: float
    out_z: float
    out_r: float


def svg_to_zr(sx: float, sy: float) -> Tuple[float, float]:
    """Преобразует реальные SVG-координаты (R, H) в (Z, R) для MAXScript."""
    return sy, sx


def parse_svg_profile(svg_path: Path, only_line: bool = False) -> List[KnotData]:
    if not svg_path.exists():
        raise FileNotFoundError(f"SVG-файл не найден:\n{svg_path}")

    root = ET.parse(svg_path).getroot()
    d = next(
        (
            e.attrib["d"]
            for e in root.iter()
            if e.tag.split("}")[-1] == "path"
            and e.attrib.get("id") == "closed-revolution-section"
        ),
        None,
    )
    if not d:
        d = next(
            (e.attrib["d"] for e in root.iter() if e.tag.split("}")[-1] == "path" and "d" in e.attrib),
            None,
        )
    if not d:
        raise ValueError("В SVG не найден тег <path> с контуром сечения.")

    tokens = re.findall(r"[MmLlCcZz]|[-+]?(?:\d*\.\d+|\d+\.?)(?:[eE][-+]?\d+)?", d)
    if not tokens:
        raise ValueError("Пустой атрибут d в SVG.")

    # Строим список сегментов: ("L", p1, p2) или ("C", p1, c1, c2, p2)
    segments = []
    i = 0
    cmd = None
    cur = (0.0, 0.0)
    start_pt = (0.0, 0.0)

    while i < len(tokens):
        if tokens[i].isalpha():
            cmd = tokens[i]
            i += 1
            if cmd.lower() == "z":
                if math.dist(cur, start_pt) > 1e-6:
                    segments.append(("L", cur, start_pt))
                cur = start_pt
                break
            continue

        if cmd is None:
            raise ValueError("Некорректный формат пути SVG.")

        if cmd in ("M", "m"):
            x, y = float(tokens[i]), float(tokens[i + 1])
            i += 2
            if cmd == "m":
                x += cur[0]
                y += cur[1]
            cur = (x, y)
            start_pt = cur
            cmd = "L" if cmd == "M" else "l"

        elif cmd in ("L", "l"):
            x, y = float(tokens[i]), float(tokens[i + 1])
            i += 2
            if cmd == "l":
                x += cur[0]
                y += cur[1]
            nxt = (x, y)
            if math.dist(cur, nxt) > 1e-6:
                segments.append(("L", cur, nxt))
            cur = nxt

        elif cmd in ("C", "c"):
            x1, y1 = float(tokens[i]), float(tokens[i + 1])
            x2, y2 = float(tokens[i + 2]), float(tokens[i + 3])
            x, y = float(tokens[i + 4]), float(tokens[i + 5])
            i += 6
            if cmd == "c":
                x1 += cur[0]
                y1 += cur[1]
                x2 += cur[0]
                y2 += cur[1]
                x += cur[0]
                y += cur[1]
            nxt = (x, y)
            if only_line:
                if math.dist(cur, nxt) > 1e-6:
                    segments.append(("L", cur, nxt))
            else:
                if math.dist(cur, nxt) > 1e-6:
                    segments.append(("C", cur, (x1, y1), (x2, y2), nxt))
            cur = nxt
        else:
            raise ValueError(f"Неподдерживаемая команда SVG: {cmd}")

    if len(segments) < 3:
        raise ValueError("Слишком мало сегментов для построения замкнутого сечения.")

    knots: List[KnotData] = []
    n_seg = len(segments)

    for idx in range(n_seg):
        seg_prev = segments[(idx - 1) % n_seg]
        seg_curr = segments[idx]

        pt_svg = seg_curr[1]
        in_svg = seg_prev[3] if seg_prev[0] == "C" else pt_svg
        out_svg = seg_curr[2] if seg_curr[0] == "C" else pt_svg

        z, r = svg_to_zr(pt_svg[0], pt_svg[1])
        iz, ir = svg_to_zr(in_svg[0], in_svg[1])
        oz, orad = svg_to_zr(out_svg[0], out_svg[1])

        is_bezier = (not only_line) and (seg_prev[0] == "C" or seg_curr[0] == "C")
        ktype = "#bezierCorner" if is_bezier else "#corner"

        knots.append(
            KnotData(
                z=z,
                r=max(0.0, r),
                ktype=ktype,
                in_z=iz,
                in_r=max(0.0, ir),
                out_z=oz,
                out_r=max(0.0, orad),
            )
        )

    return knots


def generate_maxscript(
    model_name: str,
    knots: List[KnotData],
    holes: List[Tuple[str, float, float, float, float]],
    auto_boolean: bool,
    revolution_steps: int = 120,
) -> str:
    safe_name = model_name.strip() or "Custom_Chanter"
    group_name = f"{safe_name}_Holes"

    knot_lines = []
    for k in knots:
        knot_lines.append(
            f"        #({k.ktype}, [{k.r:.6f}, {k.z:.6f}, 0], "
            f"[{k.in_r:.6f}, {k.in_z:.6f}, 0], [{k.out_r:.6f}, {k.out_z:.6f}, 0])"
        )
    knots_block = "#(\n" + ",\n".join(knot_lines) + "\n    )"

    hole_lines = []
    for h_name, z_pos, diam, angle_deg, offset_mm in holes:
        hole_lines.append(
            f'        #("{h_name}", {z_pos:.6f}, {diam:.6f}, {angle_deg:.6f}, {offset_mm:.6f})'
        )
    holes_block = "#(\n" + ",\n".join(hole_lines) + "\n    )" if hole_lines else "#()"

    ms_lines = [
        f"-- {safe_name} — generated by {APP_TITLE}",
        "-- Millimetres; Z=0 at lower bell rim.",
        "(",
        f"    local revolutionSteps = {revolution_steps}",
        "    local cutterSides = 48",
        "    local cutterLength = 60.0",
        f'    local bodyName = "{safe_name}"',
        f'    local groupName = "{group_name}"',
        f"    local doAutoBoolean = {'true' if auto_boolean else 'false'}",
        f"    local knotData = {knots_block}",
        f"    local holeSpecs = {holes_block}",
        "",
        "    fn buildLatheBody kData steps bName =",
        "    (",
        "        local shp = splineShape name:bName",
        "        addNewSpline shp",
        "        for k in kData do",
        "        (",
        "            local kType = k[1]",
        "            local pt    = k[2]",
        "            local inV   = k[3]",
        "            local outV  = k[4]",
        "            if kType == #corner then",
        "                addKnot shp 1 #corner #line pt",
        "            else",
        "                addKnot shp 1 #bezierCorner #curve pt inV outV",
        "        )",
        "        close shp 1",
        "        updateShape shp",
        "",
        "        -- Rotate spline -90 deg around X so local Y points straight up along world +Z",
        "        shp.rotation = (eulerangles -90 0 0)",
        "",
        "        local latheMod = Lathe()",
        "        latheMod.segments = steps",
        "        latheMod.weldCore = true",
        "        latheMod.flipNormals = false",
        "        addModifier shp latheMod",
        "",
        "        shp.name = bName",
        "        shp",
        "    )",
        "",
        "    fn rotateNamedNodeAroundWorldZ nodeName angleDeg =",
        "    (",
        "        local node = getNodeByName nodeName",
        "        if node != undefined and isValidNode node then",
        "        (",
        "            -- Rotate the complete node transform around the world origin.",
        "            node.transform = (rotateZMatrix angleDeg) * node.transform",
        "        )",
        "        else",
        "            format \"Could not find node named % for world-Z rotation.\\n\" nodeName",
        "    )",
        "",
        "    fn makeCutter rec sides cLen =",
        "    (",
        "        local hName  = rec[1]",
        "        local zPos   = rec[2]",
        "        local diam   = rec[3]",
        "        local angDeg = rec[4]",
        "        local offMm  = rec[5]",
        "",
        "        -- Base orientation: cylinder extends forward along -Y (Front viewport),",
        "        -- base pivot strictly on central axis [0, 0, 0] before offset & rotation.",
        "        local c = cylinder radius:(diam / 2.0) height:cLen sides:sides heightsegs:1 capsegs:1",
        '        c.name = hName + "_CUTTER"',
        "        c.rotation = (eulerangles 90 0 0)",
        "",
        "        -- Apply horizontal offset along X in local space before Z-rotation",
        "        move c [offMm, 0, 0]",
        "",
        "        -- Rotate around world Z axis by Angle degrees",
        "        rotate c (angleaxis angDeg [0, 0, 1])",
        "",
        "        -- Position at height L from bell rim",
        "        c.pos += [0, 0, zPos]",
        "        c",
        "    )",
        "",
        "    try",
        "    (",
        "        units.SystemType = #Millimeters",
        "        units.SystemScale = 1.0",
        "        units.DisplayType = #Metric",
        "        units.MetricType = #Millimeters",
        "    )",
        '    catch (format "Could not change system units; coordinates are in millimetres.\n")',
        "",
        "    local body = buildLatheBody knotData revolutionSteps bodyName",
        "",
        "    if holeSpecs.count > 0 then",
        "    (",
        "        local cutters = #()",
        "        for rec in holeSpecs do",
        "        (",
        "            append cutters (makeCutter rec cutterSides cutterLength)",
        "        )",
        "",
        "        -- Group cutters first, then rotate the GROUP around the world origin.",
        "        -- The body keeps its original orientation in both generation modes.",
        "        local holeGroup = group cutters name:groupName",
        "        rotateNamedNodeAroundWorldZ groupName 180",
        "",
        "        if doAutoBoolean then",
        "        (",
        "            -- Apply the group transform before Boolean; ungrouping preserves",
        "            -- the cutters' resulting world-space positions.",
        "            ungroup holeGroup",
        "            try",
        "            (",
        "                ProBoolean.CreateBooleanObjects body cutters 2 1 1",
        "                body.name = bodyName",
        "                select body",
        "                -- '$' is intentional: this method expects a selected ProBoolean object.",
        "                try (ProBoolean.SetPlanarEdgeRemoval $ 2) catch (format \"Could not set ProBoolean Planar Edge Removal.\\n\")",
        "                format \"% generated with Auto-Boolean (% cutters subtracted).\\n\" bodyName cutters.count",
        "            )",
        "            catch",
        "            (",
        "                format \"ProBoolean failed; rebuilding the rotated cutter group.\\n\"",
        "                for c in cutters do if isValidNode c do delete c",
        "                local fallbackCutters = #()",
        "                for rec in holeSpecs do append fallbackCutters (makeCutter rec cutterSides cutterLength)",
        "                local fallbackGroup = group fallbackCutters name:groupName",
        "                rotateNamedNodeAroundWorldZ groupName 180",
        "            )",
        "        )",
        "        else",
        "        (",
        "            format \"% generated. Knots: % | Cutters: %\\n\" bodyName knotData.count cutters.count",
        "        )",
        "    )",
        "    else",
        "    (",
        '        format "% generated (body only, no holes). Knots: %\n" bodyName knotData.count',
        "    )",
        ")",
    ]
    return "\n".join(ms_lines) + "\n"


class HoleRow:
    """Одна интерактивная строка параметров отверстия."""

    def __init__(
        self,
        parent: tk.Frame,
        app: "SplineGeneratorApp",
        l_val: str = "0",
        d_val: str = "6.0",
        angle_val: str = "0",
        offset_val: str = "0",
        reso_val: bool = False,
    ):
        self.app = app
        self.selected = False

        self.frame = tk.Frame(
            parent,
            bg=PALETTE["bg_row"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
            padx=6,
            pady=3,
        )

        self.num_var = tk.StringVar(value="#01")
        self.l_var = tk.StringVar(value=str(l_val))
        self.d_var = tk.StringVar(value=str(d_val))
        self.angle_var = tk.StringVar(value=str(angle_val))
        self.offset_var = tk.StringVar(value=str(offset_val))
        self.reso_var = tk.BooleanVar(value=bool(reso_val))

        self.num_lbl = tk.Label(
            self.frame,
            textvariable=self.num_var,
            bg=PALETTE["bg_row"],
            fg=PALETTE["accent_blue"],
            font=("Consolas", 10, "bold"),
            width=4,
            anchor="w",
        )
        self.num_lbl.pack(side="left", padx=(0, 6))

        self.entries: List[ttk.Entry] = []

        def add_field(label_text: str, var: tk.StringVar):
            lbl = tk.Label(
                self.frame,
                text=label_text,
                bg=PALETTE["bg_row"],
                fg=PALETTE["text_primary"],
                font=("Segoe UI", 9),
            )
            lbl.pack(side="left", padx=(4, 2))
            ent = ttk.Entry(self.frame, textvariable=var, width=6, justify="center")
            ent.pack(side="left", padx=(0, 6))
            self.entries.append(ent)
            self.app.register_entry_widget(ent)
            ent.bind("<FocusIn>", lambda _e: self.app.select_row(self))
            lbl.bind("<Button-1>", lambda _e: self.app.select_row(self))

        add_field("L:", self.l_var)
        add_field("D:", self.d_var)
        add_field("Angle:", self.angle_var)
        add_field("Offset:", self.offset_var)

        self.reso_chk = ttk.Checkbutton(self.frame, text="Reso", variable=self.reso_var)
        self.reso_chk.pack(side="left", padx=(6, 2))

        self.frame.bind("<Button-1>", lambda _e: self.app.select_row(self))
        self.num_lbl.bind("<Button-1>", lambda _e: self.app.select_row(self))

    def set_index(self, idx: int) -> None:
        self.num_var.set(f"#{idx:02d}")

    def set_selected(self, state: bool) -> None:
        self.selected = state
        bg = PALETTE["bg_row_selected"] if state else PALETTE["bg_row"]
        border = PALETTE["accent_blue"] if state else PALETTE["border"]
        self.frame.configure(bg=bg, highlightbackground=border)
        for child in self.frame.winfo_children():
            if isinstance(child, tk.Label):
                child.configure(bg=bg)


class SplineGeneratorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("720x660")
        self.root.minsize(720, 580)

        self.name_var = tk.StringVar(value="")
        self.svg_var = tk.StringVar(value="SplineEtalon.svg")
        self.only_line_var = tk.BooleanVar(value=False)
        self.config_var = tk.StringVar(value="Config.ini")
        self.auto_bool_var = tk.BooleanVar(value=False)
        self.status_var = tk.StringVar(value="Готов к работе.")

        self.rows: List[HoleRow] = []
        self.selected_row: Optional[HoleRow] = None

        self._build_ui()
        self._setup_global_hotkeys()
        self._init_default_rows()

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=14)
        outer.pack(fill="both", expand=True)

        # 1. Шапка
        ttk.Label(outer, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Генерация MAXScript (.ms) из SVG-сечения с параметрическими игровыми отверстиями",
            style="Muted.TLabel",
        ).pack(anchor="w", pady=(0, 8))

        tk.Frame(outer, height=1, bg=PALETTE["border"]).pack(fill="x", pady=(0, 10))

        # 2. Name
        row_name = ttk.Frame(outer)
        row_name.pack(fill="x", pady=(0, 6))
        ttk.Label(row_name, text="Name:", width=14).pack(side="left")
        self.name_entry = ttk.Entry(row_name, textvariable=self.name_var)
        self.name_entry.pack(side="left", fill="x", expand=True)
        self.register_entry_widget(self.name_entry)

        # 3. Reference SVG
        row_svg = ttk.Frame(outer)
        row_svg.pack(fill="x", pady=(0, 6))
        ttk.Label(row_svg, text="Reference SVG:", width=14).pack(side="left")
        self.svg_entry = ttk.Entry(row_svg, textvariable=self.svg_var)
        self.svg_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.register_entry_widget(self.svg_entry)
        ttk.Button(row_svg, text="Обзор...", command=self._browse_svg).pack(side="left")

        # 4. Only Line
        row_line = ttk.Frame(outer)
        row_line.pack(fill="x", pady=(0, 8))
        ttk.Checkbutton(
            row_line,
            text="Only Line (игнорировать кривые Безье, строить только прямые сегменты)",
            variable=self.only_line_var,
        ).pack(anchor="w")

        # 5. Load Config
        row_cfg = ttk.Frame(outer)
        row_cfg.pack(fill="x", pady=(0, 10))
        ttk.Label(row_cfg, text="Load Config:", width=14).pack(side="left")
        self.cfg_entry = ttk.Entry(row_cfg, textvariable=self.config_var)
        self.cfg_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))
        self.register_entry_widget(self.cfg_entry)
        ttk.Button(row_cfg, text="Обзор", command=self._browse_config).pack(side="left")

        # 6. Зона интерактивных строк отверстий
        holes_header = ttk.Frame(outer)
        holes_header.pack(fill="x", pady=(0, 4))
        ttk.Label(holes_header, text="Параметры отверстий (мм / градусы):").pack(side="left")

        holes_toolbar = ttk.Frame(outer)
        holes_toolbar.pack(fill="x", pady=(0, 6))
        ttk.Button(holes_toolbar, text="+ Добавить отверстие", command=self._add_hole_row).pack(
            side="left", padx=(0, 6)
        )
        ttk.Button(
            holes_toolbar, text="- Удалить выбранное / последнее", command=self._remove_hole_row
        ).pack(side="left", padx=(0, 12))
        ttk.Checkbutton(
            holes_toolbar, text="Auto-Boolean", variable=self.auto_bool_var
        ).pack(side="left")
        ttk.Button(holes_toolbar, text="Очистить все", command=self._clear_all_rows).pack(side="right")
        ttk.Button(holes_toolbar, text="Сбросить", command=self._reset_rows).pack(side="right", padx=(0, 5))

        # Прокручиваемый контейнер для строк
        list_container = tk.Frame(
            outer,
            bg=PALETTE["bg_input"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        list_container.pack(fill="both", expand=True, pady=(0, 10))

        self.canvas = tk.Canvas(
            list_container,
            bg=PALETTE["bg_input"],
            highlightthickness=0,
            bd=0,
        )
        self.scrollbar = ttk.Scrollbar(list_container, orient="vertical", command=self.canvas.yview)
        self.rows_holder = tk.Frame(self.canvas, bg=PALETTE["bg_input"])

        self.rows_holder.bind(
            "<Configure>",
            lambda _e: self.canvas.configure(scrollregion=self.canvas.bbox("all")),
        )
        self.canvas_window = self.canvas.create_window((0, 0), window=self.rows_holder, anchor="nw")
        self.canvas.bind(
            "<Configure>",
            lambda e: self.canvas.itemconfigure(self.canvas_window, width=e.width),
        )
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True, padx=4, pady=4)
        self.scrollbar.pack(side="right", fill="y")

        # Прокрутка колесом мыши над списком
        self.canvas.bind_all("<MouseWheel>", self._on_mousewheel)

        # 7 & 8. Нижняя панель кнопок: Export Config и широкая Generate MS-script
        bottom_bar = ttk.Frame(outer)
        bottom_bar.pack(fill="x", pady=(0, 6))

        ttk.Button(bottom_bar, text="Export Config", command=self._export_config).pack(
            side="left", padx=(0, 10), ipady=4
        )
        ttk.Button(
            bottom_bar,
            text="Generate MS-script",
            style="Accent.TButton",
            command=self._generate_ms,
        ).pack(side="left", fill="x", expand=True)

        ttk.Label(outer, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w")

    def _on_mousewheel(self, event: tk.Event) -> None:
        if self.canvas.winfo_height() < self.rows_holder.winfo_reqheight():
            self.canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")

    def register_entry_widget(self, widget: ttk.Entry) -> None:
        """Привязывает контекстное меню ПКМ к полю ввода."""
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

    @staticmethod
    def _show_context_menu(event: tk.Event, menu: tk.Menu, widget: tk.Widget) -> None:
        widget.focus_set()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _select_all_entry(widget: ttk.Entry) -> None:
        widget.focus_set()
        widget.select_range(0, "end")
        widget.icursor("end")

    def _setup_global_hotkeys(self) -> None:
        """Горячие клавиши Ctrl+A/C/V/X независимо от раскладки клавиатуры (RU/EN)."""
        self.root.bind_all("<Control-KeyPress>", self._on_ctrl_keypress, add="+")

    def _on_ctrl_keypress(self, event: tk.Event):
        if event.state & 0x20000 or event.state & 0x0008:
            return None

        widget = self.root.focus_get()
        if not isinstance(widget, (tk.Entry, ttk.Entry)):
            return None

        vk = event.keycode
        keysym = (event.keysym or "").lower()
        is_a = vk == 65 or keysym in ("a", "cyrillic_ef")
        is_c = vk == 67 or keysym in ("c", "cyrillic_es")
        is_v = vk == 86 or keysym in ("v", "cyrillic_em")
        is_x = vk == 88 or keysym in ("x", "cyrillic_che")

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
        return None

    def _init_default_rows(self) -> None:
        """По умолчанию создаёт 9 строк: 1-я (Thumb) с Angle=180, остальные с Angle=0."""
        for idx in range(9):
            angle = "180" if idx == 0 else "0"
            self._add_hole_row(l_val="0", d_val="6.0", angle_val=angle, offset_val="0", reso_val=False)
        self.status_var.set("Инициализировано 9 строк отверстий по умолчанию.")

    def _renumber_rows(self) -> None:
        for idx, row in enumerate(self.rows, start=1):
            row.set_index(idx)

    def select_row(self, target: HoleRow) -> None:
        for r in self.rows:
            r.set_selected(r is target)
        self.selected_row = target

    def _add_hole_row(
        self,
        l_val: str = "0",
        d_val: str = "6.0",
        angle_val: Optional[str] = None,
        offset_val: str = "0",
        reso_val: bool = False,
    ) -> None:
        if angle_val is None:
            angle_val = "180" if len(self.rows) == 0 else "0"
        row = HoleRow(
            self.rows_holder,
            self,
            l_val=l_val,
            d_val=d_val,
            angle_val=angle_val,
            offset_val=offset_val,
            reso_val=reso_val,
        )
        row.frame.pack(fill="x", pady=2, padx=2)
        self.rows.append(row)
        self._renumber_rows()
        self.status_var.set(f"Всего отверстий в списке: {len(self.rows)}")

    def _remove_hole_row(self) -> None:
        if not self.rows:
            return
        target = self.selected_row if (self.selected_row in self.rows) else self.rows[-1]
        self.rows.remove(target)
        target.frame.destroy()
        if self.selected_row is target:
            self.selected_row = None
        self._renumber_rows()
        self.status_var.set(f"Удалено отверстие. Осталось: {len(self.rows)}")

    def _clear_all_rows(self) -> None:
        for r in self.rows:
            r.frame.destroy()
        self.rows.clear()
        self.selected_row = None
        self.status_var.set("Список отверстий очищен (будет сгенерировано только тело чантера).")

    def _reset_rows(self) -> None:
        self._clear_all_rows()
        self._init_default_rows()
        self.status_var.set("Стандартный набор отверстий восстановлен.")

    def _resolve_path(self, raw_path: str) -> Path:
        p = Path(raw_path.strip())
        if not p.is_absolute():
            p = SCRIPT_DIR / p
        return p

    def _browse_svg(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Выберите Reference SVG",
            initialdir=str(SCRIPT_DIR),
            filetypes=[("SVG files", "*.svg"), ("All files", "*.*")],
        )
        if chosen:
            chosen_path = Path(chosen)
            try:
                rel = chosen_path.relative_to(SCRIPT_DIR)
                self.svg_var.set(str(rel))
            except ValueError:
                self.svg_var.set(str(chosen_path))

    @staticmethod
    def _parse_float(val: str, field_name: str, row_num: int) -> float:
        cleaned = val.strip().replace(",", ".")
        if not cleaned:
            return 0.0
        try:
            return float(cleaned)
        except ValueError:
            raise ValueError(f"Строка #{row_num:02d}: некорректное число в поле '{field_name}' ({val}).")

    def _collect_holes_for_ms(self) -> List[Tuple[str, float, float, float, float]]:
        result: List[Tuple[str, float, float, float, float]] = []
        for idx, row in enumerate(self.rows, start=1):
            l_mm = self._parse_float(row.l_var.get(), "L", idx)
            d_mm = self._parse_float(row.d_var.get(), "D", idx)
            ang = self._parse_float(row.angle_var.get(), "Angle", idx)
            off = self._parse_float(row.offset_var.get(), "Offset", idx)
            is_reso = row.reso_var.get()

            if d_mm <= 0:
                raise ValueError(f"Строка #{idx:02d}: диаметр D должен быть больше нуля.")

            base_name = f"Hole_{idx:02d}"
            if is_reso:
                result.append((f"{base_name}_A", l_mm, d_mm, ang, off))
                result.append((f"{base_name}_B", l_mm, d_mm, ang + 180.0, off))
            else:
                result.append((base_name, l_mm, d_mm, ang, off))
        return result

    def _export_config(self) -> None:
        raw_name = self.name_var.get().strip()
        safe_n = re.sub(r'[\\/:*?"<>|]+', "_", raw_name) if raw_name else "Default"
        out_path = SCRIPT_DIR / f"{safe_n}_Config.ini"

        cfg = configparser.ConfigParser()
        cfg["General"] = {"count": str(len(self.rows))}

        for idx, row in enumerate(self.rows, start=1):
            cfg[f"Hole_{idx:02d}"] = {
                "L": row.l_var.get().strip() or "0",
                "D": row.d_var.get().strip() or "6.0",
                "Angle": row.angle_var.get().strip() or "0",
                "Offset": row.offset_var.get().strip() or "0",
                "Reso": str(row.reso_var.get()),
            }

        try:
            with out_path.open("w", encoding="utf-8") as f:
                cfg.write(f)
            self.status_var.set(f"Конфиг сохранён: {out_path.name}")
            messagebox.showinfo("Export Config", f"Конфигурация успешно сохранена:\n{out_path}")
        except Exception as exc:
            messagebox.showerror("Ошибка сохранения", str(exc))

    def _browse_config(self) -> None:
        chosen = filedialog.askopenfilename(
            title="Выберите конфигурацию", initialdir=str(SCRIPT_DIR),
            filetypes=[("INI files", "*.ini"), ("All files", "*.*")],
        )
        if not chosen:
            return
        chosen_path = Path(chosen)
        try:
            stored_path = str(chosen_path.relative_to(SCRIPT_DIR))
        except ValueError:
            stored_path = str(chosen_path)
        self.config_var.set(stored_path)
        self._load_config(stored_path)

    def _load_config(self, selected_path: Optional[str] = None) -> None:
        cfg_raw = selected_path or self.config_var.get().strip() or "Config.ini"
        cfg_path = self._resolve_path(cfg_raw)
        if not cfg_path.exists():
            messagebox.showerror("Load Config", f"Файл конфигурации не найден:\n{cfg_path}")
            return

        cfg = configparser.ConfigParser()
        try:
            cfg.read(cfg_path, encoding="utf-8")
            if "General" in cfg:
                gen = cfg["General"]
                if gen.get("name"):
                    self.name_var.set(gen.get("name", ""))
                if gen.get("svg"):
                    self.svg_var.set(gen.get("svg", "SplineEtalon.svg"))
                if "only_line" in gen:
                    self.only_line_var.set(gen.getboolean("only_line", fallback=False))
                if "auto_boolean" in gen:
                    self.auto_bool_var.set(gen.getboolean("auto_boolean", fallback=False))

            hole_sections = [s for s in cfg.sections() if s.startswith("Hole_")]
            self._clear_all_rows()

            for sec in hole_sections:
                sdata = cfg[sec]
                self._add_hole_row(
                    l_val=sdata.get("L", "0"),
                    d_val=sdata.get("D", "6.0"),
                    angle_val=sdata.get("Angle", "0"),
                    offset_val=sdata.get("Offset", "0"),
                    reso_val=sdata.getboolean("Reso", fallback=False),
                )

            self.status_var.set(f"Загружено {len(self.rows)} отверстий из {cfg_path.name}.")
        except Exception as exc:
            messagebox.showerror("Ошибка чтения конфига", str(exc))

    def _generate_ms(self) -> None:
        try:
            raw_name = self.name_var.get().strip()
            safe_name = re.sub(r'[\\/:*?"<>|]+', "_", raw_name) if raw_name else "Generated_Chanter"

            svg_raw = self.svg_var.get().strip() or "SplineEtalon.svg"
            svg_path = self._resolve_path(svg_raw)

            knots = parse_svg_profile(svg_path, only_line=self.only_line_var.get())
            holes = self._collect_holes_for_ms()

            ms_code = generate_maxscript(
                model_name=safe_name,
                knots=knots,
                holes=holes,
                auto_boolean=self.auto_bool_var.get(),
            )
            out_ms = SCRIPT_DIR / f"{safe_name}.ms"
            out_ms.write_text(ms_code, encoding="utf-8")

            self.status_var.set(f"Сгенерирован файл: {out_ms.name} (отверстий: {len(holes)})")
            messagebox.showinfo(
                "Generate MS-script",
                f"MAXScript успешно создан:\n{out_ms}\n\n"
                f"Вершин профиля: {len(knots)}\n"
                f"Цилиндров-резаков: {len(holes)}\n"
                f"Auto-Boolean: {'Вкл' if self.auto_bool_var.get() else 'Выкл'}",
            )
        except Exception as exc:
            messagebox.showerror("Ошибка генерации", str(exc))


def main() -> None:
    hide_console_window()
    root = tk.Tk()
    apply_dark_theme(root)
    enable_windows_dark_titlebar(root)
    SplineGeneratorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
