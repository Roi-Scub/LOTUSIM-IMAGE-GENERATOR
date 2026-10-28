import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from ops_runtime import OpsRuntime,process_birth

class RuntimeTests(unittest.TestCase):
    def test_lifecycle_and_safe_event_fields(self):
        with tempfile.TemporaryDirectory() as folder,mock.patch('ops_runtime.process_birth',return_value='birth'):
            path=Path(folder)/'runtime.json';runtime=OpsRuntime(path,'rgb_detector')
            runtime.event({'sender':'agent','recipient':'other','kind':'ready','actor':'test','credentials':'NEVER_COPY'})
            runtime.complete();data=json.loads(path.read_text())
            self.assertEqual(data['state'],'complete');self.assertEqual(data['eventCount'],1)
            self.assertEqual(data['processBirth'],'birth');self.assertNotIn('NEVER_COPY',path.read_text())
            self.assertNotIn('command',data);self.assertNotIn('env',data)
    def test_events_are_bounded_and_writes_throttled(self):
        with tempfile.TemporaryDirectory() as folder,mock.patch('ops_runtime.process_birth',return_value=None):
            timer=[0.0];path=Path(folder)/'runtime.json';runtime=OpsRuntime(path,'planner',clock=lambda:timer[0])
            first=path.read_bytes()
            for index in range(250):runtime.event({'sender':'planner','kind':'route','actor':index})
            self.assertEqual(path.read_bytes(),first)
            runtime.complete();data=json.loads(path.read_text())
            self.assertEqual(data['eventCount'],250);self.assertEqual(len(data['events']),200)
    def test_broken_telemetry_path_does_not_abort_job(self):
        with tempfile.TemporaryDirectory() as folder,mock.patch('ops_runtime.process_birth',return_value=None):
            file=Path(folder)/'not_a_directory';file.write_text('x')
            runtime=OpsRuntime(file/'runtime.json','test');runtime.fail(ValueError('test failure'))
            self.assertEqual(runtime.record['state'],'failed')
    def test_process_probe_never_requests_arguments(self):
        result=mock.Mock(returncode=0,stdout='birth\n')
        with mock.patch('ops_runtime._PROCESS_RUN',return_value=result) as run:
            self.assertEqual(process_birth(123),'birth')
            self.assertEqual(run.call_args.args[0],['ps','-p','123','-o','lstart='])
            self.assertEqual(set(run.call_args.kwargs['env']),{'PATH','LC_ALL'})
    def test_probe_failure_is_optional(self):
        with mock.patch('ops_runtime._PROCESS_RUN',side_effect=PermissionError):self.assertIsNone(process_birth())
    def test_probe_malformed_adapter_output_is_optional(self):
        for result in [object(),mock.Mock(returncode=0,stdout=object()),mock.Mock(returncode=0,stdout='')]:
            with self.subTest(result=type(result).__name__),mock.patch('ops_runtime._PROCESS_RUN',return_value=result):
                self.assertIsNone(process_birth())
        with mock.patch('ops_runtime._PROCESS_RUN',side_effect=ValueError('optional adapter failure')):
            self.assertIsNone(process_birth())
    def test_worker_subprocess_mock_does_not_capture_probe(self):
        with mock.patch('ops_runtime.subprocess.run',side_effect=AssertionError('worker runner used')) as run:
            with mock.patch('ops_runtime._PROCESS_RUN',return_value=mock.Mock(returncode=1,stdout='')):
                self.assertIsNone(process_birth())
            run.assert_not_called()
    def test_invalid_pid_does_not_inspect_another_process(self):
        with mock.patch('ops_runtime._PROCESS_RUN') as run:
            for value in (0,-1,True,'1',1.5):self.assertIsNone(process_birth(value))
            run.assert_not_called()
    def test_failed_clock_does_not_abort_optional_write(self):
        with tempfile.TemporaryDirectory() as folder,mock.patch('ops_runtime.process_birth',return_value=None):
            runtime=OpsRuntime(Path(folder)/'runtime.json','test',clock=mock.Mock(side_effect=RuntimeError('clock unavailable')))
            self.assertFalse(runtime.complete())

if __name__=='__main__':unittest.main()
