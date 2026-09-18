from __future__ import annotations
import sys
import time
import urllib.request
import json
import subprocess
import yaml
from pathlib import Path

ROOT = Path(__file__).parent.parent

class ThermalController:
    _sensors_dead_until: float = 0.0
    _sensor_retry_sec: float = 300.0
    _cached_temp: float | None = None
    _cached_temp_time: float = 0.0
    _lhm_available: bool = False

    def __init__(self, config_path: Path | None = None) -> None:
        self.config_path = config_path or (ROOT / "config.yaml")
        self.enabled = True
        self.target_temp_low = 65.0
        self.target_temp_high = 80.0
        self.target_cpu_low = 60.0
        self.target_cpu_high = 85.0
        self.cooldown_min = 0.1
        self.cooldown_max = 5.0
        self.default_cooldown = 0.0
        self.last_log_time = 0.0
        
        self.load_config()
        
        # Initialize psutil if available
        self.psutil_available = False
        try:
            import psutil
            self.psutil_available = True
            # First call to cpu_percent initializes the tracker
            psutil.cpu_percent(None)
        except ImportError:
            pass

    def load_config(self) -> None:
        if not self.config_path.exists():
            return
        try:
            with open(self.config_path, "r", encoding="utf-8") as f:
                cfg = yaml.safe_load(f) or {}
                
            indexing = cfg.get("indexing", {})
            self.default_cooldown = float(indexing.get("batch_cooldown_sec", 0.0))
            
            tc = indexing.get("thermal_control", {})
            if tc:
                self.enabled = bool(tc.get("enabled", True))
                self.target_temp_low = float(tc.get("target_temp_low", 65.0))
                self.target_temp_high = float(tc.get("target_temp_high", 80.0))
                self.target_cpu_low = float(tc.get("target_cpu_low", 60.0))
                self.target_cpu_high = float(tc.get("target_cpu_high", 85.0))
                self.cooldown_min = float(tc.get("cooldown_min", 0.1))
                self.cooldown_max = float(tc.get("cooldown_max", 5.0))
        except Exception as e:
            print(f"[ThermalController] Error loading config: {e}", file=sys.stderr)

    def get_cpu_temp_lhm(self) -> float | None:
        """Query LibreHardwareMonitor JSON API if running."""
        urls = [
            "http://localhost:8085/data/list",
            "http://localhost:8085/data/list.json",
            "http://localhost:8080/data/list"
        ]
        for url in urls:
            try:
                req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req, timeout=0.5) as response:
                    if response.status == 200:
                        data = json.loads(response.read().decode('utf-8'))
                        
                        cpu_temps = []
                        def parse_nodes(nodes):
                            for node in nodes:
                                text = node.get("Text", "")
                                value = node.get("Value", "")
                                if "cpu" in text.lower() and "temp" in text.lower() and "°C" in value:
                                    try:
                                        val_num = float(value.replace("°C", "").strip().replace(",", "."))
                                        cpu_temps.append(val_num)
                                    except ValueError:
                                        pass
                                if "Children" in node and node["Children"]:
                                    parse_nodes(node["Children"])
                        
                        if isinstance(data, dict) and "Children" in data:
                            parse_nodes(data["Children"])
                        elif isinstance(data, list):
                            parse_nodes(data)
                            
                        if cpu_temps:
                            return max(cpu_temps)
            except Exception:
                pass
        return None

    def get_cpu_temp_perf_counters(self) -> float | None:
        """Query standard unprivileged WMI PerfFormattedData thermal zones."""
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                "(Get-CimInstance -ClassName Win32_PerfFormattedData_Counters_ThermalZoneInformation -ErrorAction Stop | Measure-Object -Property HighPrecisionTemperature -Maximum).Maximum"
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True, timeout=2.0)
            if res.returncode == 0:
                raw = res.stdout.strip()
                if raw and raw.replace('.', '', 1).isdigit():
                    temp_k10 = float(raw)
                    temp_c = (temp_k10 / 10.0) - 273.15
                    if 0.0 < temp_c < 150.0:
                        return temp_c
        except Exception:
            pass
        return None

    def get_cpu_temp_wmi(self) -> float | None:
        """Query WMI/PowerShell for ACPI thermal zone temperature (all zones)."""
        try:
            cmd = [
                "powershell",
                "-NoProfile",
                "-Command",
                "Get-CimInstance -Namespace root/wmi -ClassName MSAcpi_ThermalZoneTemperature -ErrorAction Stop | Select-Object -ExpandProperty CurrentTemperature"
            ]
            res = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=2.0)
            if res.returncode == 0:
                output = res.stdout.decode('utf-8', errors='replace').strip()
                lines = [float(l.strip()) for l in output.splitlines() if l.strip().isdigit()]
                if lines:
                    max_k10 = max(lines)
                    temp_c = (max_k10 / 10.0) - 273.15
                    if 0.0 < temp_c < 150.0:  # Validate sanity of values
                        return temp_c
        except Exception:
            pass
        return None

    def get_cpu_temperature(self) -> float | None:
        """Try multiple methods to query CPU Temperature with a 5-second cache."""
        now = time.time()
        if (now - ThermalController._cached_temp_time) < 5.0 and ThermalController._cached_temp is not None:
            return ThermalController._cached_temp

        if now < ThermalController._sensors_dead_until:
            return None

        temp = None
        if ThermalController._lhm_available:
            temp = self.get_cpu_temp_lhm()
            if temp is not None:
                ThermalController._cached_temp = temp
                ThermalController._cached_temp_time = now
                return temp

        # 2. Try standard unprivileged WMI PerfFormattedData (works without admin rights)
        temp = self.get_cpu_temp_perf_counters()
        if temp is not None:
            ThermalController._cached_temp = temp
            ThermalController._cached_temp_time = now
            return temp

        # 3. Try WMI ACPI via PowerShell
        temp = self.get_cpu_temp_wmi()
        if temp is not None:
            ThermalController._cached_temp = temp
            ThermalController._cached_temp_time = now
            return temp

        ThermalController._sensors_dead_until = now + ThermalController._sensor_retry_sec
        return None

    def get_cooldown(self) -> float:
        """Calculate dynamic cooldown based on temperature or CPU usage fallback."""
        if not self.enabled:
            return self.default_cooldown

        temp = None
        try:
            temp = self.get_cpu_temperature()
        except Exception as e:
            print(f"[ThermalController] Temperature lookup exception: {e}", file=sys.stderr)

        now = time.time()
        should_log = (now - self.last_log_time) > 15.0  # Log at most once every 15 seconds

        if temp is not None:
            # Emergency thermal brake: if temperature hits or exceeds 80°C, pause execution
            if temp >= 80.0:
                emergency_pause = 8.0
                print(f"[ThermalController] WARNING: CPU Temp {temp:.1f}°C >= 80°C! Pausing {emergency_pause}s for cooling...", file=sys.stderr)
                time.sleep(emergency_pause)
                ThermalController._cached_temp = None  # Force re-read on next check

            # Linear interpolation based on temperature
            if temp <= self.target_temp_low:
                cooldown = self.cooldown_min
            elif temp >= self.target_temp_high:
                cooldown = self.cooldown_max
            else:
                ratio = (temp - self.target_temp_low) / (self.target_temp_high - self.target_temp_low)
                cooldown = self.cooldown_min + ratio * (self.cooldown_max - self.cooldown_min)
            
            if should_log:
                print(f"[ThermalController] CPU Temp: {temp:.1f}°C -> Cooldown: {cooldown:.2f}s", file=sys.stderr)
                self.last_log_time = now
            return cooldown

        # Fallback to CPU usage
        if self.psutil_available:
            try:
                import psutil
                cpu_load = psutil.cpu_percent(None)
                
                # Linear interpolation based on CPU usage
                if cpu_load <= self.target_cpu_low:
                    cooldown = self.cooldown_min
                elif cpu_load >= self.target_cpu_high:
                    cooldown = self.cooldown_max
                else:
                    ratio = (cpu_load - self.target_cpu_low) / (self.target_cpu_high - self.target_cpu_low)
                    cooldown = self.cooldown_min + ratio * (self.cooldown_max - self.cooldown_min)
                
                if should_log:
                    print(f"[ThermalController] (Fallback) CPU Load: {cpu_load:.1f}% -> Cooldown: {cooldown:.2f}s", file=sys.stderr)
                    self.last_log_time = now
                return cooldown
            except Exception as e:
                print(f"[ThermalController] Fallback lookup exception: {e}", file=sys.stderr)

        # Ultimate fallback to config default
        if should_log:
            print(f"[ThermalController] (Fallback) Sensors/psutil unavailable -> Static Cooldown: {self.default_cooldown:.2f}s", file=sys.stderr)
            self.last_log_time = now
        return self.default_cooldown
