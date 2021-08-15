from ._blob_client import BlobClient
from ._models import ContentSettings
import typing


class BlobServiceClient:

    def __init__(self, **kw: typing.Any) -> None:
        ...

    def get_blob_client(self, container: str, blob: str) -> BlobClient:
        ...
