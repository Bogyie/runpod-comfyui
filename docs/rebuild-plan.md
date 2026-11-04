# RunPod ComfyUI 이미지 전면 개편 작업계획서

- 작성일: 2026-11-04
- 기준: `main`의 `ec64c78` 및 기존 Git 히스토리
- 상태: 구현 전 계획. 아래 구조와 목표 수치는 제안이며, GPU 호환성과 성능은 아직 실측하지 않았다.
- 전제: 기존 구현은 레거시로 취급한다. 기존 경로·태그·이미지 종류·접속 도구를 그대로 유지할 의무는 없다.
- 대상: RunPod Pod, Linux amd64, RTX PRO 6000 Blackwell 96GB 및 H100.
- 추가 방향: 기본 포함 노드와 이후 추가할 노드 모두 가능한 범위에서 `comfy-env`를 우선 사용한다.

## 1. 개편 목표와 결정 원칙

ComfyUI를 자주 올릴 수 있으면서도 검증된 GPU 스택을 재사용하고, 노드를 추가하다 문제가 생기면 마지막 정상 상태로 돌아갈 수 있는 이미지를 만든다. 빌드 시간만 줄이고 첫 실행 때 설치를 떠넘기는 방식은 피한다. CI 시간, 이미지 전송량, Pod 준비 시간, 환경 복구 시간을 함께 측정한다.

우선순위는 데이터 보존과 복구 가능성 → 두 GPU에서의 기능 정상 동작 → ComfyUI 업데이트 편의 → 빌드 속도와 용량 → 선택적 성능 최적화 순이다.

| 사용자 요구 | 구현 방향 | 완료 증거 |
|---|---|---|
| GitHub Actions 빌드 최적화 | GPU 기반층 재사용, 변경 범위별 빌드, registry cache | 변경 유형별 시간·전송량 비교 |
| ComfyUI 버전업 최적화 | 앱과 GPU 스택 분리, 버전 잠금과 업데이트 PR | 앱만 바꾼 업데이트 및 롤백 시연 |
| 지정한 커스텀 노드 6종 | 정확한 upstream과 SHA 고정, comfy-env 우선 적용 | 노드 등록·UI·대표 워크플로 검증 |
| RTX PRO 6000 / H100 | 동일 이미지 우선, 두 GPU별 실연산 검사 | 같은 digest의 GPU별 결과 |
| 경량화 | runtime 기반, 빌드 도구·모델 제외, 중복 패키지 관리 | 압축·압축 해제 크기와 레이어 분석 |
| 안정적인 최적화 유틸 | xformers 포함을 목표로 검증, PyTorch attention 기본 | GPU별 커널 시험 및 fallback |
| 환경 손상 관리·복구 | 프로세스 격리, 후보 환경 검증, 환경과 코드 동시 롤백 | 실패 주입 후 복구 시험 |
| HF / Civitai 다운로드 | 통합 CLI, 목록 파일, 재개·검증·영속 저장 | 공개·인증·중단·재개 시험 |

## 2. 레거시에서 가져갈 경험

### 유지할 운영 지식

- GitHub runner에서는 빌드 병렬도를 무작정 높이면 메모리와 디스크가 병목이 된다. 동시 실행 수를 측정해 제한한다.
- CUDA/PyTorch 변경과 ComfyUI·노드 변경은 다른 작업이다. 앱 업데이트마다 GPU 패키지를 다시 설치하지 않는다.
- 노드 설치는 `requirements.txt`뿐 아니라 `install.py`, 시작 훅, 런타임 다운로드까지 확인해야 한다.
- 핵심 패키지 버전 변경 검사는 유용하다. 다만 이미 손상된 환경을 나중에 발견하는 검사만으로는 충분하지 않다.
- GPU 없는 runner에서는 파일·import 검사를 할 수 있지만, CUDA 커널과 실제 워크플로 성공을 보장하지 못한다.
- 모델 별칭과 영속 경로는 명시적으로 관리한다. 기존 모델 이동 전에 충돌과 symlink를 검사한다.
- RunPod의 컨테이너 시작 명령과 PID 1 동작을 실제 Pod에서 확인해야 한다.
- Pod가 살아 있는 것과 ComfyUI가 요청을 처리할 수 있는 것은 다른 상태다.

### 새 구현에서 대체할 방식

- `pip freeze` 재설치만 하는 복구 → 깨끗한 환경 재생성과 정상 환경으로 전환.
- 모든 노드가 하나의 writable Python 환경을 공유 → `comfy-env` worker 격리를 우선하고, 필요한 예외만 공유.
- 설치 후 버전 검사에만 의존 → 설치 전 해석·제약 적용·격리·사후 검사 결합.
- 모든 빌드 단계를 별도 이미지로 공개 → 재사용 가치가 큰 기반 이미지와 사용자용 최종 이미지에 집중.
- 범용 File Browser, Caddy/AuthCrunch, GitHub CLI 등을 관성적으로 포함 → 실제 접속·운영 요구로 재선정.
- 부팅 때 기존 노드를 덮거나 재복사 → 버전과 활성·비활성 상태를 따로 기록. 비활성 노드가 재부팅 때 되살아나지 않게 한다.

## 3. 권장 아키텍처

### 3.1 이미지 구성

사용자용 최종 이미지는 우선 하나로 시작한다. `candidate`와 `stable`은 검증 단계와 태그이며 기능별 이미지 변형이 아니다. GPU별 이미지는 공통 스택이 실제로 성립하지 않을 때만 추가한다.

```text
고정한 runtime OS + Python + CUDA/PyTorch
                  │
                  ▼
gpu-base: GPU 스택 + 검증된 xformers + 시스템 라이브러리
                  │
                  ▼
app: ComfyUI + host Python lock + comfy-env/pixi + 노드 소스/어댑터
                  │
                  ▼
final: 실행 제어 + 다운로드 CLI + 환경 검사/복구 도구
                  │
                  ▼
candidate digest ── 두 GPU 검증 ── stable 태그 승격
```

`gpu-base`는 비용이 큰 층의 재사용을 위한 내부 배포 단위다. 실제 호환성 때문에 ComfyUI 요구사항이 GPU 스택 변경을 요구하면 기반층도 명시적으로 갱신한다. 단순히 Dockerfile을 나누는 것만으로 이 분리가 보장되지는 않는다.

PyTorch 공식 runtime 이미지 재사용과 최소 CUDA runtime 위에 잠근 Python 환경을 설치하는 방식을 초기 실험에서 비교한다. 전자는 관리 부담, 후자는 불필요한 conda·패키지 중복을 줄이는 데 유리할 수 있다. 정확한 버전 조합은 여섯 노드 및 comfy-env 검증 후 고정하며 레거시 버전을 자동 승계하지 않는다.

### 3.2 환경과 데이터 경계

| 영역 | 저장 위치 제안 | 관리 방식 |
|---|---|---|
| 검증된 ComfyUI·host 환경 | `/opt/runtime` | 이미지에 포함, 서비스 계정의 직접 변경 차단 |
| 검증된 기본 노드 소스·설치 정의 | `/opt/node-seeds` | SHA·패치·lock 기록 |
| 추가/업데이트 후보 코드·환경 | `/workspace/runtime/generations/<id>` | 검사 전에는 활성화하지 않음 |
| comfy-env worker 환경 | 버전별 독립 workspace | runtime fingerprint·세대와 연결 |
| 모델·입력·출력·워크플로 | `/workspace/storage` | 환경 롤백에서 제외 |
| 설치 이력·활성 환경 포인터 | `/workspace/state` | 마지막 정상 상태와 후보 상태 기록 |
| 패키지 다운로드 캐시 | `/workspace/cache` | 용량 제한, 실제 환경과 별도 관리 |

경로는 제안이다. comfy-env의 고정 버전에서 지원하는 workspace 설정과 pixi의 prefix 제약을 조사해 확정한다. 가상환경 디렉터리를 임의 경로로 복사하면 shebang·절대경로가 깨질 수 있으므로 최종 경로에 생성하고 포인터만 전환한다.

worker 환경을 이미지에 사전 구성할 수 있으면 포함해 첫 기동 설치를 줄인다. 두 GPU 공통 구성이 어렵거나 prefix 이식이 불가능하면, 잠근 설치 정의와 필요한 패키지를 준비하고 최초 1회 볼륨에 구성한다. 이 경우 최초 설치 시간과 이후 기동 시간을 분리해 보고한다. GPU 없는 CI에서 GPU/driver 자동 감지에 의존하는 설치는 피하고 지원되는 명시적 대상 설정을 사용한다.

RunPod의 container disk와 Pod volume, network volume은 수명과 성능이 다르다. Pod 삭제 후에도 유지해야 하는 모델·상태는 network volume 사용을 기본 배포 예제로 삼는다. 볼륨의 hardlink/reflink·파일 잠금·rename 동작도 실제 환경에서 검사한다. [RunPod 저장소 문서](https://docs.runpod.io/pods/storage/types)

## 4. 버전과 GPU 호환성 관리

RTX PRO 6000 Blackwell은 compute capability 12.0, H100은 9.0이다. Blackwell이라는 이름만 보고 데이터센터 B200용 커널을 그대로 사용할 수 있다고 판단하지 않는다. [NVIDIA GPU 목록](https://developer.nvidia.com/cuda/gpus)

단일 매니페스트와 생성된 lock에 다음을 기록한다.

- OS/base image digest, Python 버전, torch·torchvision·torchaudio, CUDA runtime 계열.
- xformers·Triton 및 선택한 추가 CUDA 확장의 정확한 artifact와 hash.
- ComfyUI release와 해석된 commit SHA, 프런트엔드 의존성, host 전체 패키지 lock.
- 노드 SHA, 로컬 어댑터/패치 hash, comfy-env·pixi 버전, worker별 Python·torch·CUDA 조합과 lock.
- 두 GPU에서 검증한 host driver 버전, 검증한 실행 backend, 대표 워크플로 결과.

host driver는 Pod 이미지가 설치하거나 복구하는 대상이 아니다. 기동 진단에 GPU 이름·compute capability·driver·`torch.version.cuda`·실제 커널 실행 결과를 표시한다. `nvidia-smi`가 보여 주는 CUDA 표기와 컨테이너의 실제 runtime 버전은 구분한다.

### 최적화 패키지 정책

1. 기본 실행 backend는 PyTorch SDPA를 우선한다. xformers를 설치했다고 전역 강제하지 않는다.
2. xformers는 포함을 목표로 한다. 선택한 torch 조합에 맞는 wheel과 두 GPU 커널 시험이 통과해야 정식 이미지에 넣는다. [xformers 공식 저장소](https://github.com/facebookresearch/xformers)
3. 호환 wheel이 없으면 조용히 소스 빌드하거나 torch를 교체하지 않는다. 다른 안정 조합을 검토하고, 지원 불가 상태를 기록한다.
4. FlashAttention·SageAttention은 별도 평가 대상으로 둔다. 필요한 노드가 있거나 측정상 이득이 있을 때 추가하고, 무조건 함께 설치하지 않는다. [FlashAttention 공식 저장소](https://github.com/Dao-AILab/flash-attention)
5. 선택적 backend의 실패는 명시적으로 SDPA로 우회할 수 있게 한다. 모델 로드 실패나 임의 예외까지 숨기는 광범위한 자동 재시도는 만들지 않는다.
6. host와 worker 각각 실제 선택한 backend를 기록한다. host의 성공이 worker의 확장 호환성을 대신하지 않는다.

## 5. 기본 노드와 comfy-env 적용 계획

### 5.1 포함할 노드

| 노드 | 기준 upstream | 격리 접근 | 필수 검증 |
|---|---|---|---|
| ComfyUI Manager | [Comfy-Org/ComfyUI-Manager](https://github.com/Comfy-Org/ComfyUI-Manager) | UI·설치 제어는 host 연동을 우선 검토. 설치 작업의 후보 환경 실행을 분리 | 검색·설치·비활성화·재시작·복구 경로 |
| KJNodes | [kijai/ComfyUI-KJNodes](https://github.com/kijai/ComfyUI-KJNodes) | comfy-env 어댑터 우선 시험 | 이미지/마스크·텐서·모델 객체·전역 훅 |
| iTools | [MohammadAboulEla/ComfyUI-iTools](https://github.com/MohammadAboulEla/ComfyUI-iTools) | 계산부 격리, UI/서버 연동 경계 확인 | 프롬프트·파일 저장·미리보기·프런트엔드 호환 |
| SAM3 | [PozzettiAndrea/ComfyUI-SAM3](https://github.com/PozzettiAndrea/ComfyUI-SAM3) | upstream의 comfy-env 연동을 우선 사용 | 이미지 분할·짧은 영상·모델 접근 권한 |
| Video Helper Suite | [Kosinkadink/ComfyUI-VideoHelperSuite](https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite) | comfy-env 어댑터 우선 시험 | 영상 읽기·출력·오디오·FFmpeg·배치 처리 |
| DepthAnythingV3 | [PozzettiAndrea/ComfyUI-DepthAnythingV3](https://github.com/PozzettiAndrea/ComfyUI-DepthAnythingV3) | upstream의 comfy-env 연동을 우선 사용 | 단일 이미지 깊이·여러 프레임·다른 노드와 연결 |

iTools 경로는 조사 중 정정한 공식 저장소를 사용한다. 위 표의 격리 접근은 구현 목표이며, 아직 모두 격리 실행이 가능하다고 확인한 상태는 아니다.

SAM3와 DepthAnythingV3는 확인 시점의 README에서 comfy-env/pixi를 사용하는 실험적 설치 방식을 명시한다. 따라서 최우선 호환성 실험 대상으로 둔다. [SAM3 설치 설명](https://raw.githubusercontent.com/PozzettiAndrea/ComfyUI-SAM3/main/README.md), [DepthAnythingV3 설치 설명](https://raw.githubusercontent.com/PozzettiAndrea/ComfyUI-DepthAnythingV3/main/README.md)

### 5.2 comfy-env 우선 적용 원칙

- 기본 6종과 이후 추가 노드에 같은 분류를 적용한다: upstream 격리 지원 → 최소 어댑터 적용 → 기능 일부 격리 → 불가피한 host 예외.
- 단순히 노드별 venv를 만든 뒤 host에서 import하는 방식은 격리가 아니다. comfy-env의 worker 등록과 실제 실행 프로세스를 검사한다. [worker 등록 문서](https://docs.comfy-forge.org/comfy-env/register-nodes/)
- 루트 설정과 격리 환경 설정의 역할은 구분하고, 고정한 버전의 코드·스키마에 맞춰 설치한다. 최신 문서의 키를 과거 버전에 그대로 적용하지 않는다. [comfy-env 저장소](https://github.com/PozzettiAndrea/comfy-env), [설정 문서](https://docs.comfy-forge.org/comfy-env/config/)
- 노드 전체가 어렵다면 UI·host 훅은 얇게 남기고 충돌이 큰 계산 의존성을 worker로 옮긴다. 어댑터는 upstream SHA와 함께 잠그고 변경량을 작게 유지한다.
- Manager처럼 host 서비스와 밀접한 노드는 격리율 자체보다 정상 기능과 설치 경계 보존을 우선한다. 예외 사유·host 추가 패키지·복구 절차를 기록한다.
- host와 worker 간 torch/CUDA ABI가 서로 달라도 항상 안전하다고 가정하지 않는다. 설치 문서는 torch 공유 ABI를 이유로 host pin을 worker에 맞추는 동작을 설명한다. 선택 버전에서 이를 직접 확인한다. [설치 및 pin 설명](https://docs.comfy-forge.org/comfy-env/install/)
- 격리 성공 판정에는 텐서·MASK·IMAGE·LATENT·모델 객체 전달, 진행률·취소·예외·UI route, VRAM 반환과 worker 재시작을 포함한다.
- worker 수만큼 CUDA context와 패키지 복제가 늘 수 있다. 순차·교차 실행에서 메모리와 지연을 측정하고, 호환성과 장애 범위가 같은 계산부만 환경 공유를 검토한다. [프로세스 격리 설계](https://docs.comfy-forge.org/comfy-env/adr/0001-process-isolation-via-persistent-subprocess-workers/)
- 환경을 못 만들었을 때 host import로 흘러가는 경로가 있는지 고정 버전에서 시험한다. 격리 필수 노드는 실패 시 비활성화하고 host 자동 설치로 대체하지 않는다.
- comfy-env는 의존성 격리 도구이며 파일·네트워크 접근을 막는 보안 sandbox로 간주하지 않는다. 실행 계정과 파일 권한도 별도로 관리한다.

### 5.3 숨은 노드 의존성 처리

확인 시점의 SAM3 루트 설정은 VideoHelperSuite 외에 Multiband를, DepthAnythingV3는 KJNodes·VideoHelperSuite 외에 GeometryPack을 요구한다. 여섯 저장소만 clone하면 끝나는 구성이 아니다. [SAM3 설정](https://raw.githubusercontent.com/PozzettiAndrea/ComfyUI-SAM3/main/comfy-env-root.toml), [DepthAnythingV3 설정](https://raw.githubusercontent.com/PozzettiAndrea/ComfyUI-DepthAnythingV3/main/comfy-env-root.toml)

초기 실험에서 선택한 SHA의 전체 노드 의존성을 펼친다. 필수 추가 노드는 간접 의존성으로 명시하고 SHA·설치 비용을 잠근다. 선택 기능만 요구하는 노드는 해당 기능을 분리할 수 있는지 확인한다. 지정 목록 밖의 노드가 런타임에 무기록으로 설치되지 않게 한다.

## 6. GitHub Actions 빌드와 ComfyUI 업데이트

### 6.1 빌드 파이프라인

```text
PR: 매니페스트/lock 검사 → 셸·Python·Docker 정적 검사 → 변경 범위 판정
                                                       │
                                                       ▼
필요한 기반층만 빌드 → 앱/노드/worker 구성 → CPU smoke → candidate push
                                                       │
                                                       ▼
                                GPU 2종 시험 → 동일 digest stable 승격
```

- GPU 기반층은 base digest와 GPU lock이 같으면 재사용한다. Caddy 등 운영 파일 변경이 torch 설치층을 무효화하지 않도록 COPY 순서를 설계한다.
- 무거운 노드 환경은 독립 BuildKit target/cache로 만들고 실제 최종 이미지 조립 방식은 prefix 이식 시험 후 결정한다. 공통층을 여러 runner에서 중복 빌드하는 과도한 matrix는 피한다.
- GHCR registry cache를 기본 후보로 두고 `mode=max`의 업로드 비용까지 비교한다. cache key에는 OS·Python·GPU lock·노드 SHA·어댑터·comfy-env/pixi 및 artifact hash를 반영한다.
- `RUN --mount=type=cache`와 외부 레이어 캐시는 다르다. GitHub Actions에서 cache mount 내용이 자동 영속화된다고 가정하지 않는다. 별도 캐시 저장/복원은 시간 절감 효과가 확인될 때 도입한다. [Docker 캐시 문서](https://docs.docker.com/build/ci/github-actions/cache)
- 문서만 바뀌면 이미지 빌드를 생략한다. 완전히 같은 입력의 이미지 재사용은 성공한 검증 기록과 연결하고, 캐시 hit와 검증 완료를 혼동하지 않는다.
- 입력 lock을 먼저 생성하고 설치 단계는 frozen 상태로 실행한다. 빌드 중 최신 버전을 해석하거나 외부 wheel을 임의 선택하지 않는다.
- 동시성 제한·디스크 정리는 비용을 측정해 유지한다. PR 검증·candidate 생성·배포 승격을 나눠 배포가 중간 취소되지 않게 한다.
- 기본 registry는 GHCR로 단순화한다. Docker Hub는 RunPod pull 성능이나 사용 요구가 확인되면 최종 digest를 미러링한다.

### 6.2 ComfyUI 버전업 절차

1. 정기 점검 또는 수동 명령으로 안정 release를 찾고 SHA와 프런트엔드 요구사항을 기록한 업데이트 PR을 만든다. 자동 운영 반영은 하지 않는다.
2. 기존 GPU 스택을 유지한 채 ComfyUI와 host 의존성을 다시 해석한다. 변경된 요구사항이 torch 교체를 요구하면 기반층 업데이트로 분류한다.
3. 노드 SHA는 기본적으로 유지한다. 필요한 노드·어댑터만 함께 올려 실패 원인을 좁힌다.
4. comfy-env의 host 연동과 worker lock 재사용 가능 여부도 검사한다. host 코드 변경이 worker 호환성에 영향을 줄 수 있다.
5. CPU 검사와 두 GPU의 대표 워크플로를 통과한 candidate digest만 stable로 승격한다.
6. 직전 stable digest·lock·노드 정의를 보존하고, Pod 재배포 및 정상 환경 선택으로 되돌리는 절차를 시험한다.

ComfyUI 버전 변경으로 GPU 기반층을 반드시 재빌드하는 구조와, 호환성 변화가 있어도 기반층을 무조건 재사용하는 구조를 모두 피한다.

## 7. 추가 노드 설치와 환경 복구

### 7.1 설치 흐름

운영 명령은 `comfyctl`이라는 CLI로 묶는 안을 제안한다. 이름과 문법은 구현 시 확정한다.

```text
설치 요청 → 노드/설치 훅 분석 → comfy-env 적용 분류
         → 후보 코드·host 환경·worker workspace 준비
         → 의존성 해석 및 변경 계획 표시
         → 후보에만 설치 → 패키지/노드/API/GPU 검사
         → 실행 중 작업 종료 대기 → 정상 상태 기록 → 전환·재시작
```

- `comfyctl node add <repo>`: 가능한 경우 worker 환경에 설치한다. host 예외가 필요하면 적용 범위를 출력한다.
- `comfyctl node disable <name>`: 코드 삭제와 별개로 비활성 상태를 영속화한다.
- `comfyctl env status`: host·worker별 버전, 현재 세대, drift, 마지막 정상 상태를 보여 준다.
- `comfyctl env rollback`: 마지막 정상 코드·host·worker 조합으로 전환하고 관련 worker를 종료·재시작한다.
- `comfyctl env reset`: 이미지의 검증된 기본 노드와 환경으로 돌아가되 모델·워크플로·출력을 보존한다.

Manager UI도 이 흐름으로 연결하는 것이 목표다. 우선 고정 버전의 설치·업데이트·시작 시 지연 설치 경로를 조사한다. 안전하게 연결할 확장점이 없으면 무리한 전역 monkey patch 대신 관리 CLI를 설치 경로로 제공하고 Manager의 직접 환경 변경 기능을 제한한다. UI에서 클릭한 설치만 보호되고 예약 설치나 CLI가 빠지는 상태는 완료로 인정하지 않는다.

Manager의 pip override·blacklist·자동 수정은 보조 장치다. 임의 `install.py`나 subprocess pip까지 통제하는 sandbox는 아니다. [Manager 설정](https://github.com/Comfy-Org/ComfyUI-Manager#config)

### 7.2 보호 범위와 복구 보장

- host 핵심 보호 대상: Python ABI, torch 계열, CUDA 제공 패키지, Triton, xformers, comfy-env와 ComfyUI 핵심 의존성. worker는 각 lock의 보호 범위를 별도로 가진다.
- 호환 가능한 공통 venv가 필요한 경우 `--system-site-packages` 없이 만들고 전체 lock으로 구성한다. 추가 패키지까지 제거할 수 있는 sync/재생성 방식으로 복구한다. [uv lock 문서](https://docs.astral.sh/uv/pip/compile/)
- 버전 문자열뿐 아니라 설치 artifact/hash·해석된 의존성·import 경로·`pip check` 및 GPU 커널을 검사한다.
- 이미 쓰는 환경에 `pip install -U`를 실행하지 않는다. 후보 환경은 최종 prefix에 새로 만들고 검증 후 선택한다. venv를 그대로 이동하지 않는다.
- 코드 SHA, 어댑터, host lock, worker별 lock과 환경 위치, 노드 상태를 한 상태 기록에 묶는다. Python만 되돌리고 노드는 새 버전으로 남기는 복구는 피한다.
- comfy-env의 전역 환경 이름 때문에 후보와 운영 worker가 같은 경로를 재사용하는지 검사한다. 실제 workspace 분리가 불가능하면 해당 버전에서 동시 후보 시험을 금지하고, 별도 컨테이너에서 검증 후 재구성하는 절차를 사용한다.
- 파일 캐시를 이용해 재설치 비용을 줄이되, mutable 환경끼리의 무분별한 hardlink로 다른 환경까지 바뀌지 않게 한다. 파일시스템별 copy/reflink 정책을 검증한다.
- 실행 계정이 기본 `/opt` 환경을 수정하지 못하게 한다. 임의 설치 스크립트가 모델·사용자 파일을 건드리는 문제까지 환경 롤백으로 복구된다고 약속하지 않는다.
- 네트워크 없이 즉시 가능한 복구는 보존한 정상 환경 또는 이미지 기본 환경으로 복귀하는 범위다. 삭제한 환경 재생성은 lock뿐 아니라 패키지 artifact가 필요하다.
- 최소 직전 정상 세대와 현재 세대를 보존한다. 용량 부족 시 설치를 시작하지 않고, 활성/정상 환경을 GC가 삭제하지 않게 한다.

## 8. 이미지 경량화와 실행 제어

### 경량화

- 모델 checkpoint·영상 테스트 자산은 이미지에 넣지 않는다. 다운로드 목록으로 제공한다.
- 컴파일러·CUDA toolkit·헤더는 별도 builder에만 둔다. 필수 런타임 라이브러리와 영상 처리용 FFmpeg는 남긴다.
- torch·CUDA 라이브러리의 base/venv/worker 중복을 측정한다. comfy-env 적용 때문에 커진 부분도 별도로 보고한다. 안전한 격리를 용량만을 이유로 해제하지 않는다.
- 설치와 같은 레이어에서 임시 파일을 지운다. 나중 레이어의 삭제로 이전 레이어 크기가 사라진다고 계산하지 않는다.
- 노드의 docs/tests를 일괄 삭제하지 않는다. 런타임 자산·예제 설정을 참조하는지 검사하고 제거 목록을 정한다.
- code-server·GitHub CLI·runpodctl·범용 파일 관리자 등은 필수 시나리오가 없으면 기본 이미지에서 제외한다. 필수 복구·다운로드 기능은 가벼운 CLI로 제공한다.
- 패키지 캐시를 최종 이미지와 볼륨에 중복 보관하지 않는다. 초기 준비 속도를 위해 남기는 artifact는 용량과 이유를 명시한다.

### 실행과 장애 상태

- PID 1, 종료 신호 전달, 자식 worker 정리를 단순한 entrypoint와 검증된 프로세스 관리 방식으로 구현한다. supervisord 유지 여부는 실제 RunPod 시험으로 정한다.
- 상태는 `준비 중 / 정상 / 복구 필요`로 구분한다. ComfyUI 기동 실패를 정상 상태로 표시하지 않는다.
- 반복 기동 실패 시 무한 재시작 대신 로그와 복구 경로를 제공한다. Docker HEALTHCHECK만으로 RunPod가 자동 복구한다고 가정하지 않는다.
- 공개 접근은 RunPod 프록시 또는 단일 인증 진입점 중 운영 방식에 맞게 선택한다. 레거시 Caddy/AuthCrunch 전체를 필수로 승계하지 않되, 인증 없는 관리·설치 기능을 인터넷에 노출하지 않는다.
- 정상 재기동에서는 재설치나 upstream 최신 조회를 하지 않는다. worker 재사용과 모델 캐시는 runtime fingerprint에 맞는지 확인한다.

## 9. Hugging Face / Civitai 다운로드

### 사용자 경험

HF URL·repo와 파일 경로·Civitai 모델 페이지/버전 URL을 입력하면 알맞은 모델 폴더로 내려받는 통합 명령을 제공한다. 아래는 예정 인터페이스다.

```bash
comfyctl model add 'https://huggingface.co/<owner>/<repo>/resolve/<revision>/<file>' --type diffusion_models
comfyctl model add 'https://civitai.com/models/<id>?modelVersionId=<version>' --type loras
comfyctl model sync models.yaml
comfyctl model status
```

### 구현 범위

- HF는 공식 `huggingface_hub`/`hf download` 기능을 우선 사용한다. repo·revision·파일을 해석하고 인증·다운로드 상태를 처리한다. [HF CLI 문서](https://huggingface.co/docs/huggingface_hub/guides/cli)
- Civitai는 공식 CLI 또는 Site API를 얇게 감싼다. 공식 CLI의 추가 runtime 비용과 재개·인증 지원을 비교해 선택한다. [Civitai 공식 CLI](https://github.com/civitai/cli/)
- Civitai의 model ID·version ID·file ID를 구분한다. 여러 파일이면 후보를 보여 주거나 명시적으로 선택하게 하고 임의의 첫 파일을 받지 않는다.
- 모델 종류를 알 수 없으면 `--type`으로 지정하게 한다. 저장 위치는 모델 루트 안으로 제한하고 외부 경로·악성 파일명을 거부한다.
- `HF_TOKEN`, `CIVITAI_TOKEN` 또는 권한 제한된 credential 파일을 사용한다. 이미지·Git·로그에 토큰을 남기지 않고 redirect 시 다른 호스트로 인증 헤더가 유출되지 않게 한다.
- 라이선스 동의·gated 접근이 필요한 경우 필요한 조치를 출력한다. 접근 권한 취득과 다운로드 성공을 구분한다.
- 임시 파일에 저장한 뒤 크기·제공된 hash를 확인하고 최종 경로로 rename한다. HTML 로그인 페이지를 모델 파일로 저장한 경우도 실패 처리한다.
- 중단 재개, 제한된 재시도와 backoff, 429/401/403 구분, 동시 다운로드 제한, 디스크 여유 확인을 구현한다.
- 동일 목적지 중복 작업은 잠근다. HF 캐시와 최종 모델 복사로 용량이 두 배가 되는지 측정하고 저장 정책을 정한다.
- 목록 파일은 source·repo/revision 또는 version/file ID·target·가능한 hash를 가진다. 기존 `docs/models/*.yaml`은 포맷과 링크를 재검증해 가져온다.
- 최초 버전은 CLI와 YAML 일괄 다운로드에 집중한다. 웹 UI는 다운로드 엔진이 안정된 뒤 필요하면 붙인다.

## 10. 단계별 작업과 산출물

| 단계 | 작업 | 산출물 | 다음 단계 진입 조건 |
|---|---|---|---|
| P0: 호환성 실험 | 두 GPU 기준 스택 후보, 6종/간접 노드 SHA, comfy-env 버전/격리 시험, Manager 설치 경로 분석 | 호환성 표, host/worker lock 초안, 격리 예외 목록 | SAM3·DA3 실연산, 나머지 노드의 격리 또는 예외 경로 확인 |
| P1: 빌드 기반 | 매니페스트·lock 검증기, gpu-base/app/final, 정적 검사, registry cache | 새 Dockerfile·CI·빌드 시간 기준값 | 같은 입력 재현·앱 변경 시 기반층 재사용 |
| P2: 런타임·노드 | 6종과 어댑터, worker 환경 구성, 영속 경로, readiness·로그·종료 처리 | 실행 가능한 candidate, 대표 워크플로 | 두 GPU에서 노드 연결·UI·VRAM 검증 |
| P3: 설치·복구 | 설치 후보 처리, Manager 연계/제한, 환경 상태·rollback/reset, 비활성화·GC | 관리 CLI, 장애 복구 문서 | 설치 실패·손상·중단 후 정상 상태 복귀 |
| P4: 다운로드 | HF/Civitai 해석·인증·재개·검증·일괄 처리 | 모델 CLI·목록 스키마·예제 | 공개/인증/중단/오류 시나리오 통과 |
| P5: 최적화·배포 | 캐시·용량·기동 측정, GPU 회귀, digest 승격·이전 digest 복귀 | 성능 비교표, RunPod template 가이드, 새 릴리스 | 전체 수용 기준 충족 |

선행 의존성은 P0 → P1 → P2 → P3 → P5다. P4는 영속 경로와 CLI 기반이 정해지면 P2/P3와 독립적으로 진행할 수 있다. 작업량은 P0에서 comfy-env 어댑터 난이도를 확인한 뒤 산정한다. GPU 대여·원격 실행·실제 배포는 구현 단계의 별도 실행 작업으로 남긴다.

### 예상 파일 구조

```text
build/stack.yaml                 # 직접 관리하는 버전·이미지·노드·설치 정책
locks/host/                     # host 전체 의존성과 artifact 잠금
locks/workers/                  # comfy-env/pixi 환경별 잠금
docker/                        # 기반층과 최종 이미지 정의
adapters/                      # SHA에 묶인 comfy-env 어댑터/최소 패치
runtime/                       # entrypoint·진단·상태 관리
tools/comfyctl/                 # 노드·환경·모델 관리 명령
tests/workflows/                # 6종과 연결 동작을 검증할 작은 워크플로
.github/workflows/              # 검증·candidate·업데이트·승격
docs/                          # 새 운영·업데이트·복구 가이드
```

직접 편집하는 설정과 생성물을 구분한다. 노드 설정·build args·문서의 버전 표를 따로 손으로 관리하지 않게 한다. 레거시 파일은 새 구현 검증 후 정리하고 Git 히스토리를 참조점으로 남긴다.

## 11. 수용 기준과 측정 목표

아래 시간·비율은 초기 목표다. 기존 `main`과 신규 구현을 같은 runner·네트워크 조건에서 측정한 뒤 현실적인 기준으로 확정한다. 각 조건을 가능하면 3회 측정해 중앙값과 범위를 남긴다.

| 항목 | 기준/초기 목표 |
|---|---|
| 문서만 변경 | 이미지 빌드 0회 |
| 동일 입력 재실행 | 이미 검증된 artifact 재사용, 불필요한 설치 0회 |
| ComfyUI만 업데이트 | GPU 기반층 재사용, warm build 10분 이내 목표 |
| 작은 runtime 변경 | torch/CUDA·노드 환경 재설치 0회 |
| 전체 빌드 | runner 메모리·디스크 한계 내 완료, 단계별 소요 기록 |
| 이미지 크기 | 레거시 custom-image/custom-video 각각과 비교. 추가 노드·격리 환경을 감안한 증감 원인과 중복량 제시 |
| GPU 커널 | 같은 digest로 H100·RTX PRO 6000 각각 연산·SDPA·xformers 시험 통과 |
| 6종 기능 | 노드 등록만이 아니라 대표 워크플로, UI와 노드 간 데이터 전달 통과 |
| comfy-env | 격리 대상의 실제 worker 실행 확인, host 환경 무변경, 누락 환경의 fail-closed 확인 |
| worker 자원 | 순차·교차 실행·취소·종료 후 VRAM/RAM 및 orphan process 검사 |
| 추가 설치 실패 | 기존 정상 환경 무변경, 후보 상태와 실패 로그 보존 |
| 복구 | 정상 환경이 보존된 경우 2분 이내 전환·기동 목표. 재다운로드가 필요한 재생성 시간은 별도 측정 |
| 기동 | 모델 로드 전 readiness까지 측정. 최초 환경 구성과 warm start를 분리 |
| 데이터 보존 | 업데이트·rollback·reset 후 모델·출력·워크플로 hash 불변 |
| 다운로드 | 공개·gated·복수 파일·중단 재개·잘못된 hash·용량 부족·중복 실행 시험 통과 |

환경 손상 시험에는 torch 교체를 요구하는 노드, 충돌하는 NumPy/transformers, 설치 훅 실패, worker 환경 삭제, 프로세스 강제 종료, 후보 생성 중 Pod 중단을 포함한다. 복구는 host만이 아니라 노드 코드와 worker까지 확인한다.

## 12. 초기 결정이 필요한 항목과 판단 기준

1. **기준 스택:** 최소 용량보다 두 GPU와 여섯 노드의 공통 안정 조합을 우선한다. 버전 번호는 P0 실험 결과로 확정한다.
2. **comfy-env 버전:** SAM3/DA3가 요구하는 버전과 최신 문서가 다를 수 있다. 두 노드·host·어댑터를 함께 검증한 조합을 선택한다.
3. **격리 예외:** Manager·전역 훅·모델 객체 전달이 어려운 노드는 host 예외를 최소화하되 기능을 조용히 제거하지 않는다.
4. **간접 노드:** Multiband·GeometryPack 등의 필요성을 기능별로 확인하고 최종 포함 목록에 명시한다.
5. **worker 사전 구성:** 이미지 크기와 최초 Pod 준비 시간을 함께 비교한다. 부팅 때 잠금 없는 설치를 허용하는 절충은 하지 않는다.
6. **기본 접속 방식:** RunPod 프록시와 직접 TCP의 인증·복구 동선을 확인하고 가장 단순한 구성을 정한다.

첫 구현은 P0의 호환성 실험부터 시작한다. comfy-env 격리와 Manager 설치 경계를 검증하기 전에 전체 Docker/CI 구조를 확정하지 않는다.
