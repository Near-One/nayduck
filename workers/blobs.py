import os
import traceback
import typing

import azure.storage.blob

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

    def __init__(self, conn_str: str) -> None:
        self.__server = \
            azure.storage.blob.BlobServiceClient.from_connection_string(
                conn_str)

    def _upload(self, name: str, rd: typing.BinaryIO) -> str:
        settings = azure.storage.blob.ContentSettings(
            content_type=_CONTENT_TYPE, cache_control=_CACHE_CONTROL)
        client = self.__server.get_blob_client(container='logs', blob=name)
        client.upload_blob(rd, content_settings=settings, overwrite=True)
        return client.url


_AZURE_CONNECTION_STR = os.environ.pop('AZURE_STORAGE_CONNECTION_STRING')


def get_client() -> BlobClient:
    """Returns a new client for uploading blobs to the cloud."""
    return AzureBlobClient(_AZURE_CONNECTION_STR)
