#!/usr/bin/env python3

# Copyright (c) Arduino s.r.l. and/or its affiliated companies
# SPDX-License-Identifier: MPL-2.0

import threading
import array
import rclpy
import importlib

from msgpack import Timestamp

from rclpy.node import Node
from builtin_interfaces.msg._time import Time
from arduino.router_bridge import Bridge


class ArduinoProxy:
    def __init__(self, default_node_name="arduino_proxy"):
        rclpy.init()
        self.node = Node(default_node_name)

        self.bridge = Bridge()
        if not self.bridge.connect(timeout=5):
            raise RuntimeError('Failed to connect to arduino-router.service')

        # Bridge endpoints
        self.bridge.provide("ros2/node_reg", self.register_node)
        self.bridge.provide("ros2/reg", self.register_topic)
        self.bridge.provide("ros2/sub", self.subscribe)
        self.bridge.provide("ros2/pub", self.publish)
        self.bridge.provide("ros2/time", self.get_time)

        self.publishers = {}
        self.publishers_id_counter = 0

        # Start ROS 2 spinning in a background thread
        self.ros_thread = threading.Thread(target=self._ros_thread_entry, daemon=True)
        self.ros_thread.start()

    def _ros_thread_entry(self):
        """Background thread to handle ROS 2 middleware processing."""
        rclpy.spin(self.node)

    def _import_msg_type(self, type_str: str):
        """
        Dynamically imports a message type.
        Expects format: "std_msgs/msg/String" or "std_msgs/String"
        """

        type_str = type_str.replace('/msg/', '/')
        try:
            parts = type_str.split('/')
            module_path = f"{parts[0]}.msg"
            class_name = parts[1]
            module = importlib.import_module(module_path)
            return getattr(module, class_name)
        except Exception as e:
            self.node.get_logger().error(f"Failed to import {type_str}: {e}")
            return None

    def get_time(self) -> Timestamp:
        """
        Returns the current ROS 2 time as msgpack timestamp extension.
        :return:
        """

        time = self.node.get_clock().now()
        seconds, nanoseconds = time.seconds_nanoseconds()
        return Timestamp(seconds, nanoseconds)

    def register_node(self, node_name: str) -> bool:
        """
        In ROS 2, we usually keep one Node, but we can update its
        effective identity or logging prefix.
        """
        self.node.get_logger().info(f"Remote side identified as logical node: {node_name}")
        return True

    def register_topic(self, topic_name: str, topic_type: str, time_mode: str) -> int:
        """
        Registers a topic with a specific type.
        Example topic_type: "std_msgs/msg/Int32"
        """
        MsgClass = self._import_msg_type(topic_type)
        if not MsgClass:
            raise ImportError(f"Failed to import {topic_type}")

        self.publishers_id_counter += 1
        current_id = self.publishers_id_counter

        pub = self.node.create_publisher(MsgClass, topic_name, 10)

        self.publishers[current_id] = {
            "publisher": pub,
            "type": MsgClass,
            "topic": topic_name,
            "time_mode": time_mode
        }

        return current_id
    def subscribe(self, topic_name: str, topic_type: str) -> int:
        """
        Creates a ROS 2 subscription and sets up a bridge callback.
        """
        MsgClass = self._import_msg_type(topic_type)
        if not MsgClass:
            raise ImportError(f"Failed to import {topic_type}")

        self.publishers_id_counter += 1
        sub_id = self.publishers_id_counter

        bridge_method_name = f"{sub_id}{topic_name}"

        def ros_callback(msg):
            msg_dict = self._message_to_dict(msg)
            self.bridge.call(bridge_method_name, msg_dict)

        self.node.create_subscription(
            MsgClass,
            topic_name,
            ros_callback,
            10 # QoS depth
        )

        self.node.get_logger().info(f"Subscribed to {topic_name} [{topic_type}] with ID {sub_id}")

        return sub_id

    def _message_to_dict(self, msg):
        """
        Helper to convert ROS 2 message fields into a dictionary
        that can be serialized via MsgPack.
        """
        d = {}
        for slot in msg.get_fields_and_field_types().keys():
            value = getattr(msg, slot)

            # convert memory-optimized array.array to lists before msgpack serializing
            if isinstance(value, array.array):
                if value.typecode == 'B':
                    d[slot] = value.tobytes()
                else:
                    d[slot] = value.tolist()
            elif hasattr(value, "get_fields_and_field_types"):
                d[slot] = self._message_to_dict(value)

            else:
                d[slot] = value
        return d

    def _dict_to_message(self, MsgClass, data_dict: dict, time_mode: str = ""):
        """
        Recursively converts a nested Python dictionary into an instantiated
        ROS 2 message object, matching nested fields to their required types.
        """
        if data_dict is None:
            return MsgClass()

        fields_and_types = MsgClass.get_fields_and_field_types()

        if MsgClass == Time:
            self.overwrite_time(data_dict, time_mode)

        init_kwargs = {}
        for field_name, value in data_dict.items():
            if field_name not in fields_and_types:
                continue

            if isinstance(value, dict):
                type_str = fields_and_types[field_name]

                # Strip out sequence/array wrappers if any are present in the type string
                if type_str.startswith('sequence<') or type_str.endswith('>'):
                    type_str = type_str.split('<')[-1].split('>')[0]

                SubMsgClass = self._import_msg_type(type_str.replace('::', '/'))
                if SubMsgClass:
                    init_kwargs[field_name] = self._dict_to_message(SubMsgClass, value, time_mode)
            else:
                # Primitive types or lists/arrays (like the covariance matrices) pass directly
                init_kwargs[field_name] = value

        return MsgClass(**init_kwargs)

    def overwrite_time(self, data_dict: dict, time_mode: str) -> None:
        if time_mode not in ["o", "overwrite"]:
            return

        has_sec = "sec" in data_dict
        has_nanosec = "nanosec" in data_dict

        if has_sec or has_nanosec:
            current_time = self.node.get_clock().now()
            seconds, nanoseconds = current_time.seconds_nanoseconds()

            if has_sec:
                data_dict["sec"] = seconds
            if has_nanosec:
                data_dict["nanosec"] = nanoseconds

    def publish(self, id_: int, message_data: dict) -> bool:
        """Uses the ID to find the publisher and send data."""
        pub_info = self.publishers.get(id_)
        if not pub_info:
            return False

        try:
            msg = self._dict_to_message(pub_info["type"], message_data, pub_info["time_mode"])
            pub_info["publisher"].publish(msg)
            return True
        except Exception as e:
            self.node.get_logger().error(f"Publish error on ID {id_}: {e}")
            return False


def main(args=None):
    Proxy = ArduinoProxy()
