import traceback
import typing

import azure.storage.blob

from lib import config

_CONTENT_TYPE = 'text/plain; charset=utf-8'
_CACHE_CONTROL = f'public, max-age={365 * 24 * 3600}, immutable'


class BlobClient:
    """A base class for a client for uploading blobs to the cloud."""

    def upload_test_log(self, test_id: int, name: str,
                        rd: typing.BinaryIO) -> typing.Optional[str]:
        """Uploads a test log and returns its URL.

        Args:
            test_id: ID of the test the log is for.
            name: Name (a.k.a. type) of the log.
            rd: Log file opened in binary mode.
        Returns:
            URL of the uploaded log or None if there was an error uploading the
            file.
        """
        try:
            return self._upload(f'test_{test_id}_{name}', rd)
        except Exception:
            traceback.print_exc()
            return None

    def _upload(self, name: str, rd: typing.BinaryIO) -> str:
        """Uploads given file to the cloud.

        Args:
            name: Name under which to upload the file.
            rd: The file opened in binary mode.
        Returns:
            URL of the uploaded file.
        Raises:
            Exception: If uploading fails.
        """
        raise NotImplementedError()


class AzureBlobClient(BlobClient):
    """Interface for uploading blobs to Azure."""

    def __init__(self, **kw: typing.Any) -> None:
        self.__container = kw.pop('container_name')
        self.__server = azure.storage.blob.BlobServiceClient(**kw)

    def _upload(self, name: str, rd: typing.BinaryIO) -> str:
        settings = azure.storage.blob.ContentSettings(
            content_type=_CONTENT_TYPE, cache_control=_CACHE_CONTROL)
        client = self.__server.get_blob_client(container=self.__container,
                                               blob=name)
        client.upload_blob(rd, content_settings=settings, overwrite=True)
        return client.url


def _initialise_factory(
) -> typing.Callable[[], typing.Callable[[], BlobClient]]:
    """Initialises blob store client factory.

    Reads configuration from `~/.nayduck/blob-store.json` file which must
    include a JSON dictionary with at least a "service" key.  The "service" key
    specifies which service to use (currently the only possible value is
    "Azure").  The rest of the dictionary specifies keyword arguments passed to
    the constructor of the "<service>BlobStore" class.

    Returns:
        A factory function which, when called, returns new instances of
        BlobClient for talking to the blob store service.
    Raises:
        SystemExit: if no configuration for exist or it's not properly formatted
            in some way.
    """
    cfg = config.load('blob-store')
    service = cfg.take('service', str)
    cls = globals().get(f'{service}BlobClient', None)
    if not cls or not issubclass(cls, BlobClient):
        raise SystemExit(f'{cfg.path}: {service}: unknown service')
    return lambda: cls(**cfg)  # pylint: disable=unnecessary-lambda


get_client = _initialise_factory()
