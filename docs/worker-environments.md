# comfy-env worker 환경

현재 구현은 SAM3와 DepthAnythingV3의 P0 후보다. 나머지 네 노드, 실제 분할·깊이 모델 추론, GPU worker 검증과 운영 계정 보호는 아직 남아 있다.

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
