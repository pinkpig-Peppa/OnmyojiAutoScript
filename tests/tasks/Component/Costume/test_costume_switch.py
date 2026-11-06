"""Regression tests for costume switching between list-based and string-based costumes.

List-based costumes (main13, main17) attach a multi-frame RuleGif onto the shared
asset object. String-based costumes (main1-12, 14-16) call replace_img, which must
fully strip the GIF state so the asset reverts to single-frame RuleImage behavior.
Otherwise the stale `targets` and bound RuleGif methods keep matching the previous
costume's templates after the switch.
"""
import unittest

from module.atom.image import RuleImage
from module.atom.gif import RuleGif
from tasks.Component.Costume.assets import CostumeAssets
from tasks.Component.Costume.costume_base import CostumeBase


class _DummyTask(CostumeBase):
    """Minimal stand-in that exposes asset attributes for replace_img."""
    pass


class CostumeSwitchTests(unittest.TestCase):
    def setUp(self):
        self.assets = CostumeAssets()
        self.task = _DummyTask()
        # Reuse a real asset as the shared object under test.
        self.task.I_MAIN_GOTO_TOWN = RuleImage(
            roi_front=(706, 249, 61, 57), roi_back=(200, 120, 951, 298),
            threshold=0.6, method="Template matching",
            file="./tasks/GameUi/page/page_main_goto_town.png",
        )

    def test_replace_img_strips_rule_gif_state(self):
        # Step 1: apply a list-based costume (e.g. main17) via RuleGif.attach_to.
        targets = [self.assets.I_MAIN_GOTO_TOWN_17_A,
                   self.assets.I_MAIN_GOTO_TOWN_17_B,
                   self.assets.I_MAIN_GOTO_TOWN_17_C]
        RuleGif.attach_to(self.task.I_MAIN_GOTO_TOWN, targets)
        self.assertTrue(hasattr(self.task.I_MAIN_GOTO_TOWN, "targets"))
        self.assertIn("match", self.task.I_MAIN_GOTO_TOWN.__dict__)

        # Step 2: switch to a string-based costume (e.g. main16) via replace_img.
        self.task.replace_img("I_MAIN_GOTO_TOWN", self.assets.I_MAIN_GOTO_TOWN_16)

        # The GIF state must be gone so the object behaves as a plain RuleImage.
        self.assertNotIn("targets", self.task.I_MAIN_GOTO_TOWN.__dict__)
        self.assertNotIn("appear_target", self.task.I_MAIN_GOTO_TOWN.__dict__)
        for method_name in ("pre_process", "search", "search_with_multi_scale",
                            "match_multi_scale", "match", "coord", "front_center"):
            self.assertNotIn(method_name, self.task.I_MAIN_GOTO_TOWN.__dict__,
                             f"RuleGif method {method_name} should be removed")

        # Properties must reflect the new (main16) costume.
        self.assertEqual(self.task.I_MAIN_GOTO_TOWN.file,
                         self.assets.I_MAIN_GOTO_TOWN_16.file)
        self.assertEqual(list(self.task.I_MAIN_GOTO_TOWN.roi_front),
                         list(self.assets.I_MAIN_GOTO_TOWN_16.roi_front))

    def test_replace_img_idempotent_for_string_costume(self):
        # Applying the same string-based costume twice must not leave GIF state.
        self.task.replace_img("I_MAIN_GOTO_TOWN", self.assets.I_MAIN_GOTO_TOWN_16)
        self.task.replace_img("I_MAIN_GOTO_TOWN", self.assets.I_MAIN_GOTO_TOWN_16)
        self.assertNotIn("targets", self.task.I_MAIN_GOTO_TOWN.__dict__)
        self.assertEqual(self.task.I_MAIN_GOTO_TOWN.file,
                         self.assets.I_MAIN_GOTO_TOWN_16.file)

    def test_attach_to_after_replace_img_still_works(self):
        # Switching string -> list must still attach the GIF correctly.
        self.task.replace_img("I_MAIN_GOTO_TOWN", self.assets.I_MAIN_GOTO_TOWN_16)
        targets = [self.assets.I_MAIN_GOTO_TOWN_17_A]
        RuleGif.attach_to(self.task.I_MAIN_GOTO_TOWN, targets)
        self.assertIn("targets", self.task.I_MAIN_GOTO_TOWN.__dict__)
        self.assertIs(self.task.I_MAIN_GOTO_TOWN.targets[0],
                      self.assets.I_MAIN_GOTO_TOWN_17_A)


if __name__ == "__main__":
    unittest.main()
