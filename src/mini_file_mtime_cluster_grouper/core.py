"""Group files into buckets by mtime ranges.

This module exists for archive and rotation workflows that need to bucket
files by when they were last modified — hourly for near-term rotation, daily
for long-term retention. The design is deliberately narrow: it takes a clock
function (so tests never touch wall-clock time) and an epoch (so the definition
of "day zero" is explicit), and it returns clusters keyed by integer bucket
numbers. Cluster 0 is the most recent bucket; higher numbers are older.

A key decision: bucket boundaries are anchored to a fixed epoch and computed
by integer division of (clock() - epoch) by the bucket size. This means the
boundary of "bucket 0" is not midnight of today — it is the epoch plus N full
buckets up to the clock. If you need calendar-day boundaries, choose an epoch
that is itself midnight in your timezone and a bucket size that divides evenly
into a day. This avoids pulling in timezone-aware datetime logic for what is
fundamentally an arithmetic grouping problem.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional


@dataclass(frozen=True)
class Cluster:
    """A group of files that share an mtime bucket.

    bucket: integer index; 0 is the most recent bucket, higher = older.
    start:  the lower bound of the bucket's time range (inclusive, float).
    end:    the upper bound of the bucket's time range (exclusive, float).
    files:  paths of files in this bucket, in the order they were yielded.
    """
    bucket: int
    start: float
    end: float
    files: List[str] = field(default_factory=list)


class MtimeGrouper:
    """Group file paths into mtime-based buckets.

    bucket_seconds: size of each bucket in seconds (must be > 0).
    clock:          a callable returning the current time as a float, in the
                    same units os.stat uses (seconds since the Unix epoch).
    epoch:          reference time to anchor bucket boundaries. Buckets are
                    numbered by int((clock() - epoch) // bucket_seconds).
                    Defaults to 0 (the Unix epoch). Must be <= clock().
    on_stat_error:  when a stat call fails, if None the exception propagates;
                    if a callable, it receives (path, exception) and its return
                    value (a float mtime) is used for that file.
    """

    def __init__(
        self,
        bucket_seconds: float,
        *,
        clock: Callable[[], float] = None,
        epoch: float = 0.0,
        on_stat_error: Optional[Callable[[str, BaseException], float]] = None,
    ) -> None:
        if bucket_seconds <= 0:
            raise ValueError(f"bucket_seconds must be positive, got {bucket_seconds!r}")
        self.bucket_seconds = float(bucket_seconds)
        self.clock = clock if clock is not None else self._default_clock
        self.epoch = float(epoch)
        self.on_stat_error = on_stat_error

    @staticmethod
    def _default_clock() -> float:
        return os.time.time()

    def _bucket_of(self, mtime: float, now: float) -> int:
        """Return the bucket index for mtime relative to now.

        Bucket 0 covers [now - bucket_seconds, now). Bucket n (n>0) covers the
        interval bucket_seconds earlier. Buckets for mtimes in the future
        (newer than now) get negative indices, which is a caller error we
        surface as ValueError.
        """
        delta = now - mtime
        bucket = int(delta // self.bucket_seconds)
        return bucket

    def group(self, paths: List[str]) -> Dict[int, Cluster]:
        """Group paths by mtime bucket.

        Returns a dict mapping bucket index -> Cluster. Only non-empty buckets
        appear. Files are stat'd once each, in iteration order.
        """
        now = self.clock()
        if self.epoch > now:
            raise ValueError(
                f"epoch ({self.epoch}) is in the future relative to clock ({now})"
            )
        clusters: Dict[int, Cluster] = {}
        for path in paths:
            mtime = self._stat_mtime(path, now)
            bucket = self._bucket_of(mtime, now)
            if bucket < 0:
                raise ValueError(
                    f"{path!r} has mtime {mtime} in the future "
                    f"(now={now}); cannot assign to a past bucket"
                )
            if bucket not in clusters:
                bucket_start = now - (bucket + 1) * self.bucket_seconds
                bucket_end = now - bucket * self.bucket_seconds
                clusters[bucket] = Cluster(
                    bucket=bucket,
                    start=bucket_start,
                    end=bucket_end,
                    files=[],
                )
            clusters[bucket].files.append(path)
        return clusters

    def _stat_mtime(self, path: str, now: float) -> float:
        try:
            return float(os.stat(path).st_mtime)
        except OSError as exc:
            if self.on_stat_error is None:
                raise
            mtime = self.on_stat_error(path, exc)
            return float(mtime)


def group_files(
    paths: List[str],
    bucket_seconds: float,
    *,
    clock: Callable[[], float] = None,
    epoch: float = 0.0,
    on_stat_error: Optional[Callable[[str, BaseException], float]] = None,
) -> Dict[int, Cluster]:
    """Convenience wrapper: construct a grouper and call group() in one step."""
    return MtimeGrouper(
        bucket_seconds,
        clock=clock,
        epoch=epoch,
        on_stat_error=on_stat_error,
    ).group(paths)
