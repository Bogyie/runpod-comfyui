# RunPod ComfyUI

RunPod용 ComfyUI 이미지를 전면 개편하고 있습니다.

- [작업 계획](docs/rebuild-plan.md)
- [구현 현황과 검증 범위](docs/rebuild-status.md)
- [모델 다운로드 CLI](docs/model-cli.md)
- [후보 스택](build/stack.yaml)
- [worker 구성과 검증 범위](docs/worker-environments.md)
- [Manager 연결 경계](docs/manager-integration.md)

현재 `docker/Dockerfile.probe`는 ComfyUI 핵심 환경, SAM3·DepthAnythingV3의 native worker와 iTools·KJNodes·VHS 혼합 격리를 검증하는 P0 후보입니다. 미국 H100·RTX PRO 6000에서 SAM3 이미지·영상 분할과 DA3 단일·배치 깊이 추론을 확인했습니다. iTools·KJNodes의 CPU/API·host 연동과 VHS의 영상·오디오·스트리밍·메타 배치 검사를 로컬에서 통과했습니다. Manager와 RunPod 운영 환경은 통합 중입니다. CPU 기동·worker IPC·복구 검사를 통과한 후보만 GitHub Actions에서 GHCR의 고유 `candidate-p0-workers-*` 태그로 게시합니다. `latest`와 `stable`은 갱신하지 않습니다.

```bash
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python tools/rebuild/build_probe.py
uv run python tools/rebuild/probe_workers.py
```

이전 이미지의 Dockerfile, 시작 스크립트, 서비스 설정, 문서는 [`legacy/`](legacy/ARCHIVE.md)에 보관합니다. 이전 코드는 현재 빌드 경로에서 사용하지 않습니다.
