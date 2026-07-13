"""
Test data generators for module database testing
"""

import random
from datetime import datetime, timedelta


class ModuleTestDataGenerator:
    """Generate realistic test data for module database testing"""

    LAYER_TYPES = ["L1_47", "L1_60", "L1_72", "L2_40", "L2_55", "L2_68", "L3"]
    SPACER_SIZES = ["18", "26", "40"]
    SPEEDS = ["5G", "10G"]
    GRADES = ["A++", "A+", "A", "B", "C"]
    STATUSES = ["active", "inactive", "testing", "failed", "retired"]
    CENTERS = ["Pisa", "CERN", "Other"]

    @staticmethod
    def generate_module_name(layer_type=None, spacer=None, speed=None):
        """Generate a realistic module name"""
        if not layer_type:
            layer_type = random.choice(ModuleTestDataGenerator.LAYER_TYPES)
        if not spacer:
            spacer = random.choice(ModuleTestDataGenerator.SPACER_SIZES)
        if not speed:
            speed = random.choice(ModuleTestDataGenerator.SPEEDS)

        speed_suffix = "5" if speed == "5G" else "10"
        serial = random.randint(1000, 9999)

        return f"{layer_type}_{spacer}_{speed_suffix}_{serial:04d}"

    @staticmethod
    def generate_sensor_readings(count=10):
        """Generate realistic sensor readings"""
        base_temp = 25.0
        return [round(base_temp + random.uniform(-2.0, 2.0), 2) for _ in range(count)]

    @staticmethod
    def generate_child_component():
        """Generate a child component structure"""
        component_types = ["PS Read-out Hybrid", "Sensor", "Connector", "Cable"]
        component_type = random.choice(component_types)

        base_component = {
            "childName": f"{component_type}_{random.randint(1, 999):03d}",
            "childType": component_type,
            "serialNumber": f"SN{random.randint(100000, 999999)}",
            "status": random.choice(ModuleTestDataGenerator.STATUSES),
        }

        # Add specific details based on component type
        if component_type == "PS Read-out Hybrid":
            base_component["details"] = {
                "ALPGBT_BANDWIDTH": random.choice(["5Gbps", "10Gbps"]),
                "FIRMWARE_VERSION": f"v{random.randint(1, 5)}.{random.randint(0, 9)}",
                "TEMPERATURE_LIMIT": random.randint(60, 80),
                "POWER_CONSUMPTION": round(random.uniform(2.0, 8.0), 2),
            }
        elif component_type == "Sensor":
            base_component["details"] = {
                "SENSOR_TYPE": random.choice(["temperature", "humidity", "pressure"]),
                "CALIBRATION_DATE": (
                    datetime.now() - timedelta(days=random.randint(0, 365))
                ).isoformat(),
                "READINGS": ModuleTestDataGenerator.generate_sensor_readings(),
            }

        return base_component

    @staticmethod
    def generate_crate_side_connections():
        """Generate crate side connections"""
        connections = {}

        # Randomly generate some connections
        for i in range(random.randint(0, 4)):
            crate_name = f"Crate_{chr(65 + i)}"  # Crate_A, Crate_B, etc.
            slot_count = random.randint(1, 3)
            slots = [f"Slot_{j+1}" for j in range(slot_count)]
            connections[crate_name] = slots

        return connections

    @staticmethod
    def generate_full_module_data(module_name=None):
        """Generate a complete module data structure"""
        if not module_name:
            module_name = ModuleTestDataGenerator.generate_module_name()

        # Extract info from module name
        name_parts = module_name.split("_")
        layer_type = "_".join(name_parts[:2]) if len(name_parts) >= 2 else "L1_47"
        spacer = name_parts[1] if len(name_parts) > 1 else "26"
        speed_suffix = name_parts[2] if len(name_parts) > 2 else "10"
        speed = "10G" if speed_suffix == "10" else "5G"

        # Generate children
        num_children = random.randint(1, 5)
        children = {}
        children_list = []

        for i in range(num_children):
            child = ModuleTestDataGenerator.generate_child_component()
            child_name = child["childName"]
            children[child_name] = child
            children_list.append(child)

        # Generate connections
        crate_connections = ModuleTestDataGenerator.generate_crate_side_connections()

        module_data = {
            "moduleName": module_name,
            "inventorySlot": f"INV_{random.randint(1000, 9999)}",
            "status": random.choice(ModuleTestDataGenerator.STATUSES),
            "grade": random.choice(ModuleTestDataGenerator.GRADES),
            "speed": speed,
            "spacer": spacer,
            "Current Center": random.choice(ModuleTestDataGenerator.CENTERS),
            "crateSide": crate_connections,
            "mounted_on": (
                f"TestBench_{random.randint(1, 10)}" if random.random() > 0.5 else ""
            ),
            "children": children,  # Dictionary format
            "childrenList": children_list,  # List format - for testing type preservation
            "details": {
                "DESCRIPTION": f"Test module {module_name}",
                "MANUFACTURE_DATE": (
                    datetime.now() - timedelta(days=random.randint(30, 730))
                ).isoformat(),
                "LAST_TESTED": (
                    datetime.now() - timedelta(days=random.randint(0, 30))
                ).isoformat(),
                "TEST_CYCLES": random.randint(0, 1000),
                "TEMPERATURE_RANGE": {
                    "min": round(random.uniform(-40, -20), 1),
                    "max": round(random.uniform(60, 85), 1),
                    "operating": round(random.uniform(20, 30), 1),
                },
                "ELECTRICAL_SPECS": {
                    "voltage": round(random.uniform(3.0, 5.0), 2),
                    "current": round(random.uniform(0.5, 2.0), 3),
                    "resistance": round(random.uniform(10, 100), 1),
                },
                "QA_CHECKS": [
                    {"test": "visual_inspection", "passed": True, "date": "2024-01-15"},
                    {
                        "test": "electrical_test",
                        "passed": random.choice([True, False]),
                        "date": "2024-01-16",
                    },
                    {"test": "thermal_cycling", "passed": True, "date": "2024-01-17"},
                ],
            },
            "metadata": {
                "created_by": f"user_{random.randint(1, 100)}",
                "created_at": (
                    datetime.now() - timedelta(days=random.randint(1, 365))
                ).isoformat(),
                "updated_at": datetime.now().isoformat(),
                "version": random.randint(1, 10),
                "tags": random.sample(
                    ["prototype", "production", "test", "experimental", "certified"],
                    random.randint(1, 3),
                ),
                "flags": {
                    "is_prototype": random.choice([True, False]),
                    "requires_special_handling": random.choice([True, False]),
                    "has_known_issues": random.choice([True, False]),
                },
            },
        }

        return module_data

    @staticmethod
    def generate_multiple_modules(count=5):
        """Generate multiple module data structures"""
        modules = []
        for _ in range(count):
            modules.append(ModuleTestDataGenerator.generate_full_module_data())
        return modules


# Example usage and test data
if __name__ == "__main__":
    generator = ModuleTestDataGenerator()

    # Generate a single module
    single_module = generator.generate_full_module_data()
    print("Single module example:")
    print(f"Name: {single_module['moduleName']}")
    print(f"Children count: {len(single_module['children'])}")
    print(f"Has connections: {bool(single_module['crateSide'])}")

    # Generate multiple modules
    multiple_modules = generator.generate_multiple_modules(3)
    print(f"\nGenerated {len(multiple_modules)} modules")
    for module in multiple_modules:
        print(f"- {module['moduleName']} ({module['status']})")
