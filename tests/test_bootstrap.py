import json
import tempfile
import unittest
from pathlib import Path
from dreamstime.server import App
from dreamstime.replay import BASE
from tests.dreams_provider import map_fixture


class BootstrapTests(unittest.TestCase):
    def test_installed_catalog_recognizes_work_without_an_account_login(self):
        with tempfile.TemporaryDirectory() as directory:
            catalog=map_fixture()
            catalog['preferences']={'desktop_context_enabled':True}
            Path(directory,'bootstrap-projects.json').write_text(json.dumps(catalog))
            app=App(directory)
            try:
                for offset in (0,2):
                    app.tracker.ingest({'ts':BASE+offset,'idle':0,'app':'com.figma.Desktop','title':'Renamed','document':'https://figma.com/design/atlasFile/Renamed'})
                self.assertEqual(app.tracker.report('2026-10-05')['totals'],{'atlas':2})
                self.assertFalse(app.connection.status()['connected'])
                self.assertEqual(len(app.tracker.projects()),2)
                self.assertTrue(app.tracker.setting('desktop_context_enabled'))
            finally: app.tracker.close()

    def test_reopening_keeps_history_and_user_corrections(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'bootstrap-projects.json').write_text(json.dumps(map_fixture()))
            first=App(directory)
            first.tracker.add_rule('identity','figma:atlasFile','birch')
            first.tracker.set_setting('desktop_context_enabled',False)
            for offset in (0,2):
                first.tracker.ingest({'ts':BASE+offset,'idle':0,'app':'com.figma.Desktop','title':'Renamed','document':'https://figma.com/design/atlasFile/Renamed'})
            token=first.token
            first.tracker.close()
            second=App(directory)
            try:
                self.assertEqual(second.tracker.report('2026-10-05')['totals'],{'birch':2})
                self.assertEqual(second.token,token)
                self.assertFalse(second.tracker.setting('desktop_context_enabled'))
            finally: second.tracker.close()

    def test_bad_seed_does_not_stop_the_app(self):
        with tempfile.TemporaryDirectory() as directory:
            Path(directory,'bootstrap-projects.json').write_text('invalid json')
            app=App(directory)
            try:
                self.assertEqual(app.tracker.projects(),[])
                self.assertFalse(app.connection.status()['connected'])
            finally: app.tracker.close()
