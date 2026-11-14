import os
import tempfile
import unittest
from unittest import mock

import storage


class StorageTests(unittest.TestCase):
    def test_desktop_keeps_files_in_working_directory(self):
        with mock.patch.object(storage, "_on_android", return_value=False):
            self.assertEqual(storage.data_path("alarms.json"), os.path.join(os.getcwd(), "alarms.json"))

    def test_file_left_by_older_version_is_copied_to_persistent_folder(self):
        with tempfile.TemporaryDirectory() as app_dir, tempfile.TemporaryDirectory() as files_dir:
            previous = os.getcwd()
            os.chdir(app_dir)
            try:
                with open("alarms.json", "w", encoding="utf-8") as handle:
                    handle.write("[1]")
                with mock.patch.object(storage, "data_dir", return_value=files_dir):
                    path = storage.data_path("alarms.json")
                    self.assertEqual(path, os.path.join(files_dir, "alarms.json"))
                    with open(path, encoding="utf-8") as handle:
                        self.assertEqual(handle.read(), "[1]")
                    # An existing persistent file is never overwritten by the old copy.
                    with open(path, "w", encoding="utf-8") as handle:
                        handle.write("[2]")
                    storage.data_path("alarms.json")
                    with open(path, encoding="utf-8") as handle:
                        self.assertEqual(handle.read(), "[2]")
            finally:
                os.chdir(previous)


if __name__ == "__main__":
    unittest.main()
