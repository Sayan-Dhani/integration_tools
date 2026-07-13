import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from PyQt5.QtWidgets import QApplication
import json

# Add the parent directory to sys.path to import the modules
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.module_db import ModuleDB
from tests.test_data_generator import ModuleTestDataGenerator


class TestModuleDBWithRealData(unittest.TestCase):
    """Integration tests using realistic generated data"""

    @classmethod
    def setUpClass(cls):
        """Set up QApplication for GUI tests"""
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        """Set up test fixtures"""
        with patch("db.module_db.Ui_ModuleDBWidget"):
            self.module_db = ModuleDB()

        # Mock UI components
        self.module_db.ui = Mock()
        self.module_db.ui.detailsTree = Mock()
        self.module_db.ui.moduleNameLabel = Mock()
        self.module_db.ui.tabWidget = Mock()
        self.module_db.ui.moduleDetailsTab = Mock()

        # Generate test data
        self.generator = ModuleTestDataGenerator()
        self.test_modules = self.generator.generate_multiple_modules(5)

    def test_complex_data_type_preservation(self):
        """Test data type preservation with complex, realistic module data"""
        for module_data in self.test_modules:
            with self.subTest(module=module_data["moduleName"]):
                # Store original data types
                self.module_db.original_data_types = {}
                self.module_db.store_data_types(module_data, "")

                # Verify key data types are preserved
                self.assertEqual(self.module_db.original_data_types[""], "dict")
                self.assertEqual(
                    self.module_db.original_data_types["moduleName"], "str"
                )

                # Check children structure (both dict and list formats)
                if "children" in module_data:
                    self.assertEqual(
                        self.module_db.original_data_types["children"], "dict"
                    )
                if "childrenList" in module_data:
                    self.assertEqual(
                        self.module_db.original_data_types["childrenList"], "list"
                    )

                # Check nested structures
                if "details" in module_data:
                    self.assertEqual(
                        self.module_db.original_data_types["details"], "dict"
                    )
                    if "QA_CHECKS" in module_data["details"]:
                        self.assertEqual(
                            self.module_db.original_data_types["details.QA_CHECKS"],
                            "list",
                        )

                # Check metadata flags
                if "metadata" in module_data and "flags" in module_data["metadata"]:
                    flags = module_data["metadata"]["flags"]
                    for flag_name, flag_value in flags.items():
                        flag_path = f"metadata.flags.{flag_name}"
                        if isinstance(flag_value, bool):
                            self.assertEqual(
                                self.module_db.original_data_types[flag_path], "bool"
                            )

    def test_list_order_preservation(self):
        """Test that list order is preserved during roundtrip"""
        # Create a module with ordered lists
        test_data = {
            "ordered_list": ["first", "second", "third", "fourth"],
            "qa_checks": [
                {"step": 1, "name": "visual"},
                {"step": 2, "name": "electrical"},
                {"step": 3, "name": "thermal"},
            ],
        }

        # Store data types
        self.module_db.original_data_types = {}
        self.module_db.store_data_types(test_data, "")

        # Simulate reconstruction for ordered_list
        mock_list_item = Mock()
        mock_list_item.childCount.return_value = 4

        # Create mock children in specific order
        children = []
        for i, value in enumerate(test_data["ordered_list"]):
            child = Mock()
            child.data.return_value = f"ordered_list[{i}]"
            child.childCount.return_value = 0
            child.text.return_value = value
            children.append(child)

        mock_list_item.child.side_effect = children

        result = self.module_db.get_item_value(mock_list_item, "ordered_list")

        self.assertEqual(result, test_data["ordered_list"])
        self.assertIsInstance(result, list)

    def test_nested_dict_list_combinations(self):
        """Test complex nested combinations of dicts and lists"""
        complex_data = {
            "sensors": [
                {
                    "name": "temp_sensor_1",
                    "readings": [25.1, 25.2, 25.0],
                    "metadata": {
                        "calibrated": True,
                        "calibration_points": [0.0, 25.0, 50.0, 75.0, 100.0],
                    },
                },
                {
                    "name": "pressure_sensor_1",
                    "readings": [101325, 101330, 101320],
                    "metadata": {"calibrated": False, "calibration_points": []},
                },
            ]
        }

        # Store data types
        self.module_db.original_data_types = {}
        self.module_db.store_data_types(complex_data, "")

        # Verify complex nested paths
        expected_types = {
            "": "dict",
            "sensors": "list",
            "sensors[0]": "dict",
            "sensors[0].readings": "list",
            "sensors[0].readings[0]": "float",
            "sensors[0].metadata": "dict",
            "sensors[0].metadata.calibrated": "bool",
            "sensors[0].metadata.calibration_points": "list",
            "sensors[1].metadata.calibrated": "bool",
        }

        for path, expected_type in expected_types.items():
            self.assertEqual(
                self.module_db.original_data_types[path],
                expected_type,
                f"Wrong type for path {path}",
            )

    def test_edge_case_data_types(self):
        """Test edge cases with various data types"""
        edge_case_data = {
            "null_value": None,
            "empty_string": "",
            "zero_int": 0,
            "zero_float": 0.0,
            "false_bool": False,
            "empty_list": [],
            "empty_dict": {},
            "negative_int": -42,
            "scientific_notation": 1.23e-4,
            "unicode_string": "测试数据",
            "special_chars": "!@#$%^&*()",
        }

        # Store data types
        self.module_db.original_data_types = {}
        self.module_db.store_data_types(edge_case_data, "")

        # Test type preservation for edge cases
        test_cases = [
            ("null_value", None, "NoneType"),
            ("zero_int", 0, "int"),
            ("zero_float", 0.0, "float"),
            ("false_bool", False, "bool"),
            ("empty_list", [], "list"),
            ("empty_dict", {}, "dict"),
            ("negative_int", -42, "int"),
            ("scientific_notation", 1.23e-4, "float"),
        ]

        for field, value, expected_type in test_cases:
            self.assertEqual(
                self.module_db.original_data_types[field],
                expected_type,
                f"Wrong type stored for {field}",
            )

            # Test value reconstruction
            mock_item = Mock()
            mock_item.childCount.return_value = 0
            mock_item.text.return_value = str(value)

            if value is not None:  # Skip None values for text conversion
                result = self.module_db.get_item_value(mock_item, field)
                if expected_type in ["int", "float", "bool"]:
                    self.assertEqual(result, value)
                    self.assertIsInstance(result, type(value))

    @patch("db.module_db.ModuleDB.make_api_request")
    def test_full_roundtrip_with_realistic_data(self, mock_api):
        """Test complete save/load cycle with realistic module data"""
        # Use a realistic module
        original_module = self.test_modules[0]

        # Set up the module DB state
        self.module_db.current_module_id = original_module["moduleName"]

        # Store the original data types that would be created
        self.module_db.original_data_types = {}
        self.module_db.store_data_types(original_module, "")

        # Simulate tree reconstruction
        with patch.object(
            self.module_db, "tree_to_dict_preserving_types"
        ) as mock_tree_to_dict:
            # Return a modified version of the data
            modified_data = original_module.copy()
            modified_data["status"] = "updated_status"
            mock_tree_to_dict.return_value = modified_data

            # Mock API calls for save (only the ones needed for save_module_details)
            mock_api.side_effect = [
                (True, original_module),  # GET for current data
                (True, {"success": True}),  # PUT for update
            ]

            with patch.object(self.module_db, "show_info_dialog"), patch.object(
                self.module_db, "update_module_list"
            ):

                # Call save
                self.module_db.save_module_details()

                # Verify the type-preserving method was called
                mock_tree_to_dict.assert_called_once()

                # Verify the correct number of API calls were made
                self.assertEqual(mock_api.call_count, 2)


class TestDataIntegrity(unittest.TestCase):
    """Test data integrity and consistency"""

    def setUp(self):
        """Set up test fixtures"""
        self.generator = ModuleTestDataGenerator()

    def test_generated_data_consistency(self):
        """Test that generated data is internally consistent"""
        modules = self.generator.generate_multiple_modules(10)

        for module in modules:
            with self.subTest(module=module["moduleName"]):
                # Check module name format
                name_parts = module["moduleName"].split("_")
                self.assertGreaterEqual(
                    len(name_parts), 3, "Module name should have at least 3 parts"
                )

                # Check speed consistency
                if "speed" in module:
                    speed = module["speed"]
                    self.assertIn(speed, ["5G", "10G"], f"Invalid speed: {speed}")

                # Check children structure
                if "children" in module:
                    self.assertIsInstance(
                        module["children"], dict, "Children should be a dict"
                    )

                if "childrenList" in module:
                    self.assertIsInstance(
                        module["childrenList"], list, "ChildrenList should be a list"
                    )

                # Check nested data structures
                if "details" in module and "QA_CHECKS" in module["details"]:
                    qa_checks = module["details"]["QA_CHECKS"]
                    self.assertIsInstance(qa_checks, list, "QA_CHECKS should be a list")
                    for check in qa_checks:
                        self.assertIsInstance(
                            check, dict, "Each QA check should be a dict"
                        )
                        self.assertIn(
                            "test", check, "Each QA check should have a 'test' field"
                        )
                        self.assertIn(
                            "passed",
                            check,
                            "Each QA check should have a 'passed' field",
                        )

    def test_data_serialization(self):
        """Test that generated data can be JSON serialized/deserialized"""
        modules = self.generator.generate_multiple_modules(3)

        for module in modules:
            with self.subTest(module=module["moduleName"]):
                try:
                    # Test JSON serialization
                    json_str = json.dumps(module, default=str)

                    # Test JSON deserialization
                    restored_module = json.loads(json_str)

                    # Basic structure should be preserved
                    self.assertEqual(
                        restored_module["moduleName"], module["moduleName"]
                    )

                except (TypeError, ValueError) as e:
                    self.fail(
                        f"Failed to serialize/deserialize module {module['moduleName']}: {e}"
                    )


if __name__ == "__main__":
    unittest.main(verbosity=2)
