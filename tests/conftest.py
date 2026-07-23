"""
pytest configuration for the integration_tools test suite.
Shows the test docstring alongside the test name in verbose output.
"""


def pytest_collection_modifyitems(items):
    for item in items:
        lines = (item.obj.__doc__ or "").strip().splitlines()
        doc = lines[0].strip() if lines else ""
        if doc:
            item._nodeid = f"{item.nodeid}  [{doc}]"
