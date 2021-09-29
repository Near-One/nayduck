import typing

import flask
import prometheus_client
import prometheus_flask_exporter
import sqlalchemy.engine

from . import backend_db

_Samples = typing.Sequence[typing.Tuple[str, typing.Mapping[str, str], int]]


class StatusMetric(prometheus_client.metrics.MetricWrapperBase):  # type: ignore
    _type = prometheus_client.Enum._type  # pylint: disable=protected-access

    def __init__(self, name: str, documentation: str, *,
                 registry: prometheus_client.registry.CollectorRegistry):
        super().__init__(name=name,
                         documentation=documentation,
                         registry=registry)
        self.__samples: _Samples = ()

    def set(self, statuses: typing.Iterable[sqlalchemy.engine.Row]) -> None:

        def asdict(row: sqlalchemy.engine.Row) -> typing.Dict[str, str]:
            # pylint: disable=protected-access
            return {key: str(value) for key, value in row._mapping.items()}

        self.__samples = tuple(('', asdict(status), 1) for status in statuses)

    def _metric_init(self) -> None:
        pass

    def _child_samples(self) -> _Samples:
        return self.__samples


def _set_status(pmetric: prometheus_client.Gauge,
                statuses: typing.List[typing.Sequence[typing.Any]]) -> None:
    pmetric.clear()
    for labels in statuses:
        pmetric.labels(*[str(label) for label in labels]).set(1)


class Collector:

    def __init__(self, registry: prometheus_client.registry.CollectorRegistry):
        self.m_nightly_id = prometheus_client.Gauge(
            'nayduck_nightly_run_id',
            'Run id of the last nightly run',
            registry=registry)
        self.m_nightly_start = prometheus_client.Gauge(
            'nayduck_nightly_start_timestamp',
            'Timestamp of when the last nightly run was scheduled',
            registry=registry)
        self.m_nightly_finish = prometheus_client.Gauge(
            'nayduck_nightly_finish_timestamp',
            ('Timestamp of when the last nightly run finished '
             'or NaN if still running.'),
            registry=registry)
        self.m_nightly_build_status = StatusMetric(
            'nayduck_nightly_build_status',
            'States of builds in the latest nightly run',
            registry=registry)
        self.m_nightly_test_status = StatusMetric(
            'nayduck_nightly_test_status',
            'States of tests in the latest nightly run',
            registry=registry)

    def _all(
            self
    ) -> typing.Sequence[prometheus_client.metrics.MetricWrapperBase]:
        return (self.m_nightly_id, self.m_nightly_start, self.m_nightly_finish,
                self.m_nightly_build_status, self.m_nightly_test_status)

    def describe(self) -> typing.Iterable[prometheus_client.Metric]:
        return [
            core_metric for metric in self._all()
            for core_metric in metric.describe()
        ]

    def collect(self) -> typing.Iterable[prometheus_client.Metric]:
        with backend_db.BackendDB() as server:
            metrics = server.get_metrics()
        if not metrics:
            return self.describe()
        self.m_nightly_id.set(metrics.run_id)
        self.m_nightly_start.set(metrics.start.timestamp())
        self.m_nightly_finish.set(
            metrics.finish.timestamp() if metrics.finish else float('nan'))
        self.m_nightly_test_status.set(metrics.test_statuses)
        self.m_nightly_build_status.set(metrics.build_statuses)
        return [
            core_metric for metric in self._all()
            for core_metric in metric.collect()
        ]


def initialise(app: flask.Flask) -> None:
    registry = prometheus_client.REGISTRY
    registry.register(Collector(registry=None))
    prometheus_flask_exporter.PrometheusMetrics(app,
                                                group_by='endpoint',
                                                registry=registry)
