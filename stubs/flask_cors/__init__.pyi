import typing as typing
import flask as flask

_T = typing.TypeVar('_T')


class CORS:

    def __init__(
            self,
            app: typing.Optional[flask.Flask],
            resources: typing.Dict[str, typing.Dict[str,
                                                    typing.Any]] = {}) -> None:
        ...


def cross_origin(
    origins: typing.List[str] = []
) -> typing.Callable[[typing.Callable[..., _T]], typing.Callable[..., _T],]:
    ...
