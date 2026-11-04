"""Test-only stateless node; its source must execute in a private worker."""
import json
import os
import sys


class AddedEnvironment:
    @classmethod
    def INPUT_TYPES(cls):
        return {'required': {'value': ('INT', {'default': 3})}}

    RETURN_TYPES = ('STRING',)
    FUNCTION = 'report'
    CATEGORY = 'comfyctl/tests'

    def report(self, value):
        import numpy as np
        import torch
        return (json.dumps({'value': int(np.array(value) * 2), 'prefix': sys.prefix,
                            'pid': os.getpid(), 'uid': os.getuid(), 'torch': torch.__version__}),)


NODE_CLASS_MAPPINGS = {'ComfyctlAddedEnvironment': AddedEnvironment}
