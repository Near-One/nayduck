import socket
import typing


class Process:

    def __init__(self, pid: typing.Optional[int] = ...) -> None:
        ...

    def children(self, recursive: bool = ...) -> list[Process]:
        ...

    def send_signal(self, sig: int) -> None:
        ...


class NoSuchProcess(Exception):
    pass


def wait_procs(procs: list[Process], *,
               timeout: int) -> tuple[list[Process], list[Process]]:
    ...


class _sdiskusage(typing.NamedTuple):
    total: int
    used: int
    free: int
    percent: float


def disk_usage(directory: str) -> _sdiskusage:
    ...


class _snicaddr(typing.NamedTuple):
    family: socket.AddressFamily
    address: str
    netmask: str
    broadcast: str


def net_if_addrs() -> dict[str, list[_snicaddr]]:
    ...
