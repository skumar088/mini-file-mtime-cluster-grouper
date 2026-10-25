# mini-file-mtime-cluster-grouper

Groups files into buckets by mtime ranges (hourly, daily, or any interval) for archive or rotation workflows.

```python
import os
import tempfile

from mini_file_mtime_cluster_grouper import MtimeGrouper, group_files

now = 1700000000.0

with tempfile.TemporaryDirectory() as tmp:
    f1 = os.path.join(tmp, "app.log")
    f2 = os.path.join(tmp, "app.1.log")
    for p in (f1, f2):
        open(p, "w").write("x")
    os.utime(f1, (now - 100, now - 100))
    os.utime(f2, (now - 3700, now - 3700))

    # bucket size in seconds; 3600 = hourly
    grouper = MtimeGrouper(3600, clock=lambda: now)
    clusters = grouper.group([f1, f2])
    for bucket, cluster in sorted(clusters.items()):
        print(bucket, cluster.start, cluster.end, cluster.files)

    # or in one call
    clusters = group_files([f1], 86400, clock=lambda: now)
```

## Why this exists

Archive and rotation scripts often need to answer "which files were modified in the last hour? in the last day?" — then move, compress, or delete them per bucket. Doing this with `datetime` and timezone arithmetic gets verbose and error-prone fast. This library reduces it to integer division of elapsed time by a bucket size, anchored to a fixed epoch.

The trade-off: bucket boundaries are arithmetic, not calendar-aligned. Bucket 0 is not "today" — it is the interval `[clock - bucket_seconds, clock)`. If you need midnight-aligned daily buckets, pass an `epoch` that is a midnight timestamp and a `bucket_seconds` of 86400. This keeps the library out of timezone logic entirely, which is the point.

## The awkward edge

Files with mtimes in the future (newer than the clock value) raise `ValueError`. This is deliberate: a future mtime in a rotation workflow usually means a clock skew or a file that was just written, and silently stuffing it into bucket 0 would hide the problem. If you want to tolerate stale or clock-skewed files, stat them yourself and skip the grouper for those paths, or pre-filter.

Stat failures (file missing, permission denied) propagate as `OSError` by default. Pass `on_stat_error=path_callable_returning_mtime` if you want fallback handling.
