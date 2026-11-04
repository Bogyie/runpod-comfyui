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

GitHub Actions 빌드·GHCR 게시와 두 native worker lock/CPU 연결은 확인했다. 다음 작업은 나머지 노드의 comfy-env 어댑터, Manager 설치 경계, 운영 데이터 경로·권한·복구와 인증 다운로드 시험이다. 이후 계획서의 P1–P5를 이어서 수행한다.

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

## Native comfy-env worker P0 (진행 중)

SAM3·DepthAnythingV3는 upstream의 `register_nodes`와 `SubprocessWorker`를 유지하고, worker별 frozen uv venv로 실행하는 후보를 구현했다. 설정과 SHA를 검증하여 만든 입력은 `build/inputs/workers`, 전체 artifact hash lock은 `locks/workers`에 있다. 픽시 자동 설치나 torch/CUDA 조합의 자동 변경은 사용하지 않는다. [구성·제약 설명](worker-environments.md)을 참고한다.

로컬 Linux amd64 이미지에서 다음을 실제로 통과했다.

- SAM3 15개, DA3 15개 노드의 격리 메타데이터 등록.
- IMAGE → SAM3 Point Collector → host PreviewAny: 정규화 좌표와 UI JPEG 반환.
- DA3 Camera Parameters → host PreviewAny: 카메라 텐서 행렬의 수치 보존.
- worker별 Python prefix·패키지 경로와 서로 다른 지속 프로세스 PID 확인. host site-packages를 worker sys.path에 추가하지 않았다.
- 노드의 실제 예외 전파 후 worker 생존, SAM3 worker 강제 종료 후 재생성, DA3 worker PID 유지.
- 실행 전후 host 패키지 metadata와 검사한 GPU 파일 hash 일치.
- worker에도 명시적 PyTorch attention 정책 전달. 설치된 Flash/Sage를 자동 선택하지 않도록 고정했다.
- ComfyUI 루트 HTML과 프런트엔드 entry JS의 HTTP 200, 모델 없는 코어 그래프, 누락 worker의 host import 거부.

[CPU IPC·복구 결과](../tests/evidence/workers-cpu-probe.json), [코어·프런트엔드](../tests/evidence/worker-image-host-cpu.json), [설치 guard](../tests/evidence/worker-image-guards.json), [파일 공유 측정](../tests/evidence/worker-package-sharing.json)을 보존했다. 이 결과는 로컬 Docker의 amd64 에뮬레이션에서 얻었으며 이전 GHCR 핵심 이미지의 GPU 검사와 구분한다. 이 CPU 검사만으로 실제 GPU 모델 추론을 판정하지 않는다. 새 worker 이미지의 두 GPU 실연산 결과는 아래 별도 기록에 있다. 나머지 네 노드와 운영 권한은 아직 미검증이다.

`candidate.target`을 `worker-probe`로 바꿨다. CI는 worker 입력/lock 일치와 이 IPC·장애 복구 검사를 게시 전후에 수행하고 `candidate-p0-workers-*` 태그를 사용한다. 원격 CI도 통과했으며 아래 실행과 증거에 기록했다. 실제 모델 GPU 시험에 쓸 공개 weight revision/hash도 `tests/fixtures/models-worker-smoke.yaml`에 잠갔다. weight는 이미지에 포함하지 않는다.

## Native worker 후보의 원격 게시 검증

- [성공 실행 #41773238555](https://github.com/Bogyie/runpod-comfyui/actions/runs/41773238555), 소스 SHA `045795ea58e15a04b5c4ed5edfaaa105fe9b7ab5`.
- 이미지: `ghcr.io/bogyie/runpod-comfyui:candidate-p0-workers-045795ea58e1-41773238555-1`
- 고정 참조: `ghcr.io/bogyie/runpod-comfyui@sha256:8125a0f42366db8c18644a3c55234f2db3feb8d99b3de250802b4b17ff9c0c3d`
- 빌드, 게시 전 코어/프런트엔드/guard/worker 검사, push, digest pull, 같은 검사 재실행이 모두 성공했다. 외부 익명 manifest 조회도 성공했다.
- [원격 증거](evidence/actions-41773238555/run.json)에 게시 전후 worker PID 변경, 명시적 PyTorch 정책, host metadata/검사 GPU 파일 hash 불변과 출력 수치를 보존했다.
- 압축 레이어 합계는 5,961,606,258바이트(약 5.96GB). 이전 핵심 후보 5.30GB 대비 약 0.67GB 증가했다. 모델 weight는 포함하지 않는다.
- 단일 실행의 image job은 17분 20초, 빌드 5분 31초, 게시 전 검사 1분 46초, push/pull 및 게시 후 검사 6분 27초였다. 전체 배포 시간의 병목이 설치뿐 아니라 레지스트리 전송에도 있음을 확인했다.
- 위 digest는 P0 후보이며, 이전 핵심 digest의 GPU 성공과 구분하여 아래 native worker 모델 검사를 추가했다.

## 게시 경로 최적화 실측

[성공 실행 #41775695694](https://github.com/Bogyie/runpod-comfyui/actions/runs/41775695694), 소스 `1b65664842cc5107ae34db99785ff259fb85d6f9`에서 게시 전 검사를 마친 뒤 같은 BuildKit 결과를 직접 게시했다. image job은 10분 54초, 빌드·캐시 export·로컬 load 단계는 3분 55초, 별도 게시 단계는 3초, immutable pull·게시 후 검사는 1분 41초였다. 이전 실행의 Docker CLI push는 약 4분 40초였으나 단일 실행 비교이며 캐시·네트워크 조건도 달라 전체 시간 차이를 게시 방식의 효과로만 계산하지 않는다.

게시된 digest는 `sha256:a334ee1ff1fd54b5b386d30467c869db803ccec5c5f4245de9dacd3ea1574812`다. 게시 전 로컬 config와 registry config는 모두 `sha256:c4987947a03778fa1a1b6c815bb6b148a13637117985bfe4e87fb44d68e246a5`로 일치한다. 이는 앞서 게시한 `8125…` 후보의 config와도 같다. manifest digest는 다르므로 GPU 실검증 기록은 실제 사용한 `8125…` 참조를 유지한다. [원격 검증 증거](evidence/actions-41775695694/run.json), [동일 config 검사](evidence/actions-41775695694/publish.json), 게시 전후 코어·guard·worker 결과를 보존했다. `latest`/`stable`은 갱신하지 않았다.

## Native worker 실제 모델 GPU 검사

같은 `8125…f9c0c3d` 이미지로 미국 H100(US-GA-2)과 RTX PRO 6000 Blackwell(US-NC-2)에서 CUDA 텐서 왕복과 실제 SAM3 이미지 분할·3프레임 추적, DA3 단일·3프레임 깊이 추론을 통과했다. [H100 결과](evidence/native-h100-models.json)와 [Blackwell 결과](evidence/native-blackwell-models.json)에 모델 SHA256/크기, worker CUDA·attention, 그래프 성공 상태와 출력 통계를 보존했다. 시험 Pod는 삭제 후 목록 부재까지 확인했다. 상세 범위와 재실행 방법은 [worker 문서](worker-environments.md)에 있다. 나머지 노드·운영 권한·복구·장시간 작업의 검증은 남아 있다.

두 Pod 모두 종료했으며 최종 목록이 비어 있음을 확인했다. 두 모델 검사 Pod의 생성~삭제 확인 시간으로 계산한 GPU 임대료 상한 추정치는 H100 약 $0.49, Blackwell 약 $0.14다(종료 확인 시각을 사용한 대략값, 디스크 요금·실제 청구와 구분). 승인받은 전체 검증 예산 $10 범위 안에서 진행했다.

## iTools 어댑터와 frozen worker 후보

`build/adapters/itools`와 hash guard를 적용하는 도구를 추가했다. KSampler·VAE Preview는 host 모델 객체를 사용하는 예외로 남기고, 기본 노드 20개와 선택 beta Paint/Crop은 실제 comfy-env worker로 등록한다. 원본 HTTP route와 web/style/font assets는 유지한다. Paint·기본 prompt 저장은 사용자 데이터 경로로 분리했다. worker 입력과 lock manifest에는 adapter/config/패치 도구의 hash를 포함한다.

로컬 Linux amd64 새 이미지에서 iTools 텍스트→V3 UI·이미지 프리뷰, 스타일 API, Paint multipart 업로드·바이트 readback·worker 합성의 정확한 픽셀 값, 기본 prompt 저장·로드, host 계산 모듈 두 개만 import되는 경계와 별도 worker PID를 확인했다. [검사 결과](../tests/evidence/itools-cpu-probe.json)에 범위와 이미지 ID를 남겼다. 합성 VAE 객체 dispatch는 실제 VAE/KSampler checkpoint 추론과 구분한다. [worker 문서](worker-environments.md)에 남은 cache·운영 권한 검증도 기록했다.

이 새 iTools 이미지의 전체 GPU 검증은 아직 하지 않았다. 앞의 H100·Blackwell SAM3/DA3 모델 증거는 실제로 실행한 `8125…` digest에 대한 기록이다. CI에는 iTools gate를 게시 전후 모두 추가했으며 새 원격 실행 결과는 별도 기록으로 확인한다.

같은 iTools 후보에서 [코어/프런트엔드](../tests/evidence/itools-image-host.json), [설치 guard](../tests/evidence/itools-image-guards.json), [SAM3/DA3 IPC·강제 종료 복구](../tests/evidence/itools-image-workers.json)도 통과했다. iTools 검사에서는 전용 venv 패키지 경로와 소스·assets/host 패키지의 실행 전후 hash 불변, 테스트 컨테이너 삭제까지 확인했다.

## iTools 원격 게시 결과

[성공 실행 #41779549836](https://github.com/Bogyie/runpod-comfyui/actions/runs/41779549836), 소스 `64880247cf5886bbeb399ef15e6c15b8c3c852db`에서 iTools를 포함한 native-worker 후보가 빌드·게시 전 검사·GHCR 게시·immutable pull 후 같은 검사를 모두 통과했다. 최초 실행 #41779233102는 스택 전체 input identity 생성물 누락을 재현 검사에서 잡았고, 생성물 갱신과 전체 재현 절차 후 성공했다.

- 고정 참조: `ghcr.io/bogyie/runpod-comfyui@sha256:291980f28606bd98e9b55850027892eb50b46906a0e11b26acf60c9f79b212fd`.
- 게시 전 local/registry config는 모두 `sha256:760d90fc03103a16bb60fbe37e43a9f8b752610eefafde0b74e4def498929199`로 일치했다. 익명 manifest 조회도 성공했다.
- 압축 레이어 합계 6,222,732,365바이트(약 6.22GB), 이전 2-worker 후보 대비 약 0.26GB 증가. 모델 weight는 제외한다.
- 단일 image job 13분 28초, 빌드 6분, 게시 전 검사 2분 14초, BuildKit 게시 3초, pull·게시 후 검사 2분 16초. 캐시/네트워크 조건과 검사 범위도 달라 단순 성능 비교로 해석하지 않는다.
- [Actions 증거](evidence/actions-41779549836/run.json), 게시 전후 iTools와 기존 worker/코어/guard 결과를 보존했다. 이 digest는 CPU gate를 통과한 P0 후보이며, GPU 모델 증거는 앞의 `8125…`와 구분한다.

## KJNodes 어댑터 후보

원본 catalog/host hook을 보존한 채 108개 이미지·마스크·bbox·좌표 노드를 실제 comfy-env worker로 전달하는 후보를 구현했다. FastPreview, 모델 객체와 일부 V3 문맥은 host 예외로 유지한다. `color-matcher`·OpenCV는 전용 worker에 설치했다. host matplotlib 예외는 [의존성 차이](../tests/evidence/kj-host-dependency-diff.json)에 기록했으며 기존 host pin은 변경하지 않았다.

[대표 CPU 검사](../tests/evidence/kjnodes-cpu-probe.json)에서 ColorMatchV2의 실제 픽셀 변경, MASK/bbox/정수 전달, KJ 오류 전파 후 동일 worker 재호출, worker SIGMAS→host matplotlib, FastPreview의 실제 WebSocket PNG와 host HTTP/JS를 확인했다. 합성 타입 제공·관찰 노드는 테스트 컨테이너에만 연결했고 이미지에 포함하지 않았다. 실제 checkpoint/GPU 및 108개 알고리즘 전체 성공으로 확대하지 않는다.

같은 이미지의 [코어/프런트엔드](../tests/evidence/kjnodes-image-host.json), [설치 guard](../tests/evidence/kjnodes-image-guards.json), [기존 SAM3/DA3 IPC·복구](../tests/evidence/kjnodes-image-workers.json), [iTools](../tests/evidence/kjnodes-image-itools.json)도 통과했다. 이 시점의 단위 검사는 37개다. 원격 CI의 KJ gate도 게시 전후 통과했다(아래 기록). Manager 통합, 동적 schema/파일 변경 감지, 운영 데이터·권한·복구와 업데이트/승격은 남아 있다.


## KJNodes 원격 게시 결과

[성공 실행 #41782878584](https://github.com/Bogyie/runpod-comfyui/actions/runs/41782878584), 소스 `bb9e9d7ddac87c100245b807f6799fa517a63deb`에서 빌드·게시 전 검사·GHCR 게시·immutable pull 후 같은 검사를 모두 통과했다.

- 고정 참조: `ghcr.io/bogyie/runpod-comfyui@sha256:bb89a388fac581e92d566657ad257ff9c7be90ab25bea157ea4c2333d3366763`.
- local/registry config `sha256:781197917bdd5baeeb7ea75e08ae6ec18c5c28f506c2eb0e3237cd6f4bae5fe1` 일치, 익명 manifest 조회 성공.
- 압축 레이어 합계 6,581,452,744바이트(약 6.58GB). 모델 weight는 제외한다.
- [원격 증거](evidence/actions-41782878584/run.json)에 각 gate 결과를 보존했다. 이 후보에는 아래 VHS 시험에서 발견한 CPU TensorRef view·빈 storage 수정이 없다. 당시 대표 CPU 검사 통과를 모든 텐서 형태의 지원으로 확대하지 않는다.

## VHS 혼합 격리와 CPU IPC 수정

고정 VHS `4d907bee…6126d1`의 전체 catalog, 영상·오디오 loader/combine, streaming route, VAE batching과 BatchManager·latent preview hook을 host에 보존했다. stateless IMAGE/MASK/LATENT 연산 18개는 실제 comfy-env worker로 실행한다. host OpenCV는 headless wheel로 제공하고, 중복 ffmpeg 바이너리를 가진 `imageio-ffmpeg`는 제외했다. host·worker 모두 시스템 `/usr/bin/ffmpeg`를 명시하며 tensor worker에는 OpenCV도 설치하지 않는다. requirements와 pyproject 양쪽 선언에 동일 정책을 적용하고 원본 근거를 검증한다.

실제 메타 배치에서 comfy-env 0.3.89가 CPU TensorRef의 storage offset/stride를 무시하여 shape 오류가 발생했다. parent와 persistent worker의 reader를 전송된 storage metadata로 복원하도록 고쳤다. 자체 storage가 빈 CPU tensor의 RPC 실패도 재현했고, FD 없는 명시적 empty 전략으로 양방향 처리했다. SDK 패치는 정확한 원본 hash 6개를 검사한 뒤 적용한다. upstream의 non-contiguous 정규화는 유지하며 임의 stride의 zero-copy, CUDA empty, sparse/autograd 지원을 보장하지 않는다.

VHS 원본 `BatchManager.close_inputs`는 decoder tuple의 마지막 항목인 bool을 generator로 취급했다. 실제 generator는 첫 항목이므로 hash guard 아래 두 접근을 수정했다. 실제 OpenCV decoder를 외부에서 붙잡은 채 다음 prompt로 manager를 reset하여 generator 종료와 영상 FD 부재를 확인했다.

[최종 로컬 VHS 검사](../tests/evidence/vhs-cpu-probe.json)는 H.264/AAC 6프레임 저장·디코딩, VP9/Opus HTTP 스트리밍, IMAGE/MASK/LATENT 전달, 빈 선택 결과, host queue·preview hook 유지, 3회 재실행하는 메타 배치와 decoder 명시적 종료를 통과했다. 합성 영상·오디오를 사용했으며 실제 VAE checkpoint나 모든 영상 포맷·GPU·브라우저 조작 검증은 아니다.

동일 이미지 `sha256:2e39549024559a99616e583503b9d0d73dd6a685f712f118313ff419989246ac`의 [코어](../tests/evidence/vhs-image-host.json), [guard](../tests/evidence/vhs-image-guards.json), [SAM3/DA3 IPC·CPU view/empty·복구](../tests/evidence/vhs-image-workers.json), [iTools](../tests/evidence/vhs-image-itools.json), [KJNodes](../tests/evidence/vhs-image-kjnodes.json) 회귀 검사도 통과했다. 단위 검사는 43개다. 로컬 Docker Linux amd64 에뮬레이션 결과이며 원격 빌드 시간이나 새 GPU 이미지 성공으로 간주하지 않는다. CI에는 VHS gate를 게시 전후 추가했다. 새 원격 결과와 Manager·운영 환경 통합 검증은 남아 있다.
