from __future__ import annotations

from typing import Protocol

from ahq.domain.recordings import RecordingInfo


class RecordingStore(Protocol):
    async def add(self, info: RecordingInfo, bundle: bytes) -> RecordingInfo: ...

    async def list(self, *, published_only: bool = False) -> list[RecordingInfo]: ...

    async def get(self, recording_id: str) -> RecordingInfo | None: ...

    async def bundle(self, recording_id: str) -> bytes | None: ...

    async def update(
        self, recording_id: str, *, published: bool | None = None, title: str | None = None
    ) -> RecordingInfo: ...

    async def delete(self, recording_id: str) -> None: ...
