# 기본 노드의 세대 관리

현재는 **이미 검증된 이미지 환경을 그대로 사용하는 노드 상태 변경**을 지원한다. 새 노드 설치·의존성 변경은 후속 작업이다. `--defer`는 다음 컨테이너 재기동에 적용하고, `--restart`는 기존 큐의 작업이 끝나면 host와 worker 프로세스를 교체한다.

## 명령

관리 이미지의 root 터미널에서 실행한다. 일반 서비스 계정은 관리 상태를 변경할 수 없다.

```bash
comfyctl node disable itools --defer
comfyctl env status
# 현재 작업이 끝난 뒤 컨테이너를 재기동한다.
comfyctl node enable itools --defer
comfyctl env rollback --defer
comfyctl env reset --defer
# 이미 검증해 둔 desired를 실행 중인 서비스에 적용한다.
comfyctl env apply --restart
# 후보 검사부터 작업 대기·전환까지 수행한다.
comfyctl node disable itools --restart
comfyctl env rollback --restart
```

현재 관리 식별자는 `sam3`, `depth-anything-v3`, `itools`, `kjnodes`, `video-helper-suite`다. 고정 plugin 디렉터리 이름으로도 지정할 수 있다. Manager와 새 노드의 관리 항목은 실제 통합 단계에서 추가한다.

- disable/enable은 전체 ComfyUI 코드·노드 소스를 새 최종 경로로 복사하고 `.disabled` 상태를 기록한다. 검사 전에는 다음 부팅 선택도 바꾸지 않는다.
- 후보는 서비스 UID 1000으로 별도 포트·별도 데이터 디렉터리에서 실제 ComfyUI를 기동한다. 남은 필수 노드 등록과 EmptyImage→SaveImage를 확인한다. CPU catalog/core 검사이며 GPU 모델 검증으로 표시하지 않는다.
- host와 worker 환경은 같은 이미지의 immutable 절대 prefix를 참조한다. venv를 복사·이동하거나 임시 별칭으로 실행하지 않는다. worker별 명시적 경로표를 사용한다.
- 통과한 후보만 desired 선택에 기록한다. 현재 프로세스의 active와 다음 부팅의 desired는 `env status`에서 구분한다. 반복 요청은 같은 후보를 재사용한다.
- 정상 부팅 후 관리 명령이 이미지 identity·PID namespace·heartbeat·실제 host process를 확인하면 last/previous good을 기록한다. 역사적으로 정상이었던 코드도 사용 전에 hash를 다시 검사한다.
- rollback은 미적용 후보가 있으면 마지막 정상 세대로, 이미 정상 적용됐으면 이전 정상 세대로 돌아간다. 손상된 정상 후보는 건너뛴다.
- reset은 이미지 기본 노드·환경을 선택한다. 모델·업로드·출력·워크플로는 건드리지 않는다. 비활성 상태가 기본값으로 돌아가는 것은 명시적 reset의 동작이다.

## 보존과 권한

`/workspace/runtime/control/selection.json`에 desired·last/previous good과 revision을 기록하고, `/workspace/runtime/generations/<id>`에 코드·파일 hash·환경 경로표·노드 상태·검증 기록을 묶는다. 상태 쓰기는 파일 및 디렉터리 fsync와 atomic rename을 사용하고 관리 작업은 파일 잠금으로 직렬화한다.

root bootstrap은 `/workspace` 최상위와 `runtime/control`, `runtime/generations`를 root 소유 0755로 준비한다. 서비스가 관리 디렉터리를 rename하여 바꿔치기하지 못하게 하기 위한 경계다. storage/state/cache의 서비스 경로와 기존 사용자 파일을 재귀 chown하지 않는다. 기존 volume의 소유권/모드 정책과 실제 network volume 동작은 배포 전에 확인해야 한다.

선택한 코드의 hash·노드 정의·worker 경로표·이미지 identity가 다르면 부팅 전에 거부한다. 다른 이미지의 선택을 자동 재사용하거나 노드를 자동으로 되살리지 않는다. 명시적 reset으로 현재 이미지 기본값을 선택할 수 있으며 이전/손상된 상태 기록은 별도 archive에 보존한다. 현재는 CLI/runtime 코드 변경도 fingerprint에 포함해 엄격히 구분한다. 업데이트 때 노드 상태를 보존하는 compatibility 판정·rebase는 P4의 추가 작업이다.

검사 프로세스의 OS 임시 경로와 ComfyUI의 정리 대상 temp를 분리한다. Linux comfy-env subprocess에는 외부 `PYTHONPATH`, `PYTHONHOME`, `PYTHONSTARTUP`, `PYTHONUSERBASE`를 전달하지 않는다. host와 관리 bootstrap도 isolated Python 모드를 사용한다. 소스 경로는 검증된 명시적 경로로 전달한다.

## 부팅 실패 복구

`--restart`는 root 관리 파일로 새 `/prompt`·`/api/prompt` 요청을 HTTP 503으로 거부한 뒤, 실행 중·대기 중 작업과 접수 중 요청이 모두 끝날 때까지 기다린다. 내부 메타 배치 재등록을 포함한 기존 큐는 계속 실행한다. 기본 대기 시간은 300초이며 `--drain-timeout`으로 조절한다. 대기 시간이 지나면 현재 프로세스와 미적용 선택을 유지하고 요청 접수를 다시 연다.

큐가 비면 원하는 세대를 선택하고 PID 1에 명시적으로 재시작을 요청한다. 새 프로세스의 노드 등록·세대 identity·API 준비가 확인된 뒤 전환을 확정한다. `--startup-timeout` 기본값은 330초다. 시작 실패 시 보존한 정상 세대로 되돌려 재기동하고, 복구가 확인된 뒤 요청 접수를 연다. 복구 확인도 실패하면 접수를 닫아 둔 채 컨테이너 재기동을 요구한다.

전환 중에는 `control/transition.json`과 `control/transitions/<id>.json`에 이전 선택·대상·단계를 남긴다. 관리 프로세스가 중간에 종료되면 다음 정상 entrypoint 부팅에서 미확정 전환을 이전의 온전한 세대로 복구한다. 확정된 전환은 되돌리지 않는다. 미확정 기록이 있으면 추가 관리 변경은 거부한다. 별도 컨테이너의 offline CLI 호출은 자동 journal 복구를 수행하지 않으므로 먼저 정상 entrypoint로 복구해야 한다.

정상 서비스가 없어도 이미지 entrypoint에 CLI 인수를 전달할 수 있다. 아래는 실제 검사에 사용한 Docker 방식이다.

```bash
docker run --rm -v YOUR_VOLUME:/workspace YOUR_IMAGE comfyctl env rollback --defer
# 보존된 정상 세대가 없거나 상태 자체가 손상됐으면:
docker run --rm -v YOUR_VOLUME:/workspace YOUR_IMAGE comfyctl env reset --defer
```

그 뒤 정상 CMD로 재기동한다. RunPod의 Container Start Command 전달 방식과 network volume에서는 최종 Pod 검증을 별도로 수행한다. root가 이미지 기본 `/opt` 파일 자체를 직접 바꾼 경우는 새 원본 이미지로 재배포하는 범위와 구분한다.

[기존 lifecycle 결과](../tests/evidence/generations-cpu-probe.json)는 후보 검증, 비활성 상태의 재기동 유지, 선택된 코드에서의 native SAM3/DA3 실행, enable 후보, pending rollback·reset·이전 정상 rollback, 손상된 코드 부팅 거부와 offline 복구, 데이터·패키지 불변과 서비스 계정의 관리 파일 변경/rename 거부를 기록한다.

[Live 전환 결과](../tests/evidence/live-transitions-cpu-probe.json)는 실제 실행·대기 작업의 완료, 두 prompt 경로의 503, 이전 host/native worker 회수, 대기 시간 초과 시 작업 유지, 선택 후 코드 손상에 대한 자동 롤백, 관리 프로세스 SIGKILL 후 다음 부팅의 journal 복구를 통과했다. 같은 이미지의 [deferred 회귀 검사](../tests/evidence/live-image-generations-cpu.json)도 통과했다. CPU 상태 전환 검사이며 새 패키지 설치·GPU·RunPod network volume 성공 증거로 확대하지 않는다.
