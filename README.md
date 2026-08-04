# arduino-router-ros

ROS 2 package providing the `arduino_proxy` node to bridge RPC communication between an embedded Arduino microcontroller (MCU) and the Linux MPU environment.

---

## Architecture Overview

* **MCU side (Arduino):** Runs firmware built with the standalone Arduino RPC library.
* **MPU side (Linux):** Runs the `arduino_proxy` node in this package to expose MCU RPC interfaces as ROS 2 topics and services.

---

## Prerequisites

### Flash the MCU (Arduino side)
Before running the ROS proxy, ensure your UnoQ MCU is running the RPC sketch:
1. Install the `Arduino_RouterBridge_ROS` library in Arduino IDE / Arduino CLI.
2. Flash your sketch to the board's MCU.

### Python dependencies
Before building, install the required Arduino Python utilities on your Linux MPU environment:

```bash
pip install watchdog numpy
pip install git+https://github.com/arduino/app-bricks-py.git --break-system-packages --ignore-requires-python
```
use with `--ignore-requires-python` only if python is < 3.13

## Build Instructions
Navigate to your ROS 2 workspace source directory:

```bash
cd ~/ros2_ws/src
```
Clone this repository:
```bash
git clone https://github.com/arduino/arduino-router-ros.git
```
Install standard ROS dependencies:

```bash
cd ~/ros2_ws
rosdep install --from-paths src --ignore-src -r -y
```
Build the package using colcon (make sure the ros2_venv is active):
```bash
colcon build --packages-select arduino_router_ros
```

## How to Run
Source the workspace setup script:
```bash
source ~/ros2_ws/install/setup.bash
```

Launch the proxy node:
```bash
ros2 run arduino_router_ros arduino_proxy
```

## How to Build your lib
build_lib can convert ROS2 .msg files to C++ headers for [Arduino_RouterBridge_ROS](https://github.com/arduino-libraries/Arduino_RouterBridge_ROS)

run the cli help for more information
```bash
ros2 run arduino_router_ros build_lib -h
```