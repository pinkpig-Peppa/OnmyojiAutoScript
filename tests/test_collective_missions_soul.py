"""Verify CollectiveMissions soul submission exits when OCR keeps failing."""

import unittest
from types import SimpleNamespace

from tasks.CollectiveMissions.script_task import ScriptTask


class _EmptyOcr:
    """OCR rule that never yields a number."""

    def __init__(self):
        self.calls = 0

    def ocr(self, image):
        self.calls += 1
        return ''


class SoulOcrFailureTests(unittest.TestCase):
    def build_stub(self, ocr, level_visible=False):
        events = []
        stub = SimpleNamespace()
        stub.C_CM_1 = 'C_CM_1'
        stub.C_CM_2 = 'C_CM_2'
        stub.C_CM_3 = 'C_CM_3'
        stub.I_UI_BACK_RED = 'I_UI_BACK_RED'
        stub.I_CM_RECORDS = 'I_CM_RECORDS'
        stub.O_SL_NUMBER = ocr
        stub.O_SL_LEVEL = 'O_SL_LEVEL'
        stub.L_SL_LONG = 'L_SL_LONG'
        stub.I_SL_SUBMIT = 'I_SL_SUBMIT'
        stub.device = SimpleNamespace(image=object())
        stub.ocr_appear = lambda rule: level_visible
        stub.ui_click = lambda button, destination=None: events.append((button, destination))
        stub.click = lambda rule, **kwargs: False
        frames = {'count': 0}

        def screenshot():
            frames['count'] += 1
            if frames['count'] > 40:
                raise AssertionError('_soul did not exit after OCR kept failing')

        stub.screenshot = screenshot
        return stub, events

    def test_ocr_failure_returns_false_after_bounded_retries(self):
        ocr = _EmptyOcr()
        stub, events = self.build_stub(ocr)
        self.assertFalse(ScriptTask._soul(stub, 0))
        self.assertEqual(ocr.calls, 30)
        self.assertEqual(events[-1], ('I_UI_BACK_RED', 'I_CM_RECORDS'))

    def test_no_submittable_soul_still_exits_immediately(self):
        ocr = _EmptyOcr()
        stub, events = self.build_stub(ocr, level_visible=True)
        self.assertFalse(ScriptTask._soul(stub, 0))
        self.assertEqual(ocr.calls, 1)
        self.assertEqual(events[-1], ('I_UI_BACK_RED', 'I_CM_RECORDS'))


if __name__ == "__main__":
    unittest.main()
