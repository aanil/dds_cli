"""Base class for the DDS CLI. Verifies the users access to the DDS."""

###############################################################################
# IMPORTS ########################################################### IMPORTS #
###############################################################################

# Standard library
import logging
import os
import pathlib

# Installed
import http
import requests
import simplejson

# Own modules
import dds_cli.directory
import dds_cli.timestamp

from dds_cli import (
    DDS_METHODS,
    DDS_DIR_REQUIRED_METHODS,
    DDS_KEYS_REQUIRED_METHODS,
)
from dds_cli import DDSEndpoint
from dds_cli import s3_connector as s3
from dds_cli import user
from dds_cli import exceptions
from dds_cli import utils

###############################################################################
# START LOGGING CONFIG ################################# START LOGGING CONFIG #
###############################################################################

LOG = logging.getLogger(__name__)


###############################################################################
# CLASSES ########################################################### CLASSES #
###############################################################################


class DDSBaseClass:
    """Data Delivery System base class. For common operations."""

    def __init__(
        self,
        username,
        project=None,
        dds_directory: pathlib.Path = None,
        method: str = None,
        authenticate: bool = True,
        method_check: bool = True,
        force_renew_token: bool = False,
        no_prompt: bool = False,
    ):
        """Initialize Base class for authenticating the user and preparing for DDS action."""
        self.username = username
        self.project = project
        self.method_check = method_check
        self.method = method
        self.no_prompt = no_prompt

        if self.method_check:
            # Get attempted operation e.g. put/ls/rm/get
            if self.method not in DDS_METHODS:
                raise exceptions.InvalidMethodError(attempted_method=self.method)
            LOG.debug(f"Attempted operation: {self.method}")

            # Use user defined destination if any specified
            if self.method in DDS_DIR_REQUIRED_METHODS:
                self.dds_directory = dds_cli.directory.DDSDirectory(
                    path=dds_directory
                    if dds_directory
                    else pathlib.Path.cwd()
                    / pathlib.Path(f"DataDelivery_{dds_cli.timestamp.TimeStamp().timestamp}")
                )

                self.failed_delivery_log = self.dds_directory.directories["LOGS"] / pathlib.Path(
                    "dds_failed_delivery.txt"
                )

        # Keyboardinterrupt
        self.stop_doing = False

        # Authenticate the user and get the token
        if authenticate:
            dds_user = user.User(
                username=username,
                force_renew_token=force_renew_token,
                no_prompt=no_prompt,
            )
            self.token = dds_user.token_dict

        # Project access only required if trying to upload, download or list
        # files within project
        if self.method in DDS_KEYS_REQUIRED_METHODS:
            if self.method == "put":
                self.s3connector = self.__get_safespring_keys()

            self.keys = self.__get_project_keys()

            self.status = dict()
            self.filehandler = None

    def __enter__(self):
        """Return self when using context manager."""
        return self

    def __exit__(self, exc_type, exc_value, tb, max_fileerrs: int = 40):
        """Finish and print out delivery summary."""
        if self.method in ["put", "get"]:
            self.__printout_delivery_summary()

        # Exception is not handled
        if exc_type is not None:
            LOG.debug(f"Exception: {exc_type} with value {exc_value}")
            return False

        return True

    # Private methods ############################### Private methods #
    def __get_safespring_keys(self):
        """Get safespring keys."""
        return s3.S3Connector(project_id=self.project, token=self.token)

    def __get_project_keys(self):
        """Get public and private project keys depending on method."""
        # Project public key required for both put and get
        public = self.__get_key()

        # Project private only required for get
        private = self.__get_key(private=True) if self.method == "get" else None

        return private, public

    def __get_key(self, private: bool = False):
        """Get public key for project."""
        key_type = "private" if private else "public"
        # Get key from API
        try:
            response = requests.get(
                DDSEndpoint.PROJ_PRIVATE if private else DDSEndpoint.PROJ_PUBLIC,
                params={"project": self.project},
                headers=self.token,
                timeout=DDSEndpoint.TIMEOUT,
            )
        except requests.exceptions.RequestException as err:
            LOG.fatal(str(err))
            raise SystemExit from err

        if not response.ok:
            message = "Failed getting key from DDS API"
            if response.status_code == http.HTTPStatus.INTERNAL_SERVER_ERROR:
                raise exceptions.ApiResponseError(message=f"{message}: {response.reason}")

            raise exceptions.DDSCLIException(message=f"{message}: {response.json().get('message')}")

        # Get key from response
        try:
            project_public = response.json()
        except simplejson.JSONDecodeError as err:
            LOG.fatal(str(err))
            raise SystemExit from err

        if key_type not in project_public:
            utils.console.print(
                "\n:no_entry_sign: Project access denied: No {key_type} key. :no_entry_sign:\n"
            )
            os._exit(1)

        return project_public[key_type]

    def __printout_delivery_summary(self, max_fileerrs: int = 40):
        """Print out the delivery summary if any files were cancelled."""
        # TODO: Look into a better summary print out - old deleted for now
        any_failed = self.__collect_all_failed()

        # Clear dict to not take up too much space
        self.filehandler.failed.clear()

        if any_failed:
            LOG.info(f"Failed: \n{any_failed}")
            intro_error_message = (
                f"Errors occurred during {'upload' if self.method == 'put' else 'download'}"
            )

            utils.stderr_console.print(
                f"{intro_error_message}. See {self.failed_delivery_log} for more information."
            )

        else:
            # Printout if no cancelled/failed files
            LOG.info(f"\n{'Upload' if self.method == 'put' else 'Download'} completed!\n")

        if self.method == "get" and len(self.filehandler.data) > len(any_failed):
            LOG.info(f"Any downloaded files are located: {self.filehandler.local_destination}.")

    def __collect_all_failed(self, sort: bool = True):
        """Put cancelled files from status in to failed dict and sort the output."""
        # Transform all items to string
        self.filehandler.data = {
            str(file): {str(x): str(y) for x, y in info.items()}
            for file, info in list(self.filehandler.data.items())
        }
        self.status = {
            str(file): {str(x): str(y) for x, y in info.items()}
            for file, info in list(self.status.items())
        }

        # Get cancelled files
        self.filehandler.failed.update(
            {
                file: {
                    **info,
                    "message": self.status[file]["message"],
                    "failed_op": self.status[file]["failed_op"],
                }
                for file, info in self.filehandler.data.items()
                if self.status[file]["cancel"] in [True, "True"]
            }
        )

        # Sort by which directory the files are in
        LOG.debug(self.filehandler.failed)

        # TODO: Sort more?
        return (
            sorted(self.filehandler.failed.items(), key=lambda g: g)
            if sort
            else self.filehandler.failed
        )
