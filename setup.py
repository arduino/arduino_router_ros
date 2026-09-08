import os
from glob import glob
from setuptools import find_packages, setup

package_name = 'arduino_router_ros'

setup(
    name=package_name,
    version='0.0.1',
    packages=find_packages(exclude=['test']),
    data_files=[
        ('share/ament_index/resource_index/packages',
            ['resource/' + package_name]),
        ('share/' + package_name, ['package.xml']),
    ],
    install_requires=[
        'setuptools',
        'msgpack',
        'watchdog',
        'numpy',
        'arduino-router-bridge',
    ],
    zip_safe=True,
    maintainer='arduino',
    maintainer_email='l.rossi@arduino.cc',
    description='ROS2 proxy bridge for Arduino Q boards',
    license='MPL-2.0',
    tests_require=['pytest'],
    entry_points={
        'console_scripts': [
            'arduino_proxy = arduino_router_ros.arduino_proxy:main',
            'build_lib = arduino_router_ros.library_builder:main',
        ],
    },
)