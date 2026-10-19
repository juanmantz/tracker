import json
import tempfile
import unittest
from pathlib import Path
from dreamstime.server import App
from tests.dreams_provider import map_fixture

class BootstrapUpgradeTests(unittest.TestCase):
    def test_empty_update_template_cannot_erase_an_existing_recognition_catalog(self):
        with tempfile.TemporaryDirectory() as directory:
            app=App(directory);app.tracker.import_projects(map_fixture())
            expected=app.tracker.setting('recognition_catalog')
            app.tracker.close()
            Path(directory,'bootstrap-projects.json').write_text(json.dumps({'revision':0,'nodes':[],'edges':[]}))
            reopened=App(directory)
            try:
                self.assertEqual(reopened.tracker.setting('recognition_catalog'),expected)
                self.assertIsNotNone(reopened.tracker.setting('bootstrap_stamp'))
                reopened.tracker.ingest({'ts':1,'app':'com.figma.Desktop','app_name':'Figma','title':'Atlas Studio','idle':0})
                self.assertEqual(reopened.tracker.current['project'],'atlas')
            finally:reopened.tracker.close()
