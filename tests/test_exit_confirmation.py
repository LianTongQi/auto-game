import unittest
from unittest import mock

import scheduler_launcher as launcher


class ExitConfirmationTests(unittest.TestCase):
    def run_check(self, states, deadline=100, stop=None):
        now = [0.0]
        tracker = mock.Mock()
        tracker.current.side_effect = states
        monitor = mock.Mock(deadline=deadline)
        def wait(seconds):
            now[0] += seconds
        with mock.patch.object(launcher.time, "monotonic", side_effect=lambda: now[0]), \
                mock.patch.object(launcher, "wait_interruptibly", side_effect=wait), \
                mock.patch.object(launcher, "check_stop_requested", side_effect=stop), \
                mock.patch.object(launcher, "log_info"), \
                mock.patch.object(launcher, "execute_key_action") as keys, \
                mock.patch.object(launcher, "close_process") as close:
            launcher.confirm_tool_exit("March7th", tracker, monitor)
            keys.assert_not_called()
            close.assert_not_called()
        return now[0]

    def test_already_exited_has_no_delay(self):
        self.assertEqual(self.run_check([[]]), 0)

    def test_slow_exit_is_reconciled_without_another_key_or_close(self):
        self.assertAlmostEqual(self.run_check([[{"pid": 1}]] * 18 + [[]]), 3.6)

    def test_alive_after_grace_still_blocks_next_tool(self):
        with self.assertRaisesRegex(RuntimeError, "仍未退出"):
            self.run_check([[{"pid": 1}]] * 100)

    def test_stage_budget_is_not_extended(self):
        with self.assertRaisesRegex(RuntimeError, "仍未退出"):
            self.run_check([[{"pid": 1}]] * 100, deadline=.5)

    def test_stop_is_honored(self):
        with self.assertRaisesRegex(RuntimeError, "stopped"):
            self.run_check([[{"pid": 1}]], stop=RuntimeError("stopped"))


if __name__ == "__main__":
    unittest.main()
