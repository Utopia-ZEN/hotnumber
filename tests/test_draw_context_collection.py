import unittest

from PickNumber.draw_context_collection import (
    parse_initial_data,
    _extract_search_page,
    audit_records,
    build_observation,
    import_reviewed_batch,
    parse_number_list,
    parse_video_cards,
    require_model_gate,
    source_record_from_search_result,
)
from PickNumber.order_model import Draw


class DrawContextCollectionTests(unittest.TestCase):
    def test_parse_initial_data_accepts_current_youtube_assignment(self):
        self.assertEqual(parse_initial_data('prefix ytInitialData = {"ok": true} suffix'), {"ok": True})

    def test_discovers_round_date_and_video_source(self):
        page = """
        <a href="https://www.youtube.com/watch?v=abc_123-XYZ" target="_blank">
          <img alt="로또6/45 제1237회 당첨번호 2026년 08월 15일">
        </a>
        """
        records = parse_video_cards(page, "https://example.test/index", "2026-08-21T00:00:00Z")

        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["round"], 1237)
        self.assertEqual(records[0]["draw_date"], "2026-08-15")
        self.assertEqual(records[0]["video_id"], "abc_123-XYZ")
        self.assertEqual(records[0]["review_status"], "pending")

    def test_channel_search_supports_older_title_format(self):
        payload = {
            "contents": [
                {
                    "videoRenderer": {
                        "videoId": "abcdefghijk",
                        "title": {"runs": [{"text": "로또6/45 제1061회 당첨번호 2023년 4월 1일 추첨"}]},
                    }
                },
                {
                    "continuationItemRenderer": {
                        "continuationEndpoint": {"continuationCommand": {"token": "next-page"}}
                    }
                },
            ]
        }
        videos, tokens = _extract_search_page(payload)
        self.assertEqual(videos, [("abcdefghijk", "로또6/45 제1061회 당첨번호 2023년 4월 1일 추첨")])
        self.assertEqual(tokens, ["next-page"])

    def test_source_parser_supports_pre_1055_official_title_format(self):
        page = """
        <a href="https://www.youtube.com/watch?v=0OpotZuvAs0" target="_blank">
          <img alt="로또 제1054회 당첨번호 2023년 2월 11일 추첨">
        </a>
        """
        records = parse_video_cards(page, "https://example.test/index", "2026-08-21T00:00:00Z")
        self.assertEqual(records[0]["round"], 1054)
        self.assertEqual(records[0]["draw_date"], "2023-02-11")

    def test_source_parser_supports_underscore_before_old_draw_date(self):
        page = """
        <a href="https://www.youtube.com/watch?v=TTTPJTMhLy0" target="_blank">
          <img alt="로또 제988회 당첨번호_2021년 11월 6일 추첨">
        </a>
        """
        records = parse_video_cards(page, "https://example.test/index", "2026-08-21T00:00:00Z")
        self.assertEqual(records[0]["round"], 988)
        self.assertEqual(records[0]["draw_date"], "2021-11-06")

    def test_loose_reupload_title_requires_exact_round_and_lotto_context(self):
        record = source_record_from_search_result(
            "https://www.youtube.com/watch?v=zbttQE7N3p0",
            "로또987 1등 당첨번호 추첨방송 Week43 2021",
            "https://www.youtube.com/results?search_query=987",
            "2026-08-21T00:00:00Z",
            987,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["round"], 987)
        self.assertIsNone(record["draw_date"])
        self.assertEqual(record["draw_video_url"], record["source_url"])
        self.assertIsNone(
            source_record_from_search_result(
                "https://www.youtube.com/watch?v=zbttQE7N3p0",
                "로또986 당첨번호",
                "https://example.test",
                "2026-08-21T00:00:00Z",
                987,
            )
        )

    def test_verified_order_must_match_official_draw(self):
        source = {
            "round": 1237,
            "source_channel": "동행복권",
            "source_verified": True,
        }
        draw = Draw(round=1237, numbers=(10, 20, 23, 34, 37, 40), bonus=36)

        record = build_observation(
            source,
            draw,
            [10, 40, 20, 34, 37, 23],
            36,
            325.0,
        )
        self.assertEqual(record["ordered_numbers"], [10, 40, 20, 34, 37, 23])

        with self.assertRaisesRegex(ValueError, "winning-number set"):
            build_observation(source, draw, [10, 40, 20, 34, 37, 45], 36, 325.0)
        with self.assertRaisesRegex(ValueError, "bonus"):
            build_observation(source, draw, [10, 40, 20, 34, 37, 23], 35, 325.0)

    def test_official_archive_english_title_parses_exact_round(self):
        record = source_record_from_search_result(
            "https://www.youtube.com/watch?v=hR0w0y164V8",
            "Lotto 551st Winning Numbers Draw Broadcast",
            "https://www.youtube.com/results?search_query=551",
            "2026-08-21T00:00:00Z",
            551,
        )
        self.assertIsNotNone(record)
        self.assertEqual(record["round"], 551)
        self.assertIsNone(
            source_record_from_search_result(
                "https://www.youtube.com/watch?v=hR0w0y164V8",
                "Lotto 551st Winning Numbers Draw Broadcast",
                "https://www.youtube.com/results?search_query=550",
                "2026-08-21T00:00:00Z",
                550,
            )
        )

    def test_verified_broadcaster_archive_does_not_require_reupload_checklist(self):
        source = {
            "round": 551,
            "source_channel": "SBS STORY",
            "source_channel_url": "https://www.youtube.com/@SBSstory.official",
            "source_type": "official_broadcaster_archive",
            "source_verified": True,
            "metadata_round_verified": True,
        }
        draw = Draw(round=551, numbers=(3, 6, 20, 24, 27, 44), bonus=25)
        record = build_observation(source, draw, [3, 44, 20, 6, 27, 24], 25, 0.0)
        self.assertEqual(record["source_type"], "official_broadcaster_archive")

    def test_reupload_requires_complete_content_verification(self):
        source = {
            "round": 987,
            "source_channel": "로또랩",
            "source_channel_url": "https://www.youtube.com/@lottolab1",
            "source_type": "third_party_reupload",
            "source_verified": False,
            "metadata_round_verified": True,
        }
        draw = Draw(round=987, numbers=(2, 4, 15, 23, 29, 38), bonus=7)
        checks = {
            "round_label_visible": True,
            "continuous_draw_sequence_visible": True,
            "winning_numbers_match": True,
            "bonus_match": True,
        }
        record = build_observation(
            source,
            draw,
            [23, 29, 2, 38, 15, 4],
            7,
            300.0,
            review_method="manual_reupload_video_review",
            content_verification=checks,
        )
        self.assertEqual(record["content_verification"], checks)

        checks["continuous_draw_sequence_visible"] = False
        with self.assertRaisesRegex(ValueError, "content verification"):
            build_observation(
                source,
                draw,
                [23, 29, 2, 38, 15, 4],
                7,
                300.0,
                content_verification=checks,
            )

    def test_gate_stays_closed_until_one_hundred_verified_draws(self):
        records = [
            {
                "round": index,
                "review_status": "verified",
                "ordered_numbers": [1, 2, 3, 4, 5, 6],
                "machine_id": "venus-a",
                "ball_set_id": "set-1",
            }
            for index in range(99)
        ]
        report = audit_records(records, minimum_sample=100)
        self.assertFalse(report["conditional_model_allowed"])
        with self.assertRaisesRegex(RuntimeError, "at least 100"):
            require_model_gate(report, "ordered_sequence")

        records.append(
            {
                "round": 100,
                "review_status": "verified",
                "ordered_numbers": [1, 2, 3, 4, 5, 6],
                "machine_id": "venus-a",
                "ball_set_id": "set-1",
            }
        )
        report = audit_records(records, minimum_sample=100)
        self.assertTrue(report["ordered_sequence"]["eligible"])
        self.assertEqual(report["machine"]["eligible_values"], ["venus-a"])
        self.assertEqual(report["ball_set"]["eligible_values"], ["set-1"])
        require_model_gate(report, "ordered_sequence")
        require_model_gate(report, "machine", "venus-a")

    def test_batch_import_requires_exact_preselected_rounds(self):
        source = {1237: {"round": 1237, "source_channel": "동행복권", "source_verified": True}}
        draws = {1237: Draw(round=1237, numbers=(10, 20, 23, 34, 37, 40), bonus=36)}
        batch = {
            "rounds": [1237],
            "reviewed_rows": [
                {"round": 1237, "order": [10, 40, 20, 34, 37, 23], "bonus": 36}
            ],
        }
        observations = import_reviewed_batch(batch, source, draws)
        self.assertEqual(observations[0]["ordered_numbers"], [10, 40, 20, 34, 37, 23])

        batch["rounds"] = [1236, 1237]
        with self.assertRaisesRegex(ValueError, "exactly match"):
            import_reviewed_batch(batch, source, draws)

    def test_batch_import_allows_explicitly_rejected_preselected_round(self):
        source = {1237: {"round": 1237, "source_channel": "동행복권", "source_verified": True}}
        draws = {1237: Draw(round=1237, numbers=(10, 20, 23, 34, 37, 40), bonus=36)}
        batch = {
            "rounds": [1236, 1237],
            "reviewed_rows": [
                {"round": 1237, "order": [10, 40, 20, 34, 37, 23], "bonus": 36}
            ],
            "rejected_rows": [
                {"round": 1236, "reason": "continuous draw sequence is not visible"}
            ],
        }
        observations = import_reviewed_batch(batch, source, draws)
        self.assertEqual([row["round"] for row in observations], [1237])

        batch["rejected_rows"][0]["reason"] = ""
        with self.assertRaisesRegex(ValueError, "non-empty reason"):
            import_reviewed_batch(batch, source, draws)

    def test_number_list_accepts_cli_text_and_json_arrays(self):
        expected = [1, 2, 3, 4, 5, 6]
        self.assertEqual(parse_number_list("1, 2 3,4 5,6"), expected)
        self.assertEqual(parse_number_list(expected), expected)


if __name__ == "__main__":
    unittest.main()
