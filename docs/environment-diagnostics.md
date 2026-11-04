# 환경 진단 CLI

`runtime-probe`의 `comfyctl`은 `/opt/comfyctl/venv`에 설치한다. CLI source·uv.lock·requirements hash를 runtime identity에 포함하며 host의 Hugging Face/PyTorch 의존성과 분리한다. GPU 패키지를 관리 CLI에 설치하지 않는다.

```bash
comfyctl env status
comfyctl env doctor
comfyctl env doctor --deep
```

`status`는 host·다섯 worker·도구 환경의 실제 인터프리터, Python과 패키지 버전, lock 대비 누락/추가/변경, GPU/NumPy/HF import 경로를 보여 준다. 진단은 노드나 GPU 모델 코드를 import하지 않고 각 인터프리터에서 metadata를 읽는다. host site-packages가 worker/tool 경로에 노출됐는지도 검사한다. 상태 조회의 exit code는 0이며 결과의 `ok`·`problems`·`runtime.healthy`를 함께 읽는다.

`doctor`는 각 prefix의 `uv pip check`, 실제 ComfyUI API와 runtime 상태, 제어 코드 hash를 확인한다. 문제가 없으면 0, 검사 결과에 문제가 있으면 2, 진단 자체를 수행할 수 없으면 1로 종료한다. 패키지를 설치하거나 자동 수정하지 않는다.

`--deep`은 설치된 wheel RECORD의 SHA256과 명시적인 comfy-env 로컬 패치 hash를 대조한다. GPU symlink가 같은 실제 파일을 가리키면 한 번만 hash하여 중복 읽기를 줄인다. console script·생성 파일·원래 hash가 없는 항목은 제외 개수를 표시한다. 검사 범위를 전체 디렉터리의 임의 추가 파일이나 모든 실행 상태로 확대하지 않는다. 수 GB를 읽을 수 있으므로 일반 상태 조회에는 포함하지 않는다. CUDA 커널·실제 모델 추론은 별도 GPU gate의 대상이다.

runtime 상태는 이미지 identity·PID namespace·heartbeat·host process·서비스 UID를 함께 확인한다. 이전 컨테이너의 ready 파일, 다른 이미지의 상태, 오래되거나 잘못된 heartbeat를 정상으로 취급하지 않는다. `doctor`는 loopback API 응답까지 확인한다. 읽기 전용 이미지에서 서비스 계정의 쓰기 거부는 별도 런타임 검사로 확인한다.

현재 이미지 환경을 그대로 쓰는 기본 노드의 enable/disable과 deferred rollback/reset을 지원한다. active·desired·last/previous good을 구분하고, 아직 확인하지 않은 last-known-good를 임의로 만들지 않는다. `candidate_switching_implemented`는 `deferred-state-only`로 표시한다. [세대 관리](generations.md)를 참고한다. 새 노드 설치·변경된 host/worker 환경·live queue 전환과 Manager 연결은 아직 구현 중이다.

[런타임 통합 검사](../tests/evidence/tools-runtime-cpu-probe.json)는 root 호출의 UID 1000 전환, 의도적으로 host PYTHONPATH를 넘겨도 private CLI를 사용하는 경계, 정상 dependency/파일 검사, 버전 metadata를 유지한 torch 파일 손상 감지와 기존 nonroot runtime 검사를 기록한다. 공개 파일의 실제 전송은 [별도 증거](../tests/evidence/tools-public-downloads-linux.json)로 구분한다.
