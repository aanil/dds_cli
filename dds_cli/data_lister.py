"""Data Lister -- Lists the projects and project content."""

###############################################################################
# IMPORTS ########################################################### IMPORTS #
###############################################################################

# Standard library
from dataclasses import dataclass
import logging
import os
import pathlib
from typing import Tuple, Union, List

# Installed
import requests
import simplejson
from rich.padding import Padding
from rich.table import Table
from rich.tree import Tree

# Own modules
from dds_cli import base
from dds_cli import exceptions
from dds_cli import DDSEndpoint
from dds_cli import text_handler as th

import dds_cli.utils

###############################################################################
# START LOGGING CONFIG ################################# START LOGGING CONFIG #
###############################################################################

LOG = logging.getLogger(__name__)

###############################################################################
# CLASSES ########################################################### CLASSES #
###############################################################################


class DataLister(base.DDSBaseClass):
    """Data lister class."""

    def __init__(
        self,
        method: str = "ls",
        username: str = None,
        config: pathlib.Path = None,
        project: str = None,
        project_level: bool = False,
        show_usage: bool = False,
        tree: bool = False,
    ):
        # Only method "ls" can use the DataLister class
        if method != "ls":
            raise exceptions.InvalidMethodError(
                attempted_method=method, message="DataLister attempting unauthorized method"
            )

        # Initiate DDSBaseClass to authenticate user
        super().__init__(username=username, config=config, project=project, method=method)

        self.show_usage = show_usage
        self.tree = tree

    # Public methods ########################### Public methods #
    def sort_projects(self, projects, sort_by="id"):
        """Sort the projects according to ID and either default or chosen column."""

        # Lower case sort_by options and their column title equivalents
        sorting_dict = {
            "id": "Project ID",
            "title": "Title",
            "pi": "PI",
            "status": "Status",
            "updated": "Last updated",
            "size": "Size",
            "usage": "GBHours",
            "cost": "Cost",
        }

        # Get lower case option
        sort_by = sort_by.lower()

        # Check if sorting column allowed
        if sort_by in ["usage", "cost"] and not self.show_usage:
            LOG.warning(f"Can only sort by {sort_by} when using the --usage flag.")
            sort_by = "updated"

        # Sort according to ID
        sorted_projects = sorted(projects, key=lambda i: i["Project ID"])

        # Sort again according to chosen of default option
        sort_by = sorting_dict.get(sort_by)
        if sort_by:
            sorted_projects = sorted(
                sorted_projects,
                key=lambda t: (t[sort_by] is None, t[sort_by]),
                reverse=sort_by == sorting_dict.get("updated"),
            )

        return sorted_projects

    def format_columns(self, total_size=None, usage_info=None):
        """Define the formatting for the project table according to what is returned from API."""

        default_format = {"justify": "left", "style": "", "footer": "", "overflow": "fold"}

        # Choose formattting
        column_formatting = {
            "Project ID": {
                "justify": default_format.get("justify"),
                "style": "green",
                "footer": "Total" if self.show_usage else default_format.get("footer"),
                "overflow": default_format.get("overflow"),
            },
            **{x: default_format for x in ["Title", "PI", "Status", "Last updated"]},
            "Size": {
                "justify": "center",
                "style": default_format.get("style"),
                "footer": total_size,
                "overflow": "ellipsis",
            },
        }

        if usage_info and self.show_usage:
            # Only display costs above 1 kr
            column_formatting.update(
                {
                    "GBHours": {
                        "justify": "center",
                        "style": default_format.get("style"),
                        "footer": str(usage_info["gbhours"]),
                        "overflow": "ellipsis",
                    },
                    "Cost": {
                        "justify": "center",
                        "style": default_format.get("style"),
                        "footer": str(usage_info["cost"]),
                        "overflow": "ellipsis",
                    },
                }
            )

        return column_formatting

    def list_projects(self, sort_by="Updated"):
        """Gets a list of all projects the user is involved in."""

        # Get projects from API
        try:
            response = requests.get(
                DDSEndpoint.LIST_PROJ, headers=self.token, params={"usage": self.show_usage}
            )
        except requests.exceptions.RequestException as err:
            raise exceptions.ApiRequestError(message=str(err))

        # Check resposne
        if not response.ok:
            raise exceptions.APIError(f"Failed to get list of projects: {response.text}")

        # Get result from API
        try:
            resp_json = response.json()
        except simplejson.JSONDecodeError as err:
            raise exceptions.APIError(f"Could not decode JSON response: {err}")

        # Cancel if user not involved in any projects
        usage_info = resp_json.get("total_usage")
        total_size = resp_json.get("total_size")
        project_info = resp_json.get("project_info")
        if not project_info:
            raise exceptions.NoDataError("No project info was retrieved. No files to list.")

        # Sort projects according to chosen or default, first ID
        sorted_projects = self.sort_projects(projects=project_info, sort_by=sort_by)

        # Column format
        column_formatting = self.format_columns(total_size=total_size, usage_info=usage_info)

        # Create table
        table = Table(
            title="Your Projects",
            show_header=True,
            header_style="bold",
            show_footer=self.show_usage,
            caption=(
                "The cost is calculated from the pricing provided by Safespring (unit kr/GB/month) "
                "and is therefore approximate. Contact the Data Centre for more details."
            )
            if self.show_usage
            else None,
        )

        # Add columns to table
        for colname, colformat in column_formatting.items():
            table.add_column(
                colname,
                justify=colformat["justify"],
                style=colformat["style"],
                footer=colformat["footer"],
                overflow=colformat["overflow"],
            )

        # Add all column values for each row to table
        for proj in sorted_projects:
            table.add_row(*[proj[i] for i in column_formatting])

        # Print to stdout if there are any lines
        if table.columns:
            # Use a pager if output is taller than the visible terminal
            if len(sorted_projects) + 5 > dds_cli.utils.console.height:
                with dds_cli.utils.console.pager():
                    dds_cli.utils.console.print(table)
            else:
                dds_cli.utils.console.print(table)
        else:
            raise exceptions.NoDataError(f"No projects found")

        # Return the list of projects
        return sorted_projects

    def list_files(self, folder: str = None, show_size: bool = False):
        """Create a tree displaying the files within the project."""

        LOG.info(f"Listing files for project '{self.project}'")
        if folder:
            LOG.info(f"Showing files in folder '{folder}'")

        # Make call to API
        try:
            response = requests.get(
                DDSEndpoint.LIST_FILES,
                params={"subpath": folder, "show_size": show_size},
                headers=self.token,
            )
        except requests.exceptions.RequestException as err:
            raise exceptions.APIError(f"Problem with database response: '{err}'")

        if not response.ok:
            raise exceptions.APIError(f"Failed to get list of files: '{response.text}'")

        # Get response
        try:
            resp_json = response.json()
            print(resp_json)
        except simplejson.JSONDecodeError as err:
            raise exceptions.APIError(f"Could not decode JSON response: '{err}'")

        # Check if project empty
        if "num_items" in resp_json and resp_json["num_items"] == 0:
            raise exceptions.NoDataError(f"Project '{self.project}' is empty.")

        # Get files
        files_folders = resp_json["files_folders"]

        # Sort the file/folders according to names
        sorted_files_folders = sorted(files_folders, key=lambda f: f["name"])

        # Create tree
        tree_title = folder or f"Files / directories in project: [green]{self.project}"
        tree = Tree(f"[bold magenta]{tree_title}")

        if not sorted_files_folders:
            raise exceptions.NoDataError(f"Could not find folder: '{folder}'")

        # Get max length of file name
        max_string = max([len(x["name"]) for x in sorted_files_folders])

        # Get max length of size string
        max_size = max(
            [
                len(x["size"].split(" ")[0])
                for x in sorted_files_folders
                if show_size and "size" in x
            ],
            default=0,
        )

        # Visible folders
        visible_folders = []

        # Add items to tree
        for x in sorted_files_folders:
            # Check if string is folder
            is_folder = x.pop("folder")

            # Att 1 for folders due to trailing /
            tab = th.TextHandler.format_tabs(
                string_len=len(x["name"]) + (1 if is_folder else 0),
                max_string_len=max_string,
            )

            # Add formatting if folder and set string name
            line = ""
            if is_folder:
                line = "[bold deep_sky_blue3]"
                visible_folders.append(x["name"])
            line += x["name"] + ("/" if is_folder else "")

            # Add size to line if option specified
            if show_size and "size" in x:
                line += f"{tab}{x['size'].split()[0]}"

                # Define space between number and size format
                tabs_bf_format = th.TextHandler.format_tabs(
                    string_len=len(x["size"]), max_string_len=max_size, tab_len=2
                )
                line += f"{tabs_bf_format}{x['size'].split()[1]}"
            tree.add(line)

        # Print output to stdout
        if len(files_folders) + 5 > dds_cli.utils.console.height:
            with dds_cli.utils.console.pager():
                dds_cli.utils.console.print(Padding(tree, 1))
        else:
            dds_cli.utils.console.print(Padding(tree, 1))

        # Return variable
        return visible_folders

    def list_recursive(self, show_size: bool = False):
        @dataclass
        class FileTree:
            """
            Container class for holding information about the remote file tree
            """

            subtrees: List[Union["FileTree", Tuple[str, str]]] = None
            name: str = None

        def _construct_file_tree(folder: str, basename: str) -> Tuple[FileTree, int, int]:
            """
            Recurses through the project directories and constructs a file tree
            by subsequent calls to the API
            """
            # Make call to API
            try:
                resp_json = requests.get(
                    DDSEndpoint.LIST_FILES,
                    params={"subpath": folder, "show_size": show_size},
                    headers=self.token,
                )
            except requests.exceptions.RequestException as err:
                raise exceptions.APIError(f"Problem with database response: '{err}'")

            resp_json = resp_json.json()
            tree = FileTree([], f"{basename}/")
            sorted_files_folders = sorted(resp_json["files_folders"], key=lambda f: f["name"])

            if not sorted_files_folders:
                raise exceptions.NoDataError(f"Could not find folder: '{folder}'")

            # Get max length of file name
            max_string = max([len(x["name"]) for x in sorted_files_folders])

            # Get max length of size string
            max_size = max(
                [
                    len(x["size"].split(" ")[0])
                    for x in sorted_files_folders
                    if show_size and "size" in x
                ],
                default=0,
            )
            # Rich outputs precisely one line per file/folder
            for f in sorted_files_folders:
                is_folder = f.pop("folder")

                if not is_folder:
                    tree.subtrees.append((f["name"], f.get("size") if show_size else None))
                else:
                    subtree, _max_string, _max_size = _construct_file_tree(
                        os.path.join(folder, f["name"]) if folder else f["name"],
                        f"[bold deep_sky_blue3]{f['name']}",
                    )
                    # Due to indentation, the filename strings of
                    # subdirectories are 4 characters deeper than
                    # their parent directories
                    max_string = max(max_string, _max_string + 4)
                    max_size = max(max_size, _max_size)
                    tree.subtrees.append(subtree)

            return tree, max_string, max_size

        def _construct_rich_tree(
            file_tree: FileTree, max_str: int, max_size: int, depth: int
        ) -> Tuple[Tree, int]:
            """
            Construct the rich tree from the file tree
            """
            tree = Tree(file_tree.name)
            tree_length = len(file_tree.subtrees)
            for node in file_tree.subtrees:
                if isinstance(node, FileTree):
                    subtree, length = _construct_rich_tree(node, max_str, max_size, depth + 1)
                    tree.add(subtree)
                    tree_length += length
                else:
                    line = node[0]
                    if show_size and node[1] is not None:
                        tab = th.TextHandler.format_tabs(
                            string_len=len(node[0]),
                            max_string_len=max_str - 4 * depth,
                        )
                        line += f"{tab}{node[1].split()[0]}"

                        # Define space between number and size format
                        tabs_bf_format = th.TextHandler.format_tabs(
                            string_len=len(node[1].split()[1]),
                            max_string_len=max_size,
                            tab_len=2,
                        )
                        line += f"{tabs_bf_format}{node[1].split()[1]}"
                    tree.add(line)

            return tree, tree_length

        # We use two tree walks, one for file search and one for Rich tree
        # constructing, since it is difficult to compute the correct size
        # indentation without the whole tree
        file_tree, max_string, max_size = _construct_file_tree(
            None, f"[bold magenta]Files & directories in project: [green]{self.project}"
        )

        tree, tree_length = _construct_rich_tree(file_tree, max_string, max_size, 0)

        # The first header is not accounted for by the recursion
        tree_length += 1

        # Check if the tree is t0o large to be printed directly
        # and use a pager if that is the case
        if tree_length > dds_cli.utils.console.height:
            with dds_cli.utils.console.pager():
                dds_cli.utils.console.print(
                    Padding(
                        tree,
                        1,
                    )
                )
        else:
            dds_cli.utils.console.print(
                Padding(
                    tree,
                    1,
                )
            )
