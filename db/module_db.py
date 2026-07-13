from PyQt5.QtWidgets import (
    QWidget,
    QVBoxLayout,
    QLineEdit,
    QLabel,
    QTreeWidgetItem,
    QMessageBox,
    QPushButton,
    QInputDialog,
    QHBoxLayout,
    QTreeWidget,
)
from PyQt5.QtCore import Qt, pyqtSignal
import requests
import yaml
import os
import re
from db.module_db_gui import Ui_ModuleDBWidget


class ModuleDB(QWidget):
    """Widget for managing module inventory and details"""

    # Signals
    module_selected = pyqtSignal(str)  # Emitted when module is selected

    def __init__(self, parent=None):
        super().__init__(parent)

        # Set up UI
        self.ui = Ui_ModuleDBWidget()
        self.ui.setupUi(self)

        # Initialize variables
        self.all_modules = []
        self.mounted_modules = {}
        self.current_module_id = None

        # Add layer type mapping
        self.layers_to_filters = {
            "L1_47": {
                "spacer": "2.6mm",
                "speed": "10G",
            },
            "L1_60": {
                "spacer": "4.0mm",
                "speed": "10G",
            },
            "L1_72": {
                "spacer": "4.0mm",
                "speed": "10G",
            },
            "L2_40": {
                "spacer": "2.6mm",
                "speed": "10G",
            },
            "L2_55": {
                "spacer": "2.6mm",
                "speed": "10G",
            },
            "L2_68": {
                "spacer": "4.0mm",
                "speed": "10G",
            },
            "L3": {
                "spacer": "2.6mm",
                "speed": "5G",
            },
        }

        # Setup UI components
        self.setup_filters()
        self.setup_tree_widget()
        self.setup_search()
        self.setup_module_details_tab()

        # Connect signals
        self.connect_signals()

        # Load settings
        self.load_settings()

        # Initial module list load
        self.update_module_list()

    def setup_filters(self):
        """Setup filter combo boxes"""
        # Populate layer type combo box
        self.ui.layertypeCB.clear()
        self.ui.layertypeCB.addItem("any")
        self.ui.layertypeCB.addItems(sorted(self.layers_to_filters.keys()))

        # Add "any" to status filter
        # self.ui.spacerCB_3.insertItem(0, "any")

        # Add grade options
        self.ui.spacerCB_2.addItems(["A++", "A+", "A", "B", "C"])

    def setup_tree_widget(self):
        """Setup tree widget properties"""
        # Enable sorting
        self.ui.treeWidget.setSortingEnabled(True)

        # Set column widths
        self.ui.treeWidget.setColumnWidth(0, 150)  # Name
        self.ui.treeWidget.setColumnWidth(1, 70)  # Inventory Slot
        self.ui.treeWidget.setColumnWidth(2, 70)  # Speed
        self.ui.treeWidget.setColumnWidth(3, 70)  # Spacer
        self.ui.treeWidget.setColumnWidth(4, 100)  # Status
        self.ui.treeWidget.setColumnWidth(5, 150)  # Description

        # Enable selection mode
        self.ui.treeWidget.setSelectionMode(QTreeWidget.SingleSelection)

    def connect_signals(self):
        """Connect all signals"""
        self.searchBox.textChanged.connect(self.filter_modules)
        self.ui.selectModulePB.clicked.connect(self.select_module)
        self.ui.viewDetailsPB.clicked.connect(self.view_module_details)
        self.ui.editDetailsButton.clicked.connect(self.edit_selected_detail)
        self.ui.saveDetailsButton.clicked.connect(self.save_module_details)
        self.ui.disconnectButton.clicked.connect(self.disconnect_module)

        # Connect filter signals
        self.ui.speedCB.currentTextChanged.connect(self.update_module_list)
        self.ui.spacerCB.currentTextChanged.connect(self.update_module_list)
        self.ui.spacerCB_2.currentTextChanged.connect(self.update_module_list)
        self.ui.spacerCB_3.currentTextChanged.connect(self.update_module_list)
        self.ui.layertypeCB.currentTextChanged.connect(self.update_filters_from_layer)

    def get_settings_file(self):
        """Get the settings file path"""
        config_file = os.path.join(
            os.path.expanduser("~/.config/module_db"), "settings.yaml"
        )
        bundled_file = os.path.join(
            os.path.dirname(__file__), os.pardir, "settings_integration.yaml"
        )
        if os.path.exists(config_file):
            return config_file
        elif os.path.exists(bundled_file):
            return bundled_file
        else:
            return config_file

    def load_settings(self):
        """Load settings from YAML file"""
        try:
            with open(self.get_settings_file(), "r") as f:
                settings = yaml.safe_load(f)
                if settings:
                    self.db_url = settings.get("db_url", "http://localhost:5000")
        except FileNotFoundError:
            self.db_url = "http://localhost:5000"
            self.save_settings()

    def save_settings(self):
        """Save settings to YAML file"""
        settings = {"db_url": self.db_url}
        with open(self.get_settings_file(), "w") as f:
            yaml.dump(settings, f)

    def get_api_url(self, endpoint=""):
        """Get full API URL with endpoint"""
        base_url = self.db_url.rstrip("/")
        return f"{base_url}/{endpoint.lstrip('/')}" if endpoint else base_url

    def setup_module_details_tab(self):
        """Setup the module details tab"""
        # Set up tree widget
        self.ui.detailsTree.setHeaderLabels(["Field", "Value"])
        self.ui.detailsTree.setColumnWidth(0, 200)

    def make_api_request(self, endpoint, method="GET", data=None):
        """Make API request with error handling"""
        try:
            url = self.get_api_url(endpoint)
            if method == "GET":
                response = requests.get(url)
            elif method == "POST":
                response = requests.post(url, json=data)
            elif method == "PUT":
                response = requests.put(url, json=data)
            else:
                return False, f"Unsupported method: {method}"

            if response.status_code == 200:
                return True, response.json()
            else:
                return False, response.text

        except Exception as e:
            return False, str(e)

    def update_module_list(self):
        """Update the module list from database"""
        success, modules = self.make_api_request("modules")
        if not success:
            self.show_error_dialog(f"Failed to fetch modules: {modules}")
            return

        self.all_modules = modules
        self.filter_modules()

    def filter_modules(self, search_text=None):
        """Filter modules based on search text and all filters"""
        if search_text is None:
            search_text = self.searchBox.text()
        search_text = search_text

        self.ui.treeWidget.clear()

        for module in self.all_modules:
            print(module["moduleName"])
            # Get module speed
            module_speed = ""
            if (
                "_5_" in module.get("moduleName", "")
                or "_05_" in module.get("moduleName", "")
                or "_5-" in module.get("moduleName", "")
                or "_05-" in module.get("moduleName", "")
            ):
                module_speed = "5G"
            if "_10_" in module.get("moduleName", "") or "_10-" in module.get(
                "moduleName", ""
            ):
                module_speed = "10G"

            # Check hybrid details for speed
            if isinstance(module.get("children"), dict):
                if isinstance(module.get("children").get("PS Read-out Hybrid"), dict):
                    if isinstance(
                        module.get("children").get("PS Read-out Hybrid").get("details"),
                        dict,
                    ):
                        if (
                            module.get("children")
                            .get("PS Read-out Hybrid")
                            .get("details")
                            .get("ALPGBT_BANDWIDTH")
                            is not None
                        ):
                            module_speed = (
                                module.get("children")
                                .get("PS Read-out Hybrid")
                                .get("details")
                                .get("ALPGBT_BANDWIDTH")
                            )
                            if module_speed == "10Gbps":
                                module_speed = "10G"
                            if module_speed == "5Gbps":
                                module_speed = "5G"

            module["speed"] = module_speed

            # Get spacer
            fields = module.get("moduleName", "").split("_")
            spacer = fields[1] if len(fields) > 2 else ""
            module["spacer"] = spacer
            if not "Pisa" in module.get("details", {}).get("LOCATION", ""):
                continue
            print("In Pisa")
            # Apply all filters
            if search_text and search_text not in module.get("moduleName", ""):
                continue
            print("search ok")

            speed = self.ui.speedCB.currentText()
            if speed != "any" and module_speed != speed:
                continue
            print("Speed ok")
            spacer_filter = self.ui.spacerCB.currentText()
            spacer_dict = {"4.0mm": "40", "2.6mm": "26", "1.8mm": "18", "any": "any"}
            spacer_filter = spacer_dict[spacer_filter]
            if spacer_filter != "any" and spacer != spacer_filter:
                continue
            print("Spacer ok")

            grade = self.ui.spacerCB_2.currentText()
            if grade != "any" and module.get("grade") != grade:
                continue

            status = self.ui.spacerCB_3.currentText()
            if status != "any" and module.get("status") != status:
                continue

            # Add matching module to tree
            item = QTreeWidgetItem(self.ui.treeWidget)
            item.setText(0, module.get("moduleName", ""))
            #            item.setText(1, module.get("inventorySlot", ""))
            item.setText(1, module.get("position", ""))
            item.setText(2, module.get("speed", ""))
            item.setText(3, str(module.get("spacer", "")))
            item.setText(4, module.get("status", ""))
            item.setText(6, module.get("details", {}).get("DESCRIPTION", ""))

            # Handle connections column
            connections = module.get("crateSide", {})
            print(connections)
            connections = [y[0] for x, y in connections.items() if len(y) > 0]
            connections = list(set(connections))  # Make connections entries unique
            item.setText(5, "/".join(connections))

            # Add disconnect button if there are connections
            if len(connections) > 0:
                # Create a widget to hold both connection info and button
                container = QWidget()
                layout = QVBoxLayout(container)
                layout.setContentsMargins(0, 0, 0, 0)
                layout.setSpacing(0)

                # Create button with connection info
                disconnect_button = QPushButton()
                # Make button smaller
                disconnect_button.setMaximumHeight(20)
                font = disconnect_button.font()
                font.setPointSize(8)
                disconnect_button.setFont(font)
                print("conn", connections)
                button_text = "Disconnect " + ("/".join(connections))
                disconnect_button.setText(button_text)
                disconnect_button.clicked.connect(
                    lambda checked, m=module.get(
                        "moduleName", ""
                    ): self.disconnect_module(m)
                )

                layout.addWidget(disconnect_button)
                self.ui.treeWidget.setItemWidget(item, 5, container)

            item.setText(8, module.get("mounted_on", ""))

        # Resize columns to content
        for i in range(self.ui.treeWidget.columnCount()):
            self.ui.treeWidget.resizeColumnToContents(i)

    def populate_details_tree(self, data, parent=None, path=""):
        """Recursively populate the details tree with module data"""
        if parent is None:
            self.ui.detailsTree.clear()
            parent = self.ui.detailsTree
            # Store original data structure for reference
            self.original_data_types = {}
            self.store_data_types(data, "")

            # Add disconnect button if module has connections or is mounted
            if data.get("connections") or data.get("mounted_on"):
                disconnect_item = QTreeWidgetItem(parent)
                disconnect_item.setText(0, "Actions")
                disconnect_button = QPushButton("Disconnect")
                disconnect_button.clicked.connect(self.disconnect_module)
                self.ui.detailsTree.setItemWidget(disconnect_item, 1, disconnect_button)

        if isinstance(data, dict):
            for key, value in sorted(data.items()):
                current_path = f"{path}.{key}" if path else key
                item = QTreeWidgetItem([str(key), ""])
                # Store the path in the item for later reference
                item.setData(0, Qt.UserRole, current_path)
                if parent == self.ui.detailsTree:
                    parent.addTopLevelItem(item)
                else:
                    parent.addChild(item)
                self.populate_details_tree(value, item, current_path)
        elif isinstance(data, list):
            for i, value in enumerate(data):
                current_path = f"{path}[{i}]"
                if isinstance(value, dict) and "childName" in value:
                    # Special handling for child components
                    item = QTreeWidgetItem(
                        [value["childName"], value.get("childType", "")]
                    )
                else:
                    item = QTreeWidgetItem([f"[{i}]", ""])
                item.setData(0, Qt.UserRole, current_path)
                parent.addChild(item)
                self.populate_details_tree(value, item, current_path)
        else:
            parent.setText(1, str(data))
            parent.setData(0, Qt.UserRole, path)

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

    def tree_to_dict_preserving_types(self, item, path=""):
        """Convert tree widget items back to dictionary/list preserving original types"""
        if item == self.ui.detailsTree.invisibleRootItem():
            # Root level - reconstruct the entire structure
            result = {}
            for i in range(item.childCount()):
                child = item.child(i)
                child_path = child.data(0, Qt.UserRole)
                if child_path and not child_path.startswith("Actions"):
                    key = child.text(0)
                    value = self.get_item_value(child, child_path)
                    result[key] = value
            return result
        else:
            return self.get_item_value(item, path)

    def get_item_value(self, item, path):
        """Get the value for a tree item, preserving original type"""
        if item.childCount() == 0:
            # Leaf node - convert to appropriate type
            text_value = item.text(1)
            original_type = self.original_data_types.get(path, "str")

            if original_type == "bool":
                return text_value.lower() == "true"
            elif original_type == "int":
                try:
                    return int(text_value)
                except ValueError:
                    return text_value
            elif original_type == "float":
                try:
                    return float(text_value)
                except ValueError:
                    return text_value
            else:
                return text_value
        else:
            # Non-leaf node - check if it should be a list or dict
            original_type = self.original_data_types.get(path, "dict")

            if original_type == "list":
                # Reconstruct as list
                result = []
                children_data = []
                for i in range(item.childCount()):
                    child = item.child(i)
                    child_path = child.data(0, Qt.UserRole)
                    child_value = self.get_item_value(child, child_path)
                    children_data.append((child_path, child_value))

                # Sort by list index and add to result
                children_data.sort(key=lambda x: self.extract_list_index(x[0]))
                for _, value in children_data:
                    result.append(value)
                return result
            else:
                # Reconstruct as dict
                result = {}
                for i in range(item.childCount()):
                    child = item.child(i)
                    child_path = child.data(0, Qt.UserRole)
                    key = child.text(0)
                    value = self.get_item_value(child, child_path)
                    result[key] = value
                return result

    def extract_list_index(self, path):
        """Extract list index from path like 'children[0]' -> 0"""
        import re

        match = re.search(r"\[(\d+)\]$", path)
        return int(match.group(1)) if match else 0

    def tree_to_dict(self, item):
        """Convert tree widget items back to dictionary recursively"""
        result = {}

        for i in range(item.childCount()):
            child = item.child(i)
            key = child.text(0)

            if child.childCount() > 0:
                # This is a non-leaf node, recurse
                value = self.tree_to_dict(child)
            else:
                # This is a leaf node, get its value
                value = child.text(1)
                # Try to convert to appropriate type
                try:
                    if value.lower() == "true":
                        value = True
                    elif value.lower() == "false":
                        value = False
                    elif value.isdigit():
                        value = int(value)
                    elif value.replace(".", "", 1).isdigit():
                        value = float(value)
                except:
                    pass

            # Handle nested paths using dot notation
            key_parts = key.split(".")
            current_dict = result
            for part in key_parts[:-1]:
                if part not in current_dict:
                    current_dict[part] = {}
                current_dict = current_dict[part]
            current_dict[key_parts[-1]] = value

        return result

    def merge_dicts(self, dict1, dict2):
        """Recursively merge two dictionaries"""
        result = dict1.copy()
        for key, value in dict2.items():
            if (
                key in result
                and isinstance(result[key], dict)
                and isinstance(value, dict)
            ):
                result[key] = self.merge_dicts(result[key], value)
            else:
                result[key] = value
        return result

    def select_module(self):
        """Select a module from the inventory"""
        selected_items = self.ui.treeWidget.selectedItems()
        if not selected_items:
            self.show_error_dialog("No module selected")
            return

        module_id = selected_items[0].text(0)
        self.module_selected.emit(module_id)

    def view_module_details(self):
        """View details for selected module"""
        selected_items = self.ui.treeWidget.selectedItems()
        if not selected_items:
            self.show_error_dialog("No module selected")
            return

        module_id = selected_items[0].text(0)  # Get module name
        self.current_module_id = module_id
        self.ui.moduleNameLabel.setText(module_id)
        self.load_module_details()
        self.ui.tabWidget.setCurrentWidget(self.ui.moduleDetailsTab)

    def load_module_details(self):
        """Load module details when module ID changes"""
        if not self.current_module_id:
            self.ui.moduleNameLabel.setText("")
            return

        try:
            success, module_data = self.make_api_request(
                f"modules/{self.current_module_id}"
            )
            self.current_module_data = module_data
            if success:
                self.populate_details_tree(module_data)
            else:
                self.show_error_dialog(f"Error fetching module details: {module_data}")
        except Exception as e:
            self.show_error_dialog(f"Error loading module details: {str(e)}")

    def show_error_dialog(self, message):
        """Show error dialog with message"""
        QMessageBox.critical(self, "Error", message)

    def edit_selected_detail(self):
        """Edit the selected detail"""
        item = self.ui.detailsTree.currentItem()
        if item and item.text(1):  # Only edit leaf nodes
            dialog = QInputDialog()
            dialog.setWindowTitle("Edit Value")
            dialog.setLabelText(f"Edit value for {item.text(0)}:")
            dialog.setTextValue(item.text(1))

            if dialog.exec_():
                item.setText(1, dialog.textValue())

    def save_module_details(self):
        """Save the modified module details back to the database"""
        try:
            # First get current module data to preserve all fields
            success, current_data = self.make_api_request(
                f"modules/{self.current_module_id}"
            )
            if not success:
                self.show_error_dialog(f"Error fetching module: {current_data}")
                return

            # Convert tree widget back to dictionary preserving types
            new_data = self.tree_to_dict_preserving_types(
                self.ui.detailsTree.invisibleRootItem()
            )

            # Recursively merge the data
            merged_data = self.merge_dicts(current_data, new_data)

            # Remove _id from merged data
            if "_id" in merged_data:
                del merged_data["_id"]

            # Make API request to update module
            success, result = self.make_api_request(
                endpoint=f"modules/{self.current_module_id}",
                method="PUT",
                data=merged_data,
            )

            if success:
                self.show_info_dialog("Module details updated successfully")
                self.update_module_list()  # Refresh the module list to show updated data
            else:
                self.show_error_dialog(f"Error updating module: {result}")

        except Exception as e:
            self.show_error_dialog(f"Error saving module details: {str(e)}")

    def show_info_dialog(self, message):
        """Show information dialog with message"""
        QMessageBox.information(self, "Information", message)

    def update_filters_from_layer(self, layer_type):
        """Update speed and spacer filters based on selected layer type"""
        if layer_type == "any":
            self.ui.speedCB.setCurrentText("any")
            self.ui.spacerCB.setCurrentText("any")
            return

        if layer_type in self.layers_to_filters:
            filters = self.layers_to_filters[layer_type]
            self.ui.speedCB.setCurrentText(filters["speed"])
            self.ui.spacerCB.setCurrentText(filters["spacer"])

    def setup_search(self):
        """Set up search functionality"""
        searchLayout = QHBoxLayout()
        searchLabel = QLabel("Search:")
        self.searchBox = QLineEdit()
        self.searchBox.setPlaceholderText("Search modules...")
        searchLayout.addWidget(searchLabel)
        searchLayout.addWidget(self.searchBox)
        searchLayout.addStretch()

        # Insert search layout before the tree widget
        layout = self.ui.tab_2.layout()
        if layout:
            # Insert after the filters group box
            layout.insertLayout(1, searchLayout)
        else:
            # Create layout if it doesn't exist
            layout = QVBoxLayout(self.ui.tab_2)
            layout.addLayout(searchLayout)

    def disconnect_module(self, m):
        """Disconnect the current module"""

        try:
            data = {
                "cable": m,
            }

            success, result = self.make_api_request(
                endpoint="disconnect_all_crateSide", method="POST", data=data
            )

            if success:
                self.show_info_dialog("Module disconnected successfully")
                self.update_module_list()  # Refresh the module list
                self.load_module_details()  # Refresh the details view
            else:
                self.show_error_dialog(f"Error disconnecting module: {result}")

        except Exception as e:
            self.show_error_dialog(f"Error disconnecting module: {str(e)}")

    # ... Copy other methods from main.py ...
