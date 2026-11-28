"""Recognize exit-game and battle-exit confirmation modals on 1280x720/scaled frames."""
from functools import lru_cache
from pathlib import Path

import cv2
import numpy as np


def game_exit_cancel_point(frame):
    """Recognize the "退出游戏" modal and return its Cancel button coordinate.

    Requires both the centered white panel and both teal action labels so dimmed
    game backgrounds cannot be mistaken for actionable modal buttons.
    """
    if frame is None or getattr(frame, 'ndim', None) != 3 or frame.shape[2] < 3:
        return None
    height, width = frame.shape[:2]
    if height < 400 or width < 700:
        return None

    panel = frame[int(height * 0.35):int(height * 0.65),
                  int(width * 0.26):int(width * 0.75), :3]
    if float(np.mean(np.all(panel >= 245, axis=2))) < 0.88:
        return None

    def teal_count(x1, x2):
        area = frame[int(height * 0.58):int(height * 0.64),
                     int(width * x1):int(width * x2), :3].astype(np.int16)
        red, green, blue = area[:, :, 0], area[:, :, 1], area[:, :, 2]
        return int(np.count_nonzero((red < 90) & (green > red + 35)
                                    & (blue > red + 35) & (green > 90)))

    if teal_count(0.60, 0.65) < 100 or teal_count(0.68, 0.73) < 100:
        return None
    return round(width * 0.628), round(height * 0.613)


@lru_cache(maxsize=1)
def _templates():
    path = Path(__file__).parent / 'recovery_assets' / 'exit_battle.png'
    original = cv2.imdecode(np.frombuffer(path.read_bytes(), dtype=np.uint8), cv2.IMREAD_GRAYSCALE)
    if original is None:
        raise RuntimeError('Unable to load ESC battle exit dialog template')
    templates = []
    for scale in np.arange(0.75, 2.26, 0.05):
        image = cv2.resize(original, None, fx=float(scale), fy=float(scale), interpolation=cv2.INTER_LINEAR)
        h, w = image.shape
        title_box = (int(w * 40 / 251), int(h * 40 / 161), int(w * 212 / 251), int(h * 82 / 161))
        button_box = (int(w * 14 / 251), int(h * 100 / 161), int(w * 237 / 251), int(h * 150 / 161))
        x1, y1, x2, y2 = title_box
        templates.append((image[y1:y2, x1:x2], image, title_box, button_box))
    return templates


def battle_exit_confirm_point(frame):
    """Recognize the '确认退出战斗吗？' dialog (title + both buttons) and return Confirm point."""
    if frame is None or getattr(frame, 'ndim', None) != 3:
        return None
    gray = cv2.cvtColor(frame, cv2.COLOR_RGB2GRAY)
    for title, dialog, title_box, button_box in _templates():
        if title.shape[0] > gray.shape[0] or title.shape[1] > gray.shape[1]:
            continue
        result = cv2.matchTemplate(gray, title, cv2.TM_CCOEFF_NORMED)
        _, score, _, position = cv2.minMaxLoc(result)
        if score < 0.90:
            continue
        left, top = position[0] - title_box[0], position[1] - title_box[1]
        height, width = dialog.shape
        if left < 0 or top < 0 or left + width > gray.shape[1] or top + height > gray.shape[0]:
            continue
        x1, y1, x2, y2 = button_box
        candidate = gray[top + y1:top + y2, left + x1:left + x2]
        buttons = dialog[y1:y2, x1:x2]
        if cv2.matchTemplate(candidate, buttons, cv2.TM_CCOEFF_NORMED)[0, 0] >= 0.87:
            return left + round(width * 190 / 251), top + round(height * 126 / 161)
    return None
