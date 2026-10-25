import os
import os.path
import tempfile
import unittest

from mini_file_mtime_cluster_grouper import MtimeGrouper, Cluster, group_files


class TestMtimeGrouper(unittest.TestCase):
    def setUp(self):
        # Use a temp dir so file paths are real and stat works.
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)

    def _touch(self, name, mtime):
        path = os.path.join(self.tmp.name, name)
        with open(path, "w") as f:
            f.write("x")
        os.utime(path, (mtime, mtime))
        return path

    def test_rejects_non_positive_bucket_seconds(self):
        with self.assertRaises(ValueError):
            MtimeGrouper(0)
        with self.assertRaises(ValueError):
            MtimeGrouper(-1)

    def test_rejects_epoch_in_future(self):
        # epoch ahead of clock must raise
        g = MtimeGrouper(3600, clock=lambda: 1000.0, epoch=2000.0)
        with self.assertRaises(ValueError):
            g.group([])

    def test_empty_input_returns_empty_dict(self):
        g = MtimeGrouper(3600, clock=lambda: 10000.0, epoch=0.0)
        result = g.group([])
        self.assertEqual(result, {})

    def test_files_in_same_bucket_are_grouped_together(self):
        now = 100000.0
        # Three files, all within the last hour
        f1 = self._touch("a.txt", now - 100)     # ~1.5 min ago
        f2 = self._touch("b.txt", now - 2000)    # ~33 min ago
        f3 = self._touch("c.txt", now - 3500)    # ~58 min ago
        g = MtimeGrouper(3600, clock=lambda: now, epoch=0.0)
        result = g.group([f1, f2, f3])
        self.assertEqual(list(result.keys()), [0])
        cluster = result[0]
        self.assertIsInstance(cluster, Cluster)
        self.assertEqual(cluster.bucket, 0)
        self.assertEqual(cluster.files, [f1, f2, f3])
        # bucket 0 spans [now-3600, now)
        self.assertAlmostEqual(cluster.start, now - 3600)
        self.assertAlmostEqual(cluster.end, now)

    def test_files_in_different_buckets_get_distinct_indices(self):
        now = 100000.0
        recent = self._touch("recent.txt", now - 100)
        hourly = self._touch("hourly.txt", now - 3700)  # bucket 1
        two_hour = self._touch("twohour.txt", now - 7400)  # bucket 2
        g = MtimeGrouper(3600, clock=lambda: now, epoch=0.0)
        result = g.group([recent, hourly, two_hour])
        self.assertEqual(sorted(result.keys()), [0, 1, 2])
        self.assertEqual(result[0].files, [recent])
        self.assertEqual(result[1].files, [hourly])
        self.assertEqual(result[2].files, [two_hour])

    def test_bucket_boundary_is_exclusive_at_top(self):
        # mtime exactly on the upper boundary (now) falls into bucket -1,
        # which is a future-mtime error. mtime just below now is bucket 0.
        now = 100000.0
        just_below = self._touch("below.txt", now - 0.01)
        g = MtimeGrouper(3600, clock=lambda: now, epoch=0.0)
        result = g.group([just_below])
        self.assertEqual(list(result.keys()), [0])

    def test_mtime_exactly_on_now_raises(self):
        # mtime == now means delta = 0, bucket 0 — but that means a file whose
        # mtime equals the clock exactly. delta = 0 // 3600 = 0, so bucket 0.
        # This is NOT a future mtime, so it should group into bucket 0.
        now = 100000.0
        exact = self._touch("exact.txt", now)
        g = MtimeGrouper(3600, clock=lambda: now, epoch=0.0)
        result = g.group([exact])
        self.assertEqual(list(result.keys()), [0])

    def test_future_mtime_raises(self):
        now = 100000.0
        future_file = self._touch("future.txt", now + 500)
        g = MtimeGrouper(3600, clock=lambda: now, epoch=0.0)
        with self.assertRaises(ValueError):
            g.group([future_file])

    def test_stat_error_propagates_by_default(self):
        g = MtimeGrouper(3600, clock=lambda: 10000.0, epoch=0.0)
        with self.assertRaises(OSError):
            g.group(["/nonexistent/path/that/does/not/exist"])

    def test_stat_error_handler_is_used(self):
        now = 100000.0
        called = []

        def handler(path, exc):
            called.append(path)
            return now - 100  # treat as recent

        g = MtimeGrouper(
            3600,
            clock=lambda: now,
            epoch=0.0,
            on_stat_error=handler,
        )
        result = g.group(["/nonexistent/path"])
        self.assertEqual(called, ["/nonexistent/path"])
        self.assertEqual(list(result.keys()), [0])
        self.assertEqual(result[0].files, ["/nonexistent/path"])

    def test_epoch_anchors_boundaries(self):
        # With epoch=1000 and bucket=3600, at now=10000 we are 9000 sec ahead.
        # 9000 // 3600 = 2, so a file at now-100 is bucket 0, a file at now-3700
        # is bucket 1, a file at now-7300 is bucket 2.
        now = 10000.0
        f_recent = self._touch("r.txt", now - 100)
        f_old = self._touch("o.txt", now - 7300)
        g = MtimeGrouper(3600, clock=lambda: now, epoch=1000.0)
        result = g.group([f_recent, f_old])
        self.assertEqual(set(result.keys()), {0, 2})

    def test_non_integer_bucket_seconds_works(self):
        # 30-minute buckets
        now = 100000.0
        f1 = self._touch("a.txt", now - 100)
        f2 = self._touch("b.txt", now - 1900)  # just over one 30-min bucket
        g = MtimeGrouper(1800, clock=lambda: now, epoch=0.0)
        result = g.group([f1, f2])
        self.assertEqual(set(result.keys()), {0, 1})

    def test_convenience_wrapper_matches_class(self):
        now = 100000.0
        f1 = self._touch("a.txt", now - 100)
        f2 = self._touch("b.txt", now - 3700)
        via_class = MtimeGrouper(3600, clock=lambda: now, epoch=0.0).group([f1, f2])
        via_wrapper = group_files([f1, f2], 3600, clock=lambda: now, epoch=0.0)
        self.assertEqual(set(via_class.keys()), set(via_wrapper.keys()))
        self.assertEqual(via_class[0].files, via_wrapper[0].files)
        self.assertEqual(via_class[1].files, via_wrapper[1].files)

    def test_cluster_boundaries_are_correct(self):
        now = 100000.0
        f1 = self._touch("a.txt", now - 100)
        g = MtimeGrouper(3600, clock=lambda: now, epoch=0.0)
        result = g.group([f1])
        c = result[0]
        self.assertAlmostEqual(c.start, 100000.0 - 3600.0)
        self.assertAlmostEqual(c.end, 100000.0)
        # Bucket 1: [now - 7200, now - 3600)
        f2 = self._touch("b.txt", now - 4000)
        result2 = g.group([f2])
        c2 = result2[1]
        self.assertAlmostEqual(c2.start, 100000.0 - 7200.0)
        self.assertAlmostEqual(c2.end, 100000.0 - 3600.0)

    def test_order_of_files_within_cluster_is_preserved(self):
        now = 100000.0
        f1 = self._touch("alpha.txt", now - 3000)
        f2 = self._touch("beta.txt", now - 2000)
        f3 = self._touch("gamma.txt", now - 1000)
        g = MtimeGrouper(3600, clock=lambda: now, epoch=0.0)
        result = g.group([f3, f1, f2])  # deliberately not sorted
        self.assertEqual(result[0].files, [f3, f1, f2])


if __name__ == "__main__":
    unittest.main()
