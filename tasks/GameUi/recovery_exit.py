"""Locate recovery exits on the current screenshot, with single-click checks."""
from pathlib import Path

import cv2
import numpy as np


ASSETS = Path(__file__).resolve().parent / 'res'


def exit_point(image):
    if not isinstance(image, np.ndarray) or image.ndim != 3:
        return None
    height, width = image.shape[:2]
    # Exit icons are in the top UI band. Do not match crosses in battle cards.
    source = cv2.cvtColor(image[:max(1, height // 3)], cv2.COLOR_RGB2GRAY)
    candidates = []
    for name in ('back_arrow', 'close_cross'):
        path = ASSETS / ('recovery_' + name + '.png')
        template = cv2.imdecode(np.fromfile(path, dtype=np.uint8), cv2.IMREAD_GRAYSCALE) if path.exists() else None
        if template is None:
            continue
        for scale in (0.75, 1.0, 1.25):
            scaled = cv2.resize(template, None, fx=scale, fy=scale)
            th, tw = scaled.shape
            if th > source.shape[0] or tw > width:
                continue
            result = cv2.matchTemplate(source, scaled, cv2.TM_CCOEFF_NORMED)
            _, score, _, location = cv2.minMaxLoc(result)
            if score >= 0.88:
                x, y = location
                candidates.append((score, x + tw // 2, y + th // 2, name))
    if not candidates:
        return None
    candidates.sort(reverse=True)
    best = candidates[0]
    # Multiple distinct matching exits are ambiguous: let normal navigation decide.
    if any(abs(item[1] - best[1]) > 25 or abs(item[2] - best[2]) > 25
           for item in candidates[1:]):
        return None
    return best[1], best[2], best[3]


def click_exit(task):
    point = exit_point(task.device.image)
    if point is None:
        return False
    x, y, kind = point
    before = cv2.resize(cv2.cvtColor(task.device.image, cv2.COLOR_RGB2GRAY), (64, 36))
    if task.device.click(x, y, control_name='RECOVERY_EXIT_' + kind.upper()) is False:
        return False
    # Observe after this single input. The caller still verifies the home page.
    changed = []
    for _ in range(2):
        task.screenshot()
        after = cv2.resize(cv2.cvtColor(task.device.image, cv2.COLOR_RGB2GRAY), (64, 36))
        changed.append(float(np.mean(np.abs(before.astype(np.int16) - after.astype(np.int16)))) > 12)
    return all(changed)
