from __future__ import annotations

from typing import Any, Optional, Sequence


class MySQLConnectionAbstract:
    in_transaction: bool

    def __init__(self, **kwargs: Any) -> None:
        ...

    def connect(self, **kwargs: Any) -> None:
        ...

    def reconnect(self, attempts: int = ..., delay: int = ...) -> None:
        ...

    def disconnect(self) -> None:
        ...

    def close(self) -> None:
        ...

    def is_connected(self) -> bool:
        ...

    def ping(self,
             reconnect: bool = ...,
             attempts: int = ...,
             delay: int = ...) -> None:
        ...

    def commit(self) -> None:
        ...

    def cursor(
        self,
        buffered: Optional[bool] = ...,
        raw: Optional[bool] = ...,
        prepared: Optional[bool] = ...,
        cursor_class: Optional[type] = ...,
        dictionary: Optional[bool] = ...,
        named_tuple: Optional[bool] = ...,
    ) -> MySQLCursorAbstract:
        ...

    def rollback(self) -> None:
        ...

    def start_transaction(
        self,
        consistent_snapshot: bool = ...,
        isolation_level: Optional[str] = ...,
        readonly: Optional[bool] = ...,
    ) -> None:
        ...


class MySQLCursorAbstract:

    def close(self) -> None:
        ...

    # Technically execute has an optional multi argument.  For our stubs assume
    # it’s not there and always false which means return value is always None.
    def execute(self, operation: str, params: Sequence[Any] = ...) -> None:
        ...

    def fetchone(self) -> Optional[dict[str, Any]]:
        ...

    def fetchall(self) -> list[dict[str, Any]]:
        ...

    @property
    def rowcount(self) -> int:
        ...

    @property
    def lastrowid(self) -> Optional[int]:
        ...
