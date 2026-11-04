class Paths:
    def run(self):
        import folder_paths as f
        import os
        from pathlib import Path
        model = Path(f.get_folder_paths('checkpoints')[0]) / 'runtime-marker.safetensors'
        return {'uid': os.getuid(), 'pid': os.getpid(), 'base': f.base_path, 'models': f.models_dir,
                'input': f.get_input_directory(), 'output': f.get_output_directory(), 'user': f.get_user_directory(),
                'temp': f.get_temp_directory(), 'custom_nodes': f.get_folder_paths('custom_nodes'),
                'checkpoint_paths': f.get_folder_paths('checkpoints'), 'marker': model.read_text(),
                'input_files': sorted(os.listdir(f.get_input_directory()))}
