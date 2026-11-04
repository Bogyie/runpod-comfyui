# 모델 다운로드 CLI

신규 관리 도구는 ComfyUI의 Python 환경과 별도로 설치한다. 현재 개발 환경에서는 다음과 같이 실행한다.

```bash
uv sync --frozen
uv run comfyctl model add 'https://huggingface.co/OWNER/REPO/resolve/REVISION/FILE' --type diffusion_models
uv run comfyctl model add 'https://civitai.com/models/MODEL_ID?modelVersionId=VERSION_ID' --type loras
uv run comfyctl model status --verify
```

기본 모델 경로는 `/workspace/storage/models`, 상태 기록은 `/workspace/state/comfyctl`이다. 환경변수 `STORAGE_DIR`, `COMFYCTL_STATE_DIR`로 바꾸거나 전역 옵션을 명령 앞에 지정할 수 있다.

```bash
uv run comfyctl --storage /tmp/comfy-storage --state /tmp/comfy-state model status
```

- HF 인증은 `HF_TOKEN`, Civitai 인증은 `CIVITAI_TOKEN`을 사용한다. 토큰을 URL에 넣으면 거부한다.
- `--target diffusion_models/flux/model.safetensors`로 하위 경로를 지정할 수 있다. `--sha256`으로 기대 hash를 지정할 수 있다.
- Civitai는 version ID를 지정해야 하며 여러 모델 파일이면 `--file-id`를 요구한다. 잘못된 파일을 자동 선택하지 않는다.
- 기존 목적지 파일은 일치하는 hash 또는 저장된 다운로드 기록으로 검증할 수 있을 때만 재사용한다. 임의 덮어쓰기는 하지 않는다.
- Civitai 부분 파일은 목적지 옆 숨김 `.part` 파일로 보존한다. entity validator 또는 기대 SHA256이 있으면 재개하며, 서버가 Range를 무시하면 처음부터 다시 받는다. hash 기반 재개도 마지막에 전체 파일 hash를 확인한다.
- HF 재개는 공식 클라이언트의 로컬 다운로드 metadata를 이용한다. 검증 후 파일을 최종 경로로 이동해 모델 복사본을 영구 중복 보관하지 않는다.
- 검증 전 파일은 최종 모델 파일명으로 공개하지 않는다. `status --verify`는 기록된 전체 hash를 다시 계산하므로 대형 모델에서는 시간이 걸릴 수 있다.
- 접근 권한이나 라이선스 동의는 사용자의 HF/Civitai 계정에서 먼저 충족해야 한다.

## 목록으로 받기

```yaml
schema_version: 1
models:
  - source: https://huggingface.co/OWNER/REPO/resolve/COMMIT/path/model.safetensors
    target: diffusion_models/family/model.safetensors
    # sha256: 64자리 hash
  - source: https://civitai.com/models/MODEL_ID?modelVersionId=VERSION_ID
    file_id: 123
    target: loras/family/model.safetensors
```

```bash
uv run comfyctl model sync models.yaml
```

현재 일괄 다운로드는 순차 실행으로 서버 부하와 메모리 사용을 제한한다. 저장소의 기존 모델별 YAML은 `hf_down_url`와 `target_path`도 읽는다. URL의 `main` 같은 이동 ref는 같은 파일이란 보장이 없으므로, 재현이 필요한 목록에는 commit revision과 SHA256을 지정한다.

구현 및 외부 서비스 검증의 진행 상태는 `rebuild-status.md`를 따른다.

공개 파일 통합 시험은 `uv run python tools/rebuild/smoke_downloads.py`로 재현한다. 약 110 MB를 전송하며 모델은 `.work`에만 저장한다. 실제 HTTP 206 재개를 관측하지 못하면 성공 증거를 만들지 않는다.
