# TODO

## P0 - 갈아엎는 수준으로 먼저 볼 것

- [ ] 컨테이너 생존 모델 재설계
  - 현재 `start.sh`는 ComfyUI가 죽어도 `code-server`가 살아 있으면 컨테이너를 계속 유지한다.
  - RunPod에서는 Pod는 살아 있는데 주 서비스는 죽은 상태가 될 수 있다.
  - 주 서비스 종료 시 컨테이너도 종료하거나, supervisor/healthcheck/recovery mode를 명시적으로 분리한다.

- [ ] Python 환경 복구 방식을 재설계
  - `restore-env.sh`는 lock 파일을 다시 설치할 뿐, 추가 설치된 패키지를 제거하지 않는다.
  - `--system-site-packages` venv 때문에 base image와 mutable venv 경계가 흐리다.
  - 하위호환을 버릴 수 있으므로 venv 재생성, `pip-sync`, 또는 immutable base + writable overlay 구조로 바꾼다.

- [ ] 빌드 정의를 단일 매니페스트 기반으로 재구성
  - 버전, refs, stage 정보가 workflow, Dockerfile defaults, README, docs에 중복되어 있다.
  - `compute-build-tags.sh`도 stage별 hash 계산이 손코딩되어 있다.
  - `images.yaml` 같은 단일 source of truth에서 build args, tags, docs 일부를 생성하는 구조를 검토한다.

## P1 - 신뢰성과 검증 강화

- [ ] 이미지 검증을 실제 ComfyUI 기동 검증으로 확장
  - 현재 `verify_image.py`는 custom node 디렉터리 존재만 확인한다.
  - custom node import 실패, missing system library, ComfyUI startup failure를 잡지 못한다.
  - build 단계에서 timeout 기반으로 ComfyUI를 기동하고 API endpoint를 확인한다.

- [ ] supply-chain 재현성 강화
  - `runpodctl`을 `latest`로 다운로드하지 말고 버전과 checksum 또는 digest를 고정한다.
  - `code-server.deb` 다운로드에 checksum 검증을 추가한다.
  - FlashAttention wheel resolver가 선택한 asset URL/digest를 build key 또는 lock artifact에 포함한다.

- [ ] custom node 설치 sandbox/allowlist 검토
  - 현재 각 repo의 `requirements.txt`와 `install.py`를 그대로 실행한다.
  - protected package drift 검증은 있지만 임의 파일 변경, 모델 다운로드, side effect는 통제하지 못한다.
  - 개인용이라도 node별 허용 동작, post-install 검증, 로그 보존 정책을 정한다.

- [ ] CI에 저비용 정적 검증 추가
  - Docker build 전에 `bash -n`, Python compile, `shellcheck`, `actionlint`, `hadolint` 등을 실행한다.
  - Docker build가 비싸므로 PR/manual 전 단계에서 빠르게 실패하게 만든다.

## P2 - 런타임 사용성 개선

- [ ] `CLI_ARGS` 전달 방식 개선
  - `read -ra` 기반 파싱은 quoting과 공백 포함 값을 제대로 다루기 어렵다.
  - JSON array, newline args file, 또는 명시적 env var allowlist로 바꾼다.

- [ ] `COMFY_ORIGIN` override 지원
  - 현재 `start.sh`와 `restart-comfyui.sh`는 RunPod pod id 또는 localhost로만 origin을 계산한다.
  - 사용자가 `COMFY_ORIGIN`을 명시하면 그 값을 우선 사용하게 한다.

- [ ] `restart-comfyui.sh`의 프로세스 종료 범위 축소
  - 현재 `pkill -f "python.*main.py"`는 같은 컨테이너 안의 다른 Python 프로세스를 잡을 수 있다.
  - pidfile 또는 supervisor 제어로 ComfyUI 프로세스만 종료한다.

- [ ] baked custom nodes cleanup 확인
  - `cleanup-image.sh`는 `${COMFY_HOME}` 아래 `.git`만 지우므로 `/opt/bootstrap/baked-custom-nodes`에 `.git`이 남을 수 있다.
  - 의도한 동작이면 문서화하고, 아니면 baked path도 cleanup 대상에 넣는다.

## P3 - 작은 정리

- [ ] `.gitignore` 확장
  - 로컬 산출물, temporary storage, logs, virtualenv 등 개인 작업 중 생길 수 있는 파일을 정리한다.

- [ ] 문서 자동화 범위 결정
  - README와 docs의 baseline 버전 표기가 빌드 설정과 쉽게 어긋날 수 있다.
  - 단일 매니페스트 도입 후 문서 일부를 생성하거나 검증하는 스크립트를 추가한다.

- [ ] `rtk test` 호환성 확인
  - 이 환경에서 `rtk test -f TODO.md`가 예상과 다르게 실패했다.
  - 필요하면 `rtk proxy test ...` 또는 다른 확인 방식을 문서화한다.
