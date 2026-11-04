# comfy-env worker 환경

현재 구현은 SAM3·DepthAnythingV3의 native worker와 iTools·KJNodes 혼합 격리 P0 후보다. H100·RTX PRO 6000에서 실제 분할·깊이 모델 추론과 GPU worker 연결을 확인했다. Manager·VHS와 운영 계정 보호는 아직 남아 있다.

## 실행과 설치를 분리한다

고정한 comfy-env의 `register_nodes`, 메타데이터 스캔, `SubprocessWorker`, 텐서 IPC를 사용한다. 의존성 해석은 upstream 설치기에 맡기지 않고 `uv`의 hash lock으로 수행한다. comfy-env가 일반 venv 인터프리터를 직접 실행하는 경로를 사용하므로 pixi 자동 다운로드와 CUDA wheel에 맞춘 torch 자동 변경을 거치지 않는다.

- 직접 관리하는 정의: `build/stack.yaml`의 `workers`.
- 고정 upstream 설정을 검증한 입력: `build/inputs/workers`.
- 실제 설치 파일과 hash: `locks/workers`.
- 사전 구성한 worker: `/opt/workers/sam3-nodes`, `/opt/workers/depthanythingv3-nodes`.
- `COMFYCTL_WORKER_ROOT`로 세대별 최종 prefix를 선택한다. venv를 만든 뒤 다른 경로로 옮기지 않는다.

`tools/rebuild/apply_comfy_env_patch.py`는 정확히 일치하는 원본 파일 hash에서만 패치한다. worker prefix 선택, 누락 환경 거부, CPU 검사 설정 전달, attention 정책을 적용한다. 모르는 comfy-env 버전을 추정해서 패치하지 않는다.

## 공유하는 것은 GPU 기반 패키지뿐이다

별도 venv에서 `--system-site-packages`를 사용하지 않으며 host site-packages를 worker의 `sys.path`에 넣지 않는다. NumPy·변환기·영상·기타 노드 패키지는 worker 안에 설치한다.

현재 같은 Python ABI와 GPU 스택을 쓰는 두 worker는 torch 계열·Triton·xformers·CUDA 제공 패키지의 본체 파일만 기반 환경에서 symlink로 참조한다. 작은 dist-info는 각 worker에 복사한다. uv가 symlink dist-info를 설치된 패키지로 인식하지 않는 동작을 실제로 확인했기 때문이다. 다른 ABI/torch가 필요한 후보는 이 공유 경로를 쓰면 안 된다.

이 방식의 운영 전제는 서비스 계정이 기반 패키지를 수정할 수 없다는 것이다. 현재 root로 실행하는 P0 검증 이미지는 이 계정 경계까지 완성한 운영 이미지가 아니다. P2/P3에서 계정·권한과 후보 설치를 구성한 뒤 손상·복구 시험을 추가한다.

## attention과 선택 확장

host와 worker의 기본 attention은 PyTorch다. `COMFYCTL_WORKER_ATTENTION=pytorch`가 worker의 확장 자동 선택보다 우선한다. 별도 선택 값 `xformers`도 지원하며, 모르는 값은 거부한다. xformers 설치 여부만으로 기본 backend를 바꾸지 않는다.

SAM3의 cc_torch·torch_generic_nms·FlashAttention, DA3의 FlashAttention·SageAttention은 현재 worker에 추가하지 않는다. 고정한 소스에서 PyTorch/CPU fallback이 있는 선택적 가속이며, SAM3 영상 NMS·연결 성분 처리의 성능 영향은 실제 영상 시험에서 측정해야 한다. CUDA 확장 목록이 바뀌면 입력 생성기가 검토되지 않은 확장으로 거부한다. 확장을 추가하려면 정확한 artifact와 두 GPU 커널 검증이 필요하다.

ffmpeg는 시스템 runtime 패키지, av는 잠근 Python wheel로 제공한다. DA3 설정의 C compiler는 runtime에 설치하지 않는다. 현재 worker 의존성은 Linux wheel로 구성하며 설치 훅이나 암묵적 소스 컴파일을 실행하지 않는다. host 프런트엔드·예제 미디어·문서 패키지도 worker에 중복 설치하지 않는다.

## 재현과 검증 범위

```bash
uv run python tools/rebuild/prepare_workers.py --verify-locks
uv run python tools/rebuild/build_probe.py --target worker-probe
uv run python tools/rebuild/probe_workers.py
```

`probe_workers.py`는 자신이 만든 컨테이너만 사용하고 종료 시 삭제한다. 단순 등록 검사에 더해 다음을 실제 ComfyUI API로 실행한다.

- IMAGE → SAM3 Point Collector → host PreviewAny: 좌표 정규화와 UI JPEG 반환.
- DA3 Camera Parameters → host PreviewAny: 두 카메라 행렬의 숫자와 형태 보존.
- 서로 다른 worker PID·venv prefix, worker 전용 패키지 경로와 host sys.path 비노출.
- 실제 노드 예외 전파 후 worker 생존.
- SAM3 worker 강제 종료 후 다음 호출에서 재생성, 다른 DA3 worker 유지.
- 실행 전후 host 패키지 metadata와 검사 대상 GPU 파일 hash 불변.

`tests/evidence/workers-cpu-probe.json`은 이 CPU 연결·복구 검사 결과다. SAM3 분할/영상 추적, DA3 깊이 추론, GPU IPC·VRAM 회수, UI 브라우저 조작의 성공 증거로 확대 해석하지 않는다. 실제 모델 검증용 고정 다운로드 목록은 `tests/fixtures/models-worker-smoke.yaml`에 따로 둔다.

## 다음 노드 어댑터에서 확인할 경계

현재 고정 소스에서 확인한 내용이다. 아직 해당 노드의 실제 통합 시험 결과는 아니다.

- iTools: `iTools_nodes.py`가 backend HTTP 모듈을 import하며, `backend/iserver.py`, `prompter.py`, `prompter_multi.py`가 PromptServer route를 직접 등록한다. multipart 업로드·이미지 파일 응답은 JSON 전용 worker route와 같지 않다. 계산 노드와 host HTTP 부분의 import 경계를 분리하고 원래 assets·styles 경로를 보존해야 한다.
- KJNodes: 루트의 `/kjweb_async`, 모델 시간 조회 route와 일부 노드의 PromptServer 미리보기 호출이 있다. metadata 스캔 성공만으로 미리보기나 MODEL 패치의 동작을 인정하지 않는다. 모델 패치 및 host callback을 유지하는 격리 예외가 필요한지 실제 연결 시험으로 판단한다.
- VHS: 영상·오디오 스트리밍 route, 전역 latent preview hook, host prompt queue를 다시 넣는 batch 동작이 있다. 열려 있는 입력 generator를 배치 상태에 보존하므로 일반 텐서만 전달하는 흐름과 다르다.

실제 comfy-env SubprocessWorker에 일반 dict와 generator를 보낸 [IPC 가능성 실험](evidence/comfy-env-generator-capability.json)에서 전자는 정상 반환되고 후자는 `Object of type generator is not JSON serializable`로 거부됐다. 이는 generator 경계에 대한 증거이며 VHS 워크플로 전체의 실패 판정은 아니다. 배치 기능을 없애거나 통째로 격리됐다고 주장하는 대신, 상태 소유 위치와 host 연동을 명시한 뒤 실제 영상·배치 그래프로 검증한다.

## 실제 GPU 모델 검사

GHCR의 `8125a0f4…f9c0c3d` 후보를 미국 H100(US-GA-2)과 RTX PRO 6000 Blackwell(US-NC-2)에서 실행했다. [H100 결과](evidence/native-h100-models.json)와 [Blackwell 결과](evidence/native-blackwell-models.json)에 CUDA 텐서 왕복, BF16 SDPA와 CPU 기준값 비교, worker별 prefix/PID, 실제 PyTorch attention 선택과 종료 결과를 기록했다. 이어서 고정한 공개 weight의 전체 SHA256·크기를 확인하고 다음 ComfyUI API 그래프를 통과했다.

- DA3 small BF16/SDPA: 단일 이미지와 3프레임 배치 깊이 출력.
- SAM3 BF16: 점 프롬프트 이미지 분할과 3프레임 순방향 영상 추적.
- 출력의 batch/channel 형태, 유한한 값, 비어 있지 않은 결과 확인.

입력은 256×256 합성 이미지다. 정확도·장시간 영상·성능 벤치마크나 6종 노드 전체 인증으로 해석하지 않는다. host의 할당 메모리 수치는 기록하지만 zero-copy나 GPU 전체 메모리 회수를 보장하는 시험은 아니다. 모델·관찰 노드는 일회용 Pod에만 추가했고 SAM3/DA3 소스·고정 패키지는 변경하지 않았다.

`tools/rebuild/verify_worker_gpu.py`는 CUDA 연결 검사, `verify_worker_models.py`는 실제 모델 그래프 검사다. 둘을 같은 디렉터리에 넣고 일회용 후보 컨테이너에서 `GATE_IMAGE_DIGEST=sha256:… GATE_EXPECTED_CC=9.0 python verify_worker_models.py`로 실행한다(Blackwell은 `12.0`). 모델 다운로드와 테스트 파일을 생성하므로 사용 중인 Pod에서 실행하지 않는다. CPU에서는 실패하며 성공 결과를 만들지 않는다. 당시 RunPod payload의 [정확한 suite 소스와 hash](evidence/native-worker-suite-source.json)도 보존했다. 독립 실행 스크립트는 같은 그래프를 사용하며, 인접한 CUDA 검사 파일을 읽고 결과 후 종료하도록 정리했다.

## iTools 혼합 격리 후보

고정한 iTools `a8f2fef2…a906b1a5b`에 `build/adapters/itools`를 적용한다. `apply_itools_adapter.py`는 원본 파일 hash, revision, HTTP decorator 수와 생성 파일 경로를 검증한 뒤 패치한다. adapter 파일과 패치 도구 hash도 worker manifest에 기록하며, 변경 후 lock identity를 갱신하지 않으면 빌드가 거부된다. 전체 archive를 사용하므로 스타일·폰트·web asset을 유지한다.

- upstream 기본 계산 노드 22개 중 KSampler·VAE Preview는 host 예외다. 각각 host의 live MODEL과 VAE를 직접 사용한다. host가 나머지 계산 모듈을 import하지 않도록 별도 namespace에서 두 모듈만 로드한다.
- 나머지 20개와 설정으로 켜지는 Paint/Crop beta 노드는 `itools-workernodes`의 실제 comfy-env worker로 등록한다. worker는 원래 catalog를 가져오며, 실제로 재-import할 수 있는 `worker_nodes.nodes.*` 모듈 이름을 유지한다.
- `nodes`라는 plugin 폴더가 ComfyUI의 top-level `nodes.py`를 가리는 충돌을 피하도록 worker의 ComfyUI source 경로를 우선한다. worker에서는 PromptServer를 import하거나 host HTTP route를 등록하지 않는다. multipart/file 응답과 스타일 HTTP route는 host에 유지한다.
- Paint 파일은 `<ComfyUI user directory>/comfyctl/itools/paint`, 기본 `prompts.txt`는 그 상위 데이터 폴더에 저장한다. `COMFYCTL_ITOOLS_DATA`를 지정하면 절대 경로만 허용한다. 기존 사용자 프롬프트를 덮어쓰지 않으며, 원본 examples의 내용을 최초 파일로 사용한다. 사용자가 명시한 다른 prompt 파일 경로는 원래 동작을 유지한다.

`probe_itools.py`는 자신이 만든 CPU 컨테이너를 삭제한다. 텍스트 V1→V3 UI, Checkerboard→V3 preview, Paint multipart/readback→worker 합성→host PNG와 픽셀 값, 스타일 template API, 기본 prompt 저장·로드, host 모듈 import 경계를 검사한다. VAE 예외는 소유 PID를 검사하는 합성 객체로 dispatch를 확인하며 실제 checkpoint 추론으로 표시하지 않는다. UI JS asset의 HTTP 응답과 브라우저의 실제 조작도 구분한다. 선택 rembg background-removal 기능은 이번 gate 범위가 아니다.

iTools 전용 lock은 GPU 기반층과 같은 torch 계열 pin을 유지한다. 다른 SAM3/DA3 venv의 임시 별칭을 사용한 초기 가능성 검사와 달리 최종 CPU gate는 별도로 구성한 frozen iTools prefix를 사용한다. 설정 변경에 따른 metadata cache 갱신, 영속 데이터 경로와 nonroot 권한은 P2/P3의 추가 시험 대상이다. comfy-env 0.3.89는 현재 metadata cache를 worker prefix에 쓰므로 운영 권한 분리 전에 cache 위치도 바꿔야 한다.

## KJNodes 혼합 격리 후보

고정한 KJNodes `ab72eda7…c0ba18`에 `build/adapters/kjnodes`를 적용한다. 정책에는 이미지·마스크·bbox·좌표 계산 등 108개 worker 노드를 명시했다. 전체 upstream catalog와 host hook은 유지하고, 해당 노드의 실행 클래스를 comfy-env proxy로 대체한다. 따라서 host에도 일부 계산 클래스 정의가 import되지만 해당 108개의 실행은 별도 worker로 전달한다. `color-matcher`와 OpenCV는 worker 전용 의존성으로 설치했다. host 모델/debug 차트에 필요한 matplotlib과 전이 패키지 8개만 host lock에 추가했으며 기존 pin은 바꾸지 않았다.

FastPreview·ImageResizeKJv2의 PromptServer callback, 모델/CLIP/GLIGEN 객체, 복잡한 V3 실행 문맥이 필요한 노드는 host 구현을 유지한다. 이는 해당 모델 워크플로 전체가 이미 검증됐다는 뜻은 아니다. 원래 catalog를 없애거나 선택 노드만 넣은 축소판도 아니다. 필수 worker 등록을 먼저 검증하므로 worker가 없으면 upstream host startup hook까지 실행하지 않는다. 원본 source·adapter/config/도구 hash를 worker identity에 포함한다.

[CPU 검사](../tests/evidence/kjnodes-cpu-probe.json)는 다음을 실제 ComfyUI로 통과했다.

- ColorMatchV2 histogram matching: 입력 픽셀 32 → 기준 픽셀 192. 원본을 돌려주는 upstream fallback으로 통과하지 않았음을 확인.
- ResizeMask → GetMaskSizeAndCount → host: MASK 수치·형태와 정수 width/height/count 보존.
- host bbox → KJ BboxToInt → host: 좌표·크기·중심 값 보존.
- 잘못된 bbox가 실제 KJ 노드에서 실패한 뒤 같은 PID가 살아 있고, 다른 입력의 uncached 재호출 성공.
- worker FloatToSigmas → host VisualizeSigmasKJ: 실제 matplotlib PNG와 SIGMAS 값 보존.
- host FastPreview → 실제 WebSocket binary PNG: 헤더·크기·픽셀 일치.
- 모델 시간 조회 HTTP와 web/추가 async JS asset 응답, host 패키지 불변, private worker 패키지 경로 및 컨테이너 삭제.

이는 108개 등록과 대표 CPU 워크플로에 대한 증거다. 모든 알고리즘, 실제 모델 패치·checkpoint 추론, GPU 계산과 브라우저 조작을 인증하지 않는다. 전체 노드의 새 입력 이미지 목록, `IS_CHANGED`·validation callback, 설정에 따른 metadata 갱신과 데이터 경로는 P2에서 추가 검증한다. 현재 comfy-env 0.3.89의 정적 proxy metadata를 동적 파일 목록/변경 감지의 성공 근거로 사용하지 않는다.
