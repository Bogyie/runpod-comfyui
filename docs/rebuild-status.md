# 전면 개편 구현 현황

이 문서는 `rebuild-plan.md`의 진행 증거를 기록한다. 기존 `main` 이미지는 아직 교체하지 않았다.

## 구현한 부분

- `build/upstreams.json`: 지정한 6종, ComfyUI, comfy-env, 간접 노드 2종의 조사 대상.
- `locks/upstreams.lock.json`: SHA·소스 archive hash·파일별 hash를 기록한 조사용 lock. 운영 Python/worker 의존성 lock과는 다르다.
- `tools/rebuild/snapshot_upstreams.py`: 명시적 `--resolve`에서만 이동하는 ref를 해석한다. 기본 실행은 이미 잠근 SHA/archive/file hash를 검증한다. 설치 훅은 실행하지 않는다.
- `tools/rebuild/audit_upstreams.py`: 검증된 소스의 의존성·설치 훅·worker TOML과 간접 노드 누락을 조사한다.
- `locks/comfy-env-artifact.json`: SAM3·DA3가 요구하는 comfy-env 0.3.89 wheel과 SHA256. `snapshot_artifact.py`로 실행 없이 다시 검사할 수 있다.
- `comfyctl model add/sync/status`: HF 공식 클라이언트와 Civitai Site API를 이용하는 다운로드 구현. 경로 제한, SHA256 검사, 파일 선택, 부분 다운로드 및 인증 redirect 처리를 포함한다.
- `uv.lock`: 관리 CLI 개발 환경의 의존성 lock. ComfyUI host lock으로 사용하지 않는다.
- `build/stack.yaml`: P0 실험 후보 조합. Python slim runtime + torch 2.10.0/cu128 + xformers 0.0.35이며 정식 GPU 검증을 통과한 스택이 아니다.
- `locks/gpu`, `locks/host`: Linux amd64 후보 해석 결과와 artifact hash. Manager/comfy-env가 쓰는 uv도 매니페스트 버전으로 고정한다.
- `docker/Dockerfile.probe`, `tools/rebuild/build_probe.py`: 전체 ComfyUI archive를 hash 검증 후 구성하는 Linux CPU 기동 실험. 모델·커스텀 노드·GPU 실행은 별도 검증 대상이다.
- `tools/rebuild/apply_comfy_env_patch.py`: 정확한 0.3.89 원본 파일 hash에만 적용하는 실험 패치. 명시한 CUDA 빌드 대상과 bootstrap torch를 일치시키며, 필수 worker 환경이 없거나 격리를 끄면 host import 대신 실패시킨다. 정식 채택 전 worker 실연산 검증이 필요하다.
- `.github/workflows/rebuild-check.yml`: 고정 소스 재현, 생성물 차이 검사, 단위·문법 검사. 이미지 배포 workflow와 분리했다.

## P0에서 확인한 사실

고정한 원본과 설정은 `build/upstream-audit.json`에서 확인할 수 있다. 아래는 정적 소스 분석 결과이며, GPU 실행 성공 판정이 아니다.

| 항목 | 확인 결과 | 후속 작업 |
|---|---|---|
| ComfyUI 조사 release | v0.44.0, SHA `2c75dc1b379a59e0880619d029607af5169a62ef` | host·worker 및 노드와 조합 검증 |
| SAM3/DA3 | 두 저장소 모두 `comfy-env==0.3.89`, `comfy-3d-viewers==0.2.44` 요구 | 무조건 최신 comfy-env로 치환하지 않음 |
| 최신 comfy-env 조사본 | 0.4.46, SHA `ff8650a46d295ccb5de987c74ad24cdb99d89e50` | 0.3 workspace와 호환되지 않는 레이아웃을 별도 평가 |
| workspace 분리 | 두 comfy-env 버전에서 `COMFY_ENV_ROOT` override 확인 | 환경 세대별 최종 prefix로 분리 |
| GPU 없는 빌드 | 0.3.89의 `install/workspace.py::_resolve_workspace_torch`는 CUDA torch가 있어도 GPU가 없으면 CPU index를 선택 | GPU 없는 CI에서 그대로 설치하지 않도록 명시적 target/잠금 경로 필요 |
| 격리 실패 | 0.3.89 `isolation/wrap.py::register_nodes`에서 환경이 없으면 host import 경로 존재 | 필수 격리 노드에 사전 검사와 fail-closed 처리 필요 |
| SAM3 간접 의존성 | VideoHelperSuite, Multiband | 간접 노드 SHA 포함 |
| DA3 간접 의존성 | KJNodes, VideoHelperSuite, GeometryPack | GeometryPack 기능 범위·용량 실험 |
| GeometryPack | Blender `bpy`, CGAL, igl, 여러 geometry 라이브러리와 CUDA 확장 요구 | 필수/선택 기능을 확인한 뒤 이미지 크기와 준비 시간 측정 |
| KJNodes/iTools/VHS | 선택 SHA에 upstream comfy-env worker 설정 없음 | 어댑터·서버 route·모델 객체 전달 검증 |
| Manager | UI 설치와 예약 startup 설치가 다른 경로이고 PIPFixer 실행도 있음 | 직접 변경을 막는 정책과 관리 CLI 연결을 함께 검증 |
| iTools Paint | `backend/iserver.py`가 multipart 업로드를 처리하고 노드의 `backend` 디렉터리에 이미지를 저장 | UI route를 host에 남기는 분리와 writable 데이터 경로 패치 필요성 검증 |
| VHS | `videohelpersuite/server.py`에 영상/파일 응답 route, `latent_preview.py`에 host preview hook 존재 | 계산부 격리와 host route/hook 보존을 나눠 시험. 단순 JSON proxy만으로 전체 호환을 가정하지 않음 |
| KJNodes preview | `nodes/image_nodes.py`에서 PromptServer의 client·socket metadata와 이미지 전송 사용 | IMAGE 연산뿐 아니라 preview callback과 모델 객체 전달도 시험 |

원본 근거:

- [SAM3 고정 requirements](https://github.com/PozzettiAndrea/ComfyUI-SAM3/blob/de0ff5d2c2ea435d29f800abfa568cffdfb94773/requirements.txt)
- [DA3 고정 worker 설정](https://github.com/PozzettiAndrea/ComfyUI-DepthAnythingV3/blob/20ef6c8ccf8d57a0ad6f6fa7031739eb8489f2a4/nodes/comfy-env.toml)
- [GeometryPack 고정 worker 설정](https://github.com/PozzettiAndrea/ComfyUI-GeometryPack/blob/1cbd14431bc88df27e5368f3e375b6bafd09006e/nodes/comfy-env.toml)
- [Manager 고정 설치 코드](https://github.com/Comfy-Org/ComfyUI-Manager/blob/4c50a2bc8b9e684d8a85930567957470b952bebe/glob/manager_core.py)
- comfy-env 0.3.89의 정확한 artifact는 `locks/comfy-env-artifact.json`에 기록했다.

## 검증 상태

- 소스 수집·해시 검사와 전이 노드 누락 검사는 실행했다.
- 로컬 Python 3.11에서 단위 테스트를 실행했다. 재개/오류는 가짜 transport로 재현하며, 실제 0.3.89 등록 함수가 누락 worker를 host import 전에 거부하는지도 검사한다.
- HF 공개 테스트 모델 520,212바이트와 Civitai 공개 모델 57,420,828바이트를 실제 다운로드하고 SHA256을 검증했다. Civitai는 65,536바이트 뒤 중단한 상태에서 HTTP 206 재개와 전체 hash 일치도 확인했다. `tests/evidence/public-download-gates.json`에 응답 범위와 결과를 남겼다. 인증/gated 시험은 아직 남아 있다.
- Docker Desktop에서 Linux amd64 후보 이미지를 빌드했고, 최초 후보의 ComfyUI 0.44.0 `/system_stats`·`/object_info`·`/prompt`·`/history`·`/view` 및 EmptyImage→SaveImage 출력 PNG를 확인했다. 이 초기 결과는 `tests/evidence/host-initial-cpu-probe.json`이다. installer 버전과 격리 guard를 반영한 후보도 재검증을 통과했다. 최신 결과는 `tests/evidence/host-cpu-probe.json`과 `tests/evidence/comfy-env-installed-guards.json`이다.
- RTX PRO 6000 Blackwell과 H100 실연산, RunPod 영속 볼륨, 성능·이미지 용량 비교는 아직 미검증이다.
- P0 전체를 완료한 상태가 아니다. 따라서 정식 GPU 스택 확정과 stable 이미지 배포는 수행하지 않았다. 기존 구현은 `legacy/`로 옮겨 현재 빌드 경로에서 제외했다.

## 재현 명령

```bash
uv sync --frozen
uv run python -m unittest discover -s tests -v
uv run python tools/rebuild/snapshot_upstreams.py
uv run python tools/rebuild/snapshot_artifact.py
uv run python tools/rebuild/audit_upstreams.py
uv run python tools/rebuild/prepare_lock_inputs.py
# 충분한 디스크 공간을 확보한 뒤 실행하는 Linux amd64 P0 이미지 실험
uv run python tools/rebuild/build_probe.py
# 공개 파일 다운로드와 실제 Range 재개 시험(약 110 MB 전송)
uv run python tools/rebuild/smoke_downloads.py
```

소스 snapshot 재현은 네트워크를 사용한다. upstream을 갱신하려면 `snapshot_upstreams.py --resolve`를 명시적으로 실행하고 lock과 audit diff를 검토한다.

다음 작업은 GitHub Actions 빌드와 GHCR 게시 확인, worker lock과 comfy-env 어댑터 실험, Manager 설치 경계, 인증 다운로드 시험이다. 이후 계획서의 P1–P5를 이어서 수행한다.

## 새 CI 배포 경로

`rebuild-image.yml`은 `codex/rebuild-*` 브랜치 push와 수동 실행을 지원한다. 고정 소스 검사 후 Linux amd64 후보를 빌드하고 CPU 그래프·격리 guard 검사를 통과하면 고유 `candidate-p0-host-*` 태그로 GHCR에 게시한다. 게시한 digest를 다시 pull하여 같은 검사를 반복하며 증거는 Actions artifact에 저장한다. GPU/노드 검증 전까지 stable 승격은 하지 않는다. 실제 Actions 실행 결과는 확인 후 별도로 기록한다.
