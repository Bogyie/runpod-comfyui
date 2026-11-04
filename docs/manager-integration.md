# Manager 연결 경계

조사 대상은 `4c50a2bc8b9e684d8a85930567957470b952bebe`다. [고정 소스·HTTP 경로 목록](evidence/manager-boundary-audit.json)은 정적 분석 증거다. 현재 이미지에 Manager를 통합·검증한 상태는 아니다.

## 한 곳의 subprocess hook으로는 충분하지 않다

`manager_core.ManagerFuncs.run_script`는 교체 가능한 실행 hook이고 서버가 `ManagerFuncsInComfyUI`를 설정한다. 하지만 UI의 `_queue_node_install`에는 이미 비활성인 노드를 즉시 enable하는 분기가 있고, queue worker는 별도 thread로 실행한다. 예약 설치는 prestartup에서 별도 `process_wrap`을 거치며, PIPFixer는 직접 subprocess로 패키지를 변경한다. `run_script`만 바꾸는 전역 대응으로 모든 설치를 후보 환경에 보냈다고 판정할 수 없다.

| 경로 | 원본 동작 | 통합 시 필요한 처리 |
|---|---|---|
| `/manager/queue/install`, reinstall, fix, update, update_all | 요청을 queue에 추가하고 별도 thread에서 실행; enable은 즉시 처리하는 분기도 존재 | 활성 디렉터리를 변경하지 않고 관리 후보로 변환하거나 직접 변경을 거부 |
| `/customnode/install/git_url`, `/customnode/install/pip` | git URL·패키지 직접 설치 | host 직접 설치 차단, 관리 CLI 안내 |
| disable, uninstall, update_comfyui | 코드·활성 상태·앱 변경 | 관리 상태 기록과 코드/환경을 함께 전환 |
| `/snapshot/restore` | 다음 시작을 위한 restore 예약 | Manager snapshot을 정상 환경 rollback과 혼용하지 않음 |
| `prestartup_script.py` | install-scripts 예약, lazy install/CNR switch/delete, snapshot 복원·재시작 | 기존 예약 파일이 있어도 직접 실행하지 않음; 파일을 조용히 삭제하지 않고 상태와 사유 기록 |
| `manager_util.PIPFixer.fix_broken` | torch·OpenCV·frontend·자동 수정 목록의 패키지 변경 | 실행 환경 수정을 금지하고 환경 검사/rollback으로 대체 |
| `cm-cli.py` | UI를 거치지 않는 install·post-install 등 | 관리 이미지 안에서는 직접 mutation 명령 거부; 별도 comfyctl 후보 경로 사용 |
| 모델 설치 queue | 자체 download 경로 | 검증된 모델 다운로드 CLI와 영속 경로 사용 |

원본 `security_level`과 전용 git/pip 허용 flag는 보조 설정이다. prestartup 예약과 PIPFixer까지 통제하는 실행 계정 경계가 아니며, root P0에서 immutable 환경 보호를 주장할 근거로 쓰지 않는다.

## 구현 순서와 완료 조건

1. nonroot 서비스와 root 소유 기본 코드·GPU/host/worker 환경을 구성한다. ComfyUI 및 worker의 input/output/user/models 경로를 영속 storage로 맞춘다.
2. comfyctl이 후보 세대의 최종 prefix에 코드·환경을 만들고 lock·설치 훅·GPU 변경 범위를 분석한다. 검증 전에는 활성 포인터를 바꾸지 않는다.
3. Manager의 원래 검색·catalog·프런트엔드 assets는 보존하고 mutation은 명시적으로 제한한다. 검증된 구조적 확장점이 부족하므로 개별 호출을 광범위하게 monkey patch하여 설치 엔진으로 재사용하지 않는다. 제한 응답에 실제 사용할 수 있는 comfyctl 명령을 안내한다.
4. hash guard 아래 prestartup/CLI/PIPFixer 경계를 처리하고 기존 예약 작업을 실패 주입한다. UI 차단만 확인한 결과는 완료 증거가 아니다.
5. 실제 검색·UI asset, mutation 제한, 예약 작업 차단, CLI 우회 거부, 정상 후보 설치·disable·재시작·rollback/reset을 검사한다. 모델·입력·출력 보존과 부팅 후 비활성 상태 유지도 확인한다.

이 순서는 계획서 §7.1의 관리 CLI 대체 경로를 따른다. 제한만 있는 Manager와 사용할 수 없는 CLI를 최종 구현으로 제공하지 않는다. 새 노드도 upstream comfy-env → 어댑터 → 일부 격리 → 검토한 host 예외의 순서로 분류한다.
