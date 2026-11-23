#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Windows Per-Process Network Traffic Monitor (Real-Time ETW + WinAPI)
Отслеживает сетевой трафик по процессам в реальном времени (включая трафик через локальный прокси).
Поддерживает быстрое переключение режимов Online / Offline (блокировка через Windows Firewall),
выбор интервала обновления и закрепление поверх всех окон.
Windows 10/11, Python 3.9+, только стандартная библиотека.
"""

from __future__ import annotations

import ctypes
import ctypes.wintypes as wintypes
import glob
import os
import socket
import struct
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

import tkinter as tk
from tkinter import messagebox, ttk


APP_TITLE = "Network Traffic Monitor"
FW_RULE_NAME = "TrafficMonitor_Offline_Block_All"

PALETTE = {
    "bg_main": "#1b1b1b",
    "bg_input": "#0f0f0f",
    "bg_button": "#363636",
    "bg_button_hover": "#454545",
    "bg_button_active": "#282828",
    "bg_row": "#222222",
    "border": "#383838",
    "accent_blue": "#0088ff",
    "accent_blue_dim": "#193a5a",
    "accent_green": "#2ea043",
    "accent_red": "#d73a49",
    "accent_maroon": "#4a151b",
    "text_primary": "#d4d4d4",
    "text_muted": "#888888",
    "select_bg": "#0055aa",
}


def cleanup_etw_log_files() -> None:
    """Удаляет остаточные файлы логов NT Kernel Logger, если они были созданы системой."""
    search_dirs = set()
    try:
        search_dirs.add(os.getcwd())
    except Exception:
        pass
    try:
        search_dirs.add(os.path.dirname(os.path.abspath(sys.argv[0])))
    except Exception:
        pass
    sys_drive = os.environ.get("SystemDrive", "C:")
    if sys_drive:
        search_dirs.add(sys_drive + os.sep)

    for folder in search_dirs:
        if not folder or not os.path.isdir(folder):
            continue
        pattern = os.path.join(folder, "NT Kernel Logger*")
        for path in glob.glob(pattern):
            try:
                if os.path.isfile(path):
                    os.remove(path)
            except Exception:
                pass


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
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        value = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(value), ctypes.sizeof(value)
        )
    except Exception:
        pass


def apply_dark_theme(root: tk.Tk) -> None:
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
        font=("Segoe UI", 9),
    )

    style.configure("TFrame", background=PALETTE["bg_main"])
    style.configure("TLabel", background=PALETTE["bg_main"], foreground=PALETTE["text_primary"])
    style.configure(
        "Title.TLabel",
        background=PALETTE["bg_main"],
        foreground=PALETTE["accent_blue"],
        font=("Segoe UI", 12, "bold"),
    )
    style.configure(
        "Muted.TLabel",
        background=PALETTE["bg_main"],
        foreground=PALETTE["text_muted"],
        font=("Segoe UI", 8),
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
        padding=(4, 3),
    )
    style.map("TEntry", bordercolor=[("focus", PALETTE["accent_blue"])])

    style.configure(
        "TCombobox",
        fieldbackground=PALETTE["bg_input"],
        background=PALETTE["bg_button"],
        foreground=PALETTE["accent_blue"],
        arrowcolor=PALETTE["text_primary"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["bg_button"],
        darkcolor=PALETTE["bg_button"],
        selectbackground=PALETTE["select_bg"],
        selectforeground="#ffffff",
        padding=(4, 2),
    )
    style.map(
        "TCombobox",
        fieldbackground=[("readonly", PALETTE["bg_input"])],
        foreground=[("readonly", PALETTE["accent_blue"])],
        background=[("active", PALETTE["bg_button_hover"])],
    )

    style.configure(
        "TButton",
        background=PALETTE["bg_button"],
        foreground=PALETTE["text_primary"],
        bordercolor=PALETTE["border"],
        lightcolor=PALETTE["bg_button"],
        darkcolor=PALETTE["bg_button"],
        relief="flat",
        padding=(7, 3),
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
        "BlueAction.TButton",
        background=PALETTE["accent_blue"],
        foreground="#ffffff",
        font=("Segoe UI", 9, "bold"),
        padding=(8, 3),
    )
    style.map(
        "BlueAction.TButton",
        background=[
            ("pressed", "#0066cc"),
            ("active", "#1a94ff"),
        ],
    )

    style.configure(
        "TopOff.TButton",
        background=PALETTE["bg_button"],
        foreground=PALETTE["text_muted"],
        font=("Segoe UI", 8),
        padding=(6, 2),
    )
    style.map(
        "TopOff.TButton",
        background=[("active", PALETTE["bg_button_hover"])],
        foreground=[("active", PALETTE["text_primary"])],
    )

    style.configure(
        "TopOn.TButton",
        background=PALETTE["accent_blue"],
        foreground="#ffffff",
        font=("Segoe UI", 8, "bold"),
        padding=(6, 2),
    )
    style.map(
        "TopOn.TButton",
        background=[("active", "#1a94ff")],
    )

    style.configure(
        "OnlineState.TButton",
        background=PALETTE["accent_green"],
        foreground="#ffffff",
        font=("Segoe UI", 8, "bold"),
        padding=(8, 2),
    )
    style.map(
        "OnlineState.TButton",
        background=[
            ("disabled", PALETTE["accent_blue_dim"]),
            ("pressed", "#238636"),
            ("active", "#3fb950"),
        ],
        foreground=[("disabled", "#7cc0ff")],
    )

    style.configure(
        "OfflineState.TButton",
        background=PALETTE["accent_red"],
        foreground="#ffffff",
        font=("Segoe UI", 8, "bold"),
        padding=(8, 2),
    )
    style.map(
        "OfflineState.TButton",
        background=[
            ("disabled", PALETTE["accent_maroon"]),
            ("pressed", "#a62633"),
            ("active", "#e5534b"),
        ],
        foreground=[("disabled", "#b87a82")],
    )


def format_size(num_bytes: int) -> str:
    """Форматирует байты в Kb (до 1000 Kb) и далее строго в Mb."""
    kb = num_bytes / 1024.0
    if kb < 1000.0:
        return f"{kb:.1f} Kb"
    mb = kb / 1024.0
    return f"{mb:.2f} Mb"


def is_user_admin() -> bool:
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except Exception:
        return False


def relaunch_as_admin() -> bool:
    try:
        script_path = os.path.abspath(sys.argv[0])
        params = f'"{script_path}"'
        res = ctypes.windll.shell32.ShellExecuteW(None, "runas", sys.executable, params, None, 1)
        return res > 32
    except Exception:
        return False


def _run_netsh(args: List[str]) -> Tuple[int, str]:
    try:
        creationflags = 0x08000000
        proc = subprocess.run(
            ["netsh"] + args,
            capture_output=True,
            text=True,
            encoding="cp866",
            errors="ignore",
            creationflags=creationflags,
        )
        return proc.returncode, (proc.stdout + proc.stderr).strip()
    except Exception as exc:
        return -1, str(exc)


def set_firewall_offline(enable_offline: bool) -> Tuple[bool, str]:
    """
    Управляет блокировкой всего сетевого трафика через правила Windows Firewall (WFP),
    не отключая сам сетевой адаптер / Wi-Fi.
    """
    _run_netsh(["advfirewall", "firewall", "delete", "rule", f"name={FW_RULE_NAME}"])
    if not enable_offline:
        return True, "Правила блокировки сняты (Online)."

    rc_out, out_msg = _run_netsh(
        [
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={FW_RULE_NAME}",
            "dir=out",
            "action=block",
            "profile=any",
            "enable=yes",
        ]
    )
    rc_in, in_msg = _run_netsh(
        [
            "advfirewall",
            "firewall",
            "add",
            "rule",
            f"name={FW_RULE_NAME}",
            "dir=in",
            "action=block",
            "profile=any",
            "enable=yes",
        ]
    )
    if rc_out == 0 and rc_in == 0:
        return True, "Трафик заблокирован (Offline)."
    return False, f"Ошибка брандмауэра (нужны права Администратора): {out_msg or in_msg}"


def get_process_name(pid: int) -> str:
    if pid == 0:
        return "System Idle Process"
    if pid == 4:
        return "System"
    PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
    h_proc = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h_proc:
        return f"PID {pid}"
    try:
        buf = ctypes.create_unicode_buffer(512)
        size = wintypes.DWORD(512)
        if ctypes.windll.kernel32.QueryFullProcessImageNameW(h_proc, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return f"PID {pid}"
    finally:
        ctypes.windll.kernel32.CloseHandle(h_proc)


def get_total_adapter_bytes() -> Tuple[int, int]:
    """Считывает суммарный входящий/исходящий трафик по всем активным сетевым адаптерам (GetIfTable2)."""
    try:
        class MIB_IF_ROW2(ctypes.Structure):
            _fields_ = [
                ("InterfaceLuid", ctypes.c_uint64),
                ("InterfaceIndex", wintypes.ULONG),
                ("InterfaceGuid", ctypes.c_byte * 16),
                ("Alias", wintypes.WCHAR * 257),
                ("Description", wintypes.WCHAR * 257),
                ("PhysicalAddressLength", wintypes.ULONG),
                ("PhysicalAddress", ctypes.c_byte * 32),
                ("PermanentPhysicalAddress", ctypes.c_byte * 32),
                ("Mtu", wintypes.ULONG),
                ("Type", wintypes.ULONG),
                ("TunnelType", ctypes.c_int),
                ("MediaType", ctypes.c_int),
                ("PhysicalMediumType", ctypes.c_int),
                ("AccessType", ctypes.c_int),
                ("DirectionType", ctypes.c_int),
                ("InterfaceAndOperStatusFlags", ctypes.c_byte),
                ("OperStatus", ctypes.c_int),
                ("AdminStatus", ctypes.c_int),
                ("MediaConnectState", ctypes.c_int),
                ("NetworkGuid", ctypes.c_byte * 16),
                ("ConnectionType", ctypes.c_int),
                ("TransmitLinkSpeed", ctypes.c_uint64),
                ("ReceiveLinkSpeed", ctypes.c_uint64),
                ("InOctets", ctypes.c_uint64),
                ("InUcastPkts", ctypes.c_uint64),
                ("InNUcastPkts", ctypes.c_uint64),
                ("InDiscards", ctypes.c_uint64),
                ("InErrors", ctypes.c_uint64),
                ("InUnknownProtos", ctypes.c_uint64),
                ("InUcastOctets", ctypes.c_uint64),
                ("InMulticastOctets", ctypes.c_uint64),
                ("InBroadcastOctets", ctypes.c_uint64),
                ("OutOctets", ctypes.c_uint64),
                ("OutUcastPkts", ctypes.c_uint64),
                ("OutNUcastPkts", ctypes.c_uint64),
                ("OutDiscards", ctypes.c_uint64),
                ("OutErrors", ctypes.c_uint64),
                ("OutUcastOctets", ctypes.c_uint64),
                ("OutMulticastOctets", ctypes.c_uint64),
                ("OutBroadcastOctets", ctypes.c_uint64),
                ("OutQLen", ctypes.c_uint64),
            ]

        class MIB_IF_TABLE2(ctypes.Structure):
            _fields_ = [
                ("NumEntries", wintypes.ULONG),
                ("Table", MIB_IF_ROW2 * 1),
            ]

        table_ptr = ctypes.POINTER(MIB_IF_TABLE2)()
        res = ctypes.windll.iphlpapi.GetIfTable2(ctypes.byref(table_ptr))
        if res != 0 or not table_ptr:
            return 0, 0

        try:
            count = table_ptr.contents.NumEntries
            base_addr = ctypes.addressof(table_ptr.contents.Table)
            row_size = ctypes.sizeof(MIB_IF_ROW2)
            in_total = 0
            out_total = 0
            for i in range(count):
                row = MIB_IF_ROW2.from_address(base_addr + i * row_size)
                if row.Type != 24 and row.OperStatus == 1:
                    in_total += row.InOctets
                    out_total += row.OutOctets
            return in_total, out_total
        finally:
            ctypes.windll.iphlpapi.FreeMibTable(table_ptr)
    except Exception:
        return 0, 0


def get_active_tcp_connections() -> List[Tuple[str, int, str, int, int]]:
    AF_INET = 2
    TCP_TABLE_OWNER_PID_ALL = 5

    class MIB_TCPROW_OWNER_PID(ctypes.Structure):
        _fields_ = [
            ("dwState", wintypes.DWORD),
            ("dwLocalAddr", wintypes.DWORD),
            ("dwLocalPort", wintypes.DWORD),
            ("dwRemoteAddr", wintypes.DWORD),
            ("dwRemotePort", wintypes.DWORD),
            ("dwOwningPid", wintypes.DWORD),
        ]

    size = wintypes.DWORD(0)
    ctypes.windll.iphlpapi.GetExtendedTcpTable(None, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0)
    if size.value == 0:
        return []

    buf = ctypes.create_string_buffer(size.value)
    res = ctypes.windll.iphlpapi.GetExtendedTcpTable(
        buf, ctypes.byref(size), False, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0
    )
    if res != 0:
        return []

    num_entries = struct.unpack_from("<I", buf.raw, 0)[0]
    row_size = ctypes.sizeof(MIB_TCPROW_OWNER_PID)
    result = []
    for i in range(num_entries):
        offset = 4 + i * row_size
        if offset + row_size > len(buf.raw):
            break
        state, l_addr, l_port, r_addr, r_port, pid = struct.unpack_from("<IIIIII", buf.raw, offset)
        if state in (3, 4, 5, 8):
            lip = socket.inet_ntoa(struct.pack("<I", l_addr))
            rip = socket.inet_ntoa(struct.pack("<I", r_addr))
            lp = socket.ntohs(l_port & 0xFFFF)
            rp = socket.ntohs(r_port & 0xFFFF)
            result.append((lip, lp, rip, rp, pid))
    return result


@dataclass
class ProcTraffic:
    name: str
    rx_bytes: int = 0
    tx_bytes: int = 0
    via_proxy: bool = False

    @property
    def total_bytes(self) -> int:
        return self.rx_bytes + self.tx_bytes


class EtwKernelNetworkCollector:
    """
    Сборщик реального по-процессного трафика через Windows Kernel Trace (ETW NetworkTcpIp / UdpIp)
    в реальном времени исключительно в оперативной памяти (без создания файлов логов на диске).
    """

    KERNEL_LOGGER_NAME = "NT Kernel Logger"
    TCP_GUID = uuid.UUID("{9a280ac0-c8e0-11d1-84e2-00c04fb998a2}")
    UDP_GUID = uuid.UUID("{bf3a50c5-a9c9-4988-a005-2df0b7c80f80}")

    def __init__(self, proxy_ip: str, proxy_port: int):
        self.proxy_ip = proxy_ip
        self.proxy_port = proxy_port
        self.running = False
        self.error_msg: Optional[str] = None
        self.lock = threading.Lock()
        self.stats: Dict[str, ProcTraffic] = {}
        self.pid_cache: Dict[int, str] = {}
        self._thread: Optional[threading.Thread] = None
        self._trace_handle = ctypes.c_uint64(0)
        self._session_handle = ctypes.c_uint64(0)
        self._cb_ref = None

    def _get_name(self, pid: int) -> str:
        if pid not in self.pid_cache:
            self.pid_cache[pid] = get_process_name(pid)
        return self.pid_cache[pid]

    def _add_traffic(self, pid: int, rx: int, tx: int, is_proxy: bool) -> None:
        if pid <= 0 or (rx == 0 and tx == 0):
            return
        name = self._get_name(pid)
        with self.lock:
            entry = self.stats.get(name)
            if entry is None:
                entry = ProcTraffic(name=name)
                self.stats[name] = entry
            entry.rx_bytes += rx
            entry.tx_bytes += tx
            if is_proxy:
                entry.via_proxy = True

    def start(self) -> bool:
        cleanup_etw_log_files()
        self.running = True
        self.error_msg = None
        self._thread = threading.Thread(target=self._run_etw_session, daemon=True)
        self._thread.start()
        time.sleep(0.25)
        return self.error_msg is None

    def stop(self) -> None:
        self.running = False
        try:
            self._stop_kernel_logger()
        except Exception:
            pass
        if self._trace_handle.value:
            try:
                ctypes.windll.advapi32.CloseTrace(self._trace_handle)
            except Exception:
                pass
            self._trace_handle = ctypes.c_uint64(0)
        cleanup_etw_log_files()

    def _build_properties_buffer(self):
        EVENT_TRACE_REAL_TIME_MODE = 0x00000100
        EVENT_TRACE_SYSTEM_LOGGER_MODE = 0x02000000
        EVENT_TRACE_FLAG_NETWORK_TCPIP = 0x00010000
        WNODE_FLAG_TRACED_GUID = 0x00020000

        name_bytes = (self.KERNEL_LOGGER_NAME + chr(0)).encode("utf-16le")
        props_size = 120 + len(name_bytes) + 64
        buf = ctypes.create_string_buffer(props_size)

        struct.pack_into("<I", buf, 0, props_size)
        sys_guid = uuid.UUID("{9e814aad-3204-11d2-9a82-006008a86939}").bytes_le
        buf[24:40] = sys_guid
        struct.pack_into("<I", buf, 40, 1)
        struct.pack_into("<I", buf, 44, WNODE_FLAG_TRACED_GUID)
        struct.pack_into("<I", buf, 48, 64)
        struct.pack_into("<I", buf, 64, EVENT_TRACE_REAL_TIME_MODE | EVENT_TRACE_SYSTEM_LOGGER_MODE)
        struct.pack_into("<I", buf, 72, EVENT_TRACE_FLAG_NETWORK_TCPIP)
        struct.pack_into("<I", buf, 112, 0)
        struct.pack_into("<I", buf, 116, 120)

        buf[120 : 120 + len(name_bytes)] = name_bytes
        return buf, props_size

    def _stop_kernel_logger(self) -> None:
        buf, _ = self._build_properties_buffer()
        CONTROL_TRACE_STOP = 1
        ctypes.windll.advapi32.ControlTraceW(
            ctypes.c_uint64(0),
            ctypes.c_wchar_p(self.KERNEL_LOGGER_NAME),
            buf,
            CONTROL_TRACE_STOP,
        )

    def _run_etw_session(self) -> None:
        try:
            self._stop_kernel_logger()
            cleanup_etw_log_files()

            buf, _ = self._build_properties_buffer()
            session_handle = ctypes.c_uint64(0)
            status = ctypes.windll.advapi32.StartTraceW(
                ctypes.byref(session_handle),
                ctypes.c_wchar_p(self.KERNEL_LOGGER_NAME),
                buf,
            )
            if status != 0:
                if status == 5:
                    self.error_msg = "ERROR_ACCESS_DENIED (нужны права Администратора для ETW)"
                else:
                    self.error_msg = f"StartTraceW code={status}"
                self.running = False
                return

            self._session_handle = session_handle

            class GUID(ctypes.Structure):
                _fields_ = [
                    ("Data1", wintypes.DWORD),
                    ("Data2", wintypes.WORD),
                    ("Data3", wintypes.WORD),
                    ("Data4", ctypes.c_byte * 8),
                ]

            class EVENT_HEADER(ctypes.Structure):
                _fields_ = [
                    ("Size", wintypes.USHORT),
                    ("HeaderType", wintypes.USHORT),
                    ("Flags", wintypes.USHORT),
                    ("EventProperty", wintypes.USHORT),
                    ("ThreadId", wintypes.ULONG),
                    ("ProcessId", wintypes.ULONG),
                    ("TimeStamp", ctypes.c_int64),
                    ("ProviderId", GUID),
                    ("EventDescriptor_Id", wintypes.USHORT),
                    ("EventDescriptor_Version", ctypes.c_ubyte),
                    ("EventDescriptor_Channel", ctypes.c_ubyte),
                    ("EventDescriptor_Level", ctypes.c_ubyte),
                    ("EventDescriptor_Opcode", ctypes.c_ubyte),
                    ("EventDescriptor_Task", wintypes.USHORT),
                    ("EventDescriptor_Keyword", ctypes.c_uint64),
                    ("KernelTime", wintypes.ULONG),
                    ("UserTime", wintypes.ULONG),
                    ("ActivityId", GUID),
                ]

            class ETW_BUFFER_CONTEXT(ctypes.Structure):
                _fields_ = [
                    ("ProcessorNumber", ctypes.c_ubyte),
                    ("Alignment", ctypes.c_ubyte),
                    ("LoggerId", wintypes.USHORT),
                ]

            class EVENT_RECORD(ctypes.Structure):
                _fields_ = [
                    ("EventHeader", EVENT_HEADER),
                    ("BufferContext", ETW_BUFFER_CONTEXT),
                    ("ExtendedDataCount", wintypes.USHORT),
                    ("UserDataLength", wintypes.USHORT),
                    ("ExtendedData", ctypes.c_void_p),
                    ("UserData", ctypes.c_void_p),
                    ("UserContext", ctypes.c_void_p),
                ]

            EVENT_RECORD_CALLBACK = ctypes.WINFUNCTYPE(None, ctypes.POINTER(EVENT_RECORD))

            tcp_bytes_le = self.TCP_GUID.bytes_le
            udp_bytes_le = self.UDP_GUID.bytes_le
            proxy_ip_packed = None
            try:
                if self.proxy_ip:
                    proxy_ip_packed = struct.unpack("<I", socket.inet_aton(self.proxy_ip))[0]
            except Exception:
                proxy_ip_packed = None

            def on_event(rec_ptr):
                if not self.running or not rec_ptr:
                    return
                rec = rec_ptr.contents
                hdr = rec.EventHeader
                opcode = hdr.EventDescriptor_Opcode
                if opcode not in (10, 11, 26, 27):
                    return

                prov_raw = bytes(hdr.ProviderId)
                if prov_raw != tcp_bytes_le and prov_raw != udp_bytes_le:
                    return

                ulen = rec.UserDataLength
                if not rec.UserData or ulen < 16:
                    return

                raw = ctypes.string_at(rec.UserData, ulen)
                if opcode in (10, 11) and ulen >= 20:
                    pid, pkt_size, daddr, saddr, dport, sport = struct.unpack_from("<IIIIHH", raw, 0)
                    dport = socket.ntohs(dport)
                    sport = socket.ntohs(sport)

                    is_proxy = False
                    if proxy_ip_packed is not None:
                        if self.proxy_port > 0:
                            if (daddr == proxy_ip_packed and dport == self.proxy_port) or (
                                saddr == proxy_ip_packed and sport == self.proxy_port
                            ):
                                is_proxy = True
                        else:
                            if daddr == proxy_ip_packed or saddr == proxy_ip_packed:
                                is_proxy = True

                    if not is_proxy and (daddr == 0x0100007F and saddr == 0x0100007F):
                        return

                    if opcode == 10:
                        self._add_traffic(pid, 0, pkt_size, is_proxy)
                    else:
                        self._add_traffic(pid, pkt_size, 0, is_proxy)

                elif opcode in (26, 27) and ulen >= 40:
                    pid, pkt_size = struct.unpack_from("<II", raw, 0)
                    if opcode == 26:
                        self._add_traffic(pid, 0, pkt_size, False)
                    else:
                        self._add_traffic(pid, pkt_size, 0, False)

            self._cb_ref = EVENT_RECORD_CALLBACK(on_event)

            PROCESS_TRACE_MODE_REAL_TIME = 0x00000100
            PROCESS_TRACE_MODE_EVENT_RECORD = 0x10000000

            logfile_buf = ctypes.create_string_buffer(512)
            logger_name_ptr = ctypes.c_wchar_p(self.KERNEL_LOGGER_NAME)
            cb_addr = ctypes.cast(self._cb_ref, ctypes.c_void_p).value

            struct.pack_into("<Q", logfile_buf, 8, ctypes.cast(logger_name_ptr, ctypes.c_void_p).value)
            struct.pack_into("<I", logfile_buf, 28, PROCESS_TRACE_MODE_REAL_TIME | PROCESS_TRACE_MODE_EVENT_RECORD)
            struct.pack_into("<Q", logfile_buf, 376, cb_addr)

            advapi = ctypes.windll.advapi32
            advapi.OpenTraceW.restype = ctypes.c_uint64
            advapi.OpenTraceW.argtypes = [ctypes.c_void_p]

            h_trace = advapi.OpenTraceW(logfile_buf)
            INVALID_PROCESSTRACE_HANDLE = 0xFFFFFFFFFFFFFFFF
            if h_trace == INVALID_PROCESSTRACE_HANDLE or h_trace == 0:
                self.error_msg = f"OpenTraceW failed: {ctypes.GetLastError()}"
                self.running = False
                return

            self._trace_handle = ctypes.c_uint64(h_trace)

            arr = (ctypes.c_uint64 * 1)(h_trace)
            advapi.ProcessTrace.argtypes = [
                ctypes.POINTER(ctypes.c_uint64),
                wintypes.ULONG,
                ctypes.c_void_p,
                ctypes.c_void_p,
            ]
            advapi.ProcessTrace(arr, 1, None, None)

        except Exception as exc:
            self.error_msg = str(exc)
        finally:
            self.running = False
            self._stop_kernel_logger()
            cleanup_etw_log_files()


class TrafficMonitorApp:
    def __init__(self, root: tk.Tk):
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("360x190")
        self.root.minsize(360, 190)

        self.proxy_var = tk.StringVar(value="192.168.43.1:10809")
        self.interval_var = tk.StringVar(value="0.2")
        self.status_var = tk.StringVar(value="Готов к запуску.")

        self.is_monitoring = False
        self.is_offline = False
        self.always_on_top = False

        self.collector: Optional[EtwKernelNetworkCollector] = None
        self.start_time: float = 0.0
        self.base_adapter_in: int = 0
        self.base_adapter_out: int = 0
        self.last_adapter_in: int = 0
        self.last_adapter_out: int = 0
        self.last_tick_time: float = 0.0

        self._build_ui()
        self._setup_global_hotkeys()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=8)
        outer.pack(fill="both", expand=True)

        header_row = ttk.Frame(outer)
        header_row.pack(fill="x", pady=(0, 4))

        ttk.Label(header_row, text=APP_TITLE, style="Title.TLabel").pack(side="left")

        self.top_btn = ttk.Button(
            header_row,
            text="Always top",
            style="TopOff.TButton",
            command=self._toggle_always_top,
        )
        self.top_btn.pack(side="right")

        tk.Frame(outer, height=1, bg=PALETTE["border"]).pack(fill="x", pady=(0, 5))

        ctrl_row = ttk.Frame(outer)
        ctrl_row.pack(fill="x", pady=(0, 5))

        ttk.Label(ctrl_row, text="Proxy:").pack(side="left", padx=(0, 4))
        self.proxy_entry = ttk.Entry(ctrl_row, textvariable=self.proxy_var, width=18)
        self.proxy_entry.pack(side="left", padx=(0, 6))
        self.register_text_widget(self.proxy_entry)

        self.toggle_btn = ttk.Button(
            ctrl_row,
            text="Start",
            style="BlueAction.TButton",
            command=self._toggle_monitoring,
            width=8,
        )
        self.toggle_btn.pack(side="left", padx=(0, 6))

        self.reset_btn = ttk.Button(
            ctrl_row,
            text="Сброс",
            command=self._reset_counters,
            width=6,
        )
        self.reset_btn.pack(side="right")

        mode_row = ttk.Frame(outer)
        mode_row.pack(fill="x", pady=(0, 5))

        ttk.Label(mode_row, text="Обновление (с):").pack(side="left", padx=(0, 4))
        self.interval_combo = ttk.Combobox(
            mode_row,
            textvariable=self.interval_var,
            values=["0.1", "0.2", "0.5", "1", "5"],
            state="readonly",
            width=4,
        )
        self.interval_combo.pack(side="left", padx=(0, 6))

        if not is_user_admin():
            ttk.Button(
                mode_row,
                text="Админ",
                command=self._restart_admin,
                width=6,
            ).pack(side="left", padx=(0, 4))

        self.offline_btn = ttk.Button(
            mode_row,
            text="Offline",
            style="OfflineState.TButton",
            command=self._set_offline_mode,
            width=7,
        )
        self.offline_btn.pack(side="right", padx=(4, 0))

        self.online_btn = ttk.Button(
            mode_row,
            text="Online",
            style="OnlineState.TButton",
            command=self._set_online_mode,
            width=7,
        )
        self.online_btn.pack(side="right")

        self._apply_network_buttons_visual()

        output_frame = tk.Frame(
            outer,
            bg=PALETTE["bg_input"],
            highlightthickness=1,
            highlightbackground=PALETTE["border"],
        )
        output_frame.pack(fill="both", expand=True, pady=(0, 4))

        self.output_text = tk.Text(
            output_frame,
            bg=PALETTE["bg_input"],
            fg=PALETTE["text_primary"],
            insertbackground=PALETTE["accent_blue"],
            selectbackground=PALETTE["select_bg"],
            selectforeground="#ffffff",
            font=("Consolas", 8),
            relief="flat",
            padx=6,
            pady=4,
            wrap="none",
            state="normal",
        )
        self.output_text.pack(fill="both", expand=True)
        self.register_text_widget(self.output_text)

        self.output_text.tag_configure("header", foreground=PALETTE["accent_blue"], font=("Consolas", 8, "bold"))
        self.output_text.tag_configure("header_offline", foreground=PALETTE["accent_red"], font=("Consolas", 8, "bold"))
        self.output_text.tag_configure("proxy", foreground="#4da6ff")
        self.output_text.tag_configure("muted", foreground=PALETTE["text_muted"])
        self.output_text.tag_configure("warn", foreground="#e5a93b")

        self._render_idle_screen()

        ttk.Label(outer, textvariable=self.status_var, style="Muted.TLabel").pack(anchor="w")

    def _toggle_always_top(self) -> None:
        self.always_on_top = not self.always_on_top
        self.root.attributes("-topmost", self.always_on_top)
        self.top_btn.configure(style="TopOn.TButton" if self.always_on_top else "TopOff.TButton")

    def _apply_network_buttons_visual(self) -> None:
        if not self.is_offline:
            self.online_btn.configure(state="disabled")
            self.offline_btn.configure(state="normal")
        else:
            self.offline_btn.configure(state="disabled")
            self.online_btn.configure(state="normal")

    def _set_offline_mode(self) -> None:
        if self.is_offline:
            return
        ok, msg = set_firewall_offline(True)
        if not ok:
            messagebox.showerror("Offline режим", msg)
            self.status_var.set("Ошибка включения Offline (нужны права Администратора).")
            return
        self.is_offline = True
        self._apply_network_buttons_visual()
        self.status_var.set("Режим OFFLINE: весь трафик заблокирован.")
        if self.is_monitoring:
            self._render_report()

    def _set_online_mode(self) -> None:
        if not self.is_offline:
            return
        ok, msg = set_firewall_offline(False)
        if not ok:
            messagebox.showerror("Online режим", msg)
            return
        self.is_offline = False
        self._apply_network_buttons_visual()
        self.status_var.set("Режим ONLINE: доступ в сеть восстановлен.")
        if self.is_monitoring:
            self._render_report()

    def _restart_admin(self) -> None:
        if relaunch_as_admin():
            self.root.destroy()

    def _render_idle_screen(self) -> None:
        admin_note = (
            "Права Администратора: АКТИВНЫ (полный ETW-захват)."
            if is_user_admin()
            else "ВНИМАНИЕ: Запуск БЕЗ прав Админа. Нажмите «Админ»."
        )
        self.output_text.delete("1.0", "end")
        self.output_text.insert("end", "Ожидание запуска мониторинга...\n\n", "header")
        self.output_text.insert("end", f"{admin_note}\n", "muted" if is_user_admin() else "warn")
        self.output_text.insert("end", "Нажмите Start для запуска.\n", "muted")

    def register_text_widget(self, widget: tk.Widget) -> None:
        menu = tk.Menu(
            widget,
            tearoff=0,
            bg=PALETTE["bg_button"],
            fg=PALETTE["text_primary"],
            activebackground=PALETTE["accent_blue"],
            activeforeground="#ffffff",
            borderwidth=1,
        )
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            menu.add_command(label="Вырезать", command=lambda w=widget: w.event_generate("<<Cut>>"))
            menu.add_command(label="Копировать", command=lambda w=widget: w.event_generate("<<Copy>>"))
            menu.add_command(label="Вставить", command=lambda w=widget: w.event_generate("<<Paste>>"))
            menu.add_separator()
            menu.add_command(label="Выделить всё", command=lambda w=widget: self._select_all(w))
        else:
            menu.add_command(label="Копировать", command=lambda w=widget: w.event_generate("<<Copy>>"))
            menu.add_separator()
            menu.add_command(label="Выделить всё", command=lambda w=widget: self._select_all(w))

        widget.bind("<Button-3>", lambda e, m=menu, w=widget: self._show_context_menu(e, m, w))

    @staticmethod
    def _show_context_menu(event: tk.Event, menu: tk.Menu, widget: tk.Widget) -> None:
        widget.focus_set()
        try:
            menu.tk_popup(event.x_root, event.y_root)
        finally:
            menu.grab_release()

    @staticmethod
    def _select_all(widget: tk.Widget) -> None:
        widget.focus_set()
        if isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.select_range(0, "end")
            widget.icursor("end")
        elif isinstance(widget, tk.Text):
            widget.tag_add("sel", "1.0", "end")

    def _setup_global_hotkeys(self) -> None:
        self.root.bind_all("<Control-KeyPress>", self._on_ctrl_keypress, add="+")

    def _on_ctrl_keypress(self, event: tk.Event):
        if event.state & 0x20000 or event.state & 0x0008:
            return None

        widget = self.root.focus_get()
        if not isinstance(widget, (tk.Entry, ttk.Entry, tk.Text)):
            return None

        vk = event.keycode
        keysym = (event.keysym or "").lower()
        is_a = vk == 65 or keysym in ("a", "cyrillic_ef")
        is_c = vk == 67 or keysym in ("c", "cyrillic_es")
        is_v = vk == 86 or keysym in ("v", "cyrillic_em")
        is_x = vk == 88 or keysym in ("x", "cyrillic_che")

        if is_a:
            self._select_all(widget)
            return "break"
        if is_c:
            widget.event_generate("<<Copy>>")
            return "break"
        if is_v and isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.event_generate("<<Paste>>")
            return "break"
        if is_x and isinstance(widget, (tk.Entry, ttk.Entry)):
            widget.event_generate("<<Cut>>")
            return "break"
        return None

    def _parse_proxy(self) -> Tuple[str, int]:
        raw = self.proxy_var.get().strip()
        if not raw:
            return "", 0
        if ":" in raw:
            host, port_str = raw.rsplit(":", 1)
            try:
                return host.strip(), int(port_str.strip())
            except ValueError:
                return host.strip(), 0
        return raw, 0

    def _get_interval_ms(self) -> int:
        try:
            sec = float(self.interval_var.get().replace(",", "."))
            return max(50, int(round(sec * 1000)))
        except Exception:
            return 200

    def _toggle_monitoring(self) -> None:
        if not self.is_monitoring:
            self._start_monitoring()
        else:
            self._stop_monitoring()

    def _start_monitoring(self) -> None:
        proxy_ip, proxy_port = self._parse_proxy()
        self.collector = EtwKernelNetworkCollector(proxy_ip, proxy_port)
        etw_ok = self.collector.start()

        now = time.time()
        self.start_time = now
        self.last_tick_time = now
        in_b, out_b = get_total_adapter_bytes()
        self.base_adapter_in = in_b
        self.base_adapter_out = out_b
        self.last_adapter_in = in_b
        self.last_adapter_out = out_b

        self.is_monitoring = True
        self.proxy_entry.configure(state="disabled")
        self.toggle_btn.configure(text="Stop", style="BlueAction.TButton")

        if etw_ok:
            self.status_var.set("Мониторинг активен (ETW Kernel Trace).")
        else:
            self.status_var.set(f"Режим адаптера ({self.collector.error_msg}).")

        self._update_loop()

    def _stop_monitoring(self) -> None:
        self.is_monitoring = False
        if self.collector:
            self.collector.stop()
        self.proxy_entry.configure(state="normal")
        self.toggle_btn.configure(text="Start", style="BlueAction.TButton")
        self.status_var.set("Мониторинг остановлен.")

    def _reset_counters(self) -> None:
        in_b, out_b = get_total_adapter_bytes()
        now = time.time()
        self.base_adapter_in = in_b
        self.base_adapter_out = out_b
        self.last_adapter_in = in_b
        self.last_adapter_out = out_b
        self.start_time = now
        self.last_tick_time = now
        if self.collector:
            with self.collector.lock:
                self.collector.stats.clear()
        if self.is_monitoring:
            self._render_report()
        else:
            self._render_idle_screen()
        self.status_var.set("Счётчики трафика сброшены.")

    def _update_loop(self) -> None:
        if not self.is_monitoring:
            return
        self._render_report()
        self.root.after(self._get_interval_ms(), self._update_loop)

    def _render_report(self) -> None:
        now = time.time()
        dt = max(0.05, now - self.last_tick_time)
        self.last_tick_time = now

        cur_in, cur_out = get_total_adapter_bytes()
        total_rx = max(0, cur_in - self.base_adapter_in)
        total_tx = max(0, cur_out - self.base_adapter_out)

        speed_rx = int(max(0, cur_in - self.last_adapter_in) / dt)
        speed_tx = int(max(0, cur_out - self.last_adapter_out) / dt)
        self.last_adapter_in = cur_in
        self.last_adapter_out = cur_out

        elapsed = int(now - self.start_time)
        mins, secs = divmod(elapsed, 60)
        hrs, mins = divmod(mins, 60)

        proxy_str = self.proxy_var.get().strip() or "Нет"
        mode_tag = "OFFLINE" if self.is_offline else "ONLINE"
        header_style_tag = "header_offline" if self.is_offline else "header"

        yview = self.output_text.yview()
        self.output_text.delete("1.0", "end")

        self.output_text.insert(
            "end",
            f"АДАПТЕР [{mode_tag}] ({hrs:02d}:{mins:02d}:{secs:02d} | Proxy: {proxy_str})\n",
            header_style_tag,
        )
        self.output_text.insert(
            "end",
            f"↓ {format_size(total_rx)} | ↑ {format_size(total_tx)} | Σ {format_size(total_rx + total_tx)}\n",
        )
        self.output_text.insert(
            "end",
            f"Скор.: ↓ {format_size(speed_rx)}/с  ↑ {format_size(speed_tx)}/с\n\n",
            "muted",
        )

        if self.collector and self.collector.error_msg:
            self.output_text.insert(
                "end",
                f"[!] ETW недоступен: {self.collector.error_msg}\n\n",
                "warn",
            )
            conns = get_active_tcp_connections()
            active_procs: Dict[str, int] = {}
            proxy_ip, proxy_port = self._parse_proxy()
            for _lip, _lp, rip, rp, pid in conns:
                pname = get_process_name(pid)
                tag_p = " [Proxy]" if (proxy_ip and rip == proxy_ip and (proxy_port == 0 or rp == proxy_port)) else ""
                key = f"{pname}{tag_p}"
                active_procs[key] = active_procs.get(key, 0) + 1

            for k, cnt in sorted(active_procs.items(), key=lambda x: x[1], reverse=True):
                tag = "proxy" if "[Proxy]" in k else ""
                self.output_text.insert("end", f"• {k:<28} ({cnt})\n", tag)
            self.output_text.yview_moveto(yview[0])
            return

        rows: List[ProcTraffic] = []
        if self.collector:
            with self.collector.lock:
                rows = [
                    ProcTraffic(
                        name=v.name,
                        rx_bytes=v.rx_bytes,
                        tx_bytes=v.tx_bytes,
                        via_proxy=v.via_proxy,
                    )
                    for v in self.collector.stats.values()
                ]

        rows.sort(key=lambda item: item.total_bytes, reverse=True)

        for item in rows:
            label = f"{item.name} [P]" if item.via_proxy else item.name
            if len(label) > 21:
                label = label[:18] + "..."
            line = (
                f"{label:<22} "
                f"{format_size(item.rx_bytes):>9} "
                f"{format_size(item.tx_bytes):>9} "
                f"{format_size(item.total_bytes):>9}\n"
            )
            self.output_text.insert("end", line, "proxy" if item.via_proxy else "")

        self.output_text.yview_moveto(yview[0])

    def _on_close(self) -> None:
        if self.is_offline:
            messagebox.showwarning(
                "Режим Offline активен",
                "Внимание: сейчас включён режим Offline (сеть заблокирована).\n"
                "При закрытии программы блокировка будет автоматически снята и доступ в интернет восстановится.",
            )
            set_firewall_offline(False)
            self.is_offline = False

        self._stop_monitoring()
        cleanup_etw_log_files()
        self.root.destroy()


def main() -> None:
    hide_console_window()
    cleanup_etw_log_files()
    root = tk.Tk()
    apply_dark_theme(root)
    enable_windows_dark_titlebar(root)
    TrafficMonitorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()
