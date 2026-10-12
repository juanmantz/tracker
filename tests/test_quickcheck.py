import unittest
from dreamstime.quickcheck import QuickCheck


class QuickCheckTests(unittest.TestCase):
    def test_replay_or_no_samples_cannot_pass_native_check(self):
        q = QuickCheck(); q.start(100)
        self.assertEqual(q.snapshot(131)['status'], 'needs_attention')
        self.assertTrue(all(not c['passed'] for c in q.snapshot(131)['checks']))

    def test_real_recent_samples_switch_and_title_required(self):
        q = QuickCheck(); q.start(100)
        q.observe({'ts': 101, 'app': 'editor', 'title': '', 'accessibility': False})
        q.observe({'ts': 103, 'app': 'figma', 'title': 'Client identity', 'accessibility': True})
        self.assertEqual(q.snapshot(104)['status'], 'passed')
        self.assertEqual(q.snapshot(150)['status'], 'needs_attention')

    def test_same_app_samples_alone_dont_pass(self):
        q = QuickCheck(); q.start(100)
        for ts in (101, 103, 105): q.observe({'ts': ts, 'app': 'editor', 'title': 'Doc', 'accessibility': True})
        self.assertEqual(q.snapshot(106)['status'], 'running')

    def test_restart_clears_previous_check(self):
        q = QuickCheck(); q.start(100)
        q.observe({'ts': 102, 'app': 'editor', 'title': 'Doc', 'accessibility': True})
        q.start(110)
        q.observe({'ts': 105, 'app': 'old', 'title': 'Old', 'accessibility': True})
        self.assertEqual(q.snapshot(111)['samples'], 0)

if __name__ == '__main__': unittest.main()
