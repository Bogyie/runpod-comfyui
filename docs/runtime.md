# 런타임 후보

`docker/Dockerfile.probe`의 `runtime-probe`는 실험 target이다. Manager·새 노드 설치와 최종 두 GPU/RunPod 검증은 아직 남아 있다. 모델 다운로드·환경 진단·기본 노드 상태 전환 CLI는 별도 venv로 포함했다. 운영용 stable 이미지로 간주하지 않는다.

## 실행과 경로

기본 CMD는 GPU 모드다. CPU 검사는 `--cpu --use-pytorch-cross-attention --listen 0.0.0.0 --port 8188`을 전달한다. 컨테이너 시작 명령은 비워 이미지 ENTRYPOINT를 사용한다. entrypoint가 관리 볼륨 디렉터리를 준비한 뒤 UID/GID 1000과 `no_new_privs`로 전환한다. supervisor·ComfyUI·native worker가 같은 서비스 계정을 쓴다. worker는 의존성 격리이며 사용자 파일 접근을 막는 보안 sandbox가 아니다.

| 위치 | 내용 |
|---|---|
| `/opt/runtime/venv`, `/opt/workers`, `/opt/probe/ComfyUI` | 이미지의 root 소유 기본 환경·코드 |
| `/workspace/storage/models` | 모델과 하위 유형 디렉터리 |
| `/workspace/storage/input`, `output`, `user` | 업로드·출력·워크플로/사용자 데이터 |
| `/workspace/storage/temp`, `previews`, `datasets` | ComfyUI 데이터 경로 |
| `/workspace/state/runtime-status.json` | starting / ready / restarting / recovery-required / stopped 상태 |
| `/workspace/runtime/control` | root 관리 선택·전환 journal·새 작업 접수 차단 파일 |
| `/workspace/runtime/generations` | 검증된 세대별 코드와 환경 경로표 |
| `/workspace/state/logs/comfyui.log` | 로그, 파일당 16 MiB와 백업 2개 |
| `/workspace/cache/metadata` | comfy-env 메타데이터 캐시 |
| `/workspace/cache/huggingface`, `torch` | 다운로드·모델 라이브러리 캐시 |

root bootstrap은 위 관리 디렉터리 항목만 준비하며 사용자 파일을 재귀 chown하지 않는다. symlink 경로는 거부한다. 기존 볼륨 파일이 다른 UID 소유라면 별도 권한 이전이 필요하다. `/workspace` 전체 데이터를 덮거나 기본 노드를 볼륨에 재복사하지 않는다. 기본 노드의 상태 변경은 세대별 코드 view로 준비하고, 다음 부팅 또는 기존 작업 완료 후 명시적 재시작으로 적용한다. 추가 노드/변경된 환경은 아직 남아 있다. [세대 관리](generations.md)를 참고한다.

`runtime_paths.py`는 host·메타데이터 스캔·persistent worker에서 `folder_paths`를 import하기 전에 같은 모델/데이터 설정을 적용한다. 기존 SDK의 input/output/user 재지정만으로 모델 경로까지 바뀌었다고 가정하지 않는다. 서로 다른 경로 플래그와 아직 worker에 전달하지 못하는 extra-model-paths 설정은 명시적으로 거부한다. 세대별 커스텀 모델 설정과 전체 동적 INPUT_TYPES/파일 변경 감지는 후속 작업이다.

## 캐시와 상태

runtime identity는 스택/base 정의·Dockerfile·소스 lock·host/GPU/worker/tools lock·uv.lock·SDK 패치·runtime/CLI 도구 hash에서 만든다. comfy-env 캐시는 prefix 밖으로 옮기며 runtime identity·worker prefix·노드 경로·환경 변수·storage·attention/CPU 설정을 key에 포함한다. 현재 정적 proxy metadata의 한계가 있으므로 캐시 hit를 새 입력 파일 목록/변경 감지 성공의 증거로 사용하지 않는다.

supervisor는 처음에 필수 노드가 등록된 `/object_info`를 확인한 뒤 가벼운 `/system_stats`로 API 응답을 감시한다. API가 멈추면 복구 필요 상태를 기록하고, 응답이 돌아오면 같은 프로세스에서 ready로 회복한다. 실행 실패를 무한 재시작하지 않는다. 신호를 ComfyUI 프로세스 그룹으로 전달하고 bounded wait 후 남은 자식을 종료·회수한다. 모델 없는 readiness는 실제 GPU 커널/모델 추론 성공과 구분한다. 상태에는 runtime identity와 주기적인 ready heartbeat도 기록한다. 상태 파일만으로 RunPod 플랫폼의 자동 복구를 보장하지 않는다.

## 재현

```bash
uv run --frozen python tools/rebuild/build_probe.py --target runtime-probe
uv run --frozen python tools/rebuild/probe_runtime.py
```

검사 도구는 자체 Docker volume·컨테이너만 만들고 정리한다. 읽기 전용 rootfs와 writable `/workspace`·`/tmp`, 512 MiB `/dev/shm`에서 실행한다. 기본 64 MiB shared memory의 대형 영상 적합성을 보장하는 시험은 아니다. 실제 RunPod에서는 GPU·네트워크 볼륨·shared memory 설정을 별도로 확인해야 한다.

[로컬 검증 결과](../tests/evidence/runtime-cpu-probe.json)는 서비스 UID, host/native worker 데이터 경로, 모델 위치 marker, 업로드·저장, immutable 경로 쓰기 거부, prefix 외부 metadata 캐시, 네트워크 없는 재기동과 데이터 보존, API 정지·회복 및 실패 상태를 기록한다. marker는 경로 검사용 텍스트이며 모델 추론에 사용하지 않는다. 시험용 관찰 노드는 bind mount로만 연결하며 이미지에 포함하지 않는다.

CI는 기존 worker 후보 외에 runtime preview를 별도로 빌드·검사한다. preview는 아직 GHCR 게시 대상이 아니며, 게시한 worker 후보 digest와 runtime preview의 검증 범위를 혼동하지 않는다. 최종 Manager·관리 CLI 통합 뒤 사용자용 target과 게시 경로를 합친다.

[환경 진단](environment-diagnostics.md)은 PID namespace·이미지 identity·heartbeat와 실제 host process를 대조해 이전 컨테이너의 상태 파일을 구분한다. 공개 다운로드는 선택적인 `probe_runtime.py --live-downloads` 검사이며 기본 CI에서는 외부 모델을 받지 않는다.

## Manager 읽기 전용 연결

runtime preview는 5개 계산 worker 외에 Manager UI/catalog adapter를 포함한다. Manager가 켜져 있으면 `/comfyctl/manager/status`까지 응답해야 첫 readiness를 인정한다. 서비스는 원본 Manager 설치 엔진을 실행하지 않는다. 설치·복구는 관리자 `comfyctl`로 수행하며, [지원 범위와 검증](manager-integration.md)을 따른다. GHCR에 게시한 raw worker 후보와 이 runtime preview는 별도 이미지다.
