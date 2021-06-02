"""Custom Exception classes"""


class AuthenticationError(Exception):
    """Errors due to user authentication.

    Return the message with Rich no-entry-sign emoji either side.
    """

    def __str__(self):
        return f"\n:no_entry_sign: {self.message} :no_entry_sign:\n"


class UploadError(Exception):
    """Errors relating to file uploads"""


class NoDataError(Exception):
    """Errors when there is no data to do anything with."""



class APIError(Exception):
    """Error connecting to the dds web server"""
