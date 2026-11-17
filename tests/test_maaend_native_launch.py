import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import scheduler_launcher as launcher
from supervision import maaend_game_paths, maaend_native_launch_enabled


class NativeLaunchTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.root = Path(self.folder.name)
        (self.root / 'config').mkdir()
        self.game = self.root / 'Endfield.exe'
        self.game.touch()
        self.instance = {'id': 'active', 'tasks': [
            {'enabled': True, 'taskName': '__MXU_PRETASK__LaunchGamePC'}],
            'savedDevice': {'connectedProgramPath': str(self.game)}}

    def save(self, active='active', others=()):
        (self.root / 'config/mxu-MaaEnd.json').write_text(json.dumps({
            'lastActiveInstanceId': active, 'instances': [self.instance, *others]
        }), encoding='utf-8')

    def test_enabled_native_launch_and_game_path(self):
        self.save()
        self.assertTrue(maaend_native_launch_enabled(self.root))
        self.assertEqual(maaend_game_paths(self.root), [str(self.game)])

    def test_disabled_native_launch_is_not_used(self):
        self.instance['tasks'][0]['enabled'] = False
        self.save()
        self.assertFalse(maaend_native_launch_enabled(self.root))
        self.assertEqual(maaend_game_paths(self.root), [])

    def test_other_preset_does_not_enable_native_launch(self):
        self.save(active='other', others=[{'id': 'other', 'tasks': []}])
        self.assertFalse(maaend_native_launch_enabled(self.root))

    def test_misordered_start_fails_closed(self):
        self.instance['tasks'].insert(0, {'enabled': True, 'taskName': 'Daily'})
        self.save()
        with self.assertRaisesRegex(RuntimeError, '首位'):
            maaend_native_launch_enabled(self.root)

    def test_unrelated_executable_not_adopted_as_game(self):
        other = self.root / 'Other.exe'
        other.touch()
        self.instance['savedDevice']['connectedProgramPath'] = str(other)
        self.save()
        self.assertEqual(maaend_game_paths(self.root), [])

    def test_legacy_preaction_remains_available(self):
        self.instance['tasks'] = []
        self.instance['preActions'] = [{'enabled': True, 'program': str(self.game)}]
        self.save()
        self.assertFalse(maaend_native_launch_enabled(self.root))
        self.assertEqual(maaend_game_paths(self.root), [str(self.game)])

    def test_bad_json_fails_closed(self):
        (self.root / 'config/mxu-MaaEnd.json').write_text('{', encoding='utf-8')
        with self.assertRaises(ValueError):
            maaend_native_launch_enabled(self.root)

    def test_workflow_uses_native_task_without_external_click(self):
        self.save()
        task = {'steps': [
            {'type': 'launch', 'setup_key': 'maaend', 'path': str(self.root / 'MaaEnd.exe'),
             'working_dir': str(self.root), 'save_as': 'C'},
            {'type': 'key', 'target': 'C', 'keys': ['f10']}]}
        with mock.patch.object(launcher, 'find_processes_by_path', return_value=[]), \
             mock.patch.object(launcher, 'launch_program', return_value=mock.Mock(pid=1)) as launch, \
             mock.patch.object(launcher, 'ToolProcesses'), \
             mock.patch.object(launcher, 'Stage') as stage_class, \
             mock.patch.object(launcher, 'RunStatus') as statuses, \
             mock.patch.object(launcher, 'prepare_maaend_startup') as legacy, \
             mock.patch.object(launcher, 'check_stop_requested'):
            stage = stage_class.return_value
            stage.profile, stage.state = 'maaend', 'RUNNING'
            stage.deadline = launcher.time.monotonic() + 2400
            statuses.return_value.data = {'stages': {}}
            launcher.run_workflow(task)
            legacy.assert_not_called()
            launch.assert_called_once()
            stage.send_start_key.assert_called_once()
            self.assertTrue(stage.send_start_key.call_args.args[0]['_maaend_native_start'])
            stage.wait_completion.assert_called_once()
            self.assertEqual(stage_class.call_args.args[3], 2400)


if __name__ == '__main__':
    unittest.main()
