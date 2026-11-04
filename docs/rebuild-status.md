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
- RTX PRO 6000 Blackwell과 H100에서 BF16 행렬곱·SDPA·xformers 커널을 검증했다. H100에서는 실제 ComfyUI GPU 기동·프런트엔드·모델 없는 그래프까지 확인했다. 6종 커스텀 노드 실연산·모델 샘플링·RunPod 영속 볼륨은 미검증이다.
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

`rebuild-image.yml`은 `codex/rebuild-*` 브랜치 push와 수동 실행을 지원한다. 고정 소스 검사 후 Linux amd64 후보를 빌드하고 CPU 그래프·격리 guard 검사를 통과하면 고유 `candidate-p0-host-*` 태그로 GHCR에 게시한다. 게시한 digest를 다시 pull하여 같은 검사를 반복하며 증거는 Actions artifact에 저장한다. GPU/노드 검증 전까지 stable 승격은 하지 않는다. 실제 실행은 아래 기록과 artifact에서 확인할 수 있다.

## GitHub Actions / GHCR 실검증 (2026-11-04)

- [성공 실행 #41767056659](https://github.com/Bogyie/runpod-comfyui/actions/runs/41767056659), 소스 SHA `714722c816476b8a914ff77a3522ca184d1c04e8`.
- 이미지: `ghcr.io/bogyie/runpod-comfyui:candidate-p0-host-714722c81647-41767056659-1`
- 고정 참조: `ghcr.io/bogyie/runpod-comfyui@sha256:414962d4872aaff44e96767dd74f7f046561b52dc9664a8164e80afc15bf2c23`
- 빌드 → CPU 그래프·격리 guard → push → digest pull → 동일 검사 전부 성공. 외부 익명 manifest 조회도 성공했다.
- [검증 증거](evidence/actions-41767056659/run.json): registry 조회, 원격 단계 시간, 게시 전후 API/PNG 검사와 guard 결과를 보존했다.
- 압축 레이어 합계 5,296,162,019바이트(약 5.30GB). 실제 전송량·디스크 사용량과는 다르다.
- 최초 빌드 단계 약 6분 52초, registry 캐시 적용 빌드 4분 5초. 두 번의 단일 측정이며 CUDA·host 설치 레이어의 CACHED를 로그에서 확인했다. 캐시 다운로드·이미지 로딩 비용은 여전히 남는다.
- 성공 image job 전체 12분 28초. push와 digest pull·재검증 단계가 5분 16초여서 빌드 시간 단축만으로 전체 배포 시간이 줄어들지는 않는다.
- 첫 실행은 GitHub runner Docker CLI의 `image inspect --platform` 미지원 때문에 게시 전 검사에서 실패했다. 해당 옵션을 제거하고 실제 Architecture 검사와 `docker run --platform linux/amd64`는 유지한 뒤 성공했다.
- `latest`/`stable`은 변경하지 않았다. 실행용 이미지는 P0 핵심 환경 후보이며 커스텀 노드 6종, SSH/영속 저장소 등 RunPod 운영 환경은 아직 통합하지 않았다.

## RunPod GPU 실검증 (2026-11-04)

GHCR에 게시한 동일 digest `414962d4…15bf2c23`를 사용했다. 컨테이너 내부에서 패키지를 추가·변경하지 않았다.

| GPU | 배치 | 결과 | 증거 |
|---|---|---|---|
| RTX PRO 6000 Blackwell Server Edition | US-NC-1 | CC 12.0, CUDA 12.8, BF16 행렬곱·SDPA·xformers 통과 | [커널 결과](evidence/runpod-blackwell-kernels.json) |
| H100 SXM 80GB | US-GA-2 | CC 9.0, CUDA 12.8, 동일 커널 통과 | [커널 결과](evidence/runpod-h100-kernels.json) |
| H100 ComfyUI | US-GA-2 | GPU 모드 기동, `/` HTML과 JS asset HTTP 200, API와 EmptyImage→SaveImage PNG 통과 | [UI/API 결과](evidence/runpod-h100-ui.json) |

두 GPU 모두 driver 595.91.07, torch 2.10.0+cu128, xformers 0.0.35를 확인했다. 실제 ComfyUI 기본 attention은 PyTorch로 실행했다. 이는 커널·핵심 환경 검증이며 전체 노드 지원을 인증하는 결과는 아니다.

초기 임시 GPU 커널 서버는 일반 `/`에 UI를 제공하지 않았다. H100 AP-IN-1 배치는 이미지 다운로드 중 서비스 미기동 상태였고, 사용자 요청으로 삭제 후 미국 US-GA-2에 재생성했다. 미국 배치에서는 커널 검사 후 실제 ComfyUI를 8188에 기동하도록 명령을 변경했다. Python 기본 User-Agent 요청은 RunPod 프록시에서 403을 받았지만 일반 브라우저 User-Agent로 페이지·API가 정상 응답했다.

Blackwell 검증 Pod와 인도 H100 Pod는 삭제 후 목록에서 부재를 확인했다. 미국 H100도 사용자가 정상 UI 접속을 확인한 뒤 삭제했고, 최종 Pod 목록이 비어 있음을 확인했다. 세션이 만든 GPU 자원은 남지 않았다. 영구 RunPod 템플릿은 아직 생성하지 않았다. 기록된 UI 주소는 검증 당시 주소이며 Pod 삭제 후에는 접속할 수 없다.
