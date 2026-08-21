import os
import unittest

import crawler


class CrawlerDataScopeTests(unittest.TestCase):
    def test_accepts_numeric_draw_file(self):
        root = os.path.join(crawler.DATA_DIR, "1001-2000")
        self.assertTrue(crawler.is_draw_data_file(root, "1237.lotto"))

    def test_rejects_prediction_and_summary_files(self):
        star_root = os.path.join(crawler.DATA_DIR, "star", "1001-1500")
        self.assertFalse(crawler.is_draw_data_file(star_root, "1237.lotto"))
        self.assertFalse(crawler.is_draw_data_file(star_root, "1237_star.lotto"))
        self.assertFalse(crawler.is_draw_data_file(crawler.DATA_DIR, "latest.lotto"))
