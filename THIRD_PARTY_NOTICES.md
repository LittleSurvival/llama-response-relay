# Third-party notices

The packaged Llama.cpp Launcher includes the following runtime components for hardware monitoring:

- **psutil** — BSD 3-Clause License.
- **nvidia-ml-py** — BSD License. This is a Python binding for NVIDIA's driver-provided NVML API; NVIDIA drivers and NVML are not redistributed by this project.
- **HardwareMonitor / PyHardwareMonitor** — BSD 3-Clause License, Copyright © 2022 Nicholas Feix.
- **LibreHardwareMonitorLib** and the assemblies distributed with HardwareMonitor — Mozilla Public License 2.0 and the licenses included by the upstream package.
- **pythonnet** and **clr-loader** — MIT License.

The complete LibreHardwareMonitor MPL 2.0 license text is preserved in the bundled `HardwareMonitor/lib/LICENSE` package data. Source code and license details for these components are available from their respective upstream projects and installed Python package metadata.

No third-party hardware driver is installed by Llama.cpp Launcher. Vendor APIs, drivers, permissions, and individual sensors can therefore be unavailable on a given machine; the application treats that condition as partial telemetry rather than a startup failure.
