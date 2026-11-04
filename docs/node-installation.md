# 추가 노드의 소스 분석

`comfyctl node plan`은 후보 설치에 사용할 소스 정보를 만든다. `node add`는 고정 소스의 의존성을 별도 UID에서 해석해 전체 worker lock을 만들거나 검토한 lock을 받아 별도 환경에 설치한다. 노드 등록·CPU 대표 workflow를 확인한 뒤 세대로 선택한다. 복잡한 host 예외는 전용 어댑터가 필요하다. 기본/추가 노드의 enable/disable과 전환은 [세대 관리](generations.md)를 따른다.

```bash
comfyctl node plan PozzettiAndrea/ComfyUI-SAM3 \
  --commit de0ff5d2c2ea435d29f800abfa568cffdfb94773 > sam3-plan.json
```

저장소는 `owner/repository` 또는 정확한 HTTPS GitHub 저장소 URL, 버전은 전체 40자리 소문자 commit SHA를 받는다. 이동하는 branch/tag를 설치 버전으로 사용하지 않는다. 공개 GitHub codeload에서 archive를 받아 SHA256과 모든 일반 파일의 hash를 기록한다. 이전에 검토한 archive를 다시 검사할 때는 `--archive-sha256`을 함께 지정한다.

네트워크 없이 같은 입력을 분석할 수도 있다. 로컬 archive에는 hash가 필수다.

```bash
comfyctl node plan owner/repository --commit COMMIT_SHA \
  --archive node.tar.gz --archive-sha256 ARCHIVE_SHA256 > node-plan.json
```

명령은 일반 서비스 UID로 실행할 수 있다. 소스를 디스크에 풀거나 import하지 않고, 설치·startup·build hook도 실행하지 않는다. 현재 코드·패키지·desired 선택을 바꾸지 않으며 JSON을 표준 출력에 쓴다. 압축 크기, 전체 tar 크기, 파일별/전체 파일 크기, 항목 수, 분석용 텍스트 크기를 제한한다. 경로 탈출·symlink·hardlink·특수 파일·중복 경로·복수 최상위 디렉터리는 거부한다.

결과에는 다음이 들어간다.

- 저장소·commit·archive SHA256·전체 파일 hash와 재현 가능한 `plan_sha256`.
- requirements와 pyproject의 명시된 의존성, GPU 패키지 요구, 별도 검토가 필요한 직접 URL·include·pip 옵션.
- 설치/startup/build hook과 shell script 경로, 분석할 수 없었던 텍스트·Python·TOML 목록.
- comfy-env 설정과 AST에서 찾은 `register_nodes` 호출 위치. 두 가지가 있으면 native 후보로 표시하고, 없으면 어댑터 검토 대상으로 표시한다.

`native-comfy-env-candidate`는 실행 격리 성공 판정이 아니다. 이 분석으로 임의 Python의 동작이나 동적 의존성을 증명할 수 없다. `installation_ready`는 항상 false다. 실제 installer는 GPU lock·Python ABI·hook 정책·최종 prefix·전체 의존성 lock을 검증하고, upstream 격리 → 어댑터 → 일부 격리 → 검토한 host 예외 순서로 후보를 구성해야 한다. 분석 보고서만으로 host에 pip를 실행하지 않는다.

[실제 Linux CLI 검사](../tests/evidence/node-source-linux-cli.json)는 읽기 전용 rootfs·네트워크 차단 상태의 새 이미지에서 고정 SAM3 archive를 분석했다. [전체 분석 결과](../tests/evidence/node-source-sam3-plan.json)는 53개 파일과 native 등록 위치, 설치/startup hook 및 CUDA 검토 항목을 기록한다. 단위 검사에는 실행 시 예외를 내는 소스/hook, link·경로 탈출·중복·크기 제한, hash 불일치, 불완전한 Python/TOML 및 root가 아닌 CLI 호출이 포함된다.

## 후보 환경 빌더

내부 API `comfyctl.candidate_env.prepare_environment`는 root가 예약한 세대 아래 최종 prefix에 새 venv를 만든다. 아직 직접 사용자 명령으로 노출하지 않는다. `node add`의 source 분석·의존성 해석·노드 검증과 연결하기 위한 구성 요소다.

- 입력은 전체 exact-version/SHA256 wheel lock과 그 hash다. requirements include·직접 URL·임의 index·marker·소스 빌드는 받지 않는다. marker는 앞선 해석 단계에서 대상 플랫폼에 맞게 정규화해야 한다.
- 이미지의 GPU 패키지 목록·버전과 comfy-env SDK 버전이 다르면 prefix 생성 전에 거부한다. Python은 이미지의 `/usr/local/bin/python`을 사용한다. ABI/GPU 교체는 이미지 재빌드 범위다.
- 실제 venv 생성·wheel 설치·dependency check는 서비스 UID 1000과 다른 UID 1001, 보조 그룹 없음, `no_new_privs` 상태에서 수행한다. source/node hook을 실행하는 경로는 없다. 임의 노드 코드의 보안 sandbox를 제공한다는 뜻은 아니다.
- GPU payload만 이미지의 immutable 파일에 연결한다. GPU dist-info와 CPU 패키지는 후보 안에 따로 설치한다. host site-packages를 sys.path에 넣지 않으며 venv를 옮기거나 별칭으로 실행하지 않는다.
- wheel hash·전체 설치 버전·dependency check·GPU payload 경로를 확인하고 고정 SDK 패치를 적용한다. 성공 후 root 소유로 봉인하고 설치 캐시를 제거한다. 실패한 prefix도 봉인해 보존하며 같은 경로에 재설치하지 않는다. 기본 디스크 여유 검사와 설치 timeout을 적용한다.
- 빌더 receipt의 `selected`는 false다. 빌더 자체는 노드 등록·API·GPU 검증이나 전환을 수행하지 않는다. 아래 `node add`가 코드·노드 정의·lock·receipt를 `managed-nodes-v1`으로 묶고 별도 후보 검증 뒤에 선택한다.

[실제 Linux 빌더 검사](../tests/evidence/candidate-environment-cpu.json)는 새 최종 prefix에 host의 151개 패키지 lock을 실제 wheel로 설치했다. 서비스 UID로 private NumPy와 공유 torch 경로를 확인하고 후보 파일 쓰기 거부를 검사했다. GPU 버전 불일치의 생성 전 거부, 잘못된 artifact hash의 설치 실패·봉인, 실패 prefix 재사용 거부, 선택 기록·사용자 sentinel·이미지 패키지 fingerprint 보존 및 private 사용자 파일에 대한 installer 쓰기 거부를 확인했다. 성공한 설치 캐시는 제거했고 검사 컨테이너·볼륨도 삭제했다. 이 검사는 새 노드 등록이나 GPU 모델 성공을 증명하지 않는다.

## 고정 소스의 추가·전환

관리 이미지의 root 터미널에서 실행한다. 기본값은 자동 해석이며 `--lock FILE`로 검토한 전체 exact-version/SHA256 lock을 다시 사용할 수 있다. 이미지 GPU pin·SDK 버전을 유지하고 노드의 명시된 requirements를 만족해야 한다. 이미지 의존성만으로 충분한 노드는 `/opt/locks/host.txt`도 사용할 수 있다.

대상은 현재 소스에서 빌드한 `runtime-probe`다. 별도로 GHCR에 게시한 worker 후보 digest에는 이 관리 CLI가 포함되지 않는다.

```bash
comfyctl node plan OWNER/REPOSITORY --commit FULL_COMMIT_SHA > node-plan.json
comfyctl node add OWNER/REPOSITORY --name my-node --commit FULL_COMMIT_SHA \
  --required-node NODE_CLASS_ID \
  --smoke-workflow /workspace/state/my-node-smoke.json --defer
# 기존 큐가 끝난 뒤 검증된 desired를 적용한다.
comfyctl env apply --restart
comfyctl node disable my-node --restart
comfyctl env rollback --restart
```

`--smoke-workflow`는 UI 저장 형식이 아닌 ComfyUI API prompt graph JSON이다. 최소 한 개의 `--required-node`가 실제 그래프에 들어가야 한다. 각 필수 노드가 추가한 plugin에서 등록됐는지도 검사하므로 기존 내장 노드를 지정해서 등록 실패를 숨길 수 없다. 필수 ID가 여러 개면 옵션을 반복한다. 후보는 별도 데이터 디렉터리·서비스 UID로 기동하며 core 그래프와 제공한 workflow가 통과하기 전에는 desired를 바꾸지 않는다. 검사는 CPU 기준이며 GPU 모델 성공을 대신하지 않는다.

기본 `--mode auto`는 upstream comfy-env 설정과 등록이 있으면 native 경로를 사용한다. 그 외에는 전체 원본을 `managed_worker`에 보존하고 host에는 `register_nodes`만 남기는 계산 노드용 어댑터를 만든다. host server hook이 발견되면 범용 어댑터로 설치하지 않고 검토한 전용 어댑터를 요구한다. 복잡한 V3/모델/프런트엔드 호환성을 이 범용 경로만으로 보장하지 않는다.

CUDA 확장, 처리할 수 없는 Conda/system 요구, 관리 환경 변수 덮어쓰기와 해석하지 못한 소스는 이미지 통합·전용 어댑터의 대상이다. install/startup/build hook이 있으면 기본적으로 거부한다. 분석을 검토하고 hook 없이 동작하는 노드는 `--skip-hooks`를 명시할 수 있다. hook은 실행하지 않고 보존하며, prestartup 파일은 `.disabled`로 바꿔 ComfyUI의 별도 startup 경로에서도 실행되지 않게 한다.

로컬 archive도 `--archive FILE --archive-sha256 SHA256`으로 설치할 수 있다. 이때 commit은 제공자의 선언이며 GitHub를 조회해 확인하지 않는다. 실제 바이트는 archive/file hash로 고정한다.

추가 노드는 `managed-nodes-v1` 세대로 기록한다. 이미지 host와 기본 worker binding은 유지하고, 새 worker binding만 봉인된 prefix·lock·receipt·전체 CPU 파일 manifest에 연결한다. 원본 source plan hash도 묶는다. 재기동·선택 때 코드/CPU 파일·lock·receipt와 권한이 다르면 거부한다. 비활성 상태 세대도 이 정의를 보존하므로 이전 코드와 같은 환경으로 rollback할 수 있다. prefix를 다른 경로로 옮기지 않는다. `env doctor`는 현재 추가 worker를 포함하고 `--deep`은 해당 prefix의 RECORD도 검사한다.

[범용 어댑터 검사](../tests/evidence/node-install-cpu.json)와 [native comfy-env 검사](../tests/evidence/node-install-native-cpu.json)는 각각 실제 새 worker 설치, 후보 workflow, deferred 재기동 뒤 계산 결과·별도 prefix/PID/UID, disable·rollback, CPU 파일 손상 감지와 이미지 기본값 reset을 통과했다. 설치/startup hook은 opt-in 없이 거부됐고 skip 후에도 실행되지 않았다. 입력은 오프라인 fixture archive이며 공개 upstream 설치나 GPU 모델 검증으로 표시하지 않는다. 두 검사 모두 같은 image ID `sha256:a2b556b66dad65d5ca3bab43d7c4a3e9434796a12992bba015792d38f38398be`를 사용했고 자원을 삭제했다.

추가 worker를 포함한 [deep 진단 결과](../tests/evidence/node-install-added-worker-deep.json)도 문제 없이 통과했다. 전체 165,688개 고유 파일을 hash했고 추가 prefix의 RECORD 49,638개 항목에 mismatch가 없었다.

## 자동 dependency 해석

ComfyUI의 필수 worker 요구사항과 노드의 정규화된 requirements/PyPI 설정을 합친다. host UI 패키지 생략 목록은 stack에서 생성한 이미지 baseline을 따른다. GPU lock 전체와 comfy-env·uv·comfy-kitchen·comfy-aimdo는 이미지 버전에 고정한다. 호환되는 CPU 버전은 기존 host lock을 우선하되 새 요구가 있으면 private worker 안에서 해석한다.

해석은 UID 1001·보조 그룹 없음·`no_new_privs`에서 `uv pip compile --only-binary`로 실행한다. 프로젝트/사용자 uv 설정을 읽지 않고 PyPI와 명시한 torch backend를 사용한다. source build/hook을 실행하지 않으며 interpreter 다운로드도 금지한다. `resolution/requirements.in`, `requirements.txt`, `receipt.json`, `resolve.log`를 세대에 보존한다. 설치 전 전체 hash lock과 보호 pin을 다시 확인한다. 해석 실패/timeout이면 설치와 선택으로 진행하지 않고 임시 cache를 정리한다. 반환된 lock은 이후 `--lock` 입력으로 사용할 수 있다.

[실제 resolver 검사](../tests/evidence/candidate-resolve-linux.json)는 잘못된 사용자 `uv.toml`을 무시하고 105개 패키지를 해석했다. 충돌하는 torch 요구는 설치 전에 거부됐고 선택은 생기지 않았다. [공개 Multiband 검사](../tests/evidence/public-node-install-config-guard-cpu.json)는 고정 GitHub SHA/archive hash를 직접 받아 106개 패키지 lock을 만들고 private tifffile을 설치했다. IMAGE→MULTIBAND→채널 재배열→PNG의 크기·픽셀, worker 미리보기 파일·JS asset, 별도 worker 및 `no_new_privs`, 이미지 fingerprint 보존과 reset을 통과했다. CPU 대표 경로이며 전체 UI/모든 노드/GPU 모델 검증을 뜻하지 않는다.

[Native fixture의 자동 lock lifecycle](../tests/evidence/node-install-native-auto-cpu.json)도 통과했다. 이 결과는 user uv 설정 차단 추가 전 이미지이며, 위 공개 검사와 resolver 검사는 차단이 포함된 최신 이미지에서 수행했다. 각 artifact에 image ID를 구분해 기록했다.

## 추가한 노드의 업데이트

```bash
comfyctl node update NAME --commit FULL_SHA \
  --required-node NODE_CLASS_ID --smoke-workflow graph.json --defer
comfyctl env apply --restart
```

`update`는 기존에 추가한 노드의 저장소를 유지하고 새 SHA를 분석한다. 설치와 같은 hook·의존성·GPU pin 정책을 적용한다. 새 세대의 최종 경로에 코드와 private worker를 만들며, 기존 worker에 패키지를 덮어쓰지 않는다. 새 코드가 대표 workflow를 실행한 뒤에만 desired 상태를 바꾼다. 실패하면 기존 선택을 유지한다. 코드와 worker prefix를 함께 rollback한다.

기존 노드가 비활성 상태라면 후보에서 먼저 새 노드의 계산을 검사한 뒤 비활성 상태로 돌리고 최종 catalog를 다시 검사한다. 사용자가 `enable`할 때까지 실제 서비스에서는 비활성 상태를 유지한다. `--required-node`와 smoke workflow는 새 버전에 맞게 명시해야 한다. 이미지 기본 노드는 기존 adapter·host lock·readiness 정의와 함께 이미지 빌드로 업데이트한다. 이 명령으로 기본 정의를 우회하지 않는다.

## 보존 세대와 용량 정리

```bash
# 기본: 24시간 이상 지난 미참조 세대의 삭제 계획만 출력
comfyctl env gc
# 계획을 확인한 뒤 실제 정리
comfyctl env gc --apply
# 실패 후보를 바로 정리할 필요가 있을 때만 연령 제한을 낮춘다
comfyctl env gc --min-age-hours 0
```

정리도 관리자 권한과 설치·전환에 사용하는 동일한 lock을 요구한다. 현재 실행 세대, desired, 마지막 정상/직전 정상 세대와 프로세스가 사용하는 prefix를 보존한다. 이들이 참조하는 private worker가 과거 코드 세대에 있으면 해당 소유 세대도 재귀적으로 보존한다. 단순한 parent 이력은 실행 의존성이 아니므로 모든 과거 코드를 무기한 보존하지는 않는다.

끝나지 않은 전환, 손상되거나 누락된 보존 상태, 식별할 수 없는 관리 host가 있으면 정리를 거부한다. symlink·이름이 다른 디렉터리는 삭제 대상으로 삼지 않는다. 모델·입출력·워크플로·패키지 캐시는 이 정리 범위에 포함하지 않는다. 삭제 전후 목록은 root control의 `gc/` journal에 기록한다. 중단된 정리는 아직 남아 있는 미참조 세대를 다음 실행에서 다시 계획할 수 있다. 삭제된 후보의 lock만으로 네트워크 없는 재설치를 보장하지 않는다.

현재 로컬 검증은 하나의 관리 컨테이너가 볼륨을 사용하는 범위다. RunPod network volume을 여러 Pod에서 동시에 사용하는 운영은 별도 검증 전까지 지원한다고 보지 않는다.

[Linux CPU 증거](../tests/evidence/node-update-gc-cpu.json)는 실제 private 환경 설치, 버전별 계산·rollback, 실패 후보의 선택 유지, 비활성 업데이트, 미참조 세대 삭제 후 계산과 손상/reset을 포함한다. [runtime 회귀](../tests/evidence/update-gc-image-runtime-cpu.json)는 같은 이미지에서 별도로 실행했다. 단위 검사는 중단된 정리의 journal과 다음 실행 복구도 검사한다. 공개 노드 전체 조합·GPU·network volume의 성공 증거는 아니다.
