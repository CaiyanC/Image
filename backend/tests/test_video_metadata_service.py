import unittest
from app.services.video_metadata_service import read_video_duration, validate_video_slot


class VideoMetadataTest(unittest.TestCase):
    def test_duration_boundary_is_not_rounded_before_validation(self):
        validate_video_slot(30, "场景短视频（≤30秒）")
        validate_video_slot(30.001, "场景长视频（>30秒）")
        for duration, slot in ((30.001, "场景短视频（≤30秒）"), (30, "场景长视频（>30秒）"), (None, "场景短视频（≤30秒）")):
            with self.assertRaises(ValueError):
                validate_video_slot(duration, slot)

    def test_invalid_container_does_not_invent_a_duration(self):
        self.assertIsNone(read_video_duration(b"invalid video"))
        validate_video_slot(None, "视频")
        validate_video_slot(None, "白底视频")
