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


class RosTypeParser:
    """Parses ROS2 types"""

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

                    cpp_type = self.convert_type(field_type)
                    self.fields.append((field_name, field_type, cpp_type))

            return True
        except Exception as e:
            print(f"Error parsing {filepath}: {e}", file=sys.stderr)
            return False

    def convert_type(self, ros_type: str) -> str:
        """Convert ROS2 type to C++ type"""

        # Detect array syntax: "type[]", "type[N]", or bounded "type[<=N]"
        array_match = re.match(r'^(.+?)\[(<=)?(\d*)\]$', ros_type)
        if array_match:
            base_type, bounded, size = array_match.groups()
            cpp_base = self.convert_type(base_type)  # recurse on the element type

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

# Mozilla Public License header
ARDUINO_LICENSE_HEADER = """/*
    This file is part of the ROS_RouterBridge library.

    Copyright (c) Arduino s.r.l. and/or its affiliated companies

    This Source Code Form is subject to the terms of the Mozilla Public
    License, v. 2.0. If a copy of the MPL was not distributed with this
    file, You can obtain one at http://mozilla.org/MPL/2.0/.

*/
"""

class MsgHeaderGenerator:
    """Generates Arduino_RouterBridge_ROS header files for ROS messages"""

    def __init__(self, parser: RosTypeParser, license_str: str = ARDUINO_LICENSE_HEADER):
        self.parser = parser
        self.license_str = license_str
    def generate(self) -> str:
        """Generate the complete header file content"""
        output = []

        # License header
        output.append(self.license_str)

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


class ServiceHeaderGenerator:
    """Generate a service header from request and response definitions."""

    def __init__(self, filepath: Path, package: str, license_str: str = ARDUINO_LICENSE_HEADER):
        self.filepath = filepath
        self.package = package
        self.license_str = license_str

    def generate(self) -> str:
        sections = [[]]
        for line in self.filepath.read_text().splitlines():
            line = line.split('#', 1)[0].strip()
            if line == '---':
                sections.append([])
            elif line:
                sections[-1].append(line)
        if len(sections) != 2:
            raise ValueError('service must contain exactly one --- separator')

        parser = RosTypeParser()
        parser.package = self.package
        structs = []
        name = self.filepath.stem
        for suffix, lines in zip(('Request', 'Response'), sections):
            fields = []
            for line in lines:
                parts = line.split()
                if len(parts) < 2:
                    raise ValueError(f'invalid field definition: {line}')
                ros_type, field = parts[:2]
                if '=' in field or (len(parts) > 2 and parts[2].startswith('=')):
                    continue  # ROS constants are not serialized fields.
                cpp_type = parser.convert_type(ros_type)
                base_type = ros_type.split('[', 1)[0]
                if '/' not in base_type and base_type in parser.imports:
                    cpp_type = cpp_type.replace(base_type, f'{self.package}::msg::{base_type}')
                fields.append((field, cpp_type))
            struct_name = f'{name}_{suffix}'
            output = [f'    struct {struct_name} {{']
            for i, (field, cpp_type) in enumerate(fields, 1):
                output.extend([f'        MsgPack::str_t key{i} = "{field}";',
                               f'        {cpp_type} {field}{{}};', ''])
            output.append(f'        {struct_name}() = default;')
            if fields:
                params = ', '.join(f'{cpp_type} {field}' for field, cpp_type in fields)
                initializers = ', '.join(f'{field}({field})' for field, _ in fields)
                output.append(f'        {struct_name}({params}): {initializers} {{}}')
            args = ', '.join(f'key{i}, {field}' for i, (field, _) in enumerate(fields, 1))
            output.append(f'        MSGPACK_DEFINE_MAP({args});')
            comparisons = ' && '.join(f'this->{field} == other.{field}' for field, _ in fields) or 'true'
            output.append(f'        bool operator==(const {struct_name}& other) const {{ return {comparisons}; }}')
            output.append('    };')
            structs.append('\n'.join(output))

        macro = f'ROUTERBRIDGE_ROS_{self.package.upper()}_{name.upper()}'
        lines = [self.license_str, f'#ifndef {macro}_H', f'#define {macro}_H',
                 '#include <MsgPack.h>']
        for imported in sorted(parser.imports):
            prefix = '../' if '/' in imported else ''
            lines.append(f'#include "{prefix}{imported}.h"')
        lines.extend(['', f'#define {macro} "{self.package}/srv/{name}"', '',
                      f'namespace {self.package} {{', 'namespace srv {', '',
                      '\n\n'.join(structs), '', f'    struct {name} {{',
                      f'        static constexpr const char* _iface = {macro};',
                      f'        using Request = {name}_Request;',
                      f'        using Response = {name}_Response;', '    };', '',
                      '} // namespace srv', f'}} // namespace {self.package}',
                      f'#endif //{macro}_H'])
        return '\n'.join(lines)


class LibraryGenerator:
    """Main generator for ROS 2 library"""

    def __init__(self, lib_dir: str, output_dir: str, messages: bool = True, services: bool = True,
                 license_str: str = ARDUINO_LICENSE_HEADER):
        self.lib_dir = Path(lib_dir)
        self.output_dir = Path(output_dir)
        self.messages = messages
        self.services = services
        self.license_str = license_str if license_str else ARDUINO_LICENSE_HEADER

    def generate_from_package(self, package_name: str) -> bool:
        """Generate headers for all .msg files in a package directory"""
        package_root = self.lib_dir / package_name
        package_dir = package_root / "msg"
        service_dir = package_root / "srv"

        if not package_dir.is_dir() and not service_dir.is_dir():
            print(f"Error: Package interface directory not found: {package_root}", file=sys.stderr)
            return False

        msg_files = list(package_dir.glob("*.msg")) if self.messages else []
        srv_files = list(service_dir.glob("*.srv")) if self.services else []
        collisions = {f.stem for f in msg_files} & {f.stem for f in srv_files}
        if collisions:
            print(f"Error: Message and service headers collide: {', '.join(sorted(collisions))}", file=sys.stderr)
            return False
        if not msg_files and not srv_files:
            print(f"Warning: No .msg or .srv files found in {package_root}")
            return True

        # Create output directory structure
        output_package_dir = self.output_dir / package_name
        output_package_dir.mkdir(parents=True, exist_ok=True)
        if msg_files: (output_package_dir / "msg").mkdir(parents=True, exist_ok=True)
        if srv_files: (output_package_dir / "srv").mkdir(parents=True, exist_ok=True)

        success = True
        for msg_file in msg_files:
            if not self._generate_h_from_msg_file(msg_file, package_name, output_package_dir, self.license_str):
                success = False

        for srv_file in srv_files:
            if not self._generate_h_from_srv_file(srv_file, package_name, output_package_dir, self.license_str):
                success = False

        return success

    def pack_package(self, package_name: str, zip_path: str) -> bool:
        """Pack the headers generated from a package into a ZIP archive."""
        package_dir = self.lib_dir / package_name
        try:
            with zipfile.ZipFile(zip_path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                files = []
                if self.messages:
                    files.extend((package_dir / "msg").glob("*.msg"))
                if self.services:
                    files.extend((package_dir / "srv").glob("*.srv"))
                for msg_file in sorted(files, key=lambda file: file.stem):
                    header = self.output_dir / package_name / f"{msg_file.stem}.h"
                    archive.write(header, arcname=f"{package_name}/{header.name}")
            print(f"Created archive: {zip_path}")
            return True
        except (OSError, zipfile.BadZipFile) as e:
            print(f"Error creating archive {zip_path}: {e}", file=sys.stderr)
            return False

    def _generate_h_from_msg_file(self, msg_file: Path, package_name: str, output_dir: Path, license_str: str) -> bool:
        """Generate header for a single .msg file"""
        parser = RosTypeParser()

        if not parser.parse_msg_file(str(msg_file), package_name):
            return False

        generator = MsgHeaderGenerator(parser, license_str)
        header_content = generator.generate()

        output_file = output_dir / "msg" / f"{parser.message_name}.h"

        try:
            with open(output_file, 'w') as f:
                f.write(header_content)
            print(f"Generated: {output_file}")
            return True
        except Exception as e:
            print(f"Error writing {output_file}: {e}", file=sys.stderr)
            return False

    def _generate_h_from_srv_file(self, srv_file: Path, package_name: str, output_dir: Path, license_str: str):
        """Generate header for a single .srv file"""

        try:
            content = ServiceHeaderGenerator(srv_file, package_name, license_str).generate()
            output_file = output_dir / "srv" / f"{srv_file.stem}.h"
            output_file.write_text(content)
            print(f"Generated: {output_file}")
            return True
        except (OSError, ValueError) as e:
            print(f"Error generating {srv_file}: {e}", file=sys.stderr)
            return False

def main():
    parser = argparse.ArgumentParser(
        description="Convert ROS2 .msg and .srv files to MsgPack-serializable C++ headers for Arduino"
    )
    parser.add_argument(
        "-p", "--package",
        required=True,
        help="ROS2 package name (e.g., std_msgs, sensor_msgs)"
    )
    parser.add_argument(
        "-d", "--source-dir",
        default=".",
        help="Directory containing ROS2 packages with msg/ or srv/ subdirectories (default: current directory)"
    )
    parser.add_argument("-m", "--msg", action="store_true", help="Generate message headers")
    parser.add_argument("-s", "--srv", action="store_true", help="Generate service headers")
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

    parser.add_argument(
        "-l", "--license",
        type=str,
        default=None,
        help="License text to prepend to generated header files"
    )

    args = parser.parse_args()

    all_interfaces = not (args.msg or args.srv)
    generator = LibraryGenerator(args.source_dir, args.output,
                                        messages=all_interfaces or args.msg,
                                        services=all_interfaces or args.srv,
                                        license_str=args.license)

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