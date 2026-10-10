"""Read container-reported duration without decoding uploaded video frames."""
from fractions import Fraction
from io import BytesIO
from math import isfinite


def read_video_duration(content: bytes) -> float | None:
    import av
    try:
        with av.open(BytesIO(content), mode="r") as container:
            if not container.streams.video:
                return None
            durations = [Fraction(stream.duration) * stream.time_base
                         for stream in container.streams.video
                         if stream.duration is not None and stream.time_base is not None]
            duration = max(durations) if durations else (
                Fraction(container.duration, av.time_base) if container.duration is not None else None
            )
            if duration is None or duration <= 0:
                return None
            return float(duration)
    except (av.FFmpegError, ValueError, OverflowError):
        return None


def validate_video_slot(duration: float | None, sub_category: str | None) -> None:
    if sub_category not in {"场景短视频（≤30秒）", "场景长视频（>30秒）"}:
        return
    if duration is None or not isfinite(duration) or duration <= 0:
        raise ValueError("无法读取视频时长，请重新导出视频后上传；不能验证短/长视频分类")
    if sub_category == "场景短视频（≤30秒）" and duration > 30:
        raise ValueError("场景短视频时长不能超过 30 秒，请选择场景长视频分类")
    if sub_category == "场景长视频（>30秒）" and duration <= 30:
        raise ValueError("场景长视频时长必须超过 30 秒，请选择场景短视频分类")
