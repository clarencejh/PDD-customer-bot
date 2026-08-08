"""Agent-Customer 的唯一版本号来源。"""

import re


__version__ = "1.4.0b1"
APP_VERSION = __version__


def _version_details(version: str) -> tuple[str, str, bool]:
    match = re.fullmatch(r"(\d+\.\d+\.\d+)(?:(a|b|rc)(\d+))?", version)
    if match is None:
        raise ValueError(f"不支持的应用版本格式: {version}")
    base, stage, number = match.groups()
    if stage is None:
        return f"v{base}", f"v{base}", False
    stage_names = {"a": "Alpha", "b": "Beta", "rc": "RC"}
    stage_tags = {"a": "alpha", "b": "beta", "rc": "rc"}
    return (
        f"v{base} {stage_names[stage]} {number}",
        f"v{base}-{stage_tags[stage]}.{number}",
        True,
    )


DISPLAY_VERSION, RELEASE_TAG, IS_PRERELEASE = _version_details(APP_VERSION)


__all__ = [
    "APP_VERSION",
    "DISPLAY_VERSION",
    "IS_PRERELEASE",
    "RELEASE_TAG",
    "__version__",
]
