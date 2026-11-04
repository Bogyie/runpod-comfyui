# RunPod ComfyUI

RunPod용 ComfyUI 이미지를 전면 개편하고 있습니다.

- [작업 계획](docs/rebuild-plan.md)
- [구현 현황과 검증 범위](docs/rebuild-status.md)
- [모델 다운로드 CLI](docs/model-cli.md)
- [후보 스택](build/stack.yaml)
- [worker 구성과 검증 범위](docs/worker-environments.md)
- [Manager 연결 경계](docs/manager-integration.md)
- [nonroot 런타임 후보](docs/runtime.md)
- [환경 진단 CLI](docs/environment-diagnostics.md)
- [노드 세대 관리와 이미지 rebase](docs/generations.md)
- [추가 노드 설치·업데이트](docs/node-installation.md)
- [ComfyUI 업데이트 준비](docs/comfy-updates.md)

현재 `docker/Dockerfile.probe`의 기본 대상은 Manager UI/catalog, 5개 계산 worker, 다운로드·설치·복구 CLI를 포함한 runtime 후보입니다. 노드의 CPU/API·영상·메타 배치와 설치·업데이트·손상 복구, 실제 ComfyUI 변경 후 환경 재사용·재생성·이미지 복귀를 로컬에서 검증했습니다. 최종 동일 digest의 H100·RTX PRO 6000 및 RunPod 운영 검증은 남아 있습니다.

CI는 runtime 기본 검사를 거쳐 GHCR의 고유 `candidate-runtime-*` 태그를 게시하고 같은 digest를 다시 검사합니다. 네 CPU 검증 그룹이 모두 통과해야 CPU-qualified 후보로 기록합니다. 새 게시 경로의 원격 검증은 진행 중이며, `latest`와 `stable`은 갱신하지 않습니다. 기존 raw worker 이미지와 초기 GPU 결과는 구현 현황 문서에 별도로 남겼습니다.

```bash
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python tools/rebuild/build_probe.py
uv run python tools/rebuild/probe_runtime.py
```

이전 이미지의 Dockerfile, 시작 스크립트, 서비스 설정, 문서는 [`legacy/`](legacy/ARCHIVE.md)에 보관합니다. 이전 코드는 현재 빌드 경로에서 사용하지 않습니다.
