import typing


class APScheduler:

    def init_app(self, app: typing.Any) -> None:
        ...

    def start(self, paused: bool = ...) -> None:
        ...

    def add_job(self, id: typing.Any, func: typing.Any,
                **kwargs: typing.Any) -> None:
        ...
