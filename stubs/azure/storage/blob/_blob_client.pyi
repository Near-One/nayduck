from datetime import datetime
from typing import Any, AnyStr, IO, Iterable, List, Optional, Tuple, Union


class BlobClient:
    url: str

    def upload_blob(self,
                    data: Union[Iterable[AnyStr], IO[AnyStr]],
                    blob_type: str = ...,
                    length: Optional[int] = ...,
                    metadata: Optional[dict[str, str]] = ...,
                    **kwargs: Any) -> Any:
        ...
