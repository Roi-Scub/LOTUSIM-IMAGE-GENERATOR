import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from ops_collector import Collector


class ManualCampaignDiscoveryTests(unittest.TestCase):
    def test_completed_manual_campaign_is_discovered_without_internal_jobs(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            core = root / 'core'
            unity = root / 'unity'
            core.mkdir()
            unity.mkdir()
            batch = unity / 'artifacts/manual-campaigns/test_batch'
            batch.mkdir(parents=True)
            (batch / 'status.json').write_text(
                json.dumps(
                    {
                        'schema': 'lotusim-manual-campaign-status-1',
                        'status': 'complete',
                        'completed': 2,
                        'expected': 2,
                        'boxes': 7,
                    }
                )
            )
            (batch / 'index.html').write_text('<title>Manual gallery</title>')
            rgb = batch / 'rgb'
            rgb.mkdir()
            (rgb / 'f000001.png').write_bytes(b'png fixture')
            internal = unity / 'artifacts/manual-image-jobs/test_batch/job'
            internal.mkdir(parents=True)
            (internal / 'status.json').write_text('{"status":"complete","captured":1,"expected":1}')
            collector = Collector(core, unity, docker_enabled=False)
            state = collector.snapshot()
            campaigns = state['campaigns']
            self.assertEqual(len(campaigns), 1)
            self.assertEqual(campaigns[0]['captured'], 2)
            self.assertEqual(campaigns[0]['expected'], 2)
            self.assertEqual(campaigns[0]['boxes'], 7)
            self.assertTrue(campaigns[0]['reportUrl'])
            self.assertFalse(campaigns[0]['live'])
            self.assertTrue(campaigns[0]['historical'])
            self.assertEqual(state['preview']['kind'], 'historical')


if __name__ == '__main__':
    unittest.main()
