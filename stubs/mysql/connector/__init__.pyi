from typing import Any

from mysql.connector.abstracts import MySQLConnectionAbstract
from mysql.connector import errors


def connect(*args: Any, **kwargs: Any) -> MySQLConnectionAbstract:
    ...
