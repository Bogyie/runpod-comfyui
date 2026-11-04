"""Reviewed provider omissions must cover both requirements and pyproject deps."""
import copy
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
import yaml

ROOT=Path(__file__).parents[1]
sys.path.insert(0,str(ROOT/'tools/rebuild'))
from requirements_policy import select
import prepare_workers


class RequirementsPolicyTests(unittest.TestCase):
    def test_binary_omission_requires_forced_system_provider(self):
        policy={'imageio-ffmpeg':{'reason':'Use system binary','evidence_files':['utils.py'],'requires_env':{'VHS_FORCE_FFMPEG_PATH':'/usr/bin/ffmpeg'}}}
        with self.assertRaisesRegex(ValueError,'explicit runtime environment'):
            select(['imageio-ffmpeg'],{'utils.py':'known'},policy,{})

    def test_unknown_or_unreviewed_omission_rejected(self):
        with self.assertRaisesRegex(ValueError,'Unknown root requirement'):
            select(['numpy'],{}, {'absent':{'reason':'unused','evidence_files':['missing.py']}},{})
        with self.assertRaisesRegex(ValueError,'Missing reviewed'):
            select(['numpy'],{}, {'numpy':{'reason':'unused','evidence_files':['missing.py']}},{})

    def test_worker_project_duplicates_do_not_reintroduce_unused_providers(self):
        inspected=json.loads((ROOT/'build/upstream-audit.json').read_text())
        source=inspected['sources']['video-helper-suite']
        self.assertIn('opencv-python',source['requirements'])
        self.assertIn('opencv-python',source['project_dependencies'])
        stack=yaml.safe_load((ROOT/'build/stack.yaml').read_text())
        lock=json.loads((ROOT/'locks/upstreams.lock.json').read_text())
        with tempfile.TemporaryDirectory() as tmp,patch.object(prepare_workers,'audit',return_value=inspected):
            prepare_workers.prepare(stack,lock,ROOT/'.work/upstreams',Path(tmp))
            generated=(Path(tmp)/'video-helper-suite.in').read_text()
        self.assertNotIn('opencv-python',generated)
        self.assertNotIn('imageio-ffmpeg',generated)


if __name__=='__main__':unittest.main()
