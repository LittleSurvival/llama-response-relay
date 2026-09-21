from __future__ import annotations

from dataclasses import dataclass, replace
import ctypes
import math
import os
import re
import threading
import time
from typing import Callable, Protocol, Sequence, TYPE_CHECKING

from .telemetry import Availability

if TYPE_CHECKING:
    from .process import OwnedProcessIdentity


@dataclass(frozen=True, slots=True)
class MetricReading:
    value: float | None = None
    state: Availability = Availability.UNAVAILABLE

    @classmethod
    def number(
        cls,
        value: object,
        *,
        minimum: float | None = None,
        maximum: float | None = None,
    ) -> MetricReading:
        try:
            result = float(value)  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return cls()
        if not math.isfinite(result):
            return cls()
        if minimum is not None and result < minimum:
            return cls()
        if maximum is not None and result > maximum:
            return cls()
        return cls(result, Availability.AVAILABLE)

    def stale(self) -> MetricReading:
        if self.state is not Availability.AVAILABLE:
            return self
        return replace(self, state=Availability.STALE)


@dataclass(frozen=True, slots=True)
class CpuSample:
    utilization: MetricReading = MetricReading()
    frequency_mhz: MetricReading = MetricReading()
    process_utilization: MetricReading = MetricReading()

    def stale(self) -> CpuSample:
        return CpuSample(
            self.utilization.stale(),
            self.frequency_mhz.stale(),
            self.process_utilization.stale(),
        )


@dataclass(frozen=True, slots=True)
class GpuSample:
    identifier: str
    vendor: str
    name: str
    utilization: MetricReading = MetricReading()
    frequency_mhz: MetricReading = MetricReading()
    vram_used_bytes: MetricReading = MetricReading()
    vram_total_bytes: MetricReading = MetricReading()
    temperature_c: MetricReading = MetricReading()
    source: str = ""

    @property
    def vram_utilization(self) -> MetricReading:
        if (
            self.vram_used_bytes.state is not Availability.AVAILABLE
            or self.vram_total_bytes.state is not Availability.AVAILABLE
            or self.vram_total_bytes.value is None
            or self.vram_total_bytes.value <= 0
            or self.vram_used_bytes.value is None
        ):
            return MetricReading()
        return MetricReading.number(
            self.vram_used_bytes.value / self.vram_total_bytes.value * 100.0,
            minimum=0,
            maximum=100,
        )

    def stale(self) -> GpuSample:
        return replace(
            self,
            utilization=self.utilization.stale(),
            frequency_mhz=self.frequency_mhz.stale(),
            vram_used_bytes=self.vram_used_bytes.stale(),
            vram_total_bytes=self.vram_total_bytes.stale(),
            temperature_c=self.temperature_c.stale(),
        )


@dataclass(frozen=True, slots=True)
class HardwareSnapshot:
    timestamp: float
    cpu: CpuSample = CpuSample()
    gpus: tuple[GpuSample, ...] = ()
    state: Availability = Availability.AVAILABLE

    def is_stale(self, now: float | None = None, *, after_seconds: float = 3.0) -> bool:
        current = time.monotonic() if now is None else now
        return current - self.timestamp > after_seconds

    def stale(self) -> HardwareSnapshot:
        return HardwareSnapshot(
            timestamp=self.timestamp,
            cpu=self.cpu.stale(),
            gpus=tuple(gpu.stale() for gpu in self.gpus),
            state=Availability.STALE,
        )


class CpuProvider(Protocol):
    def sample(self, process: OwnedProcessIdentity | None) -> CpuSample: ...


class CpuFrequencyProvider(Protocol):
    def sample(self, nominal_mhz: float | None) -> MetricReading: ...

    def close(self) -> None: ...


class GpuProvider(Protocol):
    name: str
    priority: int

    def sample(self) -> Sequence[GpuSample]: ...

    def close(self) -> None: ...


class WindowsPdhCpuFrequencyProvider:
    """Track average dynamic CPU frequency through a locale-independent PDH counter."""

    def __init__(self, api: object | None = None) -> None:
        self._api = api or _WindowsPdhApi()
        self._opened = False
        self._primed = False

    def sample(self, nominal_mhz: float | None) -> MetricReading:
        nominal = MetricReading.number(nominal_mhz, minimum=1)
        if nominal.value is None:
            return MetricReading()
        if not self._opened:
            try:
                self._opened = bool(self._api.open())
            except Exception:
                self._opened = False
            if not self._opened:
                return MetricReading()
        try:
            if not self._api.collect():
                return MetricReading()
            if not self._primed:
                self._primed = True
                return MetricReading()
            performance_percent = self._api.read()
        except Exception:
            return MetricReading()
        performance = MetricReading.number(
            performance_percent,
            minimum=0.01,
            maximum=1000,
        )
        if performance.value is None:
            return MetricReading()
        return MetricReading.number(
            nominal.value * performance.value / 100.0,
            minimum=1,
        )

    def close(self) -> None:
        try:
            self._api.close()
        except Exception:
            pass
        self._opened = False
        self._primed = False


class _PdhValueUnion(ctypes.Union):
    _fields_ = [
        ("long_value", ctypes.c_long),
        ("double_value", ctypes.c_double),
        ("large_value", ctypes.c_longlong),
        ("ansi_string", ctypes.c_char_p),
        ("wide_string", ctypes.c_wchar_p),
    ]


class _PdhFormattedValue(ctypes.Structure):
    _anonymous_ = ("value",)
    _fields_ = [
        ("status", ctypes.c_ulong),
        ("value", _PdhValueUnion),
    ]


class _WindowsPdhApi:
    _PDH_FMT_DOUBLE = 0x00000200
    _COUNTER_PATH = (
        r"\Processor Information(_Total)\% Processor Performance"
    )

    def __init__(self) -> None:
        if os.name != "nt":
            raise RuntimeError("Windows PDH is unavailable on this platform.")
        self._pdh = ctypes.WinDLL("pdh.dll")
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()
        self._configure_signatures()

    def _configure_signatures(self) -> None:
        self._pdh.PdhOpenQueryW.argtypes = [
            ctypes.c_wchar_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._pdh.PdhOpenQueryW.restype = ctypes.c_long
        self._pdh.PdhAddEnglishCounterW.argtypes = [
            ctypes.c_void_p,
            ctypes.c_wchar_p,
            ctypes.c_size_t,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._pdh.PdhAddEnglishCounterW.restype = ctypes.c_long
        self._pdh.PdhCollectQueryData.argtypes = [ctypes.c_void_p]
        self._pdh.PdhCollectQueryData.restype = ctypes.c_long
        self._pdh.PdhGetFormattedCounterValue.argtypes = [
            ctypes.c_void_p,
            ctypes.c_ulong,
            ctypes.POINTER(ctypes.c_ulong),
            ctypes.POINTER(_PdhFormattedValue),
        ]
        self._pdh.PdhGetFormattedCounterValue.restype = ctypes.c_long
        self._pdh.PdhCloseQuery.argtypes = [ctypes.c_void_p]
        self._pdh.PdhCloseQuery.restype = ctypes.c_long

    def open(self) -> bool:
        if self._query.value:
            return True
        if self._pdh.PdhOpenQueryW(None, 0, ctypes.byref(self._query)) != 0:
            return False
        status = self._pdh.PdhAddEnglishCounterW(
            self._query,
            self._COUNTER_PATH,
            0,
            ctypes.byref(self._counter),
        )
        if status != 0:
            self.close()
            return False
        return True

    def collect(self) -> bool:
        return bool(
            self._query.value
            and self._pdh.PdhCollectQueryData(self._query) == 0
        )

    def read(self) -> float | None:
        if not self._counter.value:
            return None
        value_type = ctypes.c_ulong()
        value = _PdhFormattedValue()
        status = self._pdh.PdhGetFormattedCounterValue(
            self._counter,
            self._PDH_FMT_DOUBLE,
            ctypes.byref(value_type),
            ctypes.byref(value),
        )
        if status != 0 or value.status != 0:
            return None
        return float(value.double_value)

    def close(self) -> None:
        if self._query.value:
            self._pdh.PdhCloseQuery(self._query)
        self._query = ctypes.c_void_p()
        self._counter = ctypes.c_void_p()


class PsutilCpuProvider:
    def __init__(
        self,
        psutil_module: object | None = None,
        *,
        frequency_provider: CpuFrequencyProvider | None = None,
    ) -> None:
        if psutil_module is None:
            import psutil as psutil_module

        self._psutil = psutil_module
        self._logical_cpus = max(1, int(self._psutil.cpu_count(logical=True) or 1))
        self._process_key: tuple[int, int] | None = None
        self._process: object | None = None
        self._process_create_time: float | None = None
        if frequency_provider is not None:
            self._frequency_provider = frequency_provider
        elif os.name == "nt":
            try:
                self._frequency_provider = WindowsPdhCpuFrequencyProvider()
            except Exception:
                self._frequency_provider = None
        else:
            self._frequency_provider = None
        self._psutil.cpu_percent(interval=None)

    def sample(self, process: OwnedProcessIdentity | None) -> CpuSample:
        utilization = MetricReading.number(
            self._safe_call(self._psutil.cpu_percent, interval=None),
            minimum=0,
            maximum=100,
        )
        frequency = self._safe_call(self._psutil.cpu_freq)
        nominal_mhz = getattr(frequency, "current", None)
        if self._frequency_provider is not None:
            frequency_mhz = self._frequency_provider.sample(nominal_mhz)
        else:
            frequency_mhz = MetricReading.number(nominal_mhz, minimum=0)
        process_utilization = self._sample_process(process)
        return CpuSample(utilization, frequency_mhz, process_utilization)

    def _sample_process(
        self, identity: OwnedProcessIdentity | None
    ) -> MetricReading:
        if identity is None:
            self._clear_process()
            return MetricReading()
        key = (identity.generation, identity.pid)
        try:
            if key != self._process_key or self._process is None:
                candidate = self._psutil.Process(identity.pid)
                create_time = float(candidate.create_time())
                candidate.cpu_percent(interval=None)
                self._process_key = key
                self._process = candidate
                self._process_create_time = create_time
                return MetricReading()
            if float(self._process.create_time()) != self._process_create_time:
                self._clear_process()
                return MetricReading()
            raw = float(self._process.cpu_percent(interval=None))
        except Exception:
            self._clear_process()
            return MetricReading()
        return MetricReading.number(
            raw / self._logical_cpus,
            minimum=0,
            maximum=100,
        )

    def _clear_process(self) -> None:
        self._process_key = None
        self._process = None
        self._process_create_time = None

    def close(self) -> None:
        if self._frequency_provider is not None:
            self._frequency_provider.close()

    @staticmethod
    def _safe_call(function: Callable[..., object], **kwargs: object) -> object | None:
        try:
            return function(**kwargs)
        except Exception:
            return None


class NvmlGpuProvider:
    name = "NVML"
    priority = 10

    def __init__(self, nvml_module: object | None = None) -> None:
        self._nvml = nvml_module
        self._initialized = False

    def sample(self) -> Sequence[GpuSample]:
        nvml = self._load()
        samples: list[GpuSample] = []
        for index in range(int(nvml.nvmlDeviceGetCount())):
            try:
                handle = nvml.nvmlDeviceGetHandleByIndex(index)
                name = _decode(nvml.nvmlDeviceGetName(handle))
                identifier = _decode(nvml.nvmlDeviceGetUUID(handle)) or f"nvidia:{index}"
                utilization = nvml.nvmlDeviceGetUtilizationRates(handle)
                memory = nvml.nvmlDeviceGetMemoryInfo(handle)
                clock = nvml.nvmlDeviceGetClockInfo(
                    handle, nvml.NVML_CLOCK_GRAPHICS
                )
                temperature = nvml.nvmlDeviceGetTemperature(
                    handle, nvml.NVML_TEMPERATURE_GPU
                )
            except Exception:
                continue
            samples.append(
                GpuSample(
                    identifier=identifier,
                    vendor="NVIDIA",
                    name=name or f"NVIDIA GPU {index + 1}",
                    utilization=MetricReading.number(
                        getattr(utilization, "gpu", None), minimum=0, maximum=100
                    ),
                    frequency_mhz=MetricReading.number(clock, minimum=0),
                    vram_used_bytes=MetricReading.number(
                        getattr(memory, "used", None), minimum=0
                    ),
                    vram_total_bytes=MetricReading.number(
                        getattr(memory, "total", None), minimum=1
                    ),
                    temperature_c=MetricReading.number(
                        temperature, minimum=-50, maximum=150
                    ),
                    source=self.name,
                )
            )
        return samples

    def _load(self) -> object:
        if self._nvml is None:
            import pynvml

            self._nvml = pynvml
        if not self._initialized:
            self._nvml.nvmlInit()
            self._initialized = True
        return self._nvml

    def close(self) -> None:
        if self._initialized and self._nvml is not None:
            try:
                self._nvml.nvmlShutdown()
            except Exception:
                pass
        self._initialized = False


class LibreHardwareMonitorGpuProvider:
    name = "LibreHardwareMonitor"
    priority = 20

    def __init__(self, computer_factory: Callable[[], object] | None = None) -> None:
        self._computer_factory = computer_factory
        self._computer: object | None = None

    def sample(self) -> Sequence[GpuSample]:
        computer = self._get_computer()
        result: list[GpuSample] = []
        for hardware in tuple(getattr(computer, "Hardware", ())):
            kind = str(getattr(hardware, "HardwareType", ""))
            vendor = _vendor_from_hardware(kind, str(getattr(hardware, "Name", "")))
            if vendor is None:
                continue
            self._update_hardware(hardware)
            sensors = list(getattr(hardware, "Sensors", ()))
            for child in tuple(getattr(hardware, "SubHardware", ())):
                self._update_hardware(child)
                sensors.extend(getattr(child, "Sensors", ()))
            result.append(self._map_device(hardware, sensors, vendor, len(result)))
        return result

    def _get_computer(self) -> object:
        if self._computer is not None:
            return self._computer
        if self._computer_factory is not None:
            computer = self._computer_factory()
        else:
            if os.name != "nt":
                raise RuntimeError("LibreHardwareMonitor is only available on Windows.")
            from HardwareMonitor.Hardware import Computer

            computer = Computer()
        computer.IsGpuEnabled = True
        computer.Open()
        self._computer = computer
        return computer

    @staticmethod
    def _update_hardware(hardware: object) -> None:
        try:
            hardware.Update()
        except Exception:
            pass

    def _map_device(
        self,
        hardware: object,
        sensors: Sequence[object],
        vendor: str,
        index: int,
    ) -> GpuSample:
        readings: dict[str, MetricReading] = {}
        for sensor in sensors:
            sensor_name = str(getattr(sensor, "Name", "")).casefold()
            sensor_type = str(getattr(sensor, "SensorType", "")).casefold()
            value = getattr(sensor, "Value", None)
            if "load" in sensor_type and (
                "gpu core" in sensor_name
                or sensor_name in {"gpu", "d3d 3d"}
                or "gpu total" in sensor_name
            ):
                readings.setdefault(
                    "utilization",
                    MetricReading.number(value, minimum=0, maximum=100),
                )
            elif "clock" in sensor_type and "gpu core" in sensor_name:
                readings.setdefault(
                    "frequency", MetricReading.number(value, minimum=0)
                )
            elif "temperature" in sensor_type and (
                "gpu core" in sensor_name
                or sensor_name in {"gpu", "gpu temperature"}
            ):
                readings.setdefault(
                    "temperature",
                    MetricReading.number(value, minimum=-50, maximum=150),
                )
            elif _is_vram_used(sensor_type, sensor_name):
                readings.setdefault(
                    "vram_used",
                    MetricReading.number(_memory_to_bytes(value, sensor_type), minimum=0),
                )
            elif _is_vram_total(sensor_type, sensor_name):
                readings.setdefault(
                    "vram_total",
                    MetricReading.number(_memory_to_bytes(value, sensor_type), minimum=1),
                )
        name = str(getattr(hardware, "Name", "")).strip() or f"{vendor} GPU {index + 1}"
        identifier = str(getattr(hardware, "Identifier", "")).strip()
        return GpuSample(
            identifier=identifier or f"{vendor.casefold()}:{index}:{_slug(name)}",
            vendor=vendor,
            name=name,
            utilization=readings.get("utilization", MetricReading()),
            frequency_mhz=readings.get("frequency", MetricReading()),
            vram_used_bytes=readings.get("vram_used", MetricReading()),
            vram_total_bytes=readings.get("vram_total", MetricReading()),
            temperature_c=readings.get("temperature", MetricReading()),
            source=self.name,
        )

    def close(self) -> None:
        computer, self._computer = self._computer, None
        if computer is not None:
            try:
                computer.Close()
            except Exception:
                pass


class GpuRegistry:
    def __init__(self, providers: Sequence[GpuProvider] | None = None) -> None:
        self.providers = list(
            providers
            if providers is not None
            else (NvmlGpuProvider(), LibreHardwareMonitorGpuProvider())
        )

    def sample(self) -> tuple[GpuSample, ...]:
        devices: list[tuple[int, GpuSample]] = []
        for provider in sorted(self.providers, key=lambda item: item.priority):
            try:
                provider_samples = provider.sample()
            except Exception:
                continue
            for sample in provider_samples:
                self._merge(devices, provider.priority, sample)
        devices.sort(key=lambda item: (_vendor_order(item[1].vendor), item[1].name.casefold()))
        return tuple(sample for _, sample in devices)

    @staticmethod
    def _merge(
        devices: list[tuple[int, GpuSample]], priority: int, incoming: GpuSample
    ) -> None:
        for index, (current_priority, current) in enumerate(devices):
            if not _same_gpu(current, incoming):
                continue
            if priority < current_priority:
                devices[index] = (priority, _fill_missing(incoming, current))
            else:
                devices[index] = (
                    current_priority,
                    _fill_missing(current, incoming),
                )
            return
        devices.append((priority, incoming))

    def close(self) -> None:
        for provider in self.providers:
            try:
                provider.close()
            except Exception:
                pass


class HardwareCollector:
    def __init__(
        self,
        callback: Callable[[HardwareSnapshot], None],
        *,
        process_source: Callable[[], OwnedProcessIdentity | None],
        cpu_provider: CpuProvider | None = None,
        gpu_registry: GpuRegistry | None = None,
        interval_seconds: float = 1.0,
        stale_after_seconds: float = 3.0,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self.callback = callback
        self.process_source = process_source
        self.cpu_provider = cpu_provider or PsutilCpuProvider()
        self.gpu_registry = gpu_registry or GpuRegistry()
        self.interval_seconds = max(0.01, interval_seconds)
        self.stale_after_seconds = max(self.interval_seconds, stale_after_seconds)
        self._monotonic = monotonic
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stopping = threading.Event()
        self._visible = False
        self._immediate = False
        self._thread: threading.Thread | None = None

    @property
    def is_running(self) -> bool:
        with self._lock:
            return self._thread is not None and self._thread.is_alive()

    def resume(self) -> None:
        with self._lock:
            self._visible = True
            self._immediate = True
            if self._thread is None or not self._thread.is_alive():
                self._stopping.clear()
                self._thread = threading.Thread(
                    target=self._run,
                    name="hardware-telemetry",
                    daemon=True,
                )
                self._thread.start()
        self._wake.set()

    def request_sample(self) -> None:
        with self._lock:
            if not self._visible:
                return
            self._immediate = True
        self._wake.set()

    def suspend(self) -> None:
        with self._lock:
            self._visible = False
        self._wake.set()

    def stop(self, *, timeout_seconds: float = 0.5) -> None:
        self._stopping.set()
        self._wake.set()
        with self._lock:
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=max(0.0, timeout_seconds))
        close_cpu = getattr(self.cpu_provider, "close", None)
        if callable(close_cpu):
            try:
                close_cpu()
            except Exception:
                pass
        self.gpu_registry.close()

    def collect_once(self) -> HardwareSnapshot:
        started = self._monotonic()
        try:
            process = self.process_source()
        except Exception:
            process = None
        try:
            cpu = self.cpu_provider.sample(process)
        except Exception:
            cpu = CpuSample()
        gpus = self.gpu_registry.sample()
        finished = self._monotonic()
        snapshot = HardwareSnapshot(finished, cpu, gpus)
        if finished - started > self.stale_after_seconds:
            return snapshot.stale()
        return snapshot

    def _run(self) -> None:
        next_poll = self._monotonic()
        while not self._stopping.is_set():
            with self._lock:
                visible = self._visible
                immediate = self._immediate
                self._immediate = False
            if not visible:
                self._wake.wait()
                self._wake.clear()
                next_poll = self._monotonic()
                continue
            now = self._monotonic()
            if not immediate and now < next_poll:
                self._wake.wait(next_poll - now)
                self._wake.clear()
                continue
            snapshot = self.collect_once()
            if not self._stopping.is_set():
                self.callback(snapshot)
            next_poll = self._monotonic() + self.interval_seconds


def format_hardware_percent(reading: MetricReading) -> str:
    if reading.state is not Availability.AVAILABLE or reading.value is None:
        return "—"
    return f"{reading.value:.0f}%"


def format_frequency(reading: MetricReading) -> str:
    if reading.state is not Availability.AVAILABLE or reading.value is None:
        return "Unavailable"
    if reading.value >= 1000:
        return f"{reading.value / 1000:.2f} GHz"
    return f"{reading.value:.0f} MHz"


def format_temperature(reading: MetricReading) -> str:
    if reading.state is not Availability.AVAILABLE or reading.value is None:
        return "Unavailable"
    return f"{reading.value:.0f} °C"


def format_vram(used: MetricReading, total: MetricReading) -> str:
    if (
        used.state is not Availability.AVAILABLE
        or total.state is not Availability.AVAILABLE
        or used.value is None
        or total.value is None
    ):
        return "Unavailable"
    gib = 1024**3
    return f"{used.value / gib:.1f} / {total.value / gib:.1f} GiB"


def _fill_missing(primary: GpuSample, fallback: GpuSample) -> GpuSample:
    def choose(first: MetricReading, second: MetricReading) -> MetricReading:
        return first if first.state is Availability.AVAILABLE else second

    return replace(
        primary,
        utilization=choose(primary.utilization, fallback.utilization),
        frequency_mhz=choose(primary.frequency_mhz, fallback.frequency_mhz),
        vram_used_bytes=choose(primary.vram_used_bytes, fallback.vram_used_bytes),
        vram_total_bytes=choose(primary.vram_total_bytes, fallback.vram_total_bytes),
        temperature_c=choose(primary.temperature_c, fallback.temperature_c),
        source="+".join(dict.fromkeys(filter(None, (primary.source, fallback.source)))),
    )


def _same_gpu(left: GpuSample, right: GpuSample) -> bool:
    if left.identifier and right.identifier and left.identifier.casefold() == right.identifier.casefold():
        return True
    return (
        left.vendor.casefold() == right.vendor.casefold()
        and _gpu_name_key(left.name, left.vendor)
        == _gpu_name_key(right.name, right.vendor)
    )


def _vendor_from_hardware(kind: str, name: str) -> str | None:
    combined = f"{kind} {name}".casefold()
    if "nvidia" in combined:
        return "NVIDIA"
    if "amd" in combined or "ati" in combined:
        return "AMD"
    if "intel" in combined:
        return "Intel"
    return None


def _is_vram_used(sensor_type: str, name: str) -> bool:
    return (
        ("smalldata" in sensor_type or "data" in sensor_type)
        and "memory" in name
        and ("used" in name or "dedicated" in name)
        and "total" not in name
        and "available" not in name
    )


def _is_vram_total(sensor_type: str, name: str) -> bool:
    return (
        ("smalldata" in sensor_type or "data" in sensor_type)
        and "memory" in name
        and "total" in name
    )


def _memory_to_bytes(value: object, sensor_type: str) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    # LibreHardwareMonitor SmallData GPU memory values are expressed in MiB.
    return number * 1024**2 if "smalldata" in sensor_type else number


def _decode(value: object) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value or "")


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _gpu_name_key(name: str, vendor: str) -> str:
    value = name.casefold()
    for token in (vendor.casefold(), "geforce", "graphics", "gpu"):
        value = value.replace(token, " ")
    return _slug(value)


def _vendor_order(vendor: str) -> int:
    return {"NVIDIA": 0, "AMD": 1, "Intel": 2}.get(vendor, 99)
