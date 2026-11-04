"""Constrain resolver inputs without executing candidate/node hooks."""
from pathlib import Path
import unittest

from comfyctl.candidate_env import CandidateEnvironmentError, frozen_pins
from comfyctl.candidate_resolve import base_requirements
from comfyctl.node_install import declared_requirements
from comfyctl.node_sources import NodeSourceError

ROOT = Path(__file__).resolve().parents[1]


class ResolverInputTests(unittest.TestCase):
    def test_core_gpu_sdk_and_uv_are_pinned_without_host_frontend(self):
        gpu = frozen_pins((ROOT/'locks/gpu/linux-amd64-cu128.txt').read_bytes())
        host = frozen_pins((ROOT/'locks/host/linux-amd64-cu128.txt').read_bytes())
        lines = base_requirements('torch\nnumpy>=1.25\ncomfyui-frontend-package==1.57.6\n', gpu, host, ['comfyui-frontend-package'])
        self.assertIn('torch==2.10.0+cu128', lines)
        self.assertIn('comfy-env==0.3.89', lines)
        self.assertIn('uv==0.10.8', lines)
        self.assertIn('comfy-kitchen==' + host['comfy-kitchen'], lines)
        self.assertFalse(any('frontend' in value for value in lines))

    def test_direct_base_urls_and_unrecognized_config_tables_fail(self):
        with self.assertRaises(CandidateEnvironmentError):
            base_requirements('pkg @ https://example.com/pkg.whl', {}, {}, [])
        with self.assertRaises(NodeSourceError):
            declared_requirements({'requirements':[], 'configuration':{'nodes/comfy-env.toml':{'cuda':'invalid'}}})

    def test_linux_marker_is_normalized_and_opaque_requirements_do_not_pass(self):
        plan = {'requirements':[{'requirements':['numpy>=2; sys_platform=="linux"','windows-curses; sys_platform=="win32"'], 'review_required_lines':[]}], 'configuration':{}}
        self.assertEqual(declared_requirements(plan), ['numpy>=2'])


if __name__ == '__main__':
    unittest.main()
