import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('gpu_gate', Path(__file__).parents[1] / 'tools/rebuild/verify_gpu.py')
gate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(gate)


class GpuGateTests(unittest.TestCase):
    def test_cpu_runner_cannot_produce_a_successful_gpu_result(self):
        torch = types.ModuleType('torch')
        torch.cuda = types.SimpleNamespace(is_available=lambda: False)
        nn = types.ModuleType('torch.nn')
        functional = types.ModuleType('torch.nn.functional')
        with patch.dict(sys.modules, {'torch': torch, 'torch.nn': nn, 'torch.nn.functional': functional}):
            with self.assertRaisesRegex(RuntimeError, 'cannot pass on a CPU runner'):
                gate.probe('12.0', '12.8')


if __name__ == '__main__':
    unittest.main()
