# 동적 노드 metadata

관리 runtime은 `INPUT_TYPES`, `IS_CHANGED`, `VALIDATE_INPUTS`를 해당 노드의 private Python 환경에서 실행한다. 파일을 추가한 다음 조회에서 선택 목록을 다시 읽으며, 검증 오류와 변경 감지 결과를 ComfyUI에 전달한다. 고정한 comfy-env 0.3.89의 원본 proxy는 시작 시 읽은 INPUT_TYPES를 반환하므로 별도 연결이 필요하다.

## 프로세스와 전송

계산 worker와 별도의 CPU metadata worker를 사용한다. `COMFY_CPU=1`, `CUDA_VISIBLE_DEVICES=''`, PyTorch attention을 적용하고 같은 source root와 models/input/output/user 경로를 쓴다. 긴 계산이 metadata RPC lock을 점유하지 않는다. host에서 노드 의존성을 import하지 않는다.

metadata는 SDK의 socket transport로 JSON 문자열만 주고받는다. tensor serializer·decoder와 전역 FD/cache 정리를 호출하지 않아 계산 중인 tensor 전송을 건드리지 않는다. tuple·bytes·float를 구분하며 NaN을 매번 새 값으로 복원해 항상 재실행하는 IS_CHANGED 신호도 보존한다. 임의 Python 객체가 필요한 metadata 콜백은 검토한 adapter가 필요하며, 실패를 host import나 성공 응답으로 바꾸지 않는다.

HTTP 요청 한 건에서는 환경별 INPUT_TYPES를 일괄 조회한다. 같은 요청의 중복 조회를 줄이고 다음 요청에서는 새 snapshot을 만든다. 파일 목록을 pickle이나 시간 기반 TTL로 고정하지 않는다. IS_CHANGED와 VALIDATE_INPUTS는 매번 실행하고, classmethod signature·기본 인자 유무·kwargs와 비동기 콜백을 전달한다. DynamicCombo 자식 입력과 V1 hidden 값 변환도 유지한다.

호출 중 worker가 죽으면 해당 요청은 실패한다. 죽은 transport와 임시 파일을 정리하고 다음 요청에서 새 CPU worker를 만든다. 살아 있는 계산 worker는 교체하지 않는다. 별도로, SDK PoolIPC의 전역 pool handle은 호출별 ContextVar로 바꿨다. 원본 두 호출의 경쟁 상태를 CPU 단위 검사에서 재현했으며 실제 GPU PoolIPC 커널 검증과는 구분한다.

## 메모리와 후보 검증

CPU metadata 프로세스도 torch와 노드 의존성을 import하므로 RAM을 사용한다. [실측 JSON](../tests/evidence/dynamic-metadata-cpu.json)에 프로세스별 RSS/PSS, 계산 중 조회 지연과 복구 시간을 남긴다. 이 수치는 로컬 Linux amd64 에뮬레이션 결과이며 native runner와 RunPod 측정은 별도다.

실행 중 서비스와 후보를 동시에 검증할 때 기본 노드 metadata pool을 두 벌 유지하지 않는다. 후보의 기본 노드 콜백은 임시 CPU worker에서 실제 실행한 뒤 종료한다. 추가 노드는 후보의 private worker에 콜백 상태를 유지한다. schema 조회·대표 계산을 생략하는 방식은 쓰지 않는다. 정상 서비스는 독립적인 warm pool을 유지한다.

metadata에서 GPU 연산이나 임의 host 객체를 요구하는 노드는 별도 adapter 검토 대상이다. 기본 노드의 CPU schema와 GPU 계산의 역할을 구분하며, metadata 성공만으로 GPU 추론 성공을 판단하지 않는다.

## 검증

[metadata gate](../tests/evidence/dynamic-metadata-cpu.json)는 실제 SDK/private 프로세스에서 다음을 검사한다.

- 실행 중 입력 파일 추가와 실제 DA3 로더의 로컬 모델 선택 목록 갱신. 모델 항목 검사는 이름뿐이며 가짜 파일을 추론에 쓰지 않는다.
- classic cache에서 동일 파일의 결과 재사용, 파일 변경 후 재실행, NaN의 연속 재실행.
- VALIDATE_INPUTS의 실제 거부와 `input_types` 인자 전달.
- 계산이 실행 중일 때 metadata 응답, worker 종료와 콜백 처리 도중 종료 후 재조회 복구, 계산 PID 보존.
- CPU/서비스 UID/private interpreter 확인, 이미지 package fingerprint 보존과 자원 정리.

기본 RAM cache의 runtime 회귀는 [별도 gate](../tests/evidence/dynamic-metadata-runtime-cpu.json)로 검사한다. GPU·RunPod network volume 및 모든 추가 노드의 metadata 호환성 인증으로 확대하지 않는다.
