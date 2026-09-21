from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
import threading
import time

import pytest

from llamacpp_launcher.hardware import (
    CpuSample,
    GpuRegistry,
    GpuSample,
    HardwareCollector,
    LibreHardwareMonitorGpuProvider,
    MetricReading,
    NvmlGpuProvider,
    PsutilCpuProvider,
    WindowsPdhCpuFrequencyProvider,
)
from llamacpp_launcher.process import OwnedProcessIdentity
from llamacpp_launcher.telemetry import Availability


class FakePsutilProcess:
    def __init__(self, pid: int, values: list[float], create_time: float = 12.0) -> None:
        self.pid = pid
        self.values = iter(values)
        self.created = create_time

    def cpu_percent(self, interval=None) -> float:
        del interval
        return next(self.values)

    def create_time(self) -> float:
        return self.created


class FakePsutil:
    def __init__(self) -> None:
        self.process = FakePsutilProcess(44, [0.0, 160.0, 320.0])
        self.frequency = SimpleNamespace(current=4200.0)

    def cpu_count(self, logical=True) -> int:
        assert logical
        return 8

    def cpu_percent(self, interval=None) -> float:
        del interval
        return 62.5

    def cpu_freq(self):
        return self.frequency

    def Process(self, pid: int) -> FakePsutilProcess:
        assert pid == 44
        return self.process


def reading(value: float | None) -> MetricReading:
    return MetricReading.number(value, minimum=0)


class FakeFrequencyProvider:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)
        self.nominal_values: list[float | None] = []
        self.closed = False

    def sample(self, nominal_mhz: float | None) -> MetricReading:
        self.nominal_values.append(nominal_mhz)
        return MetricReading.number(next(self.values), minimum=1)

    def close(self) -> None:
        self.closed = True


def gpu(
    identifier: str,
    vendor: str,
    name: str,
    *,
    utilization: float | None = None,
    clock: float | None = None,
    used: float | None = None,
    total: float | None = None,
    temperature: float | None = None,
    source: str = "",
) -> GpuSample:
    return GpuSample(
        identifier,
        vendor,
        name,
        MetricReading.number(utilization, minimum=0, maximum=100),
        reading(clock),
        reading(used),
        reading(total),
        MetricReading.number(temperature, minimum=-50, maximum=150),
        source,
    )


def test_metric_reading_and_vram_validation() -> None:
    assert MetricReading.number(float("nan")).state is Availability.UNAVAILABLE
    assert MetricReading.number(-1, minimum=0).value is None
    sample = gpu("a", "AMD", "Card", used=4, total=8)
    assert sample.vram_utilization.value == 50
    invalid = gpu("b", "Intel", "Card", used=9, total=8)
    assert invalid.vram_utilization.state is Availability.UNAVAILABLE


def test_psutil_cpu_provider_normalizes_process_and_rejects_pid_reuse() -> None:
    module = FakePsutil()
    frequency = FakeFrequencyProvider([3600, 4250, 3100, 2900])
    provider = PsutilCpuProvider(module, frequency_provider=frequency)
    identity = OwnedProcessIdentity(pid=44, generation=2)
    first = provider.sample(identity)
    assert first.utilization.value == 62.5
    assert first.frequency_mhz.value == 3600
    assert first.process_utilization.value is None
    second = provider.sample(identity)
    assert second.frequency_mhz.value == 4250
    assert second.process_utilization.value == 20
    module.process.created = 99
    reused = provider.sample(identity)
    assert reused.process_utilization.state is Availability.UNAVAILABLE
    stopped = provider.sample(None)
    assert stopped.process_utilization.state is Availability.UNAVAILABLE
    provider.close()
    assert frequency.closed
    assert frequency.nominal_values == [4200, 4200, 4200, 4200]


class FakePdhApi:
    def __init__(self, values: list[float]) -> None:
        self.values = iter(values)
        self.opened = 0
        self.collected = 0
        self.closed = False

    def open(self) -> bool:
        self.opened += 1
        return True

    def collect(self) -> bool:
        self.collected += 1
        return True

    def read(self) -> float:
        return next(self.values)

    def close(self) -> None:
        self.closed = True


def test_windows_dynamic_frequency_uses_consecutive_performance_samples() -> None:
    api = FakePdhApi([75, 125])
    provider = WindowsPdhCpuFrequencyProvider(api)
    assert provider.sample(4000).state is Availability.UNAVAILABLE
    assert provider.sample(4000).value == 3000
    assert provider.sample(4000).value == 5000
    assert provider.sample(None).state is Availability.UNAVAILABLE
    assert api.opened == 1
    assert api.collected == 3
    provider.close()
    assert api.closed


class FakeNvml:
    NVML_CLOCK_GRAPHICS = 0
    NVML_TEMPERATURE_GPU = 0

    def nvmlInit(self) -> None:
        pass

    def nvmlShutdown(self) -> None:
        pass

    def nvmlDeviceGetCount(self) -> int:
        return 1

    def nvmlDeviceGetHandleByIndex(self, index: int) -> int:
        return index

    def nvmlDeviceGetName(self, _handle: int) -> bytes:
        return b"NVIDIA GeForce RTX 4090"

    def nvmlDeviceGetUUID(self, _handle: int) -> bytes:
        return b"GPU-4090"

    def nvmlDeviceGetUtilizationRates(self, _handle: int):
        return SimpleNamespace(gpu=88)

    def nvmlDeviceGetMemoryInfo(self, _handle: int):
        return SimpleNamespace(used=8 * 1024**3, total=24 * 1024**3)

    def nvmlDeviceGetClockInfo(self, _handle: int, _kind: int) -> int:
        return 2715

    def nvmlDeviceGetTemperature(self, _handle: int, _kind: int) -> int:
        return 67


def test_nvml_adapter_maps_all_fields() -> None:
    provider = NvmlGpuProvider(FakeNvml())
    result = provider.sample()
    assert len(result) == 1
    assert result[0].vendor == "NVIDIA"
    assert result[0].utilization.value == 88
    assert result[0].frequency_mhz.value == 2715
    assert result[0].vram_utilization.value == pytest.approx(100 / 3)
    assert result[0].temperature_c.value == 67


@dataclass
class FakeSensor:
    Name: str
    SensorType: str
    Value: float


class FakeHardware:
    def __init__(self, kind: str, name: str, identifier: str) -> None:
        self.HardwareType = kind
        self.Name = name
        self.Identifier = identifier
        self.SubHardware = ()
        self.Sensors = (
            FakeSensor("GPU Core", "Load", 71),
            FakeSensor("GPU Core", "Clock", 2450),
            FakeSensor("GPU Core", "Temperature", 61),
            FakeSensor("GPU Memory Used", "SmallData", 4096),
            FakeSensor("GPU Memory Total", "SmallData", 8192),
        )

    def Update(self) -> None:
        pass


class FakeComputer:
    def __init__(self) -> None:
        self.IsGpuEnabled = False
        self.Hardware = (
            FakeHardware("GpuAmd", "AMD Radeon RX 7900 XTX", "/gpu-amd/0"),
            FakeHardware("GpuIntel", "Intel Arc A770", "/gpu-intel/0"),
        )
        self.opened = False
        self.closed = False

    def Open(self) -> None:
        self.opened = True

    def Close(self) -> None:
        self.closed = True


def test_libre_adapter_maps_amd_intel_and_closes() -> None:
    computer = FakeComputer()
    provider = LibreHardwareMonitorGpuProvider(lambda: computer)
    result = provider.sample()
    assert [item.vendor for item in result] == ["AMD", "Intel"]
    assert result[0].utilization.value == 71
    assert result[0].vram_used_bytes.value == 4096 * 1024**2
    assert result[1].temperature_c.value == 61
    provider.close()
    assert computer.closed


class StaticProvider:
    def __init__(
        self, name: str, priority: int, samples: list[GpuSample] | Exception
    ) -> None:
        self.name = name
        self.priority = priority
        self.samples = samples
        self.closed = False

    def sample(self):
        if isinstance(self.samples, Exception):
            raise self.samples
        return self.samples

    def close(self) -> None:
        self.closed = True


def test_registry_deduplicates_fills_fields_and_isolates_provider_error() -> None:
    preferred = StaticProvider(
        "native",
        10,
        [gpu("uuid", "NVIDIA", "NVIDIA GeForce RTX 4090", utilization=90, source="native")],
    )
    fallback = StaticProvider(
        "lhm",
        20,
        [
            gpu(
                "/gpu/0",
                "NVIDIA",
                "NVIDIA RTX 4090",
                clock=2500,
                temperature=60,
                source="lhm",
            ),
            gpu("intel", "Intel", "Intel Arc A770", utilization=50),
        ],
    )
    failing = StaticProvider("broken", 30, RuntimeError("driver reset"))
    registry = GpuRegistry([failing, fallback, preferred])
    result = registry.sample()
    assert len(result) == 2
    assert result[0].utilization.value == 90
    assert result[0].frequency_mhz.value == 2500
    assert result[0].temperature_c.value == 60
    assert result[1].vendor == "Intel"


class SequenceCpuProvider:
    def __init__(self) -> None:
        self.calls = 0

    def sample(self, _process) -> CpuSample:
        self.calls += 1
        return CpuSample(utilization=MetricReading.number(self.calls))


def test_collector_refreshes_suspends_resumes_and_stops_without_overlap() -> None:
    cpu = SequenceCpuProvider()
    registry = GpuRegistry([])
    snapshots = []
    received = threading.Event()

    def callback(snapshot) -> None:
        snapshots.append(snapshot)
        if len(snapshots) >= 2:
            received.set()

    collector = HardwareCollector(
        callback,
        process_source=lambda: None,
        cpu_provider=cpu,
        gpu_registry=registry,
        interval_seconds=0.02,
        stale_after_seconds=0.06,
    )
    collector.resume()
    assert received.wait(1)
    collector.suspend()
    paused_at = cpu.calls
    time.sleep(0.06)
    assert cpu.calls == paused_at
    collector.resume()
    deadline = time.monotonic() + 1
    while cpu.calls == paused_at and time.monotonic() < deadline:
        time.sleep(0.005)
    assert cpu.calls > paused_at
    collector.stop(timeout_seconds=0.5)
    assert not collector.is_running


def test_collector_marks_slow_snapshot_stale_and_keeps_partial_data() -> None:
    class SlowCpu:
        def sample(self, _process) -> CpuSample:
            time.sleep(0.02)
            return CpuSample(utilization=MetricReading.number(10))

    collector = HardwareCollector(
        lambda _snapshot: None,
        process_source=lambda: None,
        cpu_provider=SlowCpu(),
        gpu_registry=GpuRegistry([]),
        interval_seconds=0.005,
        stale_after_seconds=0.01,
    )
    snapshot = collector.collect_once()
    assert snapshot.state is Availability.STALE
    assert snapshot.cpu.utilization.state is Availability.STALE
