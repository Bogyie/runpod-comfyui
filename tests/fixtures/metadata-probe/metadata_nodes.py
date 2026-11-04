"""Callbacks read real persistent files; execution reports its worker identity."""
import hashlib
import json
import os
from pathlib import Path
import sys
import time
import folder_paths

COUNT=0


class MetadataFixture:
    RETURN_TYPES=('STRING',)
    FUNCTION='run'
    CATEGORY='comfyctl/tests'

    @classmethod
    def INPUT_TYPES(cls):
        user=Path(folder_paths.get_user_directory())
        if (user/'metadata-slow').exists():
            (user/'metadata-rpc-started').write_text('started')
            time.sleep(10)
        files=sorted(path.name for path in Path(folder_paths.get_input_directory()).glob('*.txt'))
        return {'required':{'file':(files or ['none'],),'delay':('INT',{'default':0,'min':0,'max':30})}}

    @classmethod
    def IS_CHANGED(cls,file,delay):
        path=Path(folder_paths.get_input_directory())/file
        if path.read_text()=='always-change':return float('nan')
        return hashlib.sha256(path.read_bytes()).hexdigest()

    @classmethod
    def VALIDATE_INPUTS(cls,file,delay,input_types):
        if not isinstance(input_types,dict):
            return 'input_types callback parameter was not forwarded'
        path=Path(folder_paths.get_input_directory())/file
        return 'fixture rejected this file' if path.read_text()=='reject' else True

    def run(self,file,delay):
        global COUNT
        COUNT+=1
        Path(folder_paths.get_user_directory(),'metadata-compute-started').write_text(str(COUNT))
        time.sleep(delay)
        return (json.dumps({'count':COUNT,'text':(Path(folder_paths.get_input_directory())/file).read_text(),
                            'pid':os.getpid(),'prefix':sys.prefix}),)


NODE_CLASS_MAPPINGS={'MetadataFixture':MetadataFixture}
