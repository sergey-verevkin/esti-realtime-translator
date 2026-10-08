import sys
from pathlib import Path
import time
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from transcribe import PCMSource, CHUNK_BYTES


class SourceTests(unittest.TestCase):
    def test_queue_overload_is_explicit(self):
        source = PCMSource([sys.executable, "-c",
            f"import sys; sys.stdout.buffer.write(bytes({CHUNK_BYTES * 10})); sys.stdout.flush()"],
            live=True, capacity=1)
        try:
            self.assertTrue(source.done.wait(3))
            self.assertLessEqual(source.chunks.qsize(), 1)
            with self.assertRaisesRegex(RuntimeError, "queue exceeded"):
                source.next()
        finally:
            source.close()

    def test_file_short_final_chunk_and_eof(self):
        source = PCMSource([sys.executable, "-c",
            f"import sys; sys.stdout.buffer.write(bytes({CHUNK_BYTES + 20})); sys.stdout.flush()"], live=False)
        try:
            self.assertEqual(len(source.next()[0]), CHUNK_BYTES)
            self.assertEqual(len(source.next()[0]), 20)
            self.assertIsNone(source.next())
        finally:
            source.close()

    def test_format_mismatch_fails(self):
        source = PCMSource([sys.executable, "-c",
            'import sys,time; print(\'FORMAT {"sample_rate":48000,"channels_per_frame":1,"bits_per_channel":16,"is_float":false}\',file=sys.stderr,flush=True); time.sleep(.1)'],
            live=True)
        try:
            deadline = time.monotonic() + 3
            while source.error is None and time.monotonic() < deadline:
                time.sleep(.01)
            with self.assertRaisesRegex(RuntimeError, "format mismatch"):
                source.next()
        finally:
            source.close()


if __name__ == "__main__":
    unittest.main()
