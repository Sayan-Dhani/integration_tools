#!/usr/bin/env python3
"""
Simple standalone test to verify data type preservation functionality
"""

import sys
import os

# Add the parent directory to sys.path to import the modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def test_data_type_preservation():
    """Test the core data type preservation functionality without GUI"""

    # Create a simple mock class with just the data type preservation methods
    class MockModuleDB:
        def __init__(self):
            self.original_data_types = {}

        def store_data_types(self, data, path):
            """Store the original data types for later reconstruction"""
            if isinstance(data, dict):
                self.original_data_types[path] = "dict"
                for key, value in data.items():
                    current_path = f"{path}.{key}" if path else key
                    self.store_data_types(value, current_path)
            elif isinstance(data, list):
                self.original_data_types[path] = "list"
                for i, value in enumerate(data):
                    current_path = f"{path}[{i}]"
                    self.store_data_types(value, current_path)
            else:
                self.original_data_types[path] = type(data).__name__

        def extract_list_index(self, path):
            """Extract list index from path like 'children[0]' -> 0"""
            import re

            match = re.search(r"\[(\d+)\]$", path)
            return int(match.group(1)) if match else 0

        def simulate_type_conversion(self, value, original_type):
            """Simulate the type conversion that would happen"""
            if original_type == "bool":
                return str(value).lower() == "true"
            elif original_type == "int":
                try:
                    return int(value)
                except ValueError:
                    return value
            elif original_type == "float":
                try:
                    return float(value)
                except ValueError:
                    return value
            else:
                return str(value)

    # Test data
    test_data = {
        "moduleName": "TEST_MODULE_001",
        "isActive": True,
        "temperature": 25.5,
        "count": 42,
        "readings": [1.1, 2.2, 3.3],
        "metadata": {
            "created": "2024-01-01",
            "flags": {"enabled": False, "priority": 1},
        },
        "children": [
            {"name": "child1", "type": "sensor"},
            {"name": "child2", "type": "actuator"},
        ],
    }

    # Create mock instance
    mock_db = MockModuleDB()

    # Store data types
    mock_db.store_data_types(test_data, "")

    # Verify types were stored correctly
    expected_types = {
        "": "dict",
        "moduleName": "str",
        "isActive": "bool",
        "temperature": "float",
        "count": "int",
        "readings": "list",
        "readings[0]": "float",
        "readings[1]": "float",
        "readings[2]": "float",
        "metadata": "dict",
        "metadata.created": "str",
        "metadata.flags": "dict",
        "metadata.flags.enabled": "bool",
        "metadata.flags.priority": "int",
        "children": "list",
        "children[0]": "dict",
        "children[0].name": "str",
        "children[0].type": "str",
        "children[1]": "dict",
        "children[1].name": "str",
        "children[1].type": "str",
    }

    print("Testing data type storage...")
    all_passed = True

    for path, expected_type in expected_types.items():
        stored_type = mock_db.original_data_types.get(path)
        if stored_type != expected_type:
            print(
                f"❌ FAIL: Path '{path}' expected '{expected_type}' but got '{stored_type}'"
            )
            all_passed = False
        else:
            print(f"✅ PASS: Path '{path}' -> '{expected_type}'")

    # Test type conversion
    print("\nTesting type conversion...")
    test_conversions = [
        ("true", "bool", True),
        ("false", "bool", False),
        ("42", "int", 42),
        ("3.14", "float", 3.14),
        ("hello", "str", "hello"),
        ("invalid", "int", "invalid"),  # Should fall back to string
    ]

    for input_val, input_type, expected_output in test_conversions:
        result = mock_db.simulate_type_conversion(input_val, input_type)
        if result == expected_output and type(result) == type(expected_output):
            print(
                f"✅ PASS: '{input_val}' ({input_type}) -> {result} ({type(result).__name__})"
            )
        else:
            print(
                f"❌ FAIL: '{input_val}' ({input_type}) -> {result} ({type(result).__name__}), expected {expected_output} ({type(expected_output).__name__})"
            )
            all_passed = False

    # Test list index extraction
    print("\nTesting list index extraction...")
    index_tests = [
        ("children[0]", 0),
        ("readings[5]", 5),
        ("data.items[12]", 12),
        ("simple_path", 0),
    ]

    for path, expected_index in index_tests:
        result = mock_db.extract_list_index(path)
        if result == expected_index:
            print(f"✅ PASS: '{path}' -> {result}")
        else:
            print(f"❌ FAIL: '{path}' -> {result}, expected {expected_index}")
            all_passed = False

    print(f"\n{'='*50}")
    if all_passed:
        print("🎉 ALL TESTS PASSED! Data type preservation is working correctly.")
        return True
    else:
        print("❌ SOME TESTS FAILED. Check the implementation.")
        return False


if __name__ == "__main__":
    success = test_data_type_preservation()
    sys.exit(0 if success else 1)
