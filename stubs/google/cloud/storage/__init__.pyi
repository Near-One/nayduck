import typing


class Blob:
    cache_control: typing.Optional[str]
    content_disposition: typing.Optional[str]
    content_encoding: typing.Optional[str]
    content_language: typing.Optional[str]
    content_type: typing.Optional[str]
    path: str
    public_url: str

    def upload_from_file(self, file_obj: typing.IO[bytes]) -> None:
        ...


class Bucket:

    def blob(self, blob_name: str) -> Blob:
        ...


class Client:

    @classmethod
    def from_service_account_json(cls, json_credentials_path: str) -> 'Client':
        ...

    def bucket(self, bucket_name: str) -> Bucket:
        ...
