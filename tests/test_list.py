# Standard library
import unittest.mock
import copy

# Installed
import pytest
import requests
import json

# Own modules
import dds_cli

RETURNED_PROJECTS_JSON = {
    "project_info": [
        {
            "Last updated": "Tue, 23 Nov 2021 10:27:42 GMT",
            "PI": "PI Name 1",
            "Project ID": "project_1",
            "Size": 20,
            "Status": "Available",
            "Title": "First Project",
        },
        {
            "Last updated": "Wed, 24 Nov 2021 10:27:42 GMT",
            "PI": "PI Name 2",
            "Project ID": "project_2",
            "Size": 30,
            "Status": "In Progress",
            "Title": "Second Project",
        },
    ],
    "total_size": 0,
    "total_usage": {"cost": 0.0, "usage": 0.0},
}


RETURNED_FILES_JSON = {
    "files_folders": [
        {"folder": False, "name": "simple_file.txt"},
        {"folder": False, "name": "simple_file2.txt"},
        {"folder": False, "name": "simple_file3.txt"},
        {"folder": True, "name": "subdir1"},
        {"folder": True, "name": "subdir3"},
        {"folder": True, "name": "subdir2"},
    ]
}

# Need to have two different ones since the dds code modifies the dictionary object
RETURNED_FILES_RECURSIVE_BOTTOM = {
    "files_folders": [
        {"folder": False, "name": "simple_file4.txt"},
        {"folder": False, "name": "simple_file5.txt"},
    ]
}


@pytest.fixture
def ls_runner(runner):
    """Run dds ls without a project specified."""

    def _run(cmd_list):
        return runner(cmd_list)

    yield _run


@pytest.fixture
def list_request():
    """A fixture that mocks the requests.get method.

    The functioned returned by this fixture takes parameters that adjust the status_code,
    return_json, ok, and side_effect.
    """
    with unittest.mock.patch.object(requests, "get") as mock_obj:

        def _request_mock(status_code, return_json=dict(), ok=True, side_effect=None):
            mock_returned_request = unittest.mock.MagicMock(status_code=status_code, ok=ok)
            if side_effect:
                mock_returned_request.json.side_effect = side_effect
            else:
                mock_returned_request.json.return_value = return_json
            mock_obj.return_value = mock_returned_request
            return mock_obj

        yield _request_mock


def test_list_no_projects(ls_runner, list_request):
    """Test that the list command works when no project is specified nor returned."""

    list_request_OK = list_request(200)
    result = ls_runner(["ls"])

    assert result.exit_code == 0
    list_request_OK.assert_called_with(
        dds_cli.DDSEndpoint.LIST_PROJ,
        headers=unittest.mock.ANY,
        params={"usage": False, "project": None},
    )

    assert "No project info was retrieved" in result.stderr
    assert "" == result.stdout


def test_list_no_project_specified(ls_runner, list_request):
    """Test that the list command works when no project is specified."""

    list_request_OK = list_request(200, return_json=RETURNED_PROJECTS_JSON)
    result = ls_runner(["ls"])

    assert result.exit_code == 0
    list_request_OK.assert_called_with(
        dds_cli.DDSEndpoint.LIST_PROJ,
        headers=unittest.mock.ANY,
        params={"usage": False, "project": None},
    )

    for substring in [
        "project_1",
        "project_2",
        "PI Name 1",
        "PI Name 2",
        "Available",
        "In Progress",
        "Tue, 23 Nov",
        "Wed, 24 Nov",
        "20 B",
        "30 B",
        "────────────────",  # Hack to test that there's a table printed
    ]:
        assert substring in result.stdout
    assert "" == result.stderr  # Click testing framework aborts any interactivity


def test_list_no_project_specified_json(ls_runner, list_request):
    """Test that the list command works when no project is specified with json output."""

    list_request_OK = list_request(200, return_json=RETURNED_PROJECTS_JSON)
    result = ls_runner(["ls", "--json"])

    assert result.exit_code == 0
    list_request_OK.assert_called_with(
        dds_cli.DDSEndpoint.LIST_PROJ,
        headers=unittest.mock.ANY,
        params={"usage": False, "project": None},
    )

    try:
        json_output = json.loads(result.stdout)
    except json.JSONDecodeError:
        assert False, "stdout is not JSON"

    project_ids = [project["Project ID"] for project in json_output]
    assert ["project_1", "project_2"] == project_ids


def test_list_with_project(ls_runner, list_request):
    """Test that the list command works when a project is specified."""
    # Need to use deepcopy to be able to reuse the JSON object for other tests
    # since the DataLister.list_recursive uses pop on this dictionary
    list_request_OK = list_request(200, return_json=copy.deepcopy(RETURNED_FILES_JSON))
    result = ls_runner(["ls", "project_1"])

    assert result.exit_code == 0
    list_request_OK.assert_called_with(
        dds_cli.DDSEndpoint.LIST_FILES,
        params={"project": "project_1"},
        json={"subpath": None, "show_size": False},
        headers=unittest.mock.ANY,
    )
    print(result.stdout)
    for substring in [
        "Files / directories in project: project_1",
        "simple_file.txt",
        "simple_file2.txt",
        "simple_file3.txt",
        "subdir1",
        "subdir3",
        "subdir2",
    ]:
        assert substring in result.stdout


def test_list_with_project_and_tree(ls_runner, list_request):
    """Test that the list command works when a project is specified."""

    list_request_OK = list_request(
        200,
        side_effect=[
            copy.deepcopy(RETURNED_FILES_JSON),
            copy.deepcopy(RETURNED_FILES_RECURSIVE_BOTTOM),
            copy.deepcopy(RETURNED_FILES_RECURSIVE_BOTTOM),
            copy.deepcopy(RETURNED_FILES_RECURSIVE_BOTTOM),
        ],
    )

    result = ls_runner(["ls", "--tree", "project_1"])

    assert result.exit_code == 0
    list_request_OK.assert_any_call(
        dds_cli.DDSEndpoint.LIST_FILES,
        params={"project": "project_1"},
        json={"subpath": None, "show_size": False},
        headers=unittest.mock.ANY,
    )

    list_request_OK.assert_any_call(
        dds_cli.DDSEndpoint.LIST_FILES,
        params={"project": "project_1"},
        json={"subpath": "subdir1", "show_size": False},
        headers=unittest.mock.ANY,
    )

    list_request_OK.assert_any_call(
        dds_cli.DDSEndpoint.LIST_FILES,
        params={"project": "project_1"},
        json={"subpath": "subdir2", "show_size": False},
        headers=unittest.mock.ANY,
    )

    for substring in [
        "Files & directories in project: project_1",
        "simple_file.txt",
        "simple_file2.txt",
        "simple_file3.txt",
        "subdir1",
        "subdir2",
    ]:
        assert substring in result.stdout


def test_list_with_project_and_tree_json(ls_runner, list_request):
    """Test that the list command works when a project is specified."""

    list_request_OK = list_request(
        200,
        side_effect=[
            copy.deepcopy(RETURNED_FILES_JSON),
            copy.deepcopy(RETURNED_FILES_RECURSIVE_BOTTOM),
            copy.deepcopy(RETURNED_FILES_RECURSIVE_BOTTOM),
            copy.deepcopy(RETURNED_FILES_RECURSIVE_BOTTOM),
        ],
    )

    result = ls_runner(["ls", "--tree", "--json", "project_1"])

    assert result.exit_code == 0
    list_request_OK.assert_any_call(
        dds_cli.DDSEndpoint.LIST_FILES,
        params={"project": "project_1"},
        json={"subpath": None, "show_size": False},
        headers=unittest.mock.ANY,
    )

    list_request_OK.assert_any_call(
        dds_cli.DDSEndpoint.LIST_FILES,
        params={"project": "project_1"},
        json={"subpath": "subdir1", "show_size": False},
        headers=unittest.mock.ANY,
    )

    list_request_OK.assert_any_call(
        dds_cli.DDSEndpoint.LIST_FILES,
        params={"project": "project_1"},
        json={"subpath": "subdir2", "show_size": False},
        headers=unittest.mock.ANY,
    )

    try:
        json_output = json.loads(result.stdout)
    except json.JSONDecodeError:
        assert False, "stdout is not JSON"

    assert json_output.has_key("simple_file.txt")
