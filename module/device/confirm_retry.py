"""Explicit, bounded retry for audited non-consuming modal controls."""
import cv2

from module.device.click_verification import ClickResponseUnchanged, changed
from module.exception import TaskRecoveryFailed
from module.logger import logger


def context_signature(image):
    return cv2.resize(cv2.cvtColor(image, cv2.COLOR_RGB2GRAY), (96, 54))


def click_confirm_once(task, match, controls, *, dismiss_anywhere=False):
    """match must identify this modal's button; disappearance is the destination.

    Only audited confirmation/dismiss callers may use this. Never use for a
    purchase, reward claim, battle start, or other consuming action.
    """
    device = task.device
    generation = getattr(device, '_escape_generation', 0)
    task.screenshot()
    target = match()
    if getattr(device, '_escape_generation', 0) != generation:
        raise TaskRecoveryFailed('Confirmation interrupted by recovery')
    if target is None:
        return False
    context = context_signature(device.image)
    name = target.name
    x, y = target.coord()
    receipt = getattr(device, '_verified_click', None)
    # Re-entry after an exhausted retry must not issue a new first click.
    aliases = {control.name for control in controls}
    if receipt and receipt['name'] in aliases and receipt.get('confirm_retry_used'):
        raise ClickResponseUnchanged(f'Confirmation retry already used: {name}')
    if (receipt and receipt['name'] in aliases and receipt['name'] != name
            and not receipt['changed']):
        raise ClickResponseUnchanged(f'Confirmation recognizer changed after unverified input: {name}')
    pending_receipt = bool(receipt and receipt['name'] == name and not receipt['changed'])
    if pending_receipt and dismiss_anywhere:
        x, y = receipt['x'], receipt['y']
    if not pending_receipt:
        # Re-entry with an unconfirmed receipt observes it rather than sending
        # another "first" input (even if random coordinates moved far away).
        if device.click(x, y, control_name=name) is False:
            return False
    if getattr(device, '_escape_generation', 0) != generation:
        raise TaskRecoveryFailed('Confirmation interrupted after input')
    if task._ui_verify(lambda: match() is None, controls, timeout=2, fail=False):
        return True
    if getattr(device, '_escape_generation', 0) != generation:
        raise TaskRecoveryFailed('Confirmation interrupted while waiting')
    receipt = getattr(device, '_verified_click', None)
    if (not receipt or receipt['name'] != name or receipt['changed']
            or receipt.get('confirm_retry_used')):
        raise TaskRecoveryFailed(f'Confirmation still present; retry not eligible: {name}')
    last_frame = getattr(device, 'image_frame_id', None)
    # Two distinct captures must show the same target in the same context.
    for _ in range(2):
        task.screenshot()
        frame = getattr(device, 'image_frame_id', None)
        if (frame is None or frame == last_frame
                or getattr(device, '_escape_generation', 0) != generation):
            raise TaskRecoveryFailed(f'Confirmation retry lacks fresh frames: {name}')
        last_frame = frame
        target = match()
        if target is None:
            return task._ui_verify(lambda: match() is None, controls)
        # Reward dismiss is an audited full-screen tap, not a located button.
        # Keep its original point only after matching the same modal/context.
        nx, ny = (x, y) if dismiss_anywhere else target.coord()
        if (target.name != name or abs(nx - x) >= 95 or abs(ny - y) >= 65
                or abs(nx - receipt['x']) >= 95 or abs(ny - receipt['y']) >= 65
                or changed(context, context_signature(device.image))):
            raise TaskRecoveryFailed(f'Confirmation context changed; retry cancelled: {name}')
    if getattr(device, '_escape_generation', 0) != generation:
        raise TaskRecoveryFailed('Confirmation retry interrupted by recovery')
    permit = dict(receipt=receipt, generation=generation, used=False)
    device._confirm_retry_permit = permit
    try:
        logger.info(f'Reidentified unchanged confirmation; retry once: {name}')
        if device.click(nx, ny, control_name=name) is False:
            return False
        if not permit['used']:
            raise TaskRecoveryFailed('Confirmation input did not consume its retry permit')
    finally:
        device._confirm_retry_permit = None
    return task._ui_verify(lambda: match() is None, controls)
