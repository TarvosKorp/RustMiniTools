#![cfg_attr(not(debug_assertions), windows_subsystem = "windows")]

use eframe::egui;
use std::{
    collections::HashMap,
    ffi::c_void,
    mem,
    net::Ipv4Addr,
    process::Command,
    sync::{
        atomic::{AtomicBool, AtomicU64, Ordering},
        Mutex, OnceLock,
    },
    thread,
    time::{Duration, Instant},
};

const APP_TITLE: &str = "Network Traffic Monitor";
const FW_RULE_NAME: &str = "TrafficMonitor_Offline_Block_All";

const BG_MAIN: egui::Color32 = egui::Color32::from_rgb(0x1b, 0x1b, 0x1b);
const BG_INPUT: egui::Color32 = egui::Color32::from_rgb(0x0f, 0x0f, 0x0f);
const BG_BUTTON: egui::Color32 = egui::Color32::from_rgb(0x36, 0x36, 0x36);
const BORDER: egui::Color32 = egui::Color32::from_rgb(0x38, 0x38, 0x38);
const BLUE: egui::Color32 = egui::Color32::from_rgb(0x00, 0x88, 0xff);
const GREEN: egui::Color32 = egui::Color32::from_rgb(0x2e, 0xa0, 0x43);
const RED: egui::Color32 = egui::Color32::from_rgb(0xd7, 0x3a, 0x49);
const TEXT: egui::Color32 = egui::Color32::from_rgb(0xd4, 0xd4, 0xd4);
const MUTED: egui::Color32 = egui::Color32::from_rgb(0x88, 0x88, 0x88);
const PROXY: egui::Color32 = egui::Color32::from_rgb(0x4d, 0xa6, 0xff);
const WARN: egui::Color32 = egui::Color32::from_rgb(0xe5, 0xa9, 0x3b);

#[derive(Clone, Default)]
struct ProcTraffic {
    name: String,
    rx_bytes: u64,
    tx_bytes: u64,
    via_proxy: bool,
}
impl ProcTraffic {
    fn total(&self) -> u64 { self.rx_bytes.saturating_add(self.tx_bytes) }
}

#[derive(Default)]
struct EtwState {
    proxy_ip: Option<u32>,
    proxy_port: u16,
    stats: HashMap<String, ProcTraffic>,
    pid_cache: HashMap<u32, String>,
}

static ETW_STATE: OnceLock<Mutex<EtwState>> = OnceLock::new();
static ETW_ERROR: OnceLock<Mutex<Option<String>>> = OnceLock::new();
static ETW_RUNNING: AtomicBool = AtomicBool::new(false);
static ETW_TRACE: AtomicU64 = AtomicU64::new(0);

fn etw_state() -> &'static Mutex<EtwState> {
    ETW_STATE.get_or_init(|| Mutex::new(EtwState::default()))
}
fn etw_error() -> &'static Mutex<Option<String>> {
    ETW_ERROR.get_or_init(|| Mutex::new(None))
}

#[cfg(windows)]
mod win {
    use super::*;
    use std::{ffi::OsStr, os::windows::ffi::OsStrExt, ptr};

    type Handle = *mut c_void;

    #[repr(C)]
    #[derive(Clone, Copy)]
    struct Guid {
        data1: u32, data2: u16, data3: u16, data4: [u8; 8],
    }
    #[repr(C)]
    struct EventHeader {
        size: u16, header_type: u16, flags: u16, event_property: u16,
        thread_id: u32, process_id: u32, timestamp: i64, provider_id: Guid,
        id: u16, version: u8, channel: u8, level: u8, opcode: u8,
        task: u16, keyword: u64, kernel_time: u32, user_time: u32, activity_id: Guid,
    }
    #[repr(C)]
    struct BufferContext { processor_number: u8, alignment: u8, logger_id: u16 }
    #[repr(C)]
    struct EventRecord {
        header: EventHeader, buffer_context: BufferContext,
        extended_data_count: u16, user_data_length: u16,
        extended_data: *mut c_void, user_data: *mut c_void, user_context: *mut c_void,
    }
    type EventCallback = Option<unsafe extern "system" fn(*mut EventRecord)>;

    #[link(name = "advapi32")]
    unsafe extern "system" {
        fn StartTraceW(handle: *mut u64, name: *const u16, properties: *mut c_void) -> u32;
        fn ControlTraceW(handle: u64, name: *const u16, properties: *mut c_void, control: u32) -> u32;
        fn OpenTraceW(logfile: *mut c_void) -> u64;
        fn ProcessTrace(handles: *const u64, count: u32, start: *const i64, end: *const i64) -> u32;
        fn CloseTrace(handle: u64) -> u32;
    }
    #[link(name = "iphlpapi")]
    unsafe extern "system" {
        fn GetIfTable2(table: *mut *mut MibIfTable2) -> u32;
        fn FreeMibTable(table: *mut c_void);
        fn GetExtendedTcpTable(table: *mut c_void, size: *mut u32, order: i32, family: u32, class: u32, reserved: u32) -> u32;
    }
    #[link(name = "kernel32")]
    unsafe extern "system" {
        fn OpenProcess(access: u32, inherit: i32, pid: u32) -> Handle;
        fn QueryFullProcessImageNameW(process: Handle, flags: u32, name: *mut u16, size: *mut u32) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
        fn GetLastError() -> u32;
    }
    #[link(name = "shell32")]
    unsafe extern "system" {
        fn IsUserAnAdmin() -> i32;
        fn ShellExecuteW(hwnd: Handle, operation: *const u16, file: *const u16, params: *const u16, dir: *const u16, show: i32) -> isize;
    }

    #[repr(C)]
    struct MibIfRow2 {
        luid: u64, index: u32, guid: [u8; 16], alias: [u16; 257], description: [u16; 257],
        physical_len: u32, physical: [u8; 32], permanent_physical: [u8; 32],
        mtu: u32, if_type: u32, tunnel_type: i32, media_type: i32, physical_medium: i32,
        access_type: i32, direction_type: i32, flags: u8, oper_status: i32, admin_status: i32,
        media_connect_state: i32, network_guid: [u8; 16], connection_type: i32,
        transmit_speed: u64, receive_speed: u64,
        in_octets: u64, in_ucast_pkts: u64, in_nucast_pkts: u64, in_discards: u64,
        in_errors: u64, in_unknown: u64, in_ucast_octets: u64, in_multicast_octets: u64,
        in_broadcast_octets: u64, out_octets: u64, out_ucast_pkts: u64, out_nucast_pkts: u64,
        out_discards: u64, out_errors: u64, out_ucast_octets: u64, out_multicast_octets: u64,
        out_broadcast_octets: u64, out_qlen: u64,
    }
    #[repr(C)]
    struct MibIfTable2 { count: u32, first: [MibIfRow2; 1] }

    pub fn is_admin() -> bool { unsafe { IsUserAnAdmin() != 0 } }

    pub fn relaunch_admin() -> bool {
        let exe = match std::env::current_exe() { Ok(p) => p, Err(_) => return false };
        let file: Vec<u16> = exe.as_os_str().encode_wide().chain(Some(0)).collect();
        let verb: Vec<u16> = OsStr::new("runas").encode_wide().chain(Some(0)).collect();
        let empty = [0u16];
        unsafe { ShellExecuteW(ptr::null_mut(), verb.as_ptr(), file.as_ptr(), empty.as_ptr(), ptr::null(), 1) > 32 }
    }

    pub fn adapter_bytes() -> (u64, u64) {
        unsafe {
            let mut table: *mut MibIfTable2 = ptr::null_mut();
            if GetIfTable2(&mut table) != 0 || table.is_null() { return (0, 0); }
            let count = (*table).count as usize;
            let first = ptr::addr_of!((*table).first) as *const MibIfRow2;
            let mut rx = 0u64;
            let mut tx = 0u64;
            for i in 0..count {
                let row = &*first.add(i);
                if row.if_type != 24 && row.oper_status == 1 {
                    rx = rx.saturating_add(row.in_octets);
                    tx = tx.saturating_add(row.out_octets);
                }
            }
            FreeMibTable(table as *mut c_void);
            (rx, tx)
        }
    }

    pub fn process_name(pid: u32) -> String {
        if pid == 0 { return "System Idle Process".into(); }
        if pid == 4 { return "System".into(); }
        unsafe {
            let h = OpenProcess(0x1000, 0, pid);
            if h.is_null() { return format!("PID {pid}"); }
            let mut buf = [0u16; 512];
            let mut len = buf.len() as u32;
            let ok = QueryFullProcessImageNameW(h, 0, buf.as_mut_ptr(), &mut len);
            CloseHandle(h);
            if ok == 0 { return format!("PID {pid}"); }
            String::from_utf16_lossy(&buf[..len as usize])
                .rsplit(['\\', '/']).next().unwrap_or("Unknown").to_string()
        }
    }

    fn wide(s: &str) -> Vec<u16> { OsStr::new(s).encode_wide().chain(Some(0)).collect() }

    pub fn firewall_offline(enable: bool) -> Result<String, String> {
        let _ = run_netsh(&["advfirewall", "firewall", "delete", "rule", &format!("name={FW_RULE_NAME}")]);
        if !enable { return Ok("Правила блокировки сняты (Online).".into()); }
        let name = format!("name={FW_RULE_NAME}");
        let out = run_netsh(&["advfirewall", "firewall", "add", "rule", &name, "dir=out", "action=block", "profile=any", "enable=yes"]);
        let incoming = run_netsh(&["advfirewall", "firewall", "add", "rule", &name, "dir=in", "action=block", "profile=any", "enable=yes"]);
        match (out, incoming) {
            (Ok(_), Ok(_)) => Ok("Трафик заблокирован (Offline).".into()),
            (a, b) => Err(format!("Ошибка брандмауэра (нужны права Администратора): {}; {}", a.err().unwrap_or_default(), b.err().unwrap_or_default())),
        }
    }

    fn run_netsh(args: &[&str]) -> Result<String, String> {
        use std::os::windows::process::CommandExt;
        let output = Command::new("netsh").args(args).creation_flags(0x08000000).output().map_err(|e| e.to_string())?;
        if output.status.success() {
            Ok(String::from_utf8_lossy(&output.stdout).to_string())
        } else {
            Err(format!("{}{}", String::from_utf8_lossy(&output.stdout), String::from_utf8_lossy(&output.stderr)))
        }
    }

    pub fn remove_firewall_rule() { let _ = firewall_offline(false); }

    pub fn active_tcp_connections(proxy_ip: Option<Ipv4Addr>, proxy_port: u16) -> Vec<(String, bool)> {
        const AF_INET: u32 = 2;
        const TCP_TABLE_OWNER_PID_ALL: u32 = 5;
        unsafe {
            let mut size = 0u32;
            let _ = GetExtendedTcpTable(ptr::null_mut(), &mut size, 0, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0);
            if size == 0 { return Vec::new(); }
            let mut data = vec![0u8; size as usize];
            if GetExtendedTcpTable(data.as_mut_ptr() as *mut c_void, &mut size, 0, AF_INET, TCP_TABLE_OWNER_PID_ALL, 0) != 0 { return Vec::new(); }
            if data.len() < 4 { return Vec::new(); }
            let count = u32::from_le_bytes(data[0..4].try_into().unwrap()) as usize;
            let mut map: HashMap<String, (usize, bool)> = HashMap::new();
            for i in 0..count {
                let off = 4 + i * 24;
                if off + 24 > data.len() { break; }
                let state = u32::from_le_bytes(data[off..off+4].try_into().unwrap());
                if ![3, 4, 5, 8].contains(&state) { continue; }
                let remote_addr = u32::from_le_bytes(data[off+12..off+16].try_into().unwrap());
                let remote_port_raw = u32::from_le_bytes(data[off+16..off+20].try_into().unwrap());
                let pid = u32::from_le_bytes(data[off+20..off+24].try_into().unwrap());
                let remote = Ipv4Addr::from(remote_addr.to_le_bytes());
                let port = u16::from_be((remote_port_raw & 0xffff) as u16);
                let is_proxy = proxy_ip.map(|ip| ip == remote && (proxy_port == 0 || proxy_port == port)).unwrap_or(false);
                let name = process_name(pid);
                let entry = map.entry(name).or_insert((0, is_proxy));
                entry.0 += 1;
                entry.1 |= is_proxy;
            }
            let mut rows: Vec<_> = map.into_iter().collect();
            rows.sort_by(|a,b| b.1.0.cmp(&a.1.0));
            rows.into_iter().map(|(name,(count,proxy))| (format!("{name} ({count})"), proxy)).collect()
        }
    }

    #[repr(align(8))]
    struct AlignedLogfile([u8; 512]);

    fn build_properties() -> Vec<u64> {
        let name = wide("NT Kernel Logger");
        let name_bytes = name.len() * 2;
        let size = 120 + name_bytes + 64;
        let mut words = vec![0u64; (size + 7) / 8];
        let b = unsafe { std::slice::from_raw_parts_mut(words.as_mut_ptr() as *mut u8, words.len() * 8) };
        b[0..4].copy_from_slice(&(size as u32).to_le_bytes());
        b[24..40].copy_from_slice(&[0xad,0x4a,0x81,0x9e,0x04,0x32,0xd2,0x11,0x9a,0x82,0x00,0x60,0x08,0xa8,0x69,0x39]);
        b[40..44].copy_from_slice(&1u32.to_le_bytes());
        b[44..48].copy_from_slice(&0x0002_0000u32.to_le_bytes());
        b[48..52].copy_from_slice(&(size as u32).to_le_bytes());
        b[64..68].copy_from_slice(&0x0200_0100u32.to_le_bytes());
        b[72..76].copy_from_slice(&0x0001_0000u32.to_le_bytes());
        b[112..116].copy_from_slice(&0u32.to_le_bytes());
        b[116..120].copy_from_slice(&120u32.to_le_bytes());
        for (i, v) in name.iter().enumerate() { b[120+i*2..122+i*2].copy_from_slice(&v.to_le_bytes()); }
        words
    }

    unsafe fn stop_kernel_logger() {
        let mut props = build_properties();
        let name = wide("NT Kernel Logger");
        let _ = ControlTraceW(0, name.as_ptr(), props.as_mut_ptr() as *mut c_void, 1);
    }

    pub fn start_etw(proxy: &str) -> bool {
        stop_etw();
        let parsed = proxy.rsplit_once(':').and_then(|(host,port)| Some((host.parse::<Ipv4Addr>().ok()?, port.parse::<u16>().ok()?)));
        let (ip, port) = parsed.map(|(ip,p)|(Some(u32::from_ne_bytes(ip.octets())),p)).unwrap_or((None,0));
        {
            let mut state = etw_state().lock().unwrap();
            state.proxy_ip = ip;
            state.proxy_port = port;
            state.stats.clear();
            state.pid_cache.clear();
        }
        *etw_error().lock().unwrap() = None;
        ETW_RUNNING.store(true, Ordering::SeqCst);
        thread::spawn(run_etw);
        thread::sleep(Duration::from_millis(300));
        etw_error().lock().unwrap().is_none()
    }

    pub fn stop_etw() {
        ETW_RUNNING.store(false, Ordering::SeqCst);
        unsafe { stop_kernel_logger(); }
        let h = ETW_TRACE.swap(0, Ordering::SeqCst);
        if h != 0 { unsafe { CloseTrace(h); } }
    }

    unsafe fn run_etw() {
        let result = (|| -> Result<(), String> {
            stop_kernel_logger();
            let mut props = build_properties();
            let name = wide("NT Kernel Logger");
            let mut session = 0u64;
            let status = StartTraceW(&mut session, name.as_ptr(), props.as_mut_ptr() as *mut c_void);
            if status != 0 {
                return Err(if status == 5 { "ERROR_ACCESS_DENIED (для ETW нужны права Администратора)".into() } else { format!("StartTraceW code={status}") });
            }

            let mut logfile = AlignedLogfile([0u8; 512]);
            let logger_ptr = name.as_ptr() as usize as u64;
            logfile.0[8..16].copy_from_slice(&logger_ptr.to_ne_bytes());
            logfile.0[28..32].copy_from_slice(&(0x0000_0100u32 | 0x1000_0000u32).to_le_bytes());
            let cb = event_record_callback as usize as u64;
            logfile.0[376..384].copy_from_slice(&cb.to_ne_bytes());

            let trace = OpenTraceW(logfile.0.as_mut_ptr() as *mut c_void);
            if trace == u64::MAX || trace == 0 {
                stop_kernel_logger();
                return Err(format!("OpenTraceW failed: {}", GetLastError()));
            }
            ETW_TRACE.store(trace, Ordering::SeqCst);
            let _ = ProcessTrace(&trace, 1, ptr::null(), ptr::null());
            ETW_TRACE.store(0, Ordering::SeqCst);
            Ok(())
        })();
        if let Err(e) = result {
            *etw_error().lock().unwrap() = Some(e);
        }
        ETW_RUNNING.store(false, Ordering::SeqCst);
        stop_kernel_logger();
    }

    unsafe extern "system" fn event_record_callback(record: *mut EventRecord) {
        if !ETW_RUNNING.load(Ordering::Relaxed) || record.is_null() { return; }
        let rec = &*record;
        let h = &rec.header;
        let op = h.opcode;
        if ![10,11,26,27].contains(&op) || rec.user_data.is_null() { return; }
        let provider = &h.provider_id;
        let tcp = provider.data1 == 0x9a280ac0 && provider.data2 == 0xc8e0 && provider.data3 == 0x11d1;
        let udp = provider.data1 == 0xbf3a50c5 && provider.data2 == 0xa9c9 && provider.data3 == 0x4988;
        if !tcp && !udp { return; }
        let len = rec.user_data_length as usize;
        let raw = std::slice::from_raw_parts(rec.user_data as *const u8, len);
        if tcp && len >= 20 && (op == 10 || op == 11) {
            let pid = u32::from_le_bytes(raw[0..4].try_into().unwrap());
            let packet = u32::from_le_bytes(raw[4..8].try_into().unwrap()) as u64;
            let dst = u32::from_le_bytes(raw[8..12].try_into().unwrap());
            let src = u32::from_le_bytes(raw[12..16].try_into().unwrap());
            let dp = u16::from_be(u16::from_le_bytes(raw[16..18].try_into().unwrap()));
            let sp = u16::from_be(u16::from_le_bytes(raw[18..20].try_into().unwrap()));
            let mut state = etw_state().lock().unwrap();
            let proxy = state.proxy_ip.map(|ip| {
                if state.proxy_port > 0 { (dst == ip && dp == state.proxy_port) || (src == ip && sp == state.proxy_port) }
                else { dst == ip || src == ip }
            }).unwrap_or(false);
            if !proxy && dst == 0x0100007f && src == 0x0100007f { return; }
            add_event(&mut state, pid, if op == 11 { packet } else { 0 }, if op == 10 { packet } else { 0 }, proxy);
        } else if udp && len >= 40 && (op == 26 || op == 27) {
            let pid = u32::from_le_bytes(raw[0..4].try_into().unwrap());
            let packet = u32::from_le_bytes(raw[4..8].try_into().unwrap()) as u64;
            let mut state = etw_state().lock().unwrap();
            add_event(&mut state, pid, if op == 27 { packet } else { 0 }, if op == 26 { packet } else { 0 }, false);
        }
    }

    fn add_event(state: &mut EtwState, pid: u32, rx: u64, tx: u64, proxy: bool) {
        if pid == 0 || (rx == 0 && tx == 0) { return; }
        let name = state.pid_cache.entry(pid).or_insert_with(|| process_name(pid)).clone();
        let row = state.stats.entry(name.clone()).or_insert_with(|| ProcTraffic { name, ..Default::default() });
        row.rx_bytes = row.rx_bytes.saturating_add(rx);
        row.tx_bytes = row.tx_bytes.saturating_add(tx);
        row.via_proxy |= proxy;
    }

    pub fn etw_snapshot() -> (Vec<ProcTraffic>, Option<String>) {
        let rows = etw_state().lock().unwrap().stats.values().cloned().collect();
        let error = etw_error().lock().unwrap().clone();
        (rows, error)
    }
}

#[cfg(not(windows))]
mod win {
    use super::*;
    pub fn is_admin() -> bool { false }
    pub fn relaunch_admin() -> bool { false }
    pub fn adapter_bytes() -> (u64,u64) { (0,0) }
    pub fn firewall_offline(_: bool) -> Result<String,String> { Err("Только Windows".into()) }
    pub fn remove_firewall_rule() {}
    pub fn active_tcp_connections(_: Option<Ipv4Addr>, _: u16) -> Vec<(String,bool)> { Vec::new() }
    pub fn start_etw(_: &str) -> bool { *etw_error().lock().unwrap() = Some("ETW доступен только в Windows".into()); false }
    pub fn stop_etw() {}
    pub fn etw_snapshot() -> (Vec<ProcTraffic>,Option<String>) { (Vec::new(), etw_error().lock().unwrap().clone()) }
}

fn format_size(bytes: u64) -> String {
    let kb = bytes as f64 / 1024.0;
    if kb < 1000.0 { format!("{kb:.1} Kb") } else { format!("{:.2} Mb", kb / 1024.0) }
}
fn elapsed_string(seconds: u64) -> String {
    let h = seconds / 3600;
    let m = (seconds % 3600) / 60;
    let s = seconds % 60;
    format!("{h:02}:{m:02}:{s:02}")
}

struct TrafficMonitorApp {
    proxy: String,
    interval: f32,
    monitoring: bool,
    offline: bool,
    always_top: bool,
    status: String,
    start_time: Option<Instant>,
    last_tick: Instant,
    base_in: u64,
    base_out: u64,
    last_in: u64,
    last_out: u64,
    speed_in: u64,
    speed_out: u64,
    adapter_in: u64,
    adapter_out: u64,
    rows: Vec<ProcTraffic>,
    etw_error: Option<String>,
}
impl Default for TrafficMonitorApp {
    fn default() -> Self {
        let (rx,tx) = win::adapter_bytes();
        Self {
            proxy: "192.168.43.1:10809".into(), interval: 0.2, monitoring: false,
            offline: false, always_top: false, status: "Готов к запуску.".into(),
            start_time: None, last_tick: Instant::now(), base_in: rx, base_out: tx,
            last_in: rx, last_out: tx, speed_in: 0, speed_out: 0,
            adapter_in: 0, adapter_out: 0, rows: Vec::new(), etw_error: None,
        }
    }
}
impl TrafficMonitorApp {
    fn start(&mut self) {
        let ok = win::start_etw(&self.proxy);
        let (rx,tx) = win::adapter_bytes();
        self.base_in = rx; self.base_out = tx; self.last_in = rx; self.last_out = tx;
        self.start_time = Some(Instant::now()); self.last_tick = Instant::now();
        self.monitoring = true;
        self.status = if ok { "Мониторинг активен (ETW Kernel Trace).".into() }
            else { format!("Режим адаптера ({}).", self.etw_error.clone().unwrap_or_else(|| "ETW недоступен".into())) };
    }
    fn stop(&mut self) {
        win::stop_etw();
        self.monitoring = false;
        self.status = "Мониторинг остановлен.".into();
    }
    fn reset(&mut self) {
        let (rx,tx) = win::adapter_bytes();
        self.base_in = rx; self.base_out = tx; self.last_in = rx; self.last_out = tx;
        self.last_tick = Instant::now(); self.start_time = Some(Instant::now());
        if self.monitoring { let mut s = etw_state().lock().unwrap(); s.stats.clear(); }
        self.status = "Счётчики трафика сброшены.".into();
    }
    fn set_offline(&mut self, enable: bool) {
        match win::firewall_offline(enable) {
            Ok(msg) => {
                self.offline = enable;
                self.status = if enable { "Режим OFFLINE: весь трафик заблокирован.".into() } else { "Режим ONLINE: доступ в сеть восстановлен.".into() };
                let _ = msg;
            }
            Err(e) => self.status = e,
        }
    }
    fn tick(&mut self) {
        if !self.monitoring { return; }
        let now = Instant::now();
        let dt = now.duration_since(self.last_tick).as_secs_f64().max(0.05);
        self.last_tick = now;
        let (rx,tx) = win::adapter_bytes();
        self.adapter_in = rx.saturating_sub(self.base_in);
        self.adapter_out = tx.saturating_sub(self.base_out);
        self.speed_in = (rx.saturating_sub(self.last_in) as f64 / dt) as u64;
        self.speed_out = (tx.saturating_sub(self.last_out) as f64 / dt) as u64;
        self.last_in = rx; self.last_out = tx;
        let (mut rows,err) = win::etw_snapshot();
        rows.sort_by_key(|r| std::cmp::Reverse(r.total()));
        self.rows = rows;
        self.etw_error = err;
    }
    fn apply_theme(ctx: &egui::Context) {
        let mut style = (*ctx.style()).clone();
        style.visuals = egui::Visuals::dark();
        style.visuals.panel_fill = BG_MAIN;
        style.visuals.window_fill = BG_MAIN;
        style.visuals.extreme_bg_color = BG_INPUT;
        style.visuals.faint_bg_color = BG_BUTTON;
        style.visuals.widgets.inactive.bg_fill = BG_BUTTON;
        style.visuals.widgets.hovered.bg_fill = egui::Color32::from_rgb(0x45,0x45,0x45);
        style.visuals.widgets.active.bg_fill = egui::Color32::from_rgb(0x28,0x28,0x28);
        style.visuals.widgets.inactive.fg_stroke.color = TEXT;
        style.visuals.widgets.hovered.fg_stroke.color = TEXT;
        style.visuals.widgets.active.fg_stroke.color = egui::Color32::WHITE;
        style.visuals.selection.bg_fill = egui::Color32::from_rgb(0x00,0x55,0xaa);
        style.spacing.item_spacing = egui::vec2(5.0, 4.0);
        ctx.set_style(style);
    }
    fn render_report(&mut self, ui: &mut egui::Ui) {
        let elapsed = self.start_time.map(|t| t.elapsed().as_secs()).unwrap_or(0);
        let mode = if self.offline { "OFFLINE" } else { "ONLINE" };
        let color = if self.offline { RED } else { BLUE };
        let proxy = if self.proxy.trim().is_empty() { "Нет" } else { self.proxy.trim() };
        ui.label(egui::RichText::new(format!("АДАПТЕР [{mode}] ({} | Proxy: {proxy})", elapsed_string(elapsed))).color(color).strong().monospace());
        ui.label(egui::RichText::new(format!("↓ {} | ↑ {} | Σ {}", format_size(self.adapter_in), format_size(self.adapter_out), format_size(self.adapter_in.saturating_add(self.adapter_out)))).color(TEXT).monospace());
        ui.label(egui::RichText::new(format!("Скор.: ↓ {}/с  ↑ {}/с", format_size(self.speed_in), format_size(self.speed_out))).color(MUTED).monospace());
        ui.separator();
        if let Some(err) = &self.etw_error {
            ui.label(egui::RichText::new(format!("[!] ETW недоступен: {err}")).color(WARN).monospace());
            let (ip,port) = parse_proxy(&self.proxy);
            for (name,is_proxy) in win::active_tcp_connections(ip,port) {
                ui.label(egui::RichText::new(format!("• {name}")).color(if is_proxy { PROXY } else { TEXT }).monospace());
            }
        } else {
            egui::ScrollArea::vertical().auto_shrink([false,false]).show(ui, |ui| {
                for row in &self.rows {
                    let mut label = if row.via_proxy { format!("{} [P]",row.name) } else { row.name.clone() };
                    if label.chars().count() > 21 { label = format!("{}...", label.chars().take(18).collect::<String>()); }
                    let line = format!("{label:<22} {:>9} {:>9} {:>9}", format_size(row.rx_bytes), format_size(row.tx_bytes), format_size(row.total()));
                    ui.label(egui::RichText::new(line).color(if row.via_proxy { PROXY } else { TEXT }).monospace().size(10.5));
                }
            });
        }
    }
}
fn parse_proxy(raw: &str) -> (Option<Ipv4Addr>,u16) {
    if let Some((host,port)) = raw.trim().rsplit_once(':') {
        (host.trim().parse().ok(),port.trim().parse().unwrap_or(0))
    } else { (raw.trim().parse().ok(),0) }
}

impl eframe::App for TrafficMonitorApp {
    fn update(&mut self, ctx: &egui::Context, _frame: &mut eframe::Frame) {
        Self::apply_theme(ctx);
        if self.monitoring { self.tick(); ctx.request_repaint_after(Duration::from_secs_f32(self.interval.max(0.1))); }

        egui::CentralPanel::default().frame(egui::Frame::new().fill(BG_MAIN).inner_margin(8.0)).show(ctx, |ui| {
            ui.horizontal(|ui| {
                ui.label(egui::RichText::new(APP_TITLE).color(BLUE).strong().size(16.0));
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    let text = if self.always_top { "Always top ✓" } else { "Always top" };
                    if ui.small_button(text).clicked() {
                        self.always_top = !self.always_top;
                        ctx.send_viewport_cmd(egui::ViewportCommand::WindowLevel(
                            if self.always_top { egui::viewport::WindowLevel::AlwaysOnTop } else { egui::viewport::WindowLevel::Normal }
                        ));
                    }
                });
            });
            ui.add_space(2.0);
            ui.separator();
            ui.horizontal(|ui| {
                ui.label("Proxy:");
                ui.add_enabled(!self.monitoring, egui::TextEdit::singleline(&mut self.proxy).desired_width(126.0).font(egui::TextStyle::Monospace));
                if ui.add_sized([58.0,22.0],egui::Button::new(if self.monitoring { "Stop" } else { "Start" }).fill(BLUE)).clicked() {
                    if self.monitoring { self.stop(); } else { self.start(); }
                }
                if ui.add_sized([44.0,22.0],egui::Button::new("Сброс")).clicked() { self.reset(); }
            });
            ui.horizontal(|ui| {
                ui.label("Обновление (с):");
                egui::ComboBox::from_id_salt("interval").width(48.0).selected_text(format!("{}",self.interval)).show_ui(ui, |ui| {
                    for v in [0.1f32,0.2,0.5,1.0,5.0] { ui.selectable_value(&mut self.interval,v,format!("{v:g}")); }
                });
                if !win::is_admin() && ui.button("Админ").clicked() {
                    if win::relaunch_admin() { ctx.send_viewport_cmd(egui::ViewportCommand::Close); }
                    else { self.status = "Не удалось запросить права Администратора.".into(); }
                }
                ui.with_layout(egui::Layout::right_to_left(egui::Align::Center), |ui| {
                    if self.offline {
                        if ui.add_enabled(true,egui::Button::new("Online").fill(GREEN)).clicked() { self.set_offline(false); }
                        ui.add_enabled(false,egui::Button::new("Offline").fill(RED));
                    } else {
                        if ui.add_enabled(true,egui::Button::new("Offline").fill(RED)).clicked() { self.set_offline(true); }
                        ui.add_enabled(false,egui::Button::new("Online").fill(GREEN));
                    }
                });
            });
            ui.add_space(2.0);
            egui::Frame::new().fill(BG_INPUT).stroke(egui::Stroke::new(1.0,BORDER)).inner_margin(6.0).show(ui, |ui| {
                ui.set_min_height(78.0);
                if self.monitoring { self.render_report(ui); }
                else {
                    ui.label(egui::RichText::new("Ожидание запуска мониторинга...").color(BLUE).strong().monospace());
                    if win::is_admin() {
                        ui.label(egui::RichText::new("Права Администратора: АКТИВНЫ (полный ETW-захват).").color(MUTED));
                    } else {
                        ui.label(egui::RichText::new("ВНИМАНИЕ: Запуск БЕЗ прав Админа. Нажмите «Админ».").color(WARN));
                    }
                    ui.label(egui::RichText::new("Нажмите Start для запуска.").color(MUTED));
                }
            });
            ui.label(egui::RichText::new(&self.status).color(MUTED).size(10.0));
        });
    }

    fn on_exit(&mut self, _gl: Option<&eframe::glow::Context>) {
        if self.offline { win::remove_firewall_rule(); }
        win::stop_etw();
    }
}

fn main() -> eframe::Result<()> {
    let options = eframe::NativeOptions {
        viewport: egui::ViewportBuilder::default()
            .with_title(APP_TITLE)
            .with_inner_size([360.0,190.0])
            .with_min_inner_size([360.0,190.0]),
        ..Default::default()
    };
    eframe::run_native(APP_TITLE, options, Box::new(|_cc| Ok(Box::new(TrafficMonitorApp::default()))))
}
