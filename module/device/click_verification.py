"""One input, fresh stable observations, then task-specific page verification."""
import time
import cv2
import numpy as np

from module.exception import TaskRecoveryFailed
from module.logger import logger


class ClickResponseUnchanged(TaskRecoveryFailed):
    """A repeated input was fenced because the prior click had no response."""


def signature(image, x, y):
    if image is None:
        raise TaskRecoveryFailed('Click requires a current device screenshot')
    height, width = image.shape[:2]
    # Include nearby selection marks, button feedback and modal edges.
    crop = image[max(0, y - 65):min(height, y + 65), max(0, x - 95):min(width, x + 95)]
    if not crop.size:
        raise TaskRecoveryFailed('Click verification point is outside the screen')
    return cv2.resize(cv2.cvtColor(crop, cv2.COLOR_RGB2GRAY), (48, 32))


def changed(first, second):
    return float(np.mean(np.abs(first.astype(np.int16) - second.astype(np.int16)) > 30)) > .08


def before_click(device, x, y, name):
    """A failed input may not be replayed just because its interval expired."""
    image = getattr(device, 'image', None)
    if image is None:
        device.screenshot()
    current = signature(device.image, x, y)
    previous = getattr(device, '_verified_click', None)
    permit = getattr(device, '_confirm_retry_permit', None)
    if permit is not None:
        if (previous is not permit['receipt'] or permit['used']
                or previous['name'] != name or previous['changed']
                or previous.get('confirm_retry_used')
                or abs(previous['x'] - x) >= 95 or abs(previous['y'] - y) >= 65
                or permit['generation'] != getattr(device, '_escape_generation', 0)):
            raise TaskRecoveryFailed(f'Confirmation retry permit no longer matches: {name}')
        # Consume before dispatch; an input/observation error cannot refill it.
        permit['used'] = True
        previous['confirm_retry_used'] = True
        return current
    if (previous and previous['name'] == name and not previous['changed']
            and abs(previous['x'] - x) < 95 and abs(previous['y'] - y) < 65):
        current = signature(device.image, previous['x'], previous['y'])
        deadline = time.monotonic() + 8
        while not changed(previous['before'], current):
            if time.monotonic() >= deadline:
                raise ClickResponseUnchanged(f'Click state unchanged; repeat blocked: {name}')
            device.screenshot()
            current = signature(device.image, previous['x'], previous['y'])
        logger.info(f'Click response verified before next input: {name}')
    return signature(device.image, x, y)


def after_click(device, x, y, name, before):
    """Two fresh observations; semantic stability is checked by the task's rules."""
    deadline = time.monotonic() + 8
    generation = getattr(device, '_escape_generation', 0)
    previous = None
    time.sleep(.25)
    while time.monotonic() < deadline:
        device.screenshot()
        if getattr(device, '_escape_generation', 0) != generation:
            raise TaskRecoveryFailed(f'Click verification interrupted by recovery: {name}')
        current = signature(device.image, x, y)
        # Animated courtyard backgrounds are not semantic page instability.
        # The caller must match its expected destination on these fresh frames.
        if previous is not None:
            response_changed = changed(before, current)
            permit = getattr(device, '_confirm_retry_permit', None)
            retry_used = bool(permit and permit['used'])
            device._verified_click = dict(
                name=name,
                x=x,
                y=y,
                before=before,
                changed=response_changed,
                confirm_retry_used=retry_used,
            )
            logger.info(f'Click result captured in two fresh frames: {name}; changed={response_changed}')
            return
        previous = current
        time.sleep(.15)
    raise TaskRecoveryFailed(f'Click result did not settle: {name}')
