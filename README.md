# RustMiniTools

Cargo workspace for standalone Windows utilities written in Rust.

## TrafficMonitor

A Rust/egui port of the Python reference in `Refs/TrafficMonitor..py`.

### Build locally

```powershell
cargo build --release -p traffic_monitor
```

Executable: `target/release/traffic_monitor.exe`.

### GitHub Actions

Open **Actions → TrafficMonitor → Run workflow**. The workflow is manual-only
(`workflow_dispatch`) and uploads the executable as an artifact.

The monitor uses Windows ETW Kernel Network events for per-process byte counts
and IP Helper adapter counters for aggregate traffic. ETW collection generally
requires an elevated process. The Offline/Online controls add/remove a dedicated
Windows Firewall rule pair and therefore also require Administrator privileges.

This application changes firewall rules only when the user explicitly presses
Offline or Online. On normal close, an active Offline rule is removed.
