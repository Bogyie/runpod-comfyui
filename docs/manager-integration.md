# Manager 연결 경계

runtime preview에는 Manager `4c50a2bc8b9e684d8a85930567957470b952bebe`의 원본 JavaScript UI와 고정 catalog를 포함한다. 검색과 설치 상태 조회는 읽기 전용 adapter가 처리한다. 설치·업데이트·환경 복구는 `comfyctl`을 사용한다. 계획서 §7.1의 관리 CLI 대체 경로이며 원본 Manager 설치 엔진을 재사용하지 않는다.

## 제공하는 동작

- 원본 Manager 메뉴, 6,025개 catalog, 검색, node mapping과 JS assets.
- 현재 실행 세대의 6종 기본 노드와 추가 관리 노드의 설치·활성 상태 조회. GitHub 이전 주소도 같은 저장소로 식별한다.
- Manager mutation 요청과 `/api` 별칭은 HTTP 403과 실제 사용할 명령을 반환한다. 노드·모델 UI 오류에도 `comfyctl` 안내를 표시한다.
- `comfyctl node add`는 pinned source → native comfy-env 우선 분류 → private worker lock/설치 → 후보 검사 → 세대 선택을 수행한다. [설치 방법과 제약](node-installation.md)을 따른다.
- 모델은 `comfyctl model add`, 복구는 `comfyctl env rollback` 또는 `env reset`을 사용한다. 관리자 터미널 명령이며 서비스 계정에서 직접 환경을 바꾸지 않는다.

```bash
comfyctl node add OWNER/REPO --name NAME --commit FULL_SHA \
  --required-node NODE_CLASS_ID --smoke-workflow graph.json --defer
comfyctl env apply --restart
comfyctl node disable NAME --restart
comfyctl env rollback --restart
comfyctl model add URL --type TYPE
```

원본 UI의 CNR/원격 catalog 갱신, snapshot 복원, PIP 설치, ComfyUI 업데이트, 공유와 분석 기능을 그대로 제공하는 것은 아니다. 버전은 upstream catalog의 고정 정보이며 최신 버전 확인 결과가 아니다. 모델 catalog 조회도 다운로드 완료 판정이나 모델 설치 엔진을 대체하지 않는다. Manager 전체 기능 호환으로 표시하지 않는다.

## 실행 경계

원본의 `run_script` 한 곳만 바꾸면 queue worker·즉시 enable·prestartup·PIPFixer·CLI 경로가 남는다. [고정 소스·HTTP 경로 목록](evidence/manager-boundary-audit.json)에 이 경계를 기록했다.

`apply_manager_adapter.py`는 전체 원본 Python 파일 hash를 확인한 뒤 legacy Python을 즉시 실패하는 guard로 교체한다. package init과 prestartup만 검토한 adapter로 바꾼다. `cm-cli.py`, manager_core/server/util, PIPFixer와 공유 모듈을 직접 실행해도 설치 엔진을 불러오지 않는다. 원본 JS의 오류 문구 수정도 hash와 anchor 개수를 검사한다.

prestartup은 기존 `install-scripts.txt`와 snapshot 예약 파일을 실행하거나 삭제하지 않는다. 경로·크기·hash를 `user/comfyctl/manager/blocked-startup.json`에 남긴다. `value` query를 포함하는 설정 변경과 허용 목록에 없는 Manager 경로도 거부한다. 프로세스는 일반 서비스 UID로 실행하며 이미지 및 관리 세대 코드·환경은 root 소유다. 이 정책은 원본 `security_level` 설정에 의존하지 않는다.

Manager도 다른 기본 노드처럼 disable/enable할 수 있다. 활성 상태일 때만 `/comfyctl/manager/status`를 후보 및 실제 부팅의 필수 readiness endpoint로 검사한다.

## 확인한 범위

[Linux API 검사](../tests/evidence/manager-cpu-probe.json)는 catalog·설치 상태·JS 응답, 감사 목록의 모든 POST와 `/api` 별칭 차단, legacy CLI/module 차단, 예약 파일 보존과 미실행, 이미지 패키지 fingerprint 보존, Manager disable/enable 후 route·readiness 전환과 네트워크 없는 재부팅을 통과했다. [실제 Chrome UI 검사](../tests/evidence/manager-browser-cpu.json)는 메뉴·검색·설치 상태와 변경 버튼의 CLI 안내를 확인했다.

[같은 이미지의 CLI lifecycle](../tests/evidence/manager-image-node-install-cpu.json)은 native comfy-env fixture의 자동 lock·실제 설치·계산·재부팅·disable·rollback·손상 감지·reset을 통과했다. 공개 노드 전체 호환이나 GPU/RunPod 영속 볼륨 검증으로 확대하지 않는다. CI에서도 Manager 검사를 별도 runtime preview에 적용한다. 현재 GHCR worker 후보에는 이 runtime을 아직 게시하지 않았다.
