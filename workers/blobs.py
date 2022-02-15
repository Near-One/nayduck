import gzip
import os
import re
import shutil
import tempfile
import time
import traceback
import typing

from lib import config

_CONTENT_TYPE = 'text/plain; charset=utf-8'
_CACHE_CONTROL = f'max-age={365 * 24 * 3600}'


class BlobClient:
    """A base class for a client for uploading blobs to the cloud."""

    @classmethod
    def get_test_log_href(cls, test_id: int, name: str) -> str:
        """Returns a path for downloading given test log file.

        The UI back end server provides endpoints for downloading the short logs
        from the database.  For cases where the log is not too long, those short
        logs are in fact the full logs in which case the back end endpoints can
        be used to get the log rather than having to bother uploading the blob
        to the cloud.

        Args:
            test_id: ID of the test the log is for.
            name: Name (a.k.a. type) of the log.
        Returns:
            Returns a path which can be used to download the short log from the
            UI back end.  The path is in '/logs/<test_id>/<name>' format.
        """
        assert re.search('^[-a-zA-Z0-9_][-a-zA-Z0-9_.]*$', name)
        return f'/logs/test/{int(test_id)}/{name}'

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


class GoogleBlobClient(BlobClient):
    """Interface for uploading blobs to Google Cloud Storage."""

    def __init__(self, **kw: typing.Any) -> None:
        import google.cloud.storage  # pylint: disable=import-outside-toplevel

        self.__service = google.cloud.storage.Client.from_service_account_json(
            config.CONFIG_DIR / kw.get('credentials_file', 'credentials.json'))
        self.__bucket = self.__service.bucket(kw.get('bucket_name', 'nayduck'))

    def _upload(self, name: str, rd: typing.BinaryIO) -> str:
        for ext, ctype in (('.gz', 'application/gzip'), ('.xz',
                                                         'application/x-xz'),
                           ('.bz2', 'application/x-bzip2')):
            if name.endswith(ext):
                blob = self.__bucket.blob(name)
                blob.cache_control = _CACHE_CONTROL
                blob.content_type = ctype
                blob.upload_from_file(rd)
                return blob.public_url

        try:
            mtime = os.fstat(rd.fileno()).st_mtime
        except Exception:
            mtime = time.time()

        with tempfile.TemporaryFile() as tmp:
            with gzip.GzipFile(filename=name,
                               mode='wb',
                               fileobj=tmp,
                               mtime=mtime) as wr:
                shutil.copyfileobj(rd, wr)
            tmp.seek(0)

            blob = self.__bucket.blob(name)
            blob.cache_control = _CACHE_CONTROL
            blob.content_encoding = 'gzip'
            blob.content_language = 'en'
            blob.content_type = _CONTENT_TYPE
            blob.upload_from_file(tmp)
            return blob.public_url


def __get_blob_client() -> BlobClient:
    """Initialises and returns a new blob store client.

    Reads configuration from `~/.nayduck/blob-store.json` file which must
    include a JSON dictionary with at least a "service" key.  The "service" key
    specifies which service to use (either "Azure" or "Google").  The rest of
    the dictionary specifies keyword arguments passed to the constructor of the
    "<service>BlobStore" class.

    Returns:
        A new instances of BlobClient for talking to the blob store service.
    Raises:
        SystemExit: if no configuration for exist or it's not properly formatted
            in some way.
    """
    cfg = config.load('blob-store')
    service = cfg.take('service', str)
    cls = globals().get(f'{service}BlobClient', None)
    if not cls or not issubclass(cls, BlobClient):
        raise SystemExit(f'{cfg.path}: {service}: unknown service')
    return typing.cast(BlobClient, cls(**cfg))


__CLIENT = __get_blob_client()


def get_client() -> BlobClient:
    """Returns a Blobclient singleton for talking to blob service."""
    return __CLIENT
