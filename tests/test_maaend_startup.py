import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image
from maaend_startup import StartupBlocked, button_crop, discover_launcher, prepare, validate_ocr


class RecognitionTests(unittest.TestCase):
    def test_only_exact_start_and_expected_game_are_accepted(self):
        title=[{"text":"E N D F I E L D"}]
        start=[{"text":"开 始 游 戏","x":10,"y":20,"width":100,"height":40}]
        self.assertEqual(validate_ocr(title,start),(60,40))
        for text in ("更新游戏","下载游戏","登录","购买","START"):
            with self.subTest(text=text), self.assertRaises(StartupBlocked):
                validate_ocr(title,[dict(start[0],text=text)])
        with self.assertRaises(StartupBlocked):
            validate_ocr([{"text":"OTHER GAME"}],start)
        with self.assertRaises(StartupBlocked):
            validate_ocr(title,start+start)

    def test_installer_discovery_stays_in_actual_game_install(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/"official"
            game=root/"games"/"Endfield Game"/"Endfield.exe"
            game.parent.mkdir(parents=True)
            launcher=root/"Launcher.exe"
            launcher.touch()
            self.assertEqual(discover_launcher(game),launcher)
            with self.assertRaises(StartupBlocked):
                discover_launcher(Path(d)/"unrelated"/"game.exe")

    def test_missing_launcher_is_not_replaced_with_direct_game_exe(self):
        with tempfile.TemporaryDirectory() as d:
            with self.assertRaises(StartupBlocked):
                discover_launcher(Path(d)/"games"/"Endfield"/"Endfield.exe")

    def test_no_yellow_button_fails_closed(self):
        with self.assertRaises(StartupBlocked):
            button_crop(Image.new("RGB",(1000,700),"white"))


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.now=0
        self.stage=mock.Mock()
        self.stage.signals=SimpleNamespace(started=False,success=False)
        self.stage.deadline=200
        self.games=[]
        self.stage.cb={"game_path":"Endfield.exe","scan":lambda _:self.games,
                       "tools":lambda:[],"wait":self.wait,"info":mock.Mock()}
        self.ui=mock.Mock()
        self.ui.official.return_value={"pid":10}
        self.ui.start_point.return_value=(100,100)
        self.ui.game_window.return_value=True

    def wait(self, seconds):
        self.now+=seconds

    def run_prepare(self, launch):
        with mock.patch("maaend_startup.time.monotonic",side_effect=lambda:self.now), \
             mock.patch("maaend_startup.discover_launcher",return_value=Path("Launcher.exe")):
            return prepare(self.stage,Path("runtime"),launch,ui=self.ui)

    def test_already_running_never_opens_launcher_or_presses_start(self):
        self.stage.signals.started=True
        launch=mock.Mock()
        self.run_prepare(launch)
        launch.assert_not_called()
        self.ui.click.assert_not_called()

    def test_existing_game_does_not_start_a_duplicate(self):
        self.games=[{"pid":1,"create_time":1}]
        launch=mock.Mock()
        self.run_prepare(launch)
        launch.assert_not_called()
        self.ui.click.assert_not_called()

    def test_official_launch_and_start_click_each_happen_once(self):
        self.ui.click.side_effect=lambda *_:self.games.append({"pid":1,"create_time":1})
        launch=mock.Mock()
        self.run_prepare(launch)
        self.assertEqual(launch.call_count,1)
        self.assertEqual(self.ui.click.call_count,1)
        self.assertEqual(Path(launch.call_args.args[0]["path"]).name,"Launcher.exe")

    def test_game_not_appearing_never_causes_repeat_clicks(self):
        launch=mock.Mock()
        with self.assertRaises(StartupBlocked):
            self.run_prepare(launch)
        self.assertEqual(self.ui.click.call_count,1)

    def test_ocr_or_update_screen_never_causes_a_click(self):
        self.ui.start_point.side_effect=StartupBlocked("not Start Game")
        with self.assertRaises(StartupBlocked):
            self.run_prepare(mock.Mock())
        self.ui.click.assert_not_called()

    def test_manual_start_during_recognition_wins_without_extra_input(self):
        def started(_):
            self.stage.signals.started=True
            return (100,100)
        self.ui.start_point.side_effect=started
        self.run_prepare(mock.Mock())
        self.ui.click.assert_not_called()

    def test_original_shorter_deadline_is_not_extended(self):
        self.stage.deadline=4
        with self.assertRaises(StartupBlocked):
            self.run_prepare(mock.Mock())
        self.assertLessEqual(self.now,4)


if __name__=="__main__":
    unittest.main()
