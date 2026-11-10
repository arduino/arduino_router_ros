#!/usr/bin/env python3

# Copyright (c) Arduino s.r.l. and/or its affiliated companies
# SPDX-License-Identifier: MPL-2.0

"""
ROS2 Message to MsgPack Header Generator
Converts ROS2 .msg files into C++ header files with msgpack serialization support.
"""

import os
import sys
import argparse
import re
import zipfile
from pathlib import Path
from typing import List, Tuple, Dict, Optional


class MsgParser:
    """Parses ROS2 .msg files"""

    # Mapping from ROS2 types to C++ types
    ROS2_TO_CPP_TYPES = {
        'bool': 'bool',
        'byte': 'byte',
        'int8': 'int8_t',
        'uint8': 'uint8_t',
        'int16': 'int16_t',
        'uint16': 'uint16_t',
        'int32': 'int32_t',
        'uint32': 'uint32_t',
        'int64': 'int64_t',
        'uint64': 'uint64_t',
        'float32': 'float',
        'float64': 'double',
        'string': 'MsgPack::str_t',
        'char': 'char',
        'time': 'builtin_interfaces::msg::Time',
        'duration': 'builtin_interfaces::msg::Duration',
    }

    def __init__(self):
        self.fields: List[Tuple[str, str, str]] = []  # (name, type, cpp_type)
        self.imports: set = set()
        self.package: str = ""
        self.message_name: str = ""

    def parse_msg_file(self, filepath: str, package_name: str) -> bool:
        """
        Parse a .msg file
        Returns True if successful
        """
        try:
            with open(filepath, 'r') as f:
                lines = f.readlines()

            self.package = package_name
            self.message_name = Path(filepath).stem

            for line in lines:
                # Strip comments and whitespace
                line = line.split('#')[0].strip()
                if not line:
                    continue

                # Parse field definition: "type name" or "package/type name"
                parts = line.split()
                if len(parts) >= 2:
                    field_type = parts[0]
                    field_name = parts[1]

                    cpp_type = self._convert_type(field_type)
                    self.fields.append((field_name, field_type, cpp_type))

            return True
        except Exception as e:
            print(f"Error parsing {filepath}: {e}", file=sys.stderr)
            return False

    def _convert_type(self, ros_type: str) -> str:
        """Convert ROS2 type to C++ type"""

        # Detect array syntax: "type[]", "type[N]", or bounded "type[<=N]"
        array_match = re.match(r'^(.+?)\[(<=)?(\d*)\]$', ros_type)
        if array_match:
            base_type, bounded, size = array_match.groups()
            cpp_base = self._convert_type(base_type)  # recurse on the element type

            if size and not bounded:
                # Fixed-size array, e.g. float64[9] -> std::array<double, 9>
                return f"std::array<{cpp_base}, {size}>"
            else:
                # Unbounded ([]) or bounded ([<=N]) -> std::vector
                return f"std::vector<{cpp_base}>"

        # Handle built-in types
        if ros_type in self.ROS2_TO_CPP_TYPES:
            return self.ROS2_TO_CPP_TYPES[ros_type]

        # Handle package/type references (e.g., "builtin_interfaces/Time")
        if '/' in ros_type:
            parts = ros_type.split('/')
            package = parts[0]
            msg_type = parts[1]
            self.imports.add(ros_type)
            return f"{package}::msg::{msg_type}"

        # Try to import locally
        self.imports.add(ros_type)

        # Default fallback
        return ros_type


class HeaderGenerator:
    """Generates C++ msgpack header files"""

    # Mozilla Public License header
    LICENSE_HEADER = """/*
    This file is part of the ROS_RouterBridge library.

    Copyright (c) Arduino s.r.l. and/or its affiliated companies

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.

*/
"""

    def __init__(self, parser: MsgParser):
        self.parser = parser

    def generate(self) -> str:
        """Generate the complete header file content"""
        output = []

        # License header
        output.append(self.LICENSE_HEADER)

        # Include guards
        guard = f"ROS2BRIDGE_{self.parser.package.upper()}_{self.parser.message_name.upper()}_H"
        output.append(f"#ifndef {guard}")
        output.append(f"#define {guard}")

        # Standard includes
        output.append("#include <MsgPack.h>")
        output.append("")

        # Add includes for imported types
        for import_str in sorted(self.parser.imports):
            if '/' in import_str:
                output.append(f'#include "../{import_str}.h"')
            else:
                output.append(f'#include "{import_str}.h"')

        if self.parser.imports:
            output.append("")

        # Define the type string constant
        type_str = f"{self.parser.package}/msg/{self.parser.message_name}"
        output.append(f'#define ROS2BRIDGE_{self.parser.package.upper()}_{self.parser.message_name.upper()} "{type_str}"')
        output.append("")

        # Namespace and struct
        output.append(f"namespace {self.parser.package} {{")
        output.append("")
        output.append("namespace msg {")
        output.append("")
        output.append(f"    struct {self.parser.message_name} {{")
        output.append(f'        static constexpr const char* _type = ROS2BRIDGE_{self.parser.package.upper()}_{self.parser.message_name.upper()};')
        output.append("")

        # Member variables with keys
        keys = []
        members = []
        for i, (field_name, ros_type, cpp_type) in enumerate(self.parser.fields):
            key_var = f"key{i + 1 if len(self.parser.fields) > 1 else ''}"
            keys.append(key_var)
            output.append(f'        MsgPack::str_t {key_var} = "{field_name.split("=")[0]}";')
            output.append(f"        {cpp_type} {field_name}{'{}' if 'array' in cpp_type else ''};")
            output.append("")
            members.append(field_name)

        # Default constructor
        output.append(f"        {self.parser.message_name}() = default;")
        output.append("")

        # Parameterized constructor (if there are fields)
        if self.parser.fields:
            params = ", ".join([f"{cpp_type} {name.lower().split("=")[0]}" for name, _, cpp_type in self.parser.fields])
            init_list = ", ".join([f"{name.split("=")[0]}({name.lower().split("=")[0]})" for name, _, _ in self.parser.fields])
            output.append(f"        {self.parser.message_name}({params}): {init_list} {{}}")
            output.append("")

        # MSGPACK_DEFINE_MAP macro
        msgpack_args = []
        for key_var, (name, _, _) in zip(keys, self.parser.fields):
            msgpack_args.extend([key_var, name.split("=")[0]])
        msgpack_args_str = ", ".join(msgpack_args)
        output.append(f"        MSGPACK_DEFINE_MAP({msgpack_args_str});")
        output.append("")

        # Equality operator
        comparisons = " && ".join([f"this->{name.split("=")[0]} == other.{name.split("=")[0]}" for name, _, _ in self.parser.fields])
        output.append(f"        bool operator==(const {self.parser.message_name}& other) const {{ return {comparisons}; }}")

        output.append("    };")
        output.append("")
        output.append("} // namespace msg")
        output.append("")
        output.append(f"}} // namespace {self.parser.package}")
        output.append(f"#endif //ROS2BRIDGE_{self.parser.package.upper()}_{self.parser.message_name.upper()}_H")

        return "\n".join(output)


class MessageLibraryGenerator:
    """Main generator for ROS2 message library"""

    def __init__(self, msg_dir: str, output_dir: str):
        self.msg_dir = Path(msg_dir)
        self.output_dir = Path(output_dir)

    def generate_from_package(self, package_name: str) -> bool:
        """Generate headers for all .msg files in a package directory"""
        package_dir = self.msg_dir / package_name / "msg"

        if not package_dir.exists():
            print(f"Error: Package directory not found: {package_dir}", file=sys.stderr)
            return False

        msg_files = list(package_dir.glob("*.msg"))
        if not msg_files:
            print(f"Warning: No .msg files found in {package_dir}")
            return True

        # Create output directory structure
        output_package_dir = self.output_dir / package_name
        output_package_dir.mkdir(parents=True, exist_ok=True)

        success = True
        for msg_file in msg_files:
            if not self._generate_single_file(msg_file, package_name, output_package_dir):
                success = False

        return success

    def pack_package(self, package_name: str, zip_path: str) -> bool:
        """Pack the headers generated from a package into a ZIP archive."""
        package_dir = self.msg_dir / package_name / "msg"
        try:
            with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                for msg_file in sorted(package_dir.glob("*.msg")):
                    header = self.output_dir / package_name / f"{msg_file.stem}.h"
                    archive.write(header, arcname=f"{package_name}/{header.name}")
            print(f"Created archive: {zip_path}")
            return True
        except (OSError, zipfile.BadZipFile) as e:
            print(f"Error creating archive {zip_path}: {e}", file=sys.stderr)
            return False

    def _generate_single_file(self, msg_file: Path, package_name: str, output_dir: Path) -> bool:
        """Generate header for a single .msg file"""
        parser = MsgParser()

        if not parser.parse_msg_file(str(msg_file), package_name):
            return False

        generator = HeaderGenerator(parser)
        header_content = generator.generate()

        output_file = output_dir / f"{parser.message_name}.h"

        try:
            with open(output_file, 'w') as f:
                f.write(header_content)
            print(f"Generated: {output_file}")
            return True
        except Exception as e:
            print(f"Error writing {output_file}: {e}", file=sys.stderr)
            return False


def main():
    parser = argparse.ArgumentParser(
        description="Convert ROS2 .msg files to MsgPack-serializable C++ headers for Arduino"
    )
    parser.add_argument(
        "-p", "--package",
        required=True,
        help="ROS2 package name (e.g., std_msgs, sensor_msgs)"
    )
    parser.add_argument(
        "-m", "--msg-dir",
        default=".",
        help="Directory containing ROS2 packages with msg/ subdirectories (default: current directory)"
    )
    parser.add_argument(
        "-o", "--output",
        default="./generated",
        help="Output directory for generated headers (default: ./generated)"
    )
    parser.add_argument(
        "--zip",
        metavar="PATH",
        help="Also pack generated headers into a ZIP archive at PATH"
    )

    args = parser.parse_args()

    generator = MessageLibraryGenerator(args.msg_dir, args.output)

    if generator.generate_from_package(args.package):
        if args.zip and not generator.pack_package(args.package, args.zip):
            return 1
        print(f"✓ Successfully generated headers for package '{args.package}'")
        return 0
    else:
        print(f"✗ Failed to generate headers for package '{args.package}'", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())