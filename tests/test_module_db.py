import unittest
import sys
import os
from unittest.mock import Mock, patch, MagicMock
from PyQt5.QtWidgets import QApplication, QTreeWidgetItem
from PyQt5.QtCore import Qt
from PyQt5.QtTest import QTest

# Add the parent directory to sys.path to import the module_db
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from db.module_db import ModuleDB


class TestModuleDBDataTypePreservation(unittest.TestCase):
    """Test suite for ModuleDB data type preservation functionality"""

    @classmethod
    def setUpClass(cls):
        """Set up QApplication for GUI tests"""
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        """Set up test fixtures"""
        # Mock the UI setup
        with patch("db.module_db.Ui_ModuleDBWidget"):
            self.module_db = ModuleDB()

        # Mock the UI components
        self.module_db.ui = Mock()
        self.module_db.ui.detailsTree = Mock()
        self.module_db.ui.detailsTree.invisibleRootItem = Mock()
        self.module_db.ui.detailsTree.clear = Mock()

        # Sample test data with mixed types
        self.test_data = {
            "moduleName": "Test_Module_001",
            "status": "active",
            "grade": "A+",
            "version": 1.2,
            "isEnabled": True,
            "testCount": 42,
            "children": [
                {
                    "childName": "Sensor_1",
                    "childType": "temperature",
                    "readings": [25.5, 26.0, 24.8],
                },
                {
                    "childName": "Sensor_2",
                    "childType": "pressure",
                    "readings": [101325, 101330, 101320],
                },
            ],
            "metadata": {
                "created": "2024-01-01",
                "tags": ["test", "prototype"],
                "config": {"timeout": 30, "retries": 3, "enabled": False},
            },
        }

    def test_store_data_types(self):
        """Test that data types are correctly stored"""
        self.module_db.original_data_types = {}
        self.module_db.store_data_types(self.test_data, "")

        # Check root level types
        self.assertEqual(self.module_db.original_data_types[""], "dict")
        self.assertEqual(self.module_db.original_data_types["moduleName"], "str")
        self.assertEqual(self.module_db.original_data_types["version"], "float")
        self.assertEqual(self.module_db.original_data_types["isEnabled"], "bool")
        self.assertEqual(self.module_db.original_data_types["testCount"], "int")

        # Check nested types
        self.assertEqual(self.module_db.original_data_types["children"], "list")
        self.assertEqual(self.module_db.original_data_types["children[0]"], "dict")
        self.assertEqual(
            self.module_db.original_data_types["children[0].readings"], "list"
        )
        self.assertEqual(
            self.module_db.original_data_types["children[0].readings[0]"], "float"
        )

        # Check deeply nested types
        self.assertEqual(self.module_db.original_data_types["metadata"], "dict")
        self.assertEqual(self.module_db.original_data_types["metadata.config"], "dict")
        self.assertEqual(
            self.module_db.original_data_types["metadata.config.timeout"], "int"
        )
        self.assertEqual(
            self.module_db.original_data_types["metadata.config.enabled"], "bool"
        )

    def test_extract_list_index(self):
        """Test extraction of list indices from paths"""
        self.assertEqual(self.module_db.extract_list_index("children[0]"), 0)
        self.assertEqual(self.module_db.extract_list_index("children[5]"), 5)
        self.assertEqual(self.module_db.extract_list_index("data.items[12]"), 12)
        self.assertEqual(self.module_db.extract_list_index("simple_path"), 0)

    def test_get_item_value_leaf_nodes(self):
        """Test value extraction for leaf nodes with type preservation"""
        # Set up original data types
        self.module_db.original_data_types = {
            "string_path": "str",
            "int_path": "int",
            "float_path": "float",
            "bool_true_path": "bool",
            "bool_false_path": "bool",
        }

        # Create mock tree items for leaf nodes
        string_item = Mock()
        string_item.childCount.return_value = 0
        string_item.text.return_value = "test_string"

        int_item = Mock()
        int_item.childCount.return_value = 0
        int_item.text.return_value = "42"

        float_item = Mock()
        float_item.childCount.return_value = 0
        float_item.text.return_value = "3.14"

        bool_true_item = Mock()
        bool_true_item.childCount.return_value = 0
        bool_true_item.text.return_value = "true"

        bool_false_item = Mock()
        bool_false_item.childCount.return_value = 0
        bool_false_item.text.return_value = "false"

        # Test type conversions
        self.assertEqual(
            self.module_db.get_item_value(string_item, "string_path"), "test_string"
        )
        self.assertEqual(self.module_db.get_item_value(int_item, "int_path"), 42)
        self.assertAlmostEqual(
            self.module_db.get_item_value(float_item, "float_path"), 3.14
        )
        self.assertEqual(
            self.module_db.get_item_value(bool_true_item, "bool_true_path"), True
        )
        self.assertEqual(
            self.module_db.get_item_value(bool_false_item, "bool_false_path"), False
        )

    def test_get_item_value_list_reconstruction(self):
        """Test list reconstruction from tree items"""
        # Set up original data types for a list
        self.module_db.original_data_types = {
            "list_path": "list",
            "list_path[0]": "str",
            "list_path[1]": "int",
            "list_path[2]": "float",
        }

        # Create mock tree item for the list
        list_item = Mock()
        list_item.childCount.return_value = 3

        # Create mock child items
        child0 = Mock()
        child0.data.return_value = "list_path[0]"
        child0.childCount.return_value = 0
        child0.text.return_value = "first"

        child1 = Mock()
        child1.data.return_value = "list_path[1]"
        child1.childCount.return_value = 0
        child1.text.return_value = "42"

        child2 = Mock()
        child2.data.return_value = "list_path[2]"
        child2.childCount.return_value = 0
        child2.text.return_value = "3.14"

        list_item.child.side_effect = [child0, child1, child2]

        result = self.module_db.get_item_value(list_item, "list_path")

        self.assertEqual(result, ["first", 42, 3.14])
        self.assertIsInstance(result, list)

    def test_get_item_value_dict_reconstruction(self):
        """Test dictionary reconstruction from tree items"""
        # Set up original data types for a dict
        self.module_db.original_data_types = {
            "dict_path": "dict",
            "dict_path.name": "str",
            "dict_path.count": "int",
            "dict_path.enabled": "bool",
        }

        # Create mock tree item for the dict
        dict_item = Mock()
        dict_item.childCount.return_value = 3

        # Create mock child items
        child0 = Mock()
        child0.data.return_value = "dict_path.name"
        child0.text.side_effect = [
            "name",
            "test",
        ]  # text(0) returns key, text(1) returns value
        child0.childCount.return_value = 0

        child1 = Mock()
        child1.data.return_value = "dict_path.count"
        child1.text.side_effect = ["count", "5"]
        child1.childCount.return_value = 0

        child2 = Mock()
        child2.data.return_value = "dict_path.enabled"
        child2.text.side_effect = ["enabled", "true"]
        child2.childCount.return_value = 0

        dict_item.child.side_effect = [child0, child1, child2]

        result = self.module_db.get_item_value(dict_item, "dict_path")

        expected = {"name": "test", "count": 5, "enabled": True}
        self.assertEqual(result, expected)
        self.assertIsInstance(result, dict)

    def test_full_data_roundtrip(self):
        """Test complete data roundtrip: data -> tree -> data"""
        # Store original data types
        self.module_db.original_data_types = {}
        self.module_db.store_data_types(self.test_data, "")

        # Simulate the tree population and reconstruction process
        # This is a simplified version since we can't easily mock the full tree widget

        # Test specific paths and values
        test_cases = [
            ("moduleName", "Test_Module_001", str),
            ("version", 1.2, float),
            ("isEnabled", True, bool),
            ("testCount", 42, int),
        ]

        for path, expected_value, expected_type in test_cases:
            # Simulate a leaf item
            mock_item = Mock()
            mock_item.childCount.return_value = 0
            mock_item.text.return_value = str(expected_value)

            result = self.module_db.get_item_value(mock_item, path)

            self.assertEqual(result, expected_value)
            self.assertIsInstance(result, expected_type)

    def test_edge_cases(self):
        """Test edge cases and error handling"""
        self.module_db.original_data_types = {}

        # Test with None values
        test_data_with_none = {"field": None}
        self.module_db.store_data_types(test_data_with_none, "")
        self.assertEqual(self.module_db.original_data_types["field"], "NoneType")

        # Test with empty structures
        empty_data = {"empty_list": [], "empty_dict": {}}
        self.module_db.store_data_types(empty_data, "")
        self.assertEqual(self.module_db.original_data_types["empty_list"], "list")
        self.assertEqual(self.module_db.original_data_types["empty_dict"], "dict")

        # Test invalid numeric conversion
        mock_item = Mock()
        mock_item.childCount.return_value = 0
        mock_item.text.return_value = "not_a_number"

        self.module_db.original_data_types["invalid_int"] = "int"
        result = self.module_db.get_item_value(mock_item, "invalid_int")
        self.assertEqual(result, "not_a_number")  # Should fall back to string

    def test_deeply_nested_structures(self):
        """Test handling of deeply nested data structures"""
        nested_data = {
            "level1": {
                "level2": {
                    "level3": [
                        {"name": "item1", "values": [1, 2, 3]},
                        {"name": "item2", "values": [4, 5, 6]},
                    ]
                }
            }
        }

        self.module_db.original_data_types = {}
        self.module_db.store_data_types(nested_data, "")

        # Verify deep nesting is correctly tracked
        self.assertEqual(
            self.module_db.original_data_types["level1.level2.level3"], "list"
        )
        self.assertEqual(
            self.module_db.original_data_types["level1.level2.level3[0].values"], "list"
        )
        self.assertEqual(
            self.module_db.original_data_types["level1.level2.level3[0].values[0]"],
            "int",
        )


class TestModuleDBIntegration(unittest.TestCase):
    """Integration tests for ModuleDB with mocked API calls"""

    @classmethod
    def setUpClass(cls):
        """Set up QApplication for GUI tests"""
        if not QApplication.instance():
            cls.app = QApplication([])
        else:
            cls.app = QApplication.instance()

    def setUp(self):
        """Set up test fixtures with mocked components"""
        with patch("db.module_db.Ui_ModuleDBWidget"):
            self.module_db = ModuleDB()

        # Mock UI components
        self.module_db.ui = Mock()
        self.module_db.ui.detailsTree = Mock()
        self.module_db.ui.moduleNameLabel = Mock()
        self.module_db.ui.tabWidget = Mock()
        self.module_db.ui.moduleDetailsTab = Mock()

    @patch("db.module_db.ModuleDB.make_api_request")
    def test_load_module_details_preserves_types(self, mock_api):
        """Test that loading module details preserves data types"""
        # Mock API response
        test_module_data = {
            "moduleName": "TEST_MODULE_001",
            "isActive": True,
            "temperature": 25.5,
            "readings": [1, 2, 3],
            "metadata": {"created": "2024-01-01"},
        }

        mock_api.return_value = (True, test_module_data)

        # Set current module ID
        self.module_db.current_module_id = "TEST_MODULE_001"

        # Call load_module_details without mocking populate_details_tree
        # so that store_data_types() gets called
        with patch.object(self.module_db.ui, "detailsTree") as mock_tree:
            # Mock the tree widget methods
            mock_tree.clear = Mock()
            mock_tree.addTopLevelItem = Mock()

            self.module_db.load_module_details()

            # Verify data types were stored
            self.assertIsNotNone(getattr(self.module_db, "original_data_types", None))
            expected_types = {
                "": "dict",
                "moduleName": "str",
                "isActive": "bool",
                "temperature": "float",
                "readings": "list",
                "readings[0]": "int",
                "readings[1]": "int",
                "readings[2]": "int",
                "metadata": "dict",
                "metadata.created": "str",
            }
            self.assertEqual(self.module_db.original_data_types, expected_types)

    @patch("db.module_db.ModuleDB.make_api_request")
    @patch("db.module_db.ModuleDB.show_info_dialog")
    @patch("db.module_db.ModuleDB.update_module_list")
    def test_save_module_details_preserves_types(
        self, mock_update_list, mock_show_info, mock_api
    ):
        """Test that saving module details preserves data types"""
        # Mock current module data
        current_data = {
            "moduleName": "TEST_MODULE_001",
            "isActive": True,
            "temperature": 25.5,
            "readings": [1, 2, 3],
        }

        # Mock API responses
        mock_api.side_effect = [
            (True, current_data),  # GET request
            (True, {"success": True}),  # PUT request
        ]

        # Set up module state
        self.module_db.current_module_id = "TEST_MODULE_001"
        self.module_db.original_data_types = {}

        # Mock the tree_to_dict_preserving_types method
        with patch.object(
            self.module_db, "tree_to_dict_preserving_types"
        ) as mock_tree_to_dict:
            mock_tree_to_dict.return_value = {"moduleName": "TEST_MODULE_001_UPDATED"}

            # Call save_module_details
            self.module_db.save_module_details()

            # Verify the preserving method was called
            mock_tree_to_dict.assert_called_once()

            # Verify API was called correctly
            self.assertEqual(mock_api.call_count, 2)

            # Verify success message was shown
            mock_show_info.assert_called_once()


if __name__ == "__main__":
    # Run the tests
    unittest.main(verbosity=2)
