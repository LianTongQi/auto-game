import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from PIL import Image, ImageDraw
from maaend_startup import (StartupBlocked, WindowsUI, button_bounds, button_center,
                           button_crop, button_ocr_input, discover_launcher, prepare, validate_ocr)


class RecognitionTests(unittest.TestCase):
    def test_only_exact_start_and_expected_game_are_accepted(self):
        title=[{"text":"E N D F I E L D"}]
        start=[{"text":"开 始 游 戏","x":10,"y":20,"width":100,"height":40}]
        self.assertEqual(validate_ocr(title,start),(60,40))
        for text in ("更新游戏","下载游戏","登录","购买","START","始游戏","开始","开始更新"):
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

    @staticmethod
    def launcher_image(scale=1):
        image=Image.new('RGB',(round(1000*scale),round(700*scale)),'#202020')
        # Bottom-right fixed button region; black label ink must not move its center.
        draw=ImageDraw.Draw(image)
        draw.rectangle(tuple(round(v*scale) for v in (740,580,949,639)), fill='#ffff00')
        draw.rectangle(tuple(round(v*scale) for v in (790,600,890,620)), fill='black')
        return image

    def test_click_uses_button_region_center_at_multiple_scales(self):
        for scale in (.5,.75,1,1.5,2):
            with self.subTest(scale=scale):
                image=self.launcher_image(scale)
                left,top,right,bottom=button_bounds(image)
                point=button_center(image)
                self.assertEqual(point,((left+right)/2,(top+bottom)/2))
                self.assertAlmostEqual(point[0]/scale,845,delta=2)
                self.assertAlmostEqual(point[1]/scale,610,delta=2)
                crop,offset=button_crop(image)
                self.assertGreater(crop.width,0)
                self.assertGreaterEqual(offset[0],left)

    def test_ocr_padding_preserves_the_failed_image_and_white_margins(self):
        path=Path(__file__).parent/'fixtures/launcher-start-ocr-missing-first-glyph.png'
        with Image.open(path) as source:
            source=source.convert('L')
            padded=button_ocr_input(source)
            self.assertEqual(padded.size,(source.width+90,source.height+90))
            self.assertEqual(padded.crop((45,45,45+source.width,45+source.height)).tobytes(),source.tobytes())
            self.assertEqual(padded.getpixel((0,0)),255)
            self.assertEqual(padded.getpixel((padded.width-1,padded.height-1)),255)

    def test_ocr_text_coordinates_do_not_control_click_position(self):
        image=self.launcher_image()
        with tempfile.TemporaryDirectory() as directory:
            ui=WindowsUI.__new__(WindowsUI)
            ui.runtime=Path(directory)
            ui.capture=mock.Mock(return_value=image)
            ui.native=mock.Mock(side_effect=[
                '[{"text":"ENDFIELD"}]',
                '[{"text":"开始游戏","x":-9999,"y":9999,"width":2,"height":2}]'])
            self.assertEqual(ui.start_point({}),button_center(image))
            self.assertEqual(ui.native.call_count,2)

    def test_fixed_region_still_rejects_wrong_game_and_update_labels(self):
        with tempfile.TemporaryDirectory() as directory:
            for title,label in (('OTHER GAME','开始游戏'),('ENDFIELD','更新游戏'),
                                ('ENDFIELD','登录'),('ENDFIELD','始游戏')):
                with self.subTest(title=title,label=label):
                    ui=WindowsUI.__new__(WindowsUI)
                    ui.runtime=Path(directory)
                    ui.capture=mock.Mock(return_value=self.launcher_image())
                    ui.native=mock.Mock(side_effect=[
                        '[{"text":"'+title+'"}]',
                        '[{"text":"'+label+'","x":0,"y":0,"width":100,"height":40}]'])
                    with self.assertRaises(StartupBlocked):
                        ui.start_point({})


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
